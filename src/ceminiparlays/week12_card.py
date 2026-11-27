"""Week 12 Thanksgiving Hard Rock card, priced from the live book snapshot.

The card is fixed. The operator chose four cross-game tickets by hand, and
``FIXED_TICKETS`` is that list. Nothing on this card is ranked, substituted, or
searched for: the module resolves each fixed leg to its posted hardrockbet row
and raises when the row is missing or the posted price is not the card price.

The builder reads ``config/week12/live_lines_2026-11-26.csv``. It does not
open a socket and it does not submit a bet. A missing Hard Rock line raises.
A player mean that equals a team total raises. A missing team-rates file is
not a zero, a league mean, or a slate median.

A leg from one game and a leg from another game are a cross-game parlay. It
does not take the same-game SGP haircut, so the posted leg product is the
expected price. That product is still not a captured book quote, so the card
labels it ``UNQUOTED_PARLAY_ESTIMATE`` and never prints a market EV for it.
"""

from __future__ import annotations

import csv
import shlex
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from io import StringIO
from itertools import combinations
from pathlib import Path
from zoneinfo import ZoneInfo

from ceminiparlays.book_team import canonical_team
from ceminiparlays.card_sync import sync_dated_card
from ceminiparlays.compose import (
    bench_blowout_q4_blocked,
    joint_ticket,
    q4_reception_direction_blocked,
)
from ceminiparlays.correlation import (
    LegRef,
    UnmodeledCorrelationError,
    correlation_matrix,
)
from ceminiparlays.environment import read_environment
from ceminiparlays.io import OUT_STATUSES, LineRow
from ceminiparlays.matchup_math import leg_ev
from ceminiparlays.names import fold_name_suffix_aware
from ceminiparlays.odds import american_to_decimal, decimal_to_american
from ceminiparlays.odds_api import MARKET_TO_STAT, STAT_TO_MARKET
from ceminiparlays.proppricing import BookQuote, consensus_fair_p_over
from ceminiparlays.resources import REPO_ROOT
from ceminiparlays.slips import EvaluatedLeg
from ceminiparlays.sunday_card import norm_name
from ceminiparlays.week11_card import TeamTotalAsPlayerError, fair_american, shift_fair_over

SLATE_DAY = "2026-11-26"
WEEK = REPO_ROOT / "config" / "week12"
ENV_PATH = WEEK / "environment.csv"
RATES_PATH = WEEK / "team_rates_2026-11-26.csv"
SCRIPT_PATH = WEEK / "quarter_script_2026-11-26.csv"
STARTERS_PATH = WEEK / "qb_starters_2026-11-26.csv"
SCRATCH_PATH = WEEK / "scratches_2026-11-26.csv"
Q4_PATH = WEEK / "q4_rb_checkdown_2026-11-26.csv"
LIVE_PATH = WEEK / "live_lines_2026-11-26.csv"
CARD_CSV = WEEK / "hardrock_card_2026-11-26.csv"
CARD_MD = WEEK / "card_2026-11-26.md"
SLIP_CSV = WEEK / "slip_2026-11-26.csv"

# A price that is only the product of standalone leg prices is not a quote.
UNQUOTED_PARLAY_ESTIMATE = "UNQUOTED_PARLAY_ESTIMATE"
CROSS_GAME_PRICE_NOTE = (
    "The parlay price is the product of two posted Hard Rock leg prices. "
    "It is not a captured Hard Rock quote. No market EV is claimed."
)
SLIP_FIELDS = (
    "ticket_id",
    "player",
    "market",
    "side",
    "line",
    "book_american_odds",
    "stake",
)
LOG_SLIP_COMMAND = (
    "ceminiparlays log-slip --date 2026-11-26 "
    "--slip-csv config/week12/slip_2026-11-26.csv "
    "--starters config/week12/qb_starters_2026-11-26.csv "
    "--scratches config/week12/scratches_2026-11-26.csv "
    "--sync-dirs parlays-slate parlays-recap"
)

BANKROLL_CENTS = 2000
MIN_TICKETS = 3
MAX_TICKETS = 4
TICKET_COUNT = 4
STAKE_POOL = (600, 500, 500, 400)
QUARTER_CAP_CENTS = 500
MAX_LEGS = 3
MIN_LEGS = 2
MAX_LEG_REUSE = 1
RECEPTIONS_Q4_CAP = 1
MEAN_MATCH_ABS = 0.01
EDGE_FLOOR = -0.12
LEGS_PER_GAME = 12
HR_BOOK = "hardrockbet"
HR_FAMILY = frozenset({HR_BOOK, "hardrockbet_fl"})
YARD_MARKETS = frozenset({"pass_yds", "rush_yds", "rec_yds"})
ONE_WAY_MARKETS = frozenset({"player_anytime_td", "player_1st_td", "anytime_td", "first_td"})
PLATFORM_TO_BOOK = {
    "hardrock": HR_BOOK,
    "fanduel": "fanduel",
    "draftkings": "draftkings",
    "betmgm": "betmgm",
    "pinnacle": "pinnacle",
    "betrivers": "betrivers",
}
LONG_FIELDS = [
    "bookmaker",
    "player",
    "market",
    "side",
    "line",
    "american_odds",
    "timestamp",
    "game",
    "team",
    "opp",
]
HARD_EXCLUDE_NAMES = (
    "Roschon Johnson",
    "Dontayvion Wicks",
    "Jake Ferguson",
    "Jonathan Mingo",
    "Kenneth Walker III",
    "Cole Kmet",
    "Tank Bigsby",
    "Jalen Hurts",
    "Dalton Kincaid",
    "Noah Gray",
    "Elijah Mitchell",
    "Dameon Pierce",
    "Salvon Ahmed",
    "Kendre Miller",
    "Brittain Brown",
    "Nikola Kalinic",
    "Hayden Large",
    "Zavier Scott",
    "Jared Wiley",
    "Tyler Goodson",
    "Malik Davis",
    "Princeton Fant",
    "Johnny Wilson",
    "Tom Kennedy",
    "Kendrick Law",
    "Isiah Pacheco",
    "Ben VanSumeren",
    "Devin Moore",
)
REQUIRED_GAMES = frozenset({"CHI@DET", "PHI@DAL", "KC@BUF"})
RATE_DROPS: list[str] = []
LAST_SCAN: dict[str, int] = {"plus_legs": 0, "priced_tickets": 0, "plus_tickets": 0}


class LiveLinesMissingError(ValueError):
    """The live book snapshot has no usable Hard Rock line."""


class FixedCardError(ValueError):
    """A fixed leg, price, or card rule does not hold. The card is not written."""


def hard_exclude_names() -> set[str]:
    return {norm_name(name) for name in HARD_EXCLUDE_NAMES}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def number(value: object) -> float | None:
    text = str(value or "").strip()
    if not text or text.upper() in {"NO_EVIDENCE", "FILL_FROM_SLIP"}:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    if parsed != parsed:
        return None
    return parsed


def _american_int(value: object) -> int | None:
    parsed = number(value)
    if parsed is None:
        return None
    odds = int(parsed)
    if -100 < odds < 100 or odds == 0:
        return None
    return odds


def _legal_american(price: int) -> int:
    if -100 < price < 100:
        return -100 if price < 0 else 100
    return price


def _money(cents: int) -> str:
    return f"${cents / 100:.2f}"


def _american(price: int | None) -> str:
    if price is None:
        return ""
    if price > 0:
        return f"+{price}"
    return str(price)


def _is_quarter(market: str) -> bool:
    text = str(market or "")
    return text.endswith(("_q1", "_q2", "_q3", "_q4"))


def load_team_rates(path: Path | None = None) -> dict[str, dict[str, float]] | None:
    """Read team rates. A missing file returns None.

    The caller must not replace None with zero, a league mean, or a slate median.
    """

    source = path or RATES_PATH
    if not source.is_file():
        return None
    rates: dict[str, dict[str, float]] = {}
    keys = ("pass_off", "rush_off", "pass_def", "rush_def")
    for row in read_csv(source):
        team = canonical_team(str(row.get("team") or ""))
        parsed = {key: number(row.get(key)) for key in keys}
        if team and all(value is not None for value in parsed.values()):
            rates[team] = {key: float(value) for key, value in parsed.items() if value is not None}
    if not rates:
        return None
    return rates


def player_mean_from_team_rates(
    player: str,
    team: str,
    kind: str,
    rates: dict[str, dict[str, float]] | None,
) -> float | None:
    """The only door to a team-rate mean. A missing file records a drop."""

    if rates is None or team not in rates or kind not in rates[team]:
        RATE_DROPS.append(f"{player} {kind} NO_TEAM_RATES_FILE")
        return None
    return float(rates[team][kind])


