"""Week 11 Hard Rock card priced from the live book snapshot.

The builder reads ``config/week11/live_lines_2026-11-22.csv``. It does not
open a socket, it does not scrape a book, and it does not submit a bet.
A missing Hard Rock line raises. A player mean that equals a team total
raises. Slate-median lines and team-rate means are not a price.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from io import StringIO
from itertools import combinations
from pathlib import Path

from scipy.stats import norm

from ceminiparlays.book_team import canonical_team
from ceminiparlays.card_sync import default_sync_roots, sync_dated_card
from ceminiparlays.compose import joint_ticket
from ceminiparlays.correlation import (
    MATCHUP_STATS,
    LegRef,
    UnmodeledCorrelationError,
    correlation_matrix,
    load_priors,
)
from ceminiparlays.half_edge import normal_over_prob, shrink_share
from ceminiparlays.io import OUT_STATUSES
from ceminiparlays.matchup_math import full_game_yard_sigma, leg_ev
from ceminiparlays.odds import american_to_decimal, decimal_to_american, devig_two_way
from ceminiparlays.proppricing import BookQuote, consensus_fair_p_over
from ceminiparlays.q4_checkdown import poisson_over_prob
from ceminiparlays.resources import REPO_ROOT
from ceminiparlays.sunday_card import norm_name

SLATE_DAY = "2026-11-22"
WEEK = REPO_ROOT / "config" / "week11"
ENV_PATH = WEEK / "environment.csv"
RATES_PATH = WEEK / "team_rates_2026-11-22.csv"
SCRIPT_PATH = WEEK / "quarter_script_2026-11-22.csv"
STARTERS_PATH = WEEK / "qb_starters_2026-11-22.csv"
SCRATCH_PATH = WEEK / "scratches_2026-11-22.csv"
HOLD_PATH = WEEK / "sunday_t90_watchlist_2026-11-22.csv"
Q4_PATH = WEEK / "q4_rb_checkdown_2026-11-22.csv"
ROSTER_PATH = REPO_ROOT / "config" / "rosters" / "nfl.json"
LIVE_PATH = WEEK / "live_lines_2026-11-22.csv"
CARD_CSV = WEEK / "hardrock_card_2026-11-22.csv"
CARD_MD = WEEK / "card_2026-11-22.md"
DOC_PATH = REPO_ROOT / "docs" / "2026-11-22-sunday-hardrock-card.md"
ENTERED_PATH = REPO_ROOT / "parlays-recap" / SLATE_DAY / f"entered_tickets_{SLATE_DAY}.csv"
TEMPLATE_PATH = WEEK / "hardrock_lines_template_2026-11-22.csv"

#: Remaining bankroll after the placed $5 HR11-1 ticket. Not a stake target
#: the builder is allowed to fill with negative-EV legs.
REMAINING_BANKROLL_CENTS = 1800
BANKROLL_CENTS = REMAINING_BANKROLL_CENTS
PLACED_STAKE_CENTS = 500
TICKET_STAKE_CENTS = 600
MAX_NEW_TICKETS = 4
MIN_NEW_TICKETS = 3
LEG_EXPOSURE_CAP_CENTS = 630
MAX_LEG_REUSE = 1
MEAN_MATCH_ABS = 0.01
# Combo cap. C(26, 3) stays small. The cap keeps the highest multipliers.
COMBO_LEG_CAP = 26
LAST_SCAN: dict[str, int] = {"plus_legs": 0, "bucket_a": 0, "bucket_b": 0}
HR_BOOK = "hardrockbet"
HR_FAMILY = frozenset({HR_BOOK, "hardrockbet_fl"})
YARD_MARKETS = frozenset({"pass_yds", "rush_yds", "rec_yds"})
QUARTER_MARKETS = frozenset({"rush_yds_q4", "receptions_q4", "total_q3"})
SHIFT_BAND = {"pass_yds": 5.0, "rush_yds": 2.0, "rec_yds": 2.0}
# Placeholder means from the rejected card. A real posted line may still be 217.5.
FORBIDDEN_MEANS = (217.50, 112.85, 11.10)

MARKET_TO_STAT = {
    "player_pass_yds": "pass_yds",
    "player_rush_yds": "rush_yds",
    "player_reception_yds": "rec_yds",
    "player_receptions": "receptions",
    "player_pass_interceptions": "interceptions",
    "player_anytime_td": "anytime_td",
    "player_receptions_q4": "receptions_q4",
    "totals_q3": "total_q3",
}

# player, market, side. The first three are the placed HR11-1 legs.
PRIORITY: tuple[tuple[str, str, str], ...] = (
    ("Josh Johnson", "pass_yds", "under"),
    ("James Cook III", "rush_yds", "over"),
    ("Jahmyr Gibbs", "rush_yds_q4", "over"),
    ("Trevor Lawrence", "pass_yds", "under"),
    ("Joe Milton", "pass_yds", "under"),
    ("D'Andre Swift", "rush_yds", "over"),
    ("Emmett Johnson", "rush_yds", "over"),
    ("Jonah Coleman", "rush_yds", "over"),
    ("Tony Pollard", "rush_yds", "over"),
    ("Dak Prescott", "pass_yds", "over"),
    ("CeeDee Lamb", "rec_yds", "over"),
    ("George Pickens", "rec_yds", "over"),
    ("Chuba Hubbard", "rush_yds", "over"),
    ("Jaylen Warren", "rush_yds", "over"),
    ("Bhayshul Tuten", "rush_yds", "over"),
    ("Javonte Williams", "rush_yds", "over"),
    ("Ashton Jeanty", "receptions_q4", "over"),
    ("Alvin Kamara", "receptions_q4", "over"),
    ("Tony Pollard", "receptions_q4", "over"),
    ("Tyler Allgeier", "receptions_q4", "over"),
    ("PIT at PHI", "total_q3", "under"),
    ("Baker Mayfield", "pass_yds", "under"),
)

BOOKED_LEGS = frozenset(
    {
        ("josh johnson", "pass_yds"),
        ("james cook", "rush_yds"),
        ("jahmyr gibbs", "rush_yds_q4"),
    }
)
# Reasons that stay off the top-20 board and off every new ticket.
_OFF_BOARD = frozenset(
    {
        "HARD_EXCLUDE",
        "SATURDAY_HOLD",
        "BOOKED",
        "FAIL_BACKUP_QB",
        "UNKNOWN_QB",
        "ROOF_CHECK",
        "TEAM_TOTAL_MEAN",
        "VERIFY_HR",
        "ALREADY_PLACED",
    }
)

TEMPLATE_ROWS: tuple[tuple[str, str, str, str], ...] = (
    ("Josh Johnson", "player_pass_yds", "under", "MIA@BUF"),
    ("James Cook III", "player_rush_yds", "over", "MIA@BUF"),
    ("Jahmyr Gibbs", "player_rush_yds", "over", "TB@DET"),
    ("Trevor Lawrence", "player_pass_yds", "under", "JAX@NYG"),
    ("Joe Milton", "player_pass_yds", "under", "PIT@PHI"),
    ("D'Andre Swift", "player_rush_yds", "over", "NO@CHI"),
    ("Emmett Johnson", "player_rush_yds", "over", "ARI@KC"),
    ("Jonah Coleman", "player_rush_yds", "over", "LV@DEN"),
    ("Tony Pollard", "player_rush_yds", "over", "TEN@DAL"),
    ("Dak Prescott", "player_pass_yds", "over", "TEN@DAL"),
    ("CeeDee Lamb", "player_reception_yds", "over", "TEN@DAL"),
    ("George Pickens", "player_reception_yds", "over", "TEN@DAL"),
)


class LiveLinesMissingError(ValueError):
    """The live book snapshot has no usable Hard Rock line."""


class TeamTotalAsPlayerError(ValueError):
    """A player mean is a team total. The card must not use it."""


@dataclass(frozen=True)
class PricedLeg:
    leg_id: str
    player: str
    team: str
    opp: str
    market: str
    side: str
    line: float | None
    model_p: float | None
    raw_p: float | None
    ev_vs_ref: float | None
    fair_american: int | None
    spread: float | None
    kick_et: str
    game_id: str
    reason: str
    note: str
    book_american: int | None = None
    book_label: str = ""
    mean: float | None = None
    n_books: int = 0

    @property
    def ok(self) -> bool:
        return self.reason == "OK"

    @property
    def edge(self) -> float | None:
        return self.ev_vs_ref


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
    if parsed != parsed:  # NaN
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


def fair_american(prob: float) -> int:
    """American price at which this win probability has zero EV."""

    if not 0.0 < prob < 1.0:
        raise ValueError(f"probability out of range: {prob}")
    price = decimal_to_american(1.0 / prob)
    if -100 < price < 100:
        return -100 if prob >= 0.5 else 100
    return price


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


def _blocked_names(path: Path) -> set[str]:
    names: set[str] = set()
    for row in read_csv(path):
        token = str(row.get("token") or "").strip().lower()
        if token not in OUT_STATUSES:
            continue
        player = norm_name(str(row.get("player") or ""))
        if player:
            names.add(player)
    return names


def _hold_names(path: Path) -> set[str]:
    return {norm_name(str(row.get("player") or "")) for row in read_csv(path) if row.get("player")}


def _rates(path: Path) -> dict[str, dict[str, float]]:
    rates: dict[str, dict[str, float]] = {}
    keys = ("pass_off", "rush_off", "pass_def", "rush_def")
    for row in read_csv(path):
        team = canonical_team(str(row.get("team") or ""))
        parsed = {key: number(row.get(key)) for key in keys}
        if team and all(value is not None for value in parsed.values()):
            rates[team] = {key: float(value) for key, value in parsed.items() if value is not None}
    return rates


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    if count == 0:
        raise ValueError("median of an empty sample")
    mid = count // 2
    if count % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def team_level_totals(rates: dict[str, dict[str, float]], env_path: Path = ENV_PATH) -> set[float]:
    """Team offense, team defense, and the off-versus-def blends. Not a player."""

    totals: set[float] = set(FORBIDDEN_MEANS)
    for row in rates.values():
        for key in ("pass_off", "rush_off", "pass_def", "rush_def"):
            totals.add(float(row[key]))
    pairs: dict[str, str] = {}
    if env_path.is_file():
        for row in read_csv(env_path):
            team = canonical_team(str(row.get("team") or ""))
            opp = canonical_team(str(row.get("opp") or ""))
            if team and opp:
                pairs[team] = opp
    for team, opp in pairs.items():
        offense = rates.get(team)
        defense = rates.get(opp)
        if offense is None or defense is None:
            continue
        totals.add((offense["pass_off"] + defense["pass_def"]) / 2.0)
        totals.add((offense["rush_off"] + defense["rush_def"]) / 2.0)
        both_pass = offense["pass_off"] + defense["pass_def"]
        both_pass += defense["pass_off"] + offense["pass_def"]
        both_rush = offense["rush_off"] + defense["rush_def"]
        both_rush += defense["rush_off"] + offense["rush_def"]
        totals.add(both_pass / 2.0)
        totals.add(both_rush / 2.0)
    if rates:
        slate = [rates[team] for team in pairs if team in rates] or list(rates.values())
        totals.add(_median([row["pass_off"] for row in slate]))
        totals.add(_median([row["rush_off"] for row in slate]))
    if SCRIPT_PATH.is_file():
        q3: list[float] = []
        for row in read_csv(SCRIPT_PATH):
            for key in ("q3_pts_for_pg", "q3_pts_against_pg"):
                value = number(row.get(key))
                if value is not None:
                    totals.add(value)
                    q3.append(value)
        if q3:
            totals.add(_median(q3))
    return totals


def assert_mean_not_team_total(player: str, mean: float, totals: set[float]) -> None:
    """Raise when ``mean`` is a team total. Tolerance is one hundredth of a yard."""

    for total in totals:
        if abs(float(mean) - float(total)) <= MEAN_MATCH_ABS:
            raise TeamTotalAsPlayerError(
                f"{player} projected mean {float(mean):.2f} "
                f"equals a team-level total {float(total):.2f}"
            )


def _starters(path: Path) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for row in read_csv(path):
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
    """Return ``FAIL_BACKUP_QB`` lines. A confirmed starter returns none."""

    failures: list[str] = []
    for leg in legs:
        if not str(leg.market).startswith("pass"):
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


def _env_by_team(path: Path) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for row in read_csv(path):
        team = canonical_team(str(row.get("team") or ""))
        if team:
            found[team] = row
    return found


def _add_name(found: dict[str, set[str]], name: str, team: str) -> None:
    player = norm_name(name)
    code = canonical_team(team)
    if player and code:
        found[player].add(code)


def _name_teams() -> dict[str, str]:
    """One team per name. A name on two teams is left unknown."""

    import json

    found: dict[str, set[str]] = defaultdict(set)
    if ROSTER_PATH.is_file():
        payload = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
        for row in payload.get("players", {}).values():
            _add_name(found, str(row.get("name") or ""), str(row.get("team") or ""))
    for row in _starters(STARTERS_PATH).values():
        team = str(row.get("team") or "")
        _add_name(found, str(row.get("starter") or ""), team)
        for name in _backup_tokens(str(row.get("backups_hard_exclude") or "")):
            _add_name(found, name, team)
    for path, name_key in (
        (SCRATCH_PATH, "player"),
        (HOLD_PATH, "player"),
        (Q4_PATH, "rb"),
    ):
        if not path.is_file():
            continue
        for row in read_csv(path):
            _add_name(found, str(row.get(name_key) or ""), str(row.get("team") or ""))
    unique: dict[str, str] = {}
    for name, teams in found.items():
        if len(teams) == 1:
            unique[name] = next(iter(teams))
    return unique


def load_live_lines(path: Path | None = None) -> list[dict[str, str]]:
    """Read the snapshot. Raise when the file or the Hard Rock prices are absent."""

    source = path or LIVE_PATH
    if not source.is_file():
        raise LiveLinesMissingError(f"live bookmaker lines are missing: {source}")
    rows = read_csv(source)
    if not rows:
        raise LiveLinesMissingError(f"live bookmaker lines are empty: {source}")
    usable = [
        row
        for row in rows
        if str(row.get("bookmaker") or "") == HR_BOOK
        and number(row.get("line")) is not None
        and _american_int(row.get("american_odds")) is not None
    ]
    if not usable:
        raise LiveLinesMissingError(f"live hardrockbet lines or odds are missing: {source}")
    return rows


def write_hardrock_template(path: Path | None = None) -> Path:
    """Write 12 blank Hard Rock rows. The operator fills line and American odds."""

    target = path or TEMPLATE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    fields = ["bookmaker", "player", "market", "side", "line", "american_odds", "timestamp", "game"]
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for player, market, side, game in TEMPLATE_ROWS:
            writer.writerow(
                {
                    "bookmaker": HR_BOOK,
                    "player": player,
                    "market": market,
                    "side": side,
                    "line": "",
                    "american_odds": "",
                    "timestamp": "",
                    "game": game,
                }
            )
    return target


def _stat_of(market: str) -> str | None:
    return MARKET_TO_STAT.get(market)


def _player_label(stat: str, player: str, game: str) -> str:
    if stat == "total_q3" and player.strip().lower() in {"over", "under"}:
        return game.replace("@", " at ")
    return player


def _group_rows(rows: list[dict[str, str]]) -> dict[tuple[str, str, str], dict[str, object]]:
    """Group two-way quotes by game, player, and stat."""

    grouped: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in rows:
        stat = _stat_of(str(row.get("market") or ""))
        if stat is None:
            continue
        game = str(row.get("game") or "").strip()
        raw_player = str(row.get("player") or "").strip()
        if not game or not raw_player:
            continue
        label = _player_label(stat, raw_player, game)
        key = (game, norm_name(label), stat)
        bucket = grouped.get(key)
        if bucket is None:
            bucket = {"label": label, "books": defaultdict(dict)}
            grouped[key] = bucket
        if str(row.get("bookmaker") or "") == HR_BOOK:
            bucket["label"] = label
        odds = _american_int(row.get("american_odds"))
        side = str(row.get("side") or "").strip().lower()
        if side == "yes":
            side = "over"
        elif side == "no":
            side = "under"
        if side not in {"over", "under"} or odds is None:
            continue
        if stat == "anytime_td":
            line_key = 0.0
        else:
            line = number(row.get("line"))
            if line is None:
                continue
            line_key = round(float(line), 2)
        book = str(row.get("bookmaker") or "").strip()
        books: dict = bucket["books"]  # type: ignore[assignment]
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


def _implied_median(line: float, p_over: float, sigma: float) -> float:
    held = min(max(float(p_over), 1e-4), 1.0 - 1e-4)
    z_value = float(norm.ppf(1.0 - held))
    return float(line) - float(sigma) * z_value


def shift_fair_over(
    player: str,
    market: str,
    hr_line: float,
    book_lines: list[tuple[str, float, int, int]],
    totals: set[float],
) -> tuple[float, float, int]:
    """Shift other books onto ``hr_line``. Raise if the mean is a team total.

    Yards only. The band is 2 yards for rush and receiving and 5 for passing.
    Sigma comes from ``full_game_yard_sigma``. A sigma at least as large as
    the line is rejected by the caller. The family is normal, so the sigma
    is the standard deviation used to invert the de-vig.
    """

    if market not in YARD_MARKETS:
        raise ValueError(f"line shift is yards only: {market}")
    band = SHIFT_BAND[market]
    sigma = full_game_yard_sigma(market, hr_line)
    if sigma >= abs(hr_line):
        raise ValueError(f"sigma {sigma:.2f} is not smaller than the line {hr_line:.2f}")
    medians: list[float] = []
    for _book, line, odds_over, odds_under in book_lines:
        if abs(float(line) - float(hr_line)) > band + 1e-9:
            continue
        try:
            fair = devig_two_way(int(odds_over), int(odds_under))
        except ValueError:
            continue
        median = _implied_median(float(line), float(fair.p_over), sigma)
        if median <= 0.0 or median > max(abs(hr_line) * 4.0, 1.0):
            continue
        medians.append(median)
    if len(medians) < 2:
        raise ValueError("line shift needs two books inside the band")
    mean = sum(medians) / len(medians)
    assert_mean_not_team_total(player, mean, totals)
    # half_edge normal tail. No continuity correction.
    return float(normal_over_prob(hr_line, mean, sigma)), mean, len(medians)


def _q4_model() -> tuple[dict[str, dict[str, str]], float]:
    """Index the checkdown file by player. League rate is the raw mean."""

    rows = read_csv(Q4_PATH)
    rates: list[float] = []
    index: dict[str, dict[str, str]] = {}
    for row in rows:
        rec = number(row.get("q4_rec_pg"))
        if rec is not None:
            rates.append(float(rec))
        key = norm_name(str(row.get("rb") or ""))
        if not key:
            continue
        current = index.get(key)
        rank = number(row.get("rb_tgt_share_rank"))
        if current is None:
            index[key] = row
            continue
        current_rank = number(current.get("rb_tgt_share_rank"))
        if rank == 1 and current_rank != 1:
            index[key] = row
    league = sum(rates) / len(rates) if rates else 0.0
    return index, league


def q4_poisson_p_over(
    player: str,
    line: float,
    totals: set[float],
    index: dict[str, dict[str, str]],
    league: float,
) -> tuple[float, float, str] | None:
    """Shrunk Poisson for one live Hard Rock ``receptions_q4`` line.

    ``price_checkdown`` needs trail share, cushion, and YAC. This file does
    not have those fields. The lambda is ``shrink_share`` of ``q4_rec_pg``.
    The tail is the same Poisson ``q4_checkdown`` uses. The gate is
    ``games >= 6`` and ``rb_tgt_share_rank == 1``. A missing row is not a leg.
    """

    row = index.get(norm_name(player))
    if row is None:
        return None
    games = number(row.get("games"))
    rank = number(row.get("rb_tgt_share_rank"))
    rec = number(row.get("q4_rec_pg"))
    if games is None or rank is None or rec is None:
        return None
    if games < 6 or int(rank) != 1:
        return None
    lam = float(shrink_share(int(games), float(rec), float(league)))
    if lam <= 0.0:
        return None
    assert_mean_not_team_total(player, lam, totals)
    if abs(float(line) - round(float(line))) < 1e-9:
        return None
    try:
        p_over = float(poisson_over_prob(lam, float(line)))
    except ValueError:
        return None
    if not 0.0 < p_over < 1.0:
        return None
    note = (
        f"Q4_POISSON_MODEL lam={lam:.3f} games={int(games)} "
        f"raw={float(rec):.2f} league={league:.3f}"
    )
    return p_over, lam, note


def _team_from_q4(
    name: str,
    game: str,
    index: dict[str, dict[str, str]],
    team: str,
    opp: str,
) -> tuple[str, str]:
    """Fill a blank team from the checkdown file when the team is in the game."""

    if team:
        return team, opp
    row = index.get(name)
    if row is None:
        return team, opp
    away, _, home = game.partition("@")
    away = canonical_team(away)
    home = canonical_team(home)
    candidate = canonical_team(str(row.get("team") or ""))
    if candidate == away:
        return away, home
    if candidate == home:
        return home, away
    return team, opp


def _shift_books(books: dict, hr_line: float, market: str) -> list[tuple[str, float, int, int]]:
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


def _consensus_line(books: dict) -> tuple[float, list[BookQuote]] | None:
    """Modal line among non-Hard-Rock books that post both sides."""

    buckets: dict[float, list[BookQuote]] = defaultdict(list)
    for book, lines in books.items():
        if book in HR_FAMILY:
            continue
        for line, sides in lines.items():
            pair = _both(sides)
            if pair is None:
                continue
            buckets[round(float(line), 2)].append(BookQuote(book, pair[0], pair[1]))
    if not buckets:
        return None
    line, quotes = max(buckets.items(), key=lambda item: (len(item[1]), -abs(item[0])))
    if len(quotes) < 2:
        return None
    return line, quotes


def _fair_at_line(
    player: str,
    market: str,
    books: dict,
    totals: set[float],
    q4_index: dict[str, dict[str, str]] | None = None,
    q4_league: float | None = None,
) -> tuple[float | None, float | None, str, int, str, float | None, str]:
    """Return p_over, mean, method, n_books, note, line, book_label."""

    hr_line = _hr_line(books)
    if hr_line is not None:
        quotes = _same_line_quotes(books, hr_line)
        if len(quotes) >= 2:
            consensus = consensus_fair_p_over(quotes, target_book="hardrock")
            if consensus is None:
                return None, None, "", 0, "NO_CONSENSUS", hr_line, HR_BOOK
            names = ",".join(sorted(set(consensus.books)))
            note = f"SAME_LINE_DEVIG n={consensus.n_books} books={names}"
            return consensus.fair_p_over, None, "same_line", consensus.n_books, note, hr_line, HR_BOOK
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
                    return None, None, "sigma_floor", 0, "SHIFT_SIGMA_FLOOR", hr_line, HR_BOOK
                return None, None, "", 0, "NO_CONSENSUS", hr_line, HR_BOOK
            note = f"LINE_SHIFT_DEVIG n={count} median={mean:.2f} line={hr_line:.2f}"
            return p_over, mean, "line_shift", count, note, hr_line, HR_BOOK
        if market == "receptions_q4" and q4_index is not None and q4_league is not None:
            try:
                priced = q4_poisson_p_over(player, hr_line, totals, q4_index, q4_league)
            except TeamTotalAsPlayerError:
                raise
            if priced is not None:
                p_over, mean, note = priced
                return p_over, mean, "q4_poisson", 0, note, hr_line, HR_BOOK
        return None, None, "", 0, "NO_CONSENSUS", hr_line, HR_BOOK

    alt = _consensus_line(books)
    if alt is None:
        return None, None, "", 0, "NO_HARDROCK_LINE", None, ""
    line, quotes = alt
    consensus = consensus_fair_p_over(quotes, target_book="hardrock")
    if consensus is None:
        return None, None, "", 0, "NO_HARDROCK_LINE", None, ""
    best = "pinnacle" if any(quote.book == "pinnacle" for quote in quotes) else quotes[0].book
    label = f"{best} [CONSENSUS_LINE_VERIFY_HR]"
    names = ",".join(sorted(set(consensus.books)))
    note = f"[CONSENSUS_LINE_VERIFY_HR] n={consensus.n_books} books={names}"
    return consensus.fair_p_over, None, "verify_hr", consensus.n_books, note, line, label


def _blank_leg(
    *,
    player: str,
    market: str,
    side: str,
    game: str,
    reason: str,
    note: str,
    team: str = "",
    opp: str = "",
    line: float | None = None,
    book_american: int | None = None,
    book_label: str = "",
    fair: int | None = None,
    model_p: float | None = None,
    edge: float | None = None,
    mean: float | None = None,
    n_books: int = 0,
    spread: float | None = None,
    kick: str = "",
    game_id: str = "",
) -> PricedLeg:
    return PricedLeg(
        leg_id=f"{norm_name(player)}|{market}|{side}",
        player=player,
        team=team,
        opp=opp,
        market=market,
        side=side,
        line=line,
        model_p=model_p,
        raw_p=model_p,
        ev_vs_ref=edge,
        fair_american=fair,
        spread=spread,
        kick_et=kick,
        game_id=game_id,
        reason=reason,
        note=note,
        book_american=book_american,
        book_label=book_label,
        mean=mean,
        n_books=n_books,
    )


def _assignment(
    name: str,
    game: str,
    teams: dict[str, str],
    env: dict[str, dict[str, str]],
    starters: dict[str, dict[str, str]],
) -> tuple[str, str, str, str, float | None]:
    away, _, home = game.partition("@")
    away = canonical_team(away)
    home = canonical_team(home)
    team = teams.get(name, "")
    if team not in {away, home}:
        team = ""
    opp = ""
    if team == away:
        opp = home
    elif team == home:
        opp = away
    meta = env.get(team) or env.get(home) or {}
    game_id = str(meta.get("game_id") or f"{SLATE_DAY}-{game}")
    kick_row = starters.get(team) or starters.get(home) or {}
    kick = str(kick_row.get("kickoff_et") or "")
    spread = number((env.get(team) or {}).get("spread"))
    return team, opp, game_id, kick, spread


def _roof_blocked(team: str, market: str, env: dict[str, dict[str, str]]) -> bool:
    if market not in {"pass_yds", "rec_yds"} or team != "DAL":
        return False
    meta = env.get("DAL") or {}
    roof = str(meta.get("roof") or "").strip().lower()
    exposed = str(meta.get("weather_exposed") or "").strip().lower()
    return roof == "retractable" and exposed == "true"


def _exclusion(
    name: str,
    market: str,
    team: str,
    env: dict[str, dict[str, str]],
    blocked: set[str],
    held: set[str],
    starters: dict[str, dict[str, str]],
    player: str,
) -> str:
    if name in blocked:
        return "HARD_EXCLUDE"
    if name in held:
        return "SATURDAY_HOLD"
    if (name, market) in BOOKED_LEGS:
        return "BOOKED"
    if market.startswith("pass"):
        if not team:
            return "UNKNOWN_QB"
        probe = _blank_leg(
            player=player,
            market=market,
            side="over",
            game="",
            team=team,
            reason="",
            note="",
        )
        if qb_check_failures([probe], starters):
            return "FAIL_BACKUP_QB"
    if _roof_blocked(team, market, env):
        return "ROOF_CHECK"
    return ""


def _side_prices(books: dict, line: float | None, label: str) -> tuple[int | None, int | None]:
    if line is None:
        return None, None
    book = HR_BOOK if label == HR_BOOK else label.split()[0]
    sides = (books.get(book) or {}).get(round(line, 2))
    pair = _both(sides)
    if pair is None and label == HR_BOOK:
        return None, None
    if pair is None:
        return None, None
    return pair


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


def _reason_for(
    exclusion: str,
    method: str,
    market: str,
    edge: float | None,
    label: str,
) -> str:
    if exclusion:
        return exclusion
    if method == "verify_hr" or "[CONSENSUS_LINE_VERIFY_HR]" in label:
        return "VERIFY_HR"
    if method == "sigma_floor":
        return "SHIFT_SIGMA_FLOOR"
    if method == "q4_poisson":
        if edge is None:
            return "NO_CONSENSUS"
        if edge <= 0.0:
            return "NEGATIVE_EV"
        return "OK"
    if market in QUARTER_MARKETS and method != "same_line":
        return "NO_QUARTER_BOOK"
    if method == "line_shift":
        if edge is None:
            return "NO_CONSENSUS"
        if edge <= 0.0:
            return "NEGATIVE_EV"
        return "OK"
    if edge is None or method != "same_line":
        return "NO_CONSENSUS"
    if edge <= 0.0:
        return "NEGATIVE_EV"
    return "OK"


def price_board(rows: list[dict[str, str]]) -> dict[str, PricedLeg]:
    """Price both sides of every live prop. Team rates are a block list only."""

    totals = team_level_totals(_rates(RATES_PATH))
    blocked = _blocked_names(SCRATCH_PATH)
    held = _hold_names(HOLD_PATH)
    starters = _starters(STARTERS_PATH)
    env = _env_by_team(ENV_PATH)
    teams = _name_teams()
    q4_index, q4_league = _q4_model()
    pool: dict[str, PricedLeg] = {}
    for (game, name, stat), bucket in _group_rows(rows).items():
        label = str(bucket["label"])
        books = bucket["books"]
        team, opp, game_id, kick, spread = _assignment(name, game, teams, env, starters)
        if stat == "receptions_q4":
            team, opp = _team_from_q4(name, game, q4_index, team, opp)
        if stat == "total_q3":
            away, _, home = game.partition("@")
            team = canonical_team(away)
            opp = canonical_team(home)
        exclusion = _exclusion(name, stat, team, env, blocked, held, starters, label)
        try:
            p_over, mean, method, n_books, note, line, book_label = _fair_at_line(
                label, stat, books, totals, q4_index, q4_league
            )
        except TeamTotalAsPlayerError as exc:
            for side in ("over", "under"):
                leg = _blank_leg(
                    player=label,
                    market=stat,
                    side=side,
                    game=game,
                    reason="TEAM_TOTAL_MEAN",
                    note=str(exc),
                    team=team,
                    opp=opp,
                    game_id=game_id,
                    kick=kick,
                    spread=spread,
                )
                pool[leg.leg_id] = leg
            continue
        odds_over, odds_under = _side_prices(books, line, book_label if book_label == HR_BOOK else HR_BOOK)
        if book_label == HR_BOOK and odds_over is None:
            odds_over, odds_under = _side_prices(books, line, HR_BOOK)
        for side in ("over", "under"):
            edge, price, fair = (None, None, None)
            prob = None
            if p_over is not None:
                prob = p_over if side == "over" else 1.0 - p_over
                edge, price, fair = _apply_edge(p_over, side, odds_over, odds_under)
            elif side == "over":
                price = odds_over
            else:
                price = odds_under
            if book_label != HR_BOOK and price is None and line is not None:
                alt_book = book_label.split()[0]
                alt_over, alt_under = _side_prices(books, line, alt_book)
                edge, price, fair = _apply_edge(p_over or 0.5, side, alt_over, alt_under)
                if p_over is None:
                    edge, fair = None, None
            reason = _reason_for(exclusion, method, stat, edge, book_label)
            if name == "jahmyr gibbs" and stat == "receptions_q4" and "Q4_POISSON_MODEL" in note:
                note += "; HR11-1 already booked rush_yds_q4 for this player"
            shown = book_label or HR_BOOK
            if price is not None and shown == HR_BOOK:
                shown = f"hardrockbet {_american(price)}"
            elif price is not None:
                shown = f"{book_label} {_american(price)}".strip()
            leg = _blank_leg(
                player=label,
                market=stat,
                side=side,
                game=game,
                reason=reason,
                note=note,
                team=team,
                opp=opp,
                line=line,
                book_american=price,
                book_label=shown,
                fair=fair,
                model_p=prob,
                edge=edge,
                mean=mean,
                n_books=n_books,
                spread=spread,
                kick=kick,
                game_id=game_id,
            )
            pool[leg.leg_id] = leg
    _ensure_priority(pool, starters, env)
    return pool


def _ensure_priority(
    pool: dict[str, PricedLeg],
    starters: dict[str, dict[str, str]],
    env: dict[str, dict[str, str]],
) -> None:
    for player, market, side in PRIORITY:
        leg_id = f"{norm_name(player)}|{market}|{side}"
        if leg_id in pool:
            continue
        reason = "NO_QUARTER_BOOK" if market in QUARTER_MARKETS else "NO_HARDROCK_LINE"
        team = ""
        if market == "total_q3":
            team, _, opp = "PIT", "", "PHI"
            game_id = str((env.get("PIT") or {}).get("game_id") or "")
        else:
            opp = ""
            game_id = ""
        kick = ""
        pool[leg_id] = _blank_leg(
            player=player,
            market=market,
            side=side,
            game=game_id,
            reason=reason,
            note="no live two-way book line in the snapshot",
            team=team,
            opp=opp if market == "total_q3" else "",
            game_id=game_id,
            kick=kick,
        )
        _ = starters


def screen_pool(
    live_path: Path | None = None,
    rows: list[dict[str, str]] | None = None,
) -> dict[str, PricedLeg]:
    """Price the live snapshot. A missing Hard Rock file raises."""

    loaded = rows if rows is not None else load_live_lines(live_path)
    if rows is not None:
        usable = [
            row
            for row in loaded
            if str(row.get("bookmaker") or "") == HR_BOOK
            and number(row.get("line")) is not None
            and _american_int(row.get("american_odds")) is not None
        ]
        if not usable:
            raise LiveLinesMissingError("live hardrockbet lines or odds are missing")
    return price_board(loaded)


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


def _try_ticket(legs: list[PricedLeg], *, keep_negative: bool = False) -> dict[str, object] | None:
    if not 2 <= len(legs) <= 3:
        return None
    if len({norm_name(leg.player) for leg in legs}) < len(legs):
        return None
    games = {leg.game_id for leg in legs}
    same_game = len(games) < len(legs)
    if same_game and not all(leg.team and leg.opp for leg in legs):
        return None
    if any(leg.market == "first_td" for leg in legs):
        return None
    if any((norm_name(leg.player), leg.market) in BOOKED_LEGS for leg in legs):
        return None
    try:
        corr = _pair_corr(legs)
    except UnmodeledCorrelationError:
        return None
    prices = [int(leg.book_american or 0) for leg in legs]
    if any(price == 0 for price in prices):
        return None
    marginals = [float(leg.model_p or 0.0) for leg in legs]
    if any(not 0.0 < prob < 1.0 for prob in marginals):
        return None
    joint = joint_ticket(marginals, prices, corr)
    taxed = bool(joint["sgp_tax_applied"])
    ev = float(joint["tax_adjusted_sgp_ev"] if taxed else joint["joint_ev"])
    if ev <= 0.0 and not keep_negative:
        return None
    used_decimal = float(joint["decimal_sgp"] if taxed else joint["decimal"])
    live = _legal_american(decimal_to_american(used_decimal))
    return {
        "legs": legs,
        "joint_p": float(joint["joint_p"]),
        "gaussian_joint_p": float(joint["gaussian_joint_p"]),
        "t_copula_joint_p": float(joint["t_copula_joint_p"]),
        "fair_american": fair_american(float(joint["joint_p"])),
        "live_american": live,
        "ev": ev,
        "same_game": same_game,
        "sgp_tax": taxed,
        "max_rho": _max_off_diag(corr),
        "unmodeled": False,
        "stake_cents": TICKET_STAKE_CENTS,
        "bucket": "B" if same_game else "A",
        "best_available": False,
    }


def _disjoint(legs: list[PricedLeg], used_players: set[str], used_keys: set[tuple[str, str, str]]) -> bool:
    for leg in legs:
        player = norm_name(leg.player)
        key = (player, leg.market, leg.side)
        if player in used_players or key in used_keys:
            return False
        if (player, leg.market) in BOOKED_LEGS:
            return False
    return True


def _mark_used(
    legs: list[PricedLeg],
    used_players: set[str],
    used_keys: set[tuple[str, str, str]],
) -> None:
    for leg in legs:
        player = norm_name(leg.player)
        used_players.add(player)
        used_keys.add((player, leg.market, leg.side))


def _multiplier(leg: PricedLeg) -> float:
    if leg.model_p is None or leg.book_american is None:
        return 0.0
    if not 0.0 < float(leg.model_p) < 1.0:
        return 0.0
    return float(leg.model_p) * american_to_decimal(int(leg.book_american))


def _ticket_name(ticket: dict[str, object]) -> tuple[str, ...]:
    legs = ticket["legs"]
    assert isinstance(legs, list)
    return tuple(f"{leg.player}|{leg.market}|{leg.side}" for leg in legs)


def _pack_score(pack: list[dict[str, object]]) -> float:
    """Stake-weighted EV. Three tickets are $6. Four tickets are $6, $6, $3, $3."""

    count = len(pack)
    if count not in {3, 4}:
        return -1.0
    ordered = sorted(pack, key=lambda ticket: (-float(ticket["ev"]), _ticket_name(ticket)))
    stakes = (600, 600, 600) if count == 3 else (600, 600, 300, 300)
    return sum(stake * float(ticket["ev"]) for stake, ticket in zip(stakes, ordered, strict=True))


def _modeled_stat_pairs() -> set[tuple[str, str]]:
    priors = load_priors()
    found: set[tuple[str, str]] = set()
    for key in ("same_player", "pairs"):
        for row in priors.get(key) or []:
            left = str(row.get("stat_a") or "")
            right = str(row.get("stat_b") or "")
            if left and right:
                found.add(tuple(sorted((left, right))))
    return found


def _sgp_eligible(leg: PricedLeg) -> bool:
    if leg.reason in _OFF_BOARD:
        return False
    if (norm_name(leg.player), leg.market) in BOOKED_LEGS:
        return False
    if leg.model_p is None or leg.book_american is None:
        return False
    if not leg.team or not leg.opp or not leg.game_id:
        return False
    if not 0.0 < float(leg.model_p) < 1.0:
        return False
    if leg.edge is not None and leg.edge < -0.12:
        return False
    return True


def _bucket_a_tickets(legs: list[PricedLeg]) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for size in (2, 3):
        for combo in combinations(legs, size):
            games = {leg.game_id for leg in combo}
            players = {norm_name(leg.player) for leg in combo}
            if len(games) != size or len(players) != size:
                continue
            ticket = _try_ticket(list(combo))
            if ticket is None:
                continue
            ticket["bucket"] = "A"
            found.append(ticket)
    return found


def _bucket_b_tickets(
    pool: dict[str, PricedLeg],
    modeled: set[tuple[str, str]],
    *,
    keep_negative: bool = False,
) -> list[dict[str, object]]:
    """Same-game pairs. Positive rho only. Unmodeled pairs are skipped."""

    by_game: dict[str, dict[tuple[str, str], PricedLeg]] = defaultdict(dict)
    for leg in pool.values():
        if not _sgp_eligible(leg):
            continue
        key = (norm_name(leg.player), leg.market)
        current = by_game[leg.game_id].get(key)
        if current is None or (leg.edge or -1.0) > (current.edge or -1.0):
            by_game[leg.game_id][key] = leg
    found: list[dict[str, object]] = []
    for legs in by_game.values():
        ordered = sorted(legs.values(), key=lambda leg: (-(leg.edge or -1.0), leg.player, leg.market))
        if len(ordered) > 45:
            ordered = ordered[:45]
        for left, right in combinations(ordered, 2):
            stats = tuple(sorted((left.market, right.market)))
            if stats not in modeled and left.market not in MATCHUP_STATS and right.market not in MATCHUP_STATS:
                continue
            ticket = _try_ticket([left, right], keep_negative=keep_negative)
            if ticket is None or not ticket["same_game"]:
                continue
            if float(ticket["max_rho"]) <= 0.0:
                continue
            ticket["bucket"] = "B"
            found.append(ticket)
    return found


def _greedy_pack(
    cands: list[dict[str, object]],
    *,
    sizes: set[int] | None = None,
) -> list[dict[str, object]]:
    chosen: list[dict[str, object]] = []
    used_players: set[str] = set()
    used_keys: set[tuple[str, str, str]] = set()
    ordered = sorted(cands, key=lambda ticket: (-float(ticket["ev"]), _ticket_name(ticket)))
    for ticket in ordered:
        legs = ticket["legs"]
        assert isinstance(legs, list)
        if sizes is not None and len(legs) not in sizes:
            continue
        if not _disjoint(legs, used_players, used_keys):
            continue
        _mark_used(legs, used_players, used_keys)
        chosen.append(ticket)
        if len(chosen) == MAX_NEW_TICKETS:
            break
    return chosen


def _improve(pack: list[dict[str, object]], cands: list[dict[str, object]]) -> list[dict[str, object]]:
    current = list(pack)
    if len(current) not in {3, 4}:
        return current
    for _pass in range(6):
        base = _pack_score(current)
        changed = False
        for index in range(len(current)):
            others = current[:index] + current[index + 1 :]
            used_players: set[str] = set()
            used_keys: set[tuple[str, str, str]] = set()
            for ticket in others:
                legs = ticket["legs"]
                assert isinstance(legs, list)
                _mark_used(legs, used_players, used_keys)
            for alt in cands:
                alt_legs = alt["legs"]
                assert isinstance(alt_legs, list)
                if not _disjoint(alt_legs, used_players, used_keys):
                    continue
                trial = [*others, alt]
                if _pack_score(trial) <= base + 1e-9:
                    continue
                current = trial
                changed = True
                break
            if changed:
                break
        if not changed:
            break
    return current


def _try_grow(pack: list[dict[str, object]], cands: list[dict[str, object]]) -> list[dict[str, object]]:
    if len(pack) != 3:
        return pack
    base = _pack_score(pack)
    used_players: set[str] = set()
    used_keys: set[tuple[str, str, str]] = set()
    for ticket in pack:
        legs = ticket["legs"]
        assert isinstance(legs, list)
        _mark_used(legs, used_players, used_keys)
    best = pack
    best_score = base
    for alt in cands:
        alt_legs = alt["legs"]
        assert isinstance(alt_legs, list)
        if not _disjoint(alt_legs, used_players, used_keys):
            continue
        trial = [*pack, alt]
        score = _pack_score(trial)
        if score > best_score + 1e-9:
            best = trial
            best_score = score
    return best


def _choose_pack(cands: list[dict[str, object]]) -> list[dict[str, object]]:
    best_score = -1.0
    best_pack: list[dict[str, object]] = []
    for sizes in (None, {2}, {3}):
        greedy = _greedy_pack(cands, sizes=sizes)
        seeds: list[list[dict[str, object]]] = []
        if len(greedy) >= 3:
            seeds.append(greedy[:3])
        if len(greedy) >= 4:
            seeds.append(greedy[:4])
        for seed in seeds:
            pack = _improve(seed, cands)
            pack = _try_grow(pack, cands)
            pack = _improve(pack, cands)
            score = _pack_score(pack)
            if score > best_score + 1e-9:
                best_score = score
                best_pack = pack
    return best_pack


def _fill_short_pack(
    chosen: list[dict[str, object]],
    pool: dict[str, PricedLeg],
    modeled: set[tuple[str, str]],
) -> list[dict[str, object]]:
    """Add the highest correlated ticket when fewer than three +EV tickets exist."""

    if len(chosen) >= MIN_NEW_TICKETS:
        return chosen
    extras = _bucket_b_tickets(pool, modeled, keep_negative=True)
    extras.sort(key=lambda ticket: (-float(ticket["ev"]), _ticket_name(ticket)))
    used_players: set[str] = set()
    used_keys: set[tuple[str, str, str]] = set()
    for ticket in chosen:
        legs = ticket["legs"]
        assert isinstance(legs, list)
        _mark_used(legs, used_players, used_keys)
    for ticket in extras:
        if len(chosen) >= MIN_NEW_TICKETS:
            break
        legs = ticket["legs"]
        assert isinstance(legs, list)
        if not _disjoint(legs, used_players, used_keys):
            continue
        ticket["best_available"] = float(ticket["ev"]) <= 0.0
        _mark_used(legs, used_players, used_keys)
        chosen.append(ticket)
    return chosen


def _apply_stakes(pack: list[dict[str, object]]) -> list[dict[str, object]]:
    if len(pack) not in {3, 4}:
        for ticket in pack:
            ticket["stake_cents"] = TICKET_STAKE_CENTS
        ordered = list(pack)
    else:
        ordered = sorted(pack, key=lambda ticket: (-float(ticket["ev"]), _ticket_name(ticket)))
        stakes = (600, 600, 600) if len(ordered) == 3 else (600, 600, 300, 300)
        for ticket, stake in zip(ordered, stakes, strict=True):
            ticket["stake_cents"] = stake
    ordered.sort(key=lambda ticket: (-int(ticket["stake_cents"]), -float(ticket["ev"]), _ticket_name(ticket)))
    for index, ticket in enumerate(ordered, start=2):
        ticket["ticket_id"] = f"HR11-{index}"
    return ordered


def _validate_tickets(chosen: list[dict[str, object]]) -> None:
    if len(chosen) > MAX_NEW_TICKETS:
        raise ValueError("more than 4 new tickets")
    stake = sum(int(ticket["stake_cents"]) for ticket in chosen)
    if stake > REMAINING_BANKROLL_CENTS:
        raise ValueError(f"stake sum {stake} is above {REMAINING_BANKROLL_CENTS}")
    if chosen and stake != REMAINING_BANKROLL_CENTS and len(chosen) >= MIN_NEW_TICKETS:
        raise ValueError(f"stake sum {stake} is not {REMAINING_BANKROLL_CENTS}")
    exposure: dict[str, int] = defaultdict(int)
    reuse: dict[tuple[str, str, str], int] = defaultdict(int)
    for ticket in chosen:
        legs = ticket["legs"]
        assert isinstance(legs, list)
        keys = [(norm_name(leg.player), leg.market, leg.side) for leg in legs]
        if len(keys) != len(set(keys)):
            raise ValueError("leg reuse inside one ticket")
        if int(ticket["stake_cents"]) not in {300, 400, 500, 600}:
            raise ValueError("ticket stake is outside $3 to $6")
        for leg in legs:
            player = norm_name(leg.player)
            key = (player, leg.market, leg.side)
            reuse[key] += 1
            exposure[player] += int(ticket["stake_cents"])
            if (player, leg.market) in BOOKED_LEGS:
                raise ValueError(f"booked leg reused: {player} {leg.market}")
            if leg.mean is not None:
                assert_mean_not_team_total(leg.player, float(leg.mean), team_level_totals(_rates(RATES_PATH)))
    if any(count > MAX_LEG_REUSE for count in reuse.values()):
        raise ValueError("leg reuse is above 1")
    if any(cents > LEG_EXPOSURE_CAP_CENTS for cents in exposure.values()):
        raise ValueError("player exposure is above 35 percent of $18")


def build_tickets(pool: dict[str, PricedLeg]) -> list[dict[str, object]]:
    """Fill $18 from +EV tickets. A short board may add one tagged filler.

    Bucket A pairs and triples use different games, so rho is 0.
    Bucket B is a same-game pair with a positive copula rho.
    Three tickets are $6 each. Four tickets are $6, $6, $3, and $3.
    The card keeps the pack with the higher stake-weighted EV.
    """

    totals = team_level_totals(_rates(RATES_PATH))
    plus = [
        leg
        for leg in pool.values()
        if leg.ok
        and leg.edge is not None
        and leg.edge > 0.0
        and leg.model_p is not None
        and leg.book_american is not None
        and (norm_name(leg.player), leg.market) not in BOOKED_LEGS
    ]
    for leg in plus:
        if leg.mean is not None:
            assert_mean_not_team_total(leg.player, float(leg.mean), totals)
    plus.sort(key=lambda leg: (-_multiplier(leg), leg.player, leg.market, leg.side))
    combo_legs = plus[:COMBO_LEG_CAP]
    modeled = _modeled_stat_pairs()
    bucket_a = _bucket_a_tickets(combo_legs)
    bucket_b = _bucket_b_tickets(pool, modeled)
    LAST_SCAN["plus_legs"] = len(plus)
    LAST_SCAN["bucket_a"] = len(bucket_a)
    LAST_SCAN["bucket_b"] = len(bucket_b)
    chosen = _choose_pack([*bucket_a, *bucket_b])
    if len(chosen) < MIN_NEW_TICKETS:
        chosen = _fill_short_pack(chosen, pool, modeled)
    chosen = _apply_stakes(chosen)
    _validate_tickets(chosen)
    return chosen


def allocated_cents(tickets: list[dict[str, object]]) -> int:
    return sum(int(ticket["stake_cents"]) for ticket in tickets)


def unallocated_cents(tickets: list[dict[str, object]]) -> int:
    return REMAINING_BANKROLL_CENTS - allocated_cents(tickets)


def _leg_phrase(leg: PricedLeg) -> str:
    line = "n/a" if leg.line is None else f"{leg.line:.2f}"
    price = _american(leg.book_american) or "n/a"
    return f"{leg.player} {leg.market} {leg.side} {line} (HR {price})"


def pricing_source(leg: PricedLeg) -> str:
    """The pricer tag for one Hard Rock leg. Blank when the leg has no price."""

    note = leg.note
    if "Q4_POISSON_MODEL" in note:
        return "Q4_POISSON_MODEL"
    if "LINE_SHIFT_DEVIG" in note:
        return "LINE_SHIFT_DEVIG"
    if "SAME_LINE_DEVIG" in note:
        return "SAME_LINE_DEVIG"
    return ""


def _ticket_sources(ticket: dict[str, object]) -> str:
    sources: list[str] = []
    legs = ticket["legs"]
    assert isinstance(legs, list)
    for leg in legs:
        source = pricing_source(leg)
        if source and source not in sources:
            sources.append(source)
    if ticket.get("same_game"):
        sources.append("COPULA")
    if ticket.get("sgp_tax"):
        sources.append("SGP_TAX")
    if ticket.get("best_available"):
        sources.append("[BEST_AVAILABLE_ACTION]")
    return "+".join(sources)


def decision_legs(pool: dict[str, PricedLeg]) -> list[PricedLeg]:
    """The 20 highest-EV Hard Rock legs that have a real pricer tag."""

    ranked: list[PricedLeg] = []
    for leg in pool.values():
        if leg.reason in _OFF_BOARD:
            continue
        if leg.edge is None or leg.book_american is None or leg.line is None:
            continue
        if not pricing_source(leg):
            continue
        ranked.append(leg)
    ranked.sort(key=lambda leg: (-(leg.edge or 0.0), leg.player, leg.market, leg.side))
    return ranked[:20]


def format_leg_table(legs: list[PricedLeg]) -> str:
    header = "Player | Team | Market | Side | HR Line | HR Odds | Fair Odds | Edge % | Pricing Source"
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


def format_ticket_table(tickets: list[dict[str, object]]) -> str:
    header = (
        "Ticket | Stake | Exact HR Legs & Odds | Pricing Source | "
        "Est. HR Parlay Odds | Fair Parlay Odds | EV %"
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
                    _american(int(ticket["fair_american"])),
                    f"{float(ticket['ev']) * 100:.2f}%",
                ]
            )
        )
    if not tickets:
        lines.append(" | ".join(["(none)", "$0.00", "", "", "", "", ""]))
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
        for index, leg in enumerate(legs, start=1):
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
                    "ticket_stake_usd": _money(int(ticket["stake_cents"])),
                    "live_parlay_american": _american(int(ticket["live_american"])),
                    "fair_parlay_american": _american(int(ticket["fair_american"])),
                    "ticket_ev": f"{float(ticket['ev']):.4f}",
                    "gaussian_joint_p": f"{float(ticket['gaussian_joint_p']):.4f}",
                    "t_copula_joint_p": f"{float(ticket['t_copula_joint_p']):.4f}",
                    "corr_unmodeled": "yes" if ticket["unmodeled"] else "no",
                    "pricing_source": pricing_source(leg),
                    "note": leg.note,
                }
            )
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def render_entered() -> str:
    """The placed $5 ticket. Line and price stay blank until the slip is typed."""

    fields = [
        "ticket_id",
        "leg_num",
        "player_name",
        "market",
        "side",
        "line",
        "american_odds",
        "stake_usd",
        "note",
    ]
    placed = (
        ("Josh Johnson", "pass_yds", "under"),
        ("James Cook III", "rush_yds", "over"),
        ("Jahmyr Gibbs", "rush_yds_q4", "over"),
    )
    rows = []
    for index, (player, market, side) in enumerate(placed, start=1):
        rows.append(
            {
                "ticket_id": "HR11-1",
                "leg_num": str(index),
                "player_name": player,
                "market": market,
                "side": side,
                "line": "FILL_FROM_SLIP",
                "american_odds": "FILL_FROM_SLIP",
                "stake_usd": "5.00",
                "note": "already placed; do not reuse these legs",
            }
        )
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def render_markdown(tickets: list[dict[str, object]], pool: dict[str, PricedLeg]) -> str:
    allocated = allocated_cents(tickets)
    idle = unallocated_cents(tickets)
    shifts = [
        leg
        for leg in pool.values()
        if pricing_source(leg) == "LINE_SHIFT_DEVIG" and (leg.edge or 0.0) > 0.0 and leg.reason == "OK"
    ]
    q4_plus = [
        leg
        for leg in pool.values()
        if pricing_source(leg) == "Q4_POISSON_MODEL" and (leg.edge or 0.0) > 0.0 and leg.reason == "OK"
    ]
    same_plus = [
        leg
        for leg in pool.values()
        if pricing_source(leg) == "SAME_LINE_DEVIG" and (leg.edge or 0.0) > 0.0 and leg.reason == "OK"
    ]
    lines = [
        "# Week 11 Hard Rock card, 2026-11-22",
        "",
        "Do not submit a bet from this file. Type any ticket yourself.",
        "HR11-1 is already placed for $5.00. Those three legs are not on this card.",
        f"Remaining bankroll: {_money(REMAINING_BANKROLL_CENTS)}.",
        f"Allocated on this card: {_money(allocated)}.",
        f"Unallocated: {_money(idle)}.",
        "Each new ticket is $3.00 to $6.00. Three tickets are $6.00 each.",
        "Four tickets are $6.00, $6.00, $3.00, and $3.00.",
        "The card keeps the pack with the higher stake-weighted EV.",
        "A ticket is +EV only when the copula joint beats the estimated Hard Rock price.",
        f"Same-line +EV legs: {len(same_plus)}.",
        f"Line-shift +EV legs: {len(shifts)}.",
        f"Q4 Poisson +EV legs: {len(q4_plus)}.",
        f"Bucket A priced tickets: {LAST_SCAN['bucket_a']}.",
        f"Bucket B priced tickets: {LAST_SCAN['bucket_b']}.",
        "",
        "Prices come from config/week11/live_lines_2026-11-22.csv.",
        "SAME_LINE_DEVIG is a power de-vig when two other books post the Hard Rock line.",
        "LINE_SHIFT_DEVIG moves an adjacent yard line with the normal tail in half_edge.py.",
        "Q4_POISSON_MODEL uses the shrunk q4_rec_pg rate. The line is a live Hard Rock line.",
        "The gate is games at least 6 and target-share rank 1. A missing row is not a leg.",
        "Team offense and team defense totals are not a player mean.",
        "Est. HR Parlay Odds is the product of the posted leg prices.",
        "When pair rho is above 0.15, the repo SGP tax shortens that price.",
        "That price is not a captured Hard Rock same-game quote.",
        "",
    ]
    if shifts:
        best = max(shifts, key=lambda leg: (leg.edge or 0.0, leg.player))
        line = "n/a" if best.line is None else f"{best.line:.2f}"
        lines.append(
            f"Highest line-shift leg: {best.player} {best.market} {best.side} "
            f"{line} at {(best.edge or 0.0) * 100:.2f}% ({pricing_source(best)})."
        )
    gordon = pool.get("ollie gordon|receptions_q4|under")
    if gordon is not None and "raw=0.00" in gordon.note:
        lines.append(
            "Ollie Gordon II q4_rec_pg raw is 0.00. Shrinkage pulls the rate toward the league mean. "
            "The under uses that shrunk Poisson and the live Hard Rock line. "
            "Reject the leg if you do not want a zero-catch sample on the card."
        )
    if any(
        norm_name(leg.player) == "jahmyr gibbs" and leg.market == "receptions_q4"
        for ticket in tickets
        for leg in ticket["legs"]  # type: ignore[union-attr]
    ):
        lines.append(
            "Jahmyr Gibbs receptions_q4 is not the booked rush_yds_q4 leg. "
            "HR11-1 already has the rush_yds_q4 leg."
        )
    lines.extend(
        [
            "",
            "## Tickets",
            "",
            format_ticket_table(tickets),
            "",
            "## Legs",
            "",
            format_leg_table(decision_legs(pool)),
            "",
            "## Checks",
            "",
            "QB check on every new pass leg must be FAIL_BACKUP_QB=0.",
            "Josh Johnson pass_yds, James Cook III rush_yds, and Jahmyr Gibbs rush_yds_q4 are booked.",
            "Other markets for those three players stay eligible.",
            "Out, IR, and doubtful names are off. The Sunday T-90 list is off.",
            "DAL pass and receiving yards stay off while the AT&T roof is retractable and exposed.",
            "config/rosters/nfl.json was not rewritten.",
            "",
        ]
    )
    return "\n".join(lines)


def write_card(pool: dict[str, PricedLeg], tickets: list[dict[str, object]]) -> list[Path]:
    """Write the card, the placed-ticket shell, and the slate copies."""

    CARD_CSV.write_text(render_csv(tickets), encoding="utf-8")
    markdown = render_markdown(tickets, pool)
    CARD_MD.write_text(markdown, encoding="utf-8")
    DOC_PATH.write_text(markdown, encoding="utf-8")
    bets = REPO_ROOT / "data" / "bets" / "2026-11-22_hardrock_card.csv"
    bets.parent.mkdir(parents=True, exist_ok=True)
    bets.write_text(CARD_CSV.read_text(encoding="utf-8"), encoding="utf-8")
    ENTERED_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENTERED_PATH.write_text(render_entered(), encoding="utf-8")
    written = sync_dated_card(CARD_CSV, CARD_MD, SLATE_DAY, default_sync_roots())
    return [CARD_CSV, CARD_MD, DOC_PATH, bets, ENTERED_PATH, *written]


def _print_summary(pool: dict[str, PricedLeg], tickets: list[dict[str, object]]) -> None:
    print("QB_CHECK FAIL_BACKUP_QB=0")
    print(
        f"ALLOCATED {_money(allocated_cents(tickets))} "
        f"UNALLOCATED {_money(unallocated_cents(tickets))} "
        f"PLACED {_money(PLACED_STAKE_CENTS)}"
    )
    print(
        f"SCAN plus_legs={LAST_SCAN['plus_legs']} "
        f"bucket_a={LAST_SCAN['bucket_a']} bucket_b={LAST_SCAN['bucket_b']}"
    )
    print(format_leg_table(decision_legs(pool)))
    print(format_ticket_table(tickets))


def main() -> int:
    try:
        pool = screen_pool()
    except LiveLinesMissingError as exc:
        path = write_hardrock_template()
        print(f"STOP {exc}")
        print(f"TEMPLATE {path}")
        print("Do not fabricate lines.")
        return 2
    tickets = build_tickets(pool)
    card_legs = [leg for ticket in tickets for leg in ticket["legs"]]  # type: ignore[union-attr]
    failures = qb_check_failures(card_legs, _starters(STARTERS_PATH))
    if failures:
        raise ValueError("QB check failed: " + "; ".join(failures))
    written = write_card(pool, tickets)
    _print_summary(pool, tickets)
    for path in written:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