def _blocked_names(path: Path) -> set[str]:
    names: set[str] = set()
    if not path.is_file():
        return names
    for row in read_csv(path):
        token = str(row.get("token") or "").strip().lower()
        if token not in OUT_STATUSES and token not in {"out", "ir"}:
            continue
        player = norm_name(str(row.get("player") or ""))
        if player:
            names.add(player)
    return names


def _starters(path: Path) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    if not path.is_file():
        return found
    for row in read_csv(path):
        team = canonical_team(str(row.get("team") or ""))
        if team:
            found[team] = row
    return found


def _packet_teams() -> dict[str, str]:
    """Names from the week packet. The roster file is not a fill for a blank team."""

    found: dict[str, str] = {}
    for row in _starters(STARTERS_PATH).values():
        team = canonical_team(str(row.get("team") or ""))
        name = norm_name(str(row.get("starter") or ""))
        if team and name:
            found[name] = team
    if Q4_PATH.is_file():
        for row in read_csv(Q4_PATH):
            team = canonical_team(str(row.get("team") or ""))
            name = norm_name(str(row.get("rb") or ""))
            if team and name and name not in found:
                found[name] = team
    if SCRATCH_PATH.is_file():
        for row in read_csv(SCRATCH_PATH):
            team = canonical_team(str(row.get("team") or ""))
            name = norm_name(str(row.get("player") or ""))
            if team and name and name not in found:
                found[name] = team
    return found


def kickoff_commence(day: date, kickoff_et: str) -> str:
    """Turn ``1:00 PM ET`` on ``day`` into a UTC ``...Z`` stamp."""

    text = kickoff_et.replace("ET", "").strip()
    parsed = datetime.strptime(text, "%I:%M %p")
    local = datetime(
        day.year,
        day.month,
        day.day,
        parsed.hour,
        parsed.minute,
        tzinfo=ZoneInfo("America/New_York"),
    )
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _game_labels() -> dict[str, str]:
    """Map a UTC commence stamp to ``AWAY@HOME`` from the starter kickoff."""

    labels: dict[str, str] = {}
    day = date.fromisoformat(SLATE_DAY)
    games: dict[str, str] = {}
    if ENV_PATH.is_file():
        for row in read_csv(ENV_PATH):
            game_id = str(row.get("game_id") or "")
            label = game_id.split("-")[-1] if game_id else ""
            team = canonical_team(str(row.get("team") or ""))
            if team and "@" in label:
                games[team] = label
    for row in _starters(STARTERS_PATH).values():
        team = canonical_team(str(row.get("team") or ""))
        label = games.get(team, "")
        kick = str(row.get("kickoff_et") or "").strip()
        if not label or not kick:
            continue
        labels[kickoff_commence(day, kick)] = label
    return labels


def _fill_team(name: str, game: str, team: str, opp: str, packet: dict[str, str]) -> tuple[str, str]:
    away, _, home = game.partition("@")
    sides = {canonical_team(away), canonical_team(home)}
    current = canonical_team(team)
    other = canonical_team(opp)
    if current in sides and other in sides and current != other:
        return current, other
    if current in sides:
        partner = (sides - {current}).pop()
        return current, partner
    candidate = packet.get(norm_name(name), "")
    if candidate in sides:
        partner = (sides - {candidate}).pop()
        return candidate, partner
    return "", ""


def widen_snapshot(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Turn a fetch slate into one row per side. Prices are copied, not invented."""

    if rows and "bookmaker" in rows[0] and "american_odds" in rows[0]:
        return rows
    games = _game_labels()
    packet = _packet_teams()
    widened: list[dict[str, str]] = []
    for row in rows:
        platform = str(row.get("platform") or "").strip().lower()
        book = PLATFORM_TO_BOOK.get(platform, "")
        if not book:
            continue
        stat = str(row.get("stat_type") or "").strip()
        market = STAT_TO_MARKET.get(stat, "")
        if not market:
            continue
        commence = str(row.get("commence_time") or "").strip()
        game = games.get(commence, "")
        if not game:
            raise LiveLinesMissingError(f"no game for commence_time {commence}")
        player = str(row.get("player_name") or "").strip()
        team, opp = _fill_team(
            player,
            game,
            str(row.get("team") or ""),
            str(row.get("opp") or ""),
            packet,
        )
        stamp = str(row.get("captured_at") or "").strip()
        over = _american_int(row.get("book_over"))
        under = _american_int(row.get("book_under"))
        line = str(row.get("line") or "").strip()
        if stat in {"anytime_td", "first_td"} or market in ONE_WAY_MARKETS:
            yes = _american_int(row.get("leg_odds"))
            if yes is None:
                yes = over
            if yes is None:
                continue
            widened.append(
                {
                    "bookmaker": book,
                    "player": player,
                    "market": market,
                    "side": "yes",
                    "line": line,
                    "american_odds": str(yes),
                    "timestamp": stamp,
                    "game": game,
                    "team": team,
                    "opp": opp,
                }
            )
            continue
        if over is None or under is None or not line:
            continue
        for side, price in (("over", over), ("under", under)):
            widened.append(
                {
                    "bookmaker": book,
                    "player": player,
                    "market": market,
                    "side": side,
                    "line": line,
                    "american_odds": str(price),
                    "timestamp": stamp,
                    "game": game,
                    "team": team,
                    "opp": opp,
                }
            )
    return widened


def write_snapshot(rows: list[dict[str, str]], path: Path | None = None) -> Path:
    target = path or LIVE_PATH
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LONG_FIELDS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return target


def snapshot_report(rows: list[dict[str, str]]) -> dict[str, object]:
    """Fail-closed facts for the Hard Rock rows. One-way markets have no line."""

    hard = [row for row in rows if row.get("bookmaker") == HR_BOOK]
    seen = {row.get("game") for row in hard}
    missing = sorted(REQUIRED_GAMES - seen)
    two_way_bad = [
        row
        for row in hard
        if row.get("market") not in ONE_WAY_MARKETS
        and (not str(row.get("line") or "").strip() or not str(row.get("american_odds") or "").strip())
    ]
    one_way_blank = [
        row
        for row in hard
        if row.get("market") in ONE_WAY_MARKETS and not str(row.get("line") or "").strip()
    ]
    prices = [str(row.get("american_odds") or "").strip() for row in hard if str(row.get("american_odds") or "").strip()]
    minus = sum(1 for price in prices if price in {"-110", "-110.0"})
    share = (minus / len(prices)) if prices else 0.0
    blocked = hard_exclude_names()
    excluded = [row for row in rows if norm_name(str(row.get("player") or "")) in blocked]
    return {
        "hard_rows": len(hard),
        "missing_games": missing,
        "two_way_bad": two_way_bad,
        "one_way_blank": len(one_way_blank),
        "minus110_share": share,
        "minus110_count": minus,
        "price_cells": len(prices),
        "excluded": excluded,
    }


@dataclass(frozen=True)
class PricedLeg:
    player: str
    team: str
    opp: str
    market: str
    side: str
    line: float | None
    model_p: float | None
    edge: float | None
    fair_american: int | None
    game_id: str
    reason: str
    note: str
    book_american: int | None = None
    book_label: str = ""
    mean: float | None = None
    n_books: int = 0
    spread: float | None = None
    kick_et: str = ""

    @property
    def leg_id(self) -> str:
        return f"{norm_name(self.player)}|{self.market}|{self.side}"

    @property
    def ok(self) -> bool:
        return self.reason == "OK"


@dataclass(frozen=True)
class FixedLeg:
    """One operator-chosen leg, exactly as the desk wrote it."""

    player: str
    game: str
    market: str
    side: str
    line: float
    american: int


@dataclass(frozen=True)
class FixedTicket:
    """One operator-chosen cross-game ticket. Nothing here is optimized."""

    ticket_id: str
    stake_cents: int
    legs: tuple[FixedLeg, FixedLeg]


# The operator's card. Do not re-rank it, do not substitute a leg, and do not
# let a search pick a leg. The desk wrote these four tickets by hand.
# ``James Cook III`` is the desk spelling while the book posts ``James Cook``;
# ``fold_name_suffix_aware`` folds the two spellings to one key.
# The ``total_q3`` leg is a team total, so its player column is the team ``BUF``.
FIXED_TICKETS: tuple[FixedTicket, ...] = (
    FixedTicket(
        "HR12-1",
        600,
        (
            FixedLeg("James Cook III", "KC@BUF", "rush_yds", "over", 82.5, -115),
            FixedLeg("CeeDee Lamb", "PHI@DAL", "rec_yds", "over", 89.5, -115),
        ),
    ),
    FixedTicket(
        "HR12-2",
        500,
        (
            FixedLeg("Patrick Mahomes", "KC@BUF", "pass_yds", "under", 236.5, -115),
            FixedLeg("Amon-Ra St. Brown", "CHI@DET", "rec_yds", "over", 82.5, -115),
        ),
    ),
    FixedTicket(
        "HR12-3",
        500,
        (
            FixedLeg("BUF", "KC@BUF", "total_q3", "under", 7.5, 100),
            FixedLeg("George Pickens", "PHI@DAL", "rec_yds", "over", 68.5, -115),
        ),
    ),
    FixedTicket(
        "HR12-4",
        400,
        (
            FixedLeg("Caleb Williams", "CHI@DET", "pass_yds", "over", 261.5, -115),
            FixedLeg("Javonte Williams", "PHI@DAL", "rush_yds", "over", 75.5, -115),
        ),
    ),
)


def _forbidden_totals(rates: dict[str, dict[str, float]] | None) -> set[float]:
    """Team totals a player mean must not equal. No slate median is added."""

    totals: set[float] = set()
    if rates:
        for row in rates.values():
            for key in ("pass_off", "rush_off", "pass_def", "rush_def"):
                totals.add(float(row[key]))
    if ENV_PATH.is_file():
        for row in read_csv(ENV_PATH):
            implied = number(row.get("implied_total"))
            if implied is not None:
                totals.add(float(implied))
    if SCRIPT_PATH.is_file():
        for row in read_csv(SCRIPT_PATH):
            for key in ("q3_pts_for_pg", "q3_pts_against_pg"):
                value = number(row.get(key))
                if value is not None:
                    totals.add(float(value))
    return totals


def assert_mean_not_team_total(player: str, mean: float, totals: set[float]) -> None:
    for total in totals:
        if abs(float(mean) - float(total)) <= MEAN_MATCH_ABS:
            raise TeamTotalAsPlayerError(
                f"{player} projected mean {float(mean):.2f} equals a team-level total {float(total):.2f}"
            )


def _env_index() -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    if not ENV_PATH.is_file():
        return found
    for row in read_csv(ENV_PATH):
        team = canonical_team(str(row.get("team") or ""))
        if team:
            found[team] = row
    return found


def _backup_tokens(text: str) -> set[str]:
    names: set[str] = set()
    for part in text.split(";"):
        cleaned = part.split("(")[0].strip()
        if cleaned:
            names.add(norm_name(cleaned))
    return names


def qb_check_failures(legs: list[PricedLeg], starters: dict[str, dict[str, str]]) -> list[str]:
    failures: list[str] = []
    for leg in legs:
        if not _needs_qb(leg.market):
            continue
        row = starters.get(leg.team)
        if row is None:
            failures.append(f"FAIL_BACKUP_QB {leg.player} {leg.team} no starter row")
            continue
        starter = norm_name(str(row.get("starter") or ""))
        backups = _backup_tokens(str(row.get("backups_hard_exclude") or ""))
        player = norm_name(leg.player)
        if player != starter or player in backups:
            failures.append(f"FAIL_BACKUP_QB {leg.player} {leg.team} starter={row.get('starter')}")
    return failures


def _needs_qb(market: str) -> bool:
    return market.startswith("pass") or market == "interceptions"


def _group_rows(rows: list[dict[str, str]]) -> dict[tuple[str, str, str], dict[str, object]]:
    grouped: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in rows:
        market = str(row.get("market") or "")
        stat = MARKET_TO_STAT.get(market)
        if stat is None or stat in {"anytime_td", "first_td"}:
            continue
        game = str(row.get("game") or "").strip()
        player = str(row.get("player") or "").strip()
        if not game or not player:
            continue
        key = (game, norm_name(player), stat)
        bucket = grouped.get(key)
        if bucket is None:
            bucket = {
                "label": player,
                "team": canonical_team(str(row.get("team") or "")),
                "opp": canonical_team(str(row.get("opp") or "")),
                "books": defaultdict(dict),
            }
            grouped[key] = bucket
        if str(row.get("bookmaker") or "") == HR_BOOK:
            bucket["label"] = player
            if row.get("team"):
                bucket["team"] = canonical_team(str(row.get("team") or ""))
            if row.get("opp"):
                bucket["opp"] = canonical_team(str(row.get("opp") or ""))
        odds = _american_int(row.get("american_odds"))
        side = str(row.get("side") or "").strip().lower()
        if side == "yes":
            side = "over"
        elif side == "no":
            side = "under"
        line = number(row.get("line"))
        if side not in {"over", "under"} or odds is None or line is None:
            continue
        book = str(row.get("bookmaker") or "").strip()
        books: dict = bucket["books"]  # type: ignore[assignment]
        line_key = round(float(line), 2)
        sides = books[book].get(line_key)
        if sides is None:
            sides = {}
            books[book][line_key] = sides
        sides.setdefault(side, odds)
    return grouped


def _both(sides: dict[str, int] | None) -> tuple[int, int] | None:
    if not sides or "over" not in sides or "under" not in sides:
        return None
    return int(sides["over"]), int(sides["under"])


def _hr_line(books: dict) -> float | None:
    lines = books.get(HR_BOOK) or {}
    both = [line for line, sides in lines.items() if _both(sides)]
    if not both:
        return None
    return float(sorted(both, key=lambda line: (abs(line), line))[0])


def _same_line_quotes(books: dict, line: float) -> list[BookQuote]:
    quotes: list[BookQuote] = []
    for book, lines in books.items():
        if book in HR_FAMILY:
            continue
        pair = _both(lines.get(round(line, 2)))
        if pair is None:
            continue
        quotes.append(BookQuote(book=book, odds_over=pair[0], odds_under=pair[1]))
    return quotes


def _shift_books(books: dict, hr_line: float, market: str) -> list[tuple[str, float, int, int]]:
    from ceminiparlays.week11_card import SHIFT_BAND

    band = SHIFT_BAND.get(market, 0.0)
    found: list[tuple[str, float, int, int]] = []
    for book, lines in books.items():
        if book in HR_FAMILY:
            continue
        for line, sides in lines.items():
            pair = _both(sides)
            if pair is None:
                continue
            if abs(float(line) - hr_line) > band + 1e-9:
                continue
            found.append((book, float(line), pair[0], pair[1]))
    return found


def _fair_at_line(
    player: str,
    market: str,
    books: dict,
    totals: set[float],
) -> tuple[float | None, float | None, str, int, str, float | None]:
    hr_line = _hr_line(books)
    if hr_line is None:
        return None, None, "", 0, "NO_HARDROCK_LINE", None
    quotes = _same_line_quotes(books, hr_line)
    if len(quotes) >= 2:
        consensus = consensus_fair_p_over(quotes, target_book="hardrock")
        if consensus is None or consensus.n_books < 2:
            return None, None, "", 0, "NO_CONSENSUS", hr_line
        names = ",".join(sorted(set(consensus.books)))
        note = f"SAME_LINE_DEVIG n={consensus.n_books} books={names}"
        return consensus.fair_p_over, None, "same_line", consensus.n_books, note, hr_line
    if market in YARD_MARKETS:
        try:
            p_over, mean, count = shift_fair_over(
                player,
                market,
                hr_line,
                _shift_books(books, hr_line, market),
                totals,
            )
        except TeamTotalAsPlayerError:
            raise
        except ValueError as exc:
            text = str(exc)
            if text.startswith("sigma"):
                return None, None, "sigma_floor", 0, "SHIFT_SIGMA_FLOOR", hr_line
            return None, None, "", 0, "NO_CONSENSUS", hr_line
        assert_mean_not_team_total(player, mean, totals)
        note = f"LINE_SHIFT_DEVIG n={count} median={mean:.2f} line={hr_line:.2f}"
        return p_over, mean, "line_shift", count, note, hr_line
    return None, None, "", 0, "NO_CONSENSUS", hr_line


def _apply_edge(
    p_over: float,
    side: str,
    odds_over: int | None,
    odds_under: int | None,
) -> tuple[float | None, int | None, int | None]:
    price = odds_over if side == "over" else odds_under
    if price is None:
        return None, None, None
    prob = p_over if side == "over" else 1.0 - p_over
    if not 0.0 < prob < 1.0:
        return None, price, None
    return leg_ev(prob, price), price, fair_american(prob)


def _reason_for(exclusion: str, method: str, edge: float | None) -> str:
    if exclusion:
        return exclusion
    if method == "sigma_floor":
        return "SHIFT_SIGMA_FLOOR"
    if method not in {"same_line", "line_shift"} or edge is None:
        return "NO_CONSENSUS"
    if edge <= 0.0:
        return "NEGATIVE_EV"
    return "OK"


def _exclusion(
    name: str,
    market: str,
    team: str,
    blocked: set[str],
    hard: set[str],
    starters: dict[str, dict[str, str]],
    player: str,
) -> str:
    if name in hard or name in blocked:
        return "HARD_EXCLUDE"
    if _needs_qb(market):
        if not team:
            return "UNKNOWN_QB"
        row = starters.get(team)
        if row is None:
            return "UNKNOWN_QB"
        starter = norm_name(str(row.get("starter") or ""))
        backups = _backup_tokens(str(row.get("backups_hard_exclude") or ""))
        if name != starter or name in backups:
            return "FAIL_BACKUP_QB"
    if team == "DAL" and market.startswith("rush") and _is_quarter(market):
        return "BENCH_BLOWOUT_RISK"
    return ""


def _as_evaluated(leg: PricedLeg) -> EvaluatedLeg:
    over = leg.book_american if leg.side == "over" else None
    under = leg.book_american if leg.side == "under" else None
    row = LineRow(
        slate_id=SLATE_DAY,
        platform="hardrock",
        player_name=leg.player,
        player_key=norm_name(leg.player),
        team=leg.team,
        opponent=leg.opp,
        stat_type=leg.market,
        line=0.0 if leg.line is None else float(leg.line),
        side=leg.side,
        line_type="quarter" if _is_quarter(leg.market) else "standard",
        captured_at="",
        displayed_multiplier=None,
        injury_status="",
        book_over=over,
        book_under=under,
    )
    return EvaluatedLeg(
        line=row,
        fair_p=float(leg.model_p or 0.0),
        implied_p=0.0,
        edge=float(leg.edge or 0.0),
        source="week12",
        family="",
        median=float(leg.mean or 0.0),
        warn="",
    )


def _script_block(leg: PricedLeg, environment: object) -> str:
    probed = _as_evaluated(leg)
    if bench_blowout_q4_blocked(probed, environment):  # type: ignore[arg-type]
        return "BENCH_BLOWOUT_RISK"
    if q4_reception_direction_blocked(probed, environment):  # type: ignore[arg-type]
        return "Q4_DIRECTION"
    if (
        leg.team == "BUF"
        and leg.market.startswith("rush")
        and _is_quarter(leg.market)
        and (leg.line is None or leg.book_american is None)
    ):
        return "NO_HARDROCK_LINE"
    return ""


def price_board(rows: list[dict[str, str]]) -> dict[str, PricedLeg]:
    """Price both sides from live two-way markets. Team rates are not a mean."""

    rates = load_team_rates(RATES_PATH)
    if rates is None and not any(item.endswith("NO_TEAM_RATES_FILE") for item in RATE_DROPS):
        RATE_DROPS.append("team_rates file absent; no player mean used a team rate NO_TEAM_RATES_FILE")
    totals = _forbidden_totals(rates)
    blocked = _blocked_names(SCRATCH_PATH)
    hard = hard_exclude_names()
    starters = _starters(STARTERS_PATH)
    env_rows = _env_index()
    environment = read_environment(ENV_PATH)
    pool: dict[str, PricedLeg] = {}
    for (game, name, stat), bucket in _group_rows(rows).items():
        label = str(bucket["label"])
        books = bucket["books"]
        team = canonical_team(str(bucket.get("team") or ""))
        opp = canonical_team(str(bucket.get("opp") or ""))
        away, _, home = game.partition("@")
        if stat == "total_q3":
            team = canonical_team(away)
            opp = canonical_team(home)
            label = game.replace("@", " at ")
        meta = env_rows.get(team) or env_rows.get(canonical_team(home)) or {}
        game_id = str(meta.get("game_id") or f"{SLATE_DAY}-{game}")
        kick = str((starters.get(team) or starters.get(canonical_team(home)) or {}).get("kickoff_et") or "")
        spread = number((env_rows.get(team) or {}).get("spread"))
        exclusion = _exclusion(name, stat, team, blocked, hard, starters, label)
        try:
            p_over, mean, method, n_books, note, line = _fair_at_line(label, stat, books, totals)
        except TeamTotalAsPlayerError as exc:
            for side in ("over", "under"):
                leg = PricedLeg(
                    player=label,
                    team=team,
                    opp=opp,
                    market=stat,
                    side=side,
                    line=None,
                    model_p=None,
                    edge=None,
                    fair_american=None,
                    game_id=game_id,
                    reason="TEAM_TOTAL_MEAN",
                    note=str(exc),
                    spread=spread,
                    kick_et=kick,
                )
                pool[leg.leg_id] = leg
            continue
        if line is None:
            continue
        sides = (books.get(HR_BOOK) or {}).get(round(line, 2)) if isinstance(books, dict) else None
        pair = _both(sides)
        odds_over, odds_under = (None, None) if pair is None else pair
        if odds_over is None or odds_under is None:
            continue
        for side in ("over", "under"):
            edge, price, fair = (None, None, None)
            prob = None
            if p_over is not None:
                prob = p_over if side == "over" else 1.0 - p_over
                edge, price, fair = _apply_edge(p_over, side, odds_over, odds_under)
            reason = _reason_for(exclusion, method, edge)
            leg = PricedLeg(
                player=label,
                team=team,
                opp=opp,
                market=stat,
                side=side,
                line=line,
                model_p=prob,
                edge=edge,
                fair_american=fair,
                game_id=game_id,
                reason=reason,
                note=note,
                book_american=price,
                book_label=f"hardrockbet {_american(price)}".strip(),
                mean=mean,
                n_books=n_books,
                spread=spread,
                kick_et=kick,
            )
            script = _script_block(leg, environment)
            if script and reason in {"OK", "NEGATIVE_EV"}:
                leg = PricedLeg(
                    player=leg.player,
                    team=leg.team,
                    opp=leg.opp,
                    market=leg.market,
                    side=leg.side,
                    line=leg.line,
                    model_p=leg.model_p,
                    edge=leg.edge,
                    fair_american=leg.fair_american,
                    game_id=leg.game_id,
                    reason=script,
                    note=leg.note,
                    book_american=leg.book_american,
                    book_label=leg.book_label,
                    mean=leg.mean,
                    n_books=leg.n_books,
                    spread=leg.spread,
                    kick_et=leg.kick_et,
                )
            pool[leg.leg_id] = leg
    return pool


def pricing_source(leg: PricedLeg) -> str:
    note = leg.note
    if "LINE_SHIFT_DEVIG" in note:
        return "LINE_SHIFT_DEVIG"
    if "SAME_LINE_DEVIG" in note:
        return "SAME_LINE_DEVIG"
    return ""


def _pair_corr(legs: list[PricedLeg]):
    refs = [
        LegRef(
            player_key=norm_name(leg.player),
            team=leg.team,
            opponent=leg.opp,
            stat_type=leg.market,
            side=leg.side,
        )
        for leg in legs
    ]
    return correlation_matrix(refs)


def _max_off_diag(corr) -> float:
    size = int(corr.shape[0])
    best = 0.0
    for left in range(size):
        for right in range(left + 1, size):
            best = max(best, float(corr[left, right]))
    return best


def _try_ticket(legs: list[PricedLeg]) -> dict[str, object] | None:
    if not MIN_LEGS <= len(legs) <= MAX_LEGS:
        return None
    if len({norm_name(leg.player) for leg in legs}) < len(legs):
        return None
    if any(not leg.team or not leg.opp for leg in legs):
        return None
    if len({leg.game_id for leg in legs}) != 1:
        return None
    prices = [int(leg.book_american or 0) for leg in legs]
    if any(price == 0 for price in prices):
        return None
    marginals = [float(leg.model_p or 0.0) for leg in legs]
    if any(not 0.0 < prob < 1.0 for prob in marginals):
        return None
    try:
        corr = _pair_corr(legs)
    except UnmodeledCorrelationError:
        return None
    joint = joint_ticket(marginals, prices, corr)
    taxed = bool(joint["sgp_tax_applied"])
    ev = float(joint["tax_adjusted_sgp_ev"] if taxed else joint["joint_ev"])
    used_decimal = float(joint["decimal_sgp"] if taxed else joint["decimal"])
    max_rho = _max_off_diag(corr)
    if max_rho <= 0.0:
        return None
    return {
        "legs": legs,
        "joint_p": float(joint["joint_p"]),
        "gaussian_joint_p": float(joint["gaussian_joint_p"]),
        "t_copula_joint_p": float(joint["t_copula_joint_p"]),
        "fair_american": fair_american(float(joint["joint_p"])),
        "live_american": _legal_american(decimal_to_american(used_decimal)),
        "ev": ev,
        "same_game": True,
        "sgp_tax": taxed,
        "max_rho": max_rho,
        "unmodeled": False,
        "stake_cents": 0,
        "best_available": ev <= 0.0,
    }


def _eligible(leg: PricedLeg) -> bool:
    if leg.reason not in {"OK", "NEGATIVE_EV"}:
        return False
    if not pricing_source(leg):
        return False
    if leg.model_p is None or leg.book_american is None or leg.line is None:
        return False
    if not leg.team or not leg.opp or not leg.game_id:
        return False
    if not 0.0 < float(leg.model_p) < 1.0:
        return False
    if leg.edge is None or leg.edge < EDGE_FLOOR:
        return False
    if norm_name(leg.player) in hard_exclude_names():
        return False
    return True


def _best_sides(pool: dict[str, PricedLeg]) -> list[PricedLeg]:
    found: dict[tuple[str, str, str], PricedLeg] = {}
    for leg in pool.values():
        if not _eligible(leg):
            continue
        key = (leg.game_id, norm_name(leg.player), leg.market)
        current = found.get(key)
        if current is None or (leg.edge or -9.0) > (current.edge or -9.0):
            found[key] = leg
    return list(found.values())


def _ticket_name(ticket: dict[str, object]) -> tuple[str, ...]:
    legs = ticket["legs"]
    assert isinstance(legs, list)
    return tuple(f"{leg.player}|{leg.market}|{leg.side}" for leg in legs)


def _candidate_tickets(pool: dict[str, PricedLeg]) -> list[dict[str, object]]:
    by_game: dict[str, list[PricedLeg]] = defaultdict(list)
    for leg in _best_sides(pool):
        by_game[leg.game_id].append(leg)
    found: list[dict[str, object]] = []
    for legs in by_game.values():
        ordered = sorted(legs, key=lambda leg: (-(leg.edge or -9.0), leg.player, leg.market))
        ordered = ordered[:LEGS_PER_GAME]
        for size in (2, 3):
            for combo in combinations(ordered, size):
                ticket = _try_ticket(list(combo))
                if ticket is not None:
                    found.append(ticket)
    found.sort(key=lambda ticket: (-float(ticket["ev"]), _ticket_name(ticket)))
    return found


def _q4_rec_count(legs: list[PricedLeg]) -> int:
    return sum(1 for leg in legs if leg.market == "receptions_q4")


def _card_q4_rec(tickets: list[dict[str, object]]) -> int:
    total = 0
    for ticket in tickets:
        legs = ticket["legs"]
        assert isinstance(legs, list)
        total += _q4_rec_count(legs)
    return total


def _pack(cands: list[dict[str, object]], *, allow_q4_rec: bool) -> list[dict[str, object]]:
    chosen: list[dict[str, object]] = []
    used: set[str] = set()
    q4_rec = 0
    quarter_markets: set[str] = set()
    for ticket in cands:
        legs = ticket["legs"]
        assert isinstance(legs, list)
        players = {norm_name(leg.player) for leg in legs}
        if players & used:
            continue
        rec = _q4_rec_count(legs)
        if rec and not allow_q4_rec:
            continue
        if q4_rec + rec > RECEPTIONS_Q4_CAP:
            continue
        stats = {leg.market for leg in legs if _is_quarter(leg.market)}
        if stats & quarter_markets:
            continue
        used |= players
        q4_rec += rec
        quarter_markets |= stats
        chosen.append(ticket)
        if len(chosen) == TICKET_COUNT:
            break
    return chosen


def _choose_pack(cands: list[dict[str, object]]) -> list[dict[str, object]]:
    """Fill +EV tickets first. Prefer zero ``receptions_q4`` legs."""

    plus = [ticket for ticket in cands if float(ticket["ev"]) > 0.0]
    rest = [ticket for ticket in cands if float(ticket["ev"]) <= 0.0]
    ordered = plus + rest
    clean = _pack(ordered, allow_q4_rec=False)
    if len(clean) >= TICKET_COUNT:
        return clean[:TICKET_COUNT]
    mixed = _pack(ordered, allow_q4_rec=True)
    if len(mixed) > len(clean):
        return mixed[:TICKET_COUNT]
    return clean


def assign_stakes(tickets: list[dict[str, object]]) -> None:
    """Whole-dollar stakes from $4 to $6. The four stakes sum to $20."""

    if len(tickets) != TICKET_COUNT:
        raise ValueError(f"need {TICKET_COUNT} tickets to sum to $20.00, found {len(tickets)}")
    ordered = sorted(tickets, key=lambda ticket: (-float(ticket["ev"]), _ticket_name(ticket)))
    pool = list(STAKE_POOL)
    spent: dict[str, int] = defaultdict(int)
    for ticket in ordered:
        legs = ticket["legs"]
        assert isinstance(legs, list)
        stats = {leg.market for leg in legs if _is_quarter(leg.market)}
        chosen: int | None = None
        for stake in sorted(pool, reverse=True):
            if any(spent[stat] + stake > QUARTER_CAP_CENTS for stat in stats):
                continue
            chosen = stake
            break
        if chosen is None:
            raise ValueError("quarter-market stake cap blocks every stake")
        pool.remove(chosen)
        ticket["stake_cents"] = chosen
        for stat in stats:
            spent[stat] += chosen
    if sum(int(ticket["stake_cents"]) for ticket in tickets) != BANKROLL_CENTS:
        raise ValueError("stakes do not sum to 2000 cents")


def _validate_tickets(tickets: list[dict[str, object]], totals: set[float]) -> None:
    if not MIN_TICKETS <= len(tickets) <= MAX_TICKETS:
        raise ValueError(f"ticket count {len(tickets)} is outside 3 to 4")
    stakes = [int(ticket["stake_cents"]) for ticket in tickets]
    if sum(stakes) != BANKROLL_CENTS:
        raise ValueError(f"stake sum {sum(stakes)} is not {BANKROLL_CENTS}")
    if any(stake < 400 or stake > 600 or stake % 100 for stake in stakes):
        raise ValueError(f"ticket stake is outside $4 to $6: {stakes}")
    reuse: dict[tuple[str, str, str], int] = defaultdict(int)
    q4_rec = 0
    quarter: dict[str, int] = defaultdict(int)
    hard = hard_exclude_names()
    for ticket in tickets:
        legs = ticket["legs"]
        assert isinstance(legs, list)
        if not MIN_LEGS <= len(legs) <= MAX_LEGS:
            raise ValueError("a ticket must have 2 or 3 legs")
        for leg in legs:
            key = (norm_name(leg.player), leg.market, leg.side)
            reuse[key] += 1
            if norm_name(leg.player) in hard:
                raise ValueError(f"hard-excluded player on the card: {leg.player}")
            if leg.market == "receptions_q4":
                q4_rec += 1
            if _is_quarter(leg.market):
                quarter[leg.market] += int(ticket["stake_cents"])
            if leg.mean is not None:
                assert_mean_not_team_total(leg.player, float(leg.mean), totals)
            if leg.line is None or leg.book_american is None or leg.fair_american is None:
                raise ValueError(f"leg is missing a live price: {leg.player} {leg.market}")
    if any(count > MAX_LEG_REUSE for count in reuse.values()):
        raise ValueError("a leg is on more than one ticket")
    if q4_rec > RECEPTIONS_Q4_CAP:
        raise ValueError("more than one receptions_q4 leg")
    if any(cents > QUARTER_CAP_CENTS for cents in quarter.values()):
        raise ValueError("a quarter market is above 25 percent of the stake")


def build_tickets(pool: dict[str, PricedLeg]) -> list[dict[str, object]]:
    """Pick four correlated same-game tickets. +EV fills first.

    The Week 12 card does not call this. ``build_fixed_card`` writes that card,
    because the operator rejected an optimizer-chosen card. This search stays
    for a same-game card, and it keeps the SGP-tax joint price reachable.

    Three tickets cannot sum to $20 when each stake is $4 to $6.
    A ticket with EV at or under zero is marked ``[BEST_AVAILABLE_CORRELATED_SGP]``.
    The EV number is the copula joint. It is not replaced.
    """

    rates = load_team_rates(RATES_PATH)
    totals = _forbidden_totals(rates)
    plus_legs = [leg for leg in pool.values() if leg.ok and leg.edge is not None and leg.edge > 0.0]
    cands = _candidate_tickets(pool)
    LAST_SCAN["plus_legs"] = len(plus_legs)
    LAST_SCAN["priced_tickets"] = len(cands)
    LAST_SCAN["plus_tickets"] = sum(1 for ticket in cands if float(ticket["ev"]) > 0.0)
    chosen = _choose_pack(cands)
    if len(chosen) < TICKET_COUNT:
        raise ValueError(
            f"only {len(chosen)} correlated tickets; need {TICKET_COUNT} to stake $20.00"
        )
    for ticket in chosen:
        ticket["best_available"] = float(ticket["ev"]) <= 0.0
    assign_stakes(chosen)
    ordered = sorted(
        chosen,
        key=lambda ticket: (-int(ticket["stake_cents"]), -float(ticket["ev"]), _ticket_name(ticket)),
    )
    for index, ticket in enumerate(ordered, start=1):
        ticket["ticket_id"] = f"HR12-{index}"
    _validate_tickets(ordered, totals)
    return ordered


def raw_game_label(game_id: object) -> str:
    """``2026-11-26-KC@BUF`` becomes ``KC@BUF``. A bare label is left as it is."""

    text = str(game_id or "").strip()
    prefix = f"{SLATE_DAY}-"
    return text[len(prefix) :] if text.startswith(prefix) else text


def _leg_key(
    game: str,
    player_key: str,
    market: str,
    side: str,
    line: float,
) -> tuple[str, str, str, str, float]:
    return (game, player_key, market, side.strip().lower(), round(float(line), 2))


def _player_key(market: str, player: str) -> str:
    """A team total has no player. It folds to one empty key, not a name."""

    if market == "total_q3":
        return ""
    return fold_name_suffix_aware(player)


def snapshot_leg_index(rows: list[dict[str, str]]) -> dict[tuple, dict[str, str]]:
    """Index the posted hardrockbet rows by game, player key, market, side, and line.

    The index holds one row per leg. Two hardrockbet rows for one leg raise,
    because the card needs one posted price and not a choice of two.
    """

    index: dict[tuple, dict[str, str]] = {}
    for row in rows:
        if str(row.get("bookmaker") or "").strip() != HR_BOOK:
            continue
        market = MARKET_TO_STAT.get(str(row.get("market") or ""), "")
        side = str(row.get("side") or "").strip().lower()
        line = number(row.get("line"))
        game = str(row.get("game") or "").strip()
        player = str(row.get("player") or "").strip()
        if not market or side not in {"over", "under"} or line is None:
            continue
        if not game or not player:
            continue
        key = _leg_key(game, _player_key(market, player), market, side, float(line))
        if key in index:
            raise FixedCardError(f"two hardrockbet rows for one leg: {key}")
        index[key] = {**row, "market": market}
    return index


def resolve_leg_row(spec: FixedLeg, index: dict[tuple, dict[str, str]]) -> dict[str, str]:
    """The one posted hardrockbet row for a fixed leg.

    A missing row raises. A posted price that is not the card price raises.
    A price is never adjusted to fit the card.
    """

    key = _leg_key(spec.game, _player_key(spec.market, spec.player), spec.market, spec.side, spec.line)
    row = index.get(key)
    if row is None:
        raise FixedCardError(
            f"{spec.player} {spec.game} {spec.market} {spec.side} {spec.line:.2f} "
            "has no hardrockbet row"
        )
    posted = _american_int(row.get("american_odds"))
    if posted is None:
        raise FixedCardError(f"{spec.player} {spec.market} {spec.side} has no posted price")
    if posted != int(spec.american):
        raise FixedCardError(
            f"{spec.player} {spec.market} {spec.side} is posted at {_american(posted)}, "
            f"not the card price {_american(int(spec.american))}"
        )
    return row


def model_reference(spec: FixedLeg, pool: dict[str, PricedLeg]) -> PricedLeg | None:
    """The de-vig row for a fixed leg, when the board priced it.

    It is a model reference only. The price on the card is the posted price.
    """

    for leg in pool.values():
        if leg.market != spec.market or leg.side != spec.side:
            continue
        if raw_game_label(leg.game_id) != spec.game:
            continue
        if leg.line is None or round(float(leg.line), 2) != round(float(spec.line), 2):
            continue
        if spec.market == "total_q3":
            return leg
        if fold_name_suffix_aware(leg.player) == fold_name_suffix_aware(spec.player):
            return leg
    return None


def card_leg(spec: FixedLeg, row: dict[str, str], pool: dict[str, PricedLeg]) -> PricedLeg:
    """One card leg: the posted row, plus the de-vig model price as a reference."""

    model = model_reference(spec, pool)
    market = spec.market
    player = spec.player if market == "total_q3" else str(row.get("player") or spec.player).strip()
    if model is not None and model.note:
        note = f"MODEL_REFERENCE {model.note}"
    elif model is not None:
        note = "MODEL_REFERENCE none"
    else:
        note = "MODEL_REFERENCE none: the saved board has no de-vig price for this leg"
    return PricedLeg(
        player=player,
        team=canonical_team(str(row.get("team") or "")),
        opp=canonical_team(str(row.get("opp") or "")),
        market=market,
        side=spec.side,
        line=round(float(spec.line), 2),
        model_p=None if model is None else model.model_p,
        edge=None if model is None else model.edge,
        fair_american=None if model is None else model.fair_american,
        game_id=f"{SLATE_DAY}-{spec.game}",
        reason="OK",
        note=note,
        book_american=int(spec.american),
        book_label=f"{HR_BOOK} {_american(int(spec.american))}".strip(),
        mean=None,
        n_books=0 if model is None else model.n_books,
        spread=None if model is None else model.spread,
        kick_et="" if model is None else model.kick_et,
    )


def product_decimal(legs: list[PricedLeg]) -> float:
    """The product of the posted leg prices. It is an estimate, not a quote."""

    total = 1.0
    for leg in legs:
        if leg.book_american is None:
            raise FixedCardError(f"leg has no posted price: {leg.player} {leg.market}")
        total *= american_to_decimal(int(leg.book_american))
    return total


def fair_parlay_american(legs: list[PricedLeg]) -> int | None:
    """The de-vig model fair price for the cross-game joint, or None.

    None when any leg has no de-vig price. A missing model price is never
    filled with a guess, and the product is labelled a model reference.
    """

    joint = 1.0
    for leg in legs:
        if leg.model_p is None or not 0.0 < float(leg.model_p) < 1.0:
            return None
        joint *= float(leg.model_p)
    if not 0.0 < joint < 1.0:
        return None
    return fair_american(joint)


def build_fixed_card(
    rows: list[dict[str, str]],
    pool: dict[str, PricedLeg] | None = None,
) -> list[dict[str, object]]:
    """The four operator tickets, resolved to the saved board.

    No leg is ranked, substituted, or searched for. ``ticket_ev`` stays empty
    because the ticket price is only the product of two posted leg prices.
    """

    board = pool if pool is not None else {}
    index = snapshot_leg_index(rows)
    tickets: list[dict[str, object]] = []
    seen: set[str] = set()
    for spec in FIXED_TICKETS:
        legs: list[PricedLeg] = []
        for folder in spec.legs:
            leg = card_leg(folder, resolve_leg_row(folder, index), board)
            if leg.leg_id in seen:
                raise FixedCardError(f"a leg is reused on the card: {leg.player} {leg.market}")
            seen.add(leg.leg_id)
            legs.append(leg)
        if len({leg.game_id for leg in legs}) != len(legs):
            raise FixedCardError(f"{spec.ticket_id} is not a cross-game ticket")
        tickets.append(
            {
                "ticket_id": spec.ticket_id,
                "stake_cents": int(spec.stake_cents),
                "legs": legs,
                "live_american": _legal_american(decimal_to_american(product_decimal(legs))),
                "fair_american": fair_parlay_american(legs),
                "ev": None,
                "pricing_source": UNQUOTED_PARLAY_ESTIMATE,
                "same_game": False,
                "cross_game": True,
                # No copula joint is modeled across two games.
                "sgp_tax": False,
                "unmodeled": True,
                "gaussian_joint_p": None,
                "t_copula_joint_p": None,
            }
        )
    validate_fixed_card(tickets)
    return tickets


def validate_fixed_card(tickets: list[dict[str, object]]) -> None:
    """Fail closed on every card rule. Nothing an optimizer wrote can pass."""

    if len(tickets) != TICKET_COUNT:
        raise FixedCardError(f"the card needs {TICKET_COUNT} tickets, found {len(tickets)}")
    stakes = [int(ticket["stake_cents"]) for ticket in tickets]
    if sum(stakes) != BANKROLL_CENTS:
        raise FixedCardError(f"stake sum {sum(stakes)} cents is not {BANKROLL_CENTS}")
    if stakes != list(STAKE_POOL):
        raise FixedCardError(f"stakes {stakes} are not the operator's {list(STAKE_POOL)}")
    hard = hard_exclude_names()
    reuse: dict[str, int] = defaultdict(int)
    quarter: dict[str, int] = defaultdict(int)
    quarter_legs = 0
    legs_total = 0
    for ticket in tickets:
        legs = ticket["legs"]
        assert isinstance(legs, list)
        if len(legs) != 2:
            raise FixedCardError(f"{ticket['ticket_id']} has {len(legs)} legs, not 2")
        if ticket.get("pricing_source") != UNQUOTED_PARLAY_ESTIMATE:
            raise FixedCardError(f"{ticket['ticket_id']} is not priced as an unquoted estimate")
        if ticket.get("ev") is not None:
            raise FixedCardError(
                f"{ticket['ticket_id']} claims an EV from a product of leg prices"
            )
        if len({leg.game_id for leg in legs}) != 2:
            raise FixedCardError(f"{ticket['ticket_id']} is not cross-game")
        for leg in legs:
            legs_total += 1
            reuse[leg.leg_id] += 1
            if norm_name(leg.player) in hard:
                raise FixedCardError(f"banned player on the card: {leg.player}")
            if norm_name(leg.player) == "josh allen" or fold_name_suffix_aware(leg.player) == "josh_allen":
                raise FixedCardError(f"a Josh Allen leg is not allowed: {leg.player}")
            if leg.market == "receptions_q4":
                raise FixedCardError("a receptions_q4 leg is not allowed")
            if _is_quarter(leg.market):
                quarter_legs += 1
                if leg.market != "total_q3":
                    raise FixedCardError(
                        f"a quarter market other than total_q3 is not allowed: {leg.market}"
                    )
                quarter[leg.market] += int(ticket["stake_cents"])
            if raw_game_label(leg.game_id) == "CHI@DET" and leg.side == "under":
                raise FixedCardError(f"a CHI@DET under is not allowed: {leg.player} {leg.market}")
            if leg.line is None or leg.book_american is None:
                raise FixedCardError(f"leg is missing a live price: {leg.player} {leg.market}")
    if legs_total != 8:
        raise FixedCardError(f"the card has {legs_total} legs, not 8")
    if len(reuse) != 8:
        raise FixedCardError("the eight legs are not eight distinct legs")
    if any(count > MAX_LEG_REUSE for count in reuse.values()):
        raise FixedCardError("a leg is on more than one ticket")
    if quarter_legs != 1:
        raise FixedCardError(f"the card carries {quarter_legs} quarter-market legs, not 1")
    if any(cents > QUARTER_CAP_CENTS for cents in quarter.values()):
        raise FixedCardError("the quarter market is above the $5.00 cap")


def card_legs(tickets: list[dict[str, object]]) -> list[PricedLeg]:
    """The eight legs in card order."""

    found: list[PricedLeg] = []
    for ticket in tickets:
        legs = ticket["legs"]
        assert isinstance(legs, list)
        found.extend(legs)
    return found


def decision_legs(pool: dict[str, PricedLeg]) -> list[PricedLeg]:
    ranked = [
        leg
        for leg in pool.values()
        if leg.reason not in {"HARD_EXCLUDE", "FAIL_BACKUP_QB", "UNKNOWN_QB", "TEAM_TOTAL_MEAN"}
        and leg.edge is not None
        and leg.book_american is not None
        and leg.line is not None
        and leg.fair_american is not None
        and pricing_source(leg)
    ]
    ranked.sort(key=lambda leg: (-(leg.edge or 0.0), leg.player, leg.market, leg.side))
    return ranked[:20]


def format_leg_table(legs: list[PricedLeg]) -> str:
    header = "Player | Team | Market | Side | Exact HR Line | HR Odds | Fair Odds | Edge % | Pricing Method"
    lines = [header, " | ".join(["---"] * 9)]
    for leg in legs:
        line = "" if leg.line is None else f"{leg.line:.2f}"
        edge = "" if leg.edge is None else f"{leg.edge * 100:.2f}%"
        lines.append(
            " | ".join(
                [
                    leg.player,
                    leg.team,
                    leg.market,
                    leg.side,
                    line,
                    _american(leg.book_american),
                    _american(leg.fair_american),
                    edge,
                    pricing_source(leg),
                ]
            )
        )
    return "\n".join(lines)


def _leg_phrase(leg: PricedLeg) -> str:
    line = "n/a" if leg.line is None else f"{leg.line:.2f}"
    price = _american(leg.book_american) or "n/a"
    return f"{leg.player} {leg.market} {leg.side} {line} (HR {price})"


def _ticket_sources(ticket: dict[str, object]) -> str:
    """The ticket price source. A fixed card is an unquoted product.

    A same-game ticket still reports its de-vig legs, the copula joint, and
    the SGP tax, so the existing same-game path is not disabled.
    """

    source = str(ticket.get("pricing_source") or "")
    if source:
        return source
    sources: list[str] = []
    legs = ticket["legs"]
    assert isinstance(legs, list)
    for leg in legs:
        leg_source = pricing_source(leg)
        if leg_source and leg_source not in sources:
            sources.append(leg_source)
    sources.append("COPULA")
    if ticket.get("sgp_tax"):
        sources.append("SGP_TAX")
    if ticket.get("best_available"):
        sources.append("[BEST_AVAILABLE_CORRELATED_SGP]")
    return "+".join(sources)


def _ticket_ev_text(ticket: dict[str, object]) -> str:
    """An unquoted product never prints a market EV. It prints the label."""

    if str(ticket.get("pricing_source") or "") == UNQUOTED_PARLAY_ESTIMATE:
        return UNQUOTED_PARLAY_ESTIMATE
    ev = ticket.get("ev")
    if ev is None:
        return ""
    return f"{float(ev) * 100:.2f}%"


def _ticket_fair_text(ticket: dict[str, object]) -> str:
    fair = ticket.get("fair_american")
    if fair is None:
        return ""
    return _american(int(fair))


def format_ticket_table(tickets: list[dict[str, object]]) -> str:
    header = (
        "Ticket | Stake | Exact HR Legs & Odds | Pricing Source | "
        "Est. HR Parlay Odds | Fair Parlay Odds (model) | EV"
    )
    lines = [header, " | ".join(["---"] * 7)]
    for ticket in tickets:
        legs = ticket["legs"]
        assert isinstance(legs, list)
        text = "; ".join(_leg_phrase(leg) for leg in legs)
        lines.append(
            " | ".join(
                [
                    str(ticket["ticket_id"]),
                    _money(int(ticket["stake_cents"])),
                    text,
                    _ticket_sources(ticket),
                    _american(int(ticket["live_american"])),
                    _ticket_fair_text(ticket),
                    _ticket_ev_text(ticket),
                ]
            )
        )
    return "\n".join(lines)


def render_csv(tickets: list[dict[str, object]]) -> str:
    fields = [
        "ticket_id",
        "leg_num",
        "game_id",
        "kick_et",
        "player_name",
        "team",
        "opp",
        "market",
        "side",
        "line",
        "book_american_odds",
        "fair_american",
        "edge",
        "model_prob",
        "ticket_stake_usd",
        "live_parlay_american",
        "fair_parlay_american",
        "ticket_ev",
        "gaussian_joint_p",
        "t_copula_joint_p",
        "corr_unmodeled",
        "pricing_source",
        "note",
    ]
    rows: list[dict[str, str]] = []
    for ticket in tickets:
        legs = ticket["legs"]
        assert isinstance(legs, list)
        ticket_source = str(ticket.get("pricing_source") or "")
        ticket_ev = ticket.get("ev")
        for index, leg in enumerate(legs, start=1):
            # An unquoted product never carries a market EV, even if a caller
            # hands render_csv a number. The fixed-card validator also rejects it.
            ev_text = ""
            if ticket_source != UNQUOTED_PARLAY_ESTIMATE and ticket_ev is not None:
                ev_text = f"{float(ticket_ev):.4f}"
            fair = ticket.get("fair_american")
            gaussian = ticket.get("gaussian_joint_p")
            copula = ticket.get("t_copula_joint_p")
            rows.append(
                {
                    "ticket_id": str(ticket["ticket_id"]),
                    "leg_num": str(index),
                    "game_id": leg.game_id,
                    "kick_et": leg.kick_et,
                    "player_name": leg.player,
                    "team": leg.team,
                    "opp": leg.opp,
                    "market": leg.market,
                    "side": leg.side,
                    "line": "" if leg.line is None else f"{leg.line:.2f}",
                    "book_american_odds": _american(leg.book_american),
                    "fair_american": _american(leg.fair_american),
                    "edge": "" if leg.edge is None else f"{leg.edge:.4f}",
                    "model_prob": "" if leg.model_p is None else f"{leg.model_p:.4f}",
                    "ticket_stake_usd": f"{int(ticket['stake_cents']) / 100:.2f}",
                    "live_parlay_american": _american(int(ticket["live_american"])),
                    "fair_parlay_american": "" if fair is None else _american(int(fair)),
                    "ticket_ev": ev_text,
                    "gaussian_joint_p": "" if gaussian is None else f"{float(gaussian):.4f}",
                    "t_copula_joint_p": "" if copula is None else f"{float(copula):.4f}",
                    "corr_unmodeled": "yes" if ticket["unmodeled"] else "no",
                    "pricing_source": ticket_source or pricing_source(leg),
                    "note": leg.note,
                }
            )
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def render_markdown(tickets: list[dict[str, object]], pool: dict[str, PricedLeg]) -> str:
    legs = card_legs(tickets)
    drops = list(RATE_DROPS)
    model_refs = sum(1 for leg in legs if leg.model_p is not None)
    lines = [
        "# Week 12 Hard Rock card, 2026-11-26",
        "",
        "Do not submit a bet from this file. Type any ticket yourself.",
        f"Stake on this card: {_money(BANKROLL_CENTS)}.",
        "Each ticket is $4.00 to $6.00. The four stakes are $6.00, $5.00, $5.00, and $4.00.",
        "The four tickets are fixed. No optimizer chose, ranked, or substituted a leg.",
        "Each ticket is a cross-game parlay: its two legs come from two different games.",
        CROSS_GAME_PRICE_NOTE,
        "The card has 8 legs on 4 tickets. No leg is reused.",
        f"This card has {_card_q4_rec(tickets)} receptions_q4 legs.",
        "No CHI@DET under is on the card. No Josh Allen leg is on the card.",
        "The total_q3 leg is a team total: the player column is BUF and the game is KC@BUF.",
        "",
        "Prices come from config/week12/live_lines_2026-11-26.csv at the posted Hard Rock price.",
        "Fair Parlay Odds is the de-vigged model reference only. It is not market EV.",
        "A leg's Fair Odds and Edge % are model references. The posted HR price is the card price.",
        f"Card legs with a de-vig model reference: {model_refs} of {len(legs)}.",
        "",
        "Team rates file: config/week12/team_rates_2026-11-26.csv is absent.",
        "No player mean was set to zero, a league mean, or a slate median.",
        "Drops:",
    ]
    if drops:
        lines.extend(f"- {item}" for item in drops)
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Tickets",
            "",
            format_ticket_table(tickets),
            "",
            "## Legs",
            "",
            format_leg_table(legs),
            "",
            "## Checks",
            "",
            "QB check on every pass leg and interception leg must be FAIL_BACKUP_QB=0.",
            "PHI starter is Joe Milton. Jalen Hurts is IR and is not on the card.",
            "Out and IR names from config/week12/scratches_2026-11-26.csv are off.",
            "The card has zero receptions_q4 legs and one total_q3 leg.",
            "The only CHI@DET legs are Amon-Ra St. Brown over and Caleb Williams over.",
            "config/rosters/nfl.json was not rewritten.",
            "",
        ]
    )
    return "\n".join(lines)


def _shell_leg(body: str) -> str:
    """Quote one log-slip leg. A name with an apostrophe stays one argument."""

    if any(char in body for char in "\"\\$`"):
        return shlex.quote(body)
    return f'"{body}"'


def log_slip_commands(tickets: list[dict[str, object]]) -> str:
    """Template only. Odds stay blank until the operator types the in-app price."""

    lines = [
        "Do not run these until you type the in-app American parlay price in place of the blank odds.",
    ]
    for ticket in tickets:
        legs = ticket["legs"]
        assert isinstance(legs, list)
        stake = f"{int(ticket['stake_cents']) / 100:.2f}"
        parts = [
            "PYTHONPATH=src python3 -m ceminiparlays log-slip",
            "--date 2026-11-26",
            "--starters config/week12/qb_starters_2026-11-26.csv",
            "--scratches config/week12/scratches_2026-11-26.csv",
            "--sync-dirs parlays-slate parlays-recap",
            f"--ticket-id {ticket['ticket_id']}",
        ]
        for leg in legs:
            line = "" if leg.line is None else f"{leg.line:.2f}"
            body = f"{leg.player}|{leg.market}|{leg.side}|{line}||{stake}"
            parts.append("--leg " + _shell_leg(body))
        lines.append(" ".join(parts))
    return "\n".join(lines)


def render_slip_csv(tickets: list[dict[str, object]]) -> str:
    """The eight typed legs, one per row. The stake repeats on both legs."""

    rows: list[dict[str, str]] = []
    for ticket in tickets:
        legs = ticket["legs"]
        assert isinstance(legs, list)
        stake = f"{int(ticket['stake_cents']) / 100:.2f}"
        for leg in legs:
            if leg.book_american is None or leg.line is None:
                raise FixedCardError(f"leg has no posted price: {leg.player} {leg.market}")
            rows.append(
                {
                    "ticket_id": str(ticket["ticket_id"]),
                    "player": leg.player,
                    "market": leg.market,
                    "side": leg.side,
                    "line": f"{float(leg.line):.2f}",
                    "book_american_odds": str(int(leg.book_american)),
                    "stake": stake,
                }
            )
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(SLIP_FIELDS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def write_card(pool: dict[str, PricedLeg], tickets: list[dict[str, object]]) -> list[Path]:
    CARD_CSV.parent.mkdir(parents=True, exist_ok=True)
    CARD_CSV.write_text(render_csv(tickets), encoding="utf-8")
    CARD_MD.write_text(render_markdown(tickets, pool), encoding="utf-8")
    SLIP_CSV.write_text(render_slip_csv(tickets), encoding="utf-8")
    roots = [REPO_ROOT / "parlays-slate", REPO_ROOT / "parlays-recap"]
    written = sync_dated_card(CARD_CSV, CARD_MD, SLATE_DAY, roots)
    return [CARD_CSV, CARD_MD, SLIP_CSV, *written]


def prepare_snapshot(path: Path | None = None) -> list[dict[str, str]]:
    """Widen a fetch file in place. A second run leaves the long file as it is."""

    source = path or LIVE_PATH
    if not source.is_file():
        raise LiveLinesMissingError(f"live bookmaker lines are missing: {source}")
    rows = read_csv(source)
    if not rows:
        raise LiveLinesMissingError(f"live bookmaker lines are empty: {source}")
    widened = widen_snapshot(rows)
    if widened is not rows:
        write_snapshot(widened, source)
    return widened


def _print_snapshot(report: dict[str, object]) -> None:
    missing = report["missing_games"]
    assert isinstance(missing, list)
    print(
        f"SNAPSHOT hr_rows={report['hard_rows']} missing_games={missing} "
        f"two_way_null_price_rows={len(report['two_way_bad'])} "  # type: ignore[arg-type]
        f"one_way_blank_line_rows={report['one_way_blank']} "
        f"minus110_count={report['minus110_count']} "
        f"minus110_share={float(report['minus110_share']):.4f}"
    )
    excluded = report["excluded"]
    assert isinstance(excluded, list)
    names = sorted({str(row.get("player") or "") for row in excluded})
    print(f"SNAPSHOT_EXCLUDED rows={len(excluded)} players={names}")
    print("SNAPSHOT_EXCLUDED rows are not priced.")


def _print_summary(pool: dict[str, PricedLeg], tickets: list[dict[str, object]]) -> None:
    print("QB_CHECK FAIL_BACKUP_QB=0")
    print(
        f"ALLOCATED {_money(sum(int(ticket['stake_cents']) for ticket in tickets))} "
        f"TICKETS {len(tickets)} "
        f"LEGS {len(card_legs(tickets))}"
    )
    print(format_leg_table(card_legs(tickets)))
    print(format_ticket_table(tickets))
    print(LOG_SLIP_COMMAND)


def main() -> int:
    RATE_DROPS.clear()
    try:
        rows = prepare_snapshot()
    except LiveLinesMissingError as exc:
        print(f"STOP {exc}")
        return 2
    report = snapshot_report(rows)
    _print_snapshot(report)
    if report["missing_games"]:
        print("STOP a Thanksgiving game has no hardrockbet row")
        return 2
    two_way_bad = report["two_way_bad"]
    assert isinstance(two_way_bad, list)
    if two_way_bad:
        print(f"STOP {len(two_way_bad)} hardrockbet two-way rows have an empty line or price")
        for row in two_way_bad[:20]:
            print(f"BAD {row.get('game')} {row.get('player')} {row.get('market')} {row.get('side')}")
        return 2
    pool = price_board(rows)
    try:
        # The operator's four cross-game tickets are fixed. No optimizer runs.
        tickets = build_fixed_card(rows, pool)
    except ValueError as exc:
        print(f"STOP {exc}")
        return 2
    failures = qb_check_failures(
        [leg for ticket in tickets for leg in ticket["legs"]],  # type: ignore[union-attr]
        _starters(STARTERS_PATH),
    )
    if failures:
        print("STOP " + "; ".join(failures))
        return 2
    written = write_card(pool, tickets)
    _print_summary(pool, tickets)
    for path in written:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
