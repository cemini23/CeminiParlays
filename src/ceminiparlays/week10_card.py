"""Week 10 Hard Rock research card for an $18.00 bankroll.

The builder reads the Week 10 packet tables in ``config/``. It does not open
a socket, it does not scrape a book, and it does not submit a bet. ``-110``
is the reference juice ladder. It is not a captured Hard Rock price.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import numpy as np

from ceminiparlays.book_team import canonical_team
from ceminiparlays.compose import MAX_TICKETS_PER_PROP, joint_ticket, redundant_quarter_pair
from ceminiparlays.correlation import LegRef, UnmodeledCorrelationError, correlation_matrix
from ceminiparlays.grade_card import LEDGER_COLUMNS, archive_card_copies
from ceminiparlays.half_edge import normal_over_prob
from ceminiparlays.io import OUT_STATUSES
from ceminiparlays.matchup_math import (
    clip_main_line_prob,
    fair_over_prob,
    full_game_yard_sigma,
    leg_ev,
    poisson_over_prob,
    sigma_floor,
)
from ceminiparlays.odds import american_to_decimal
from ceminiparlays.q4_checkdown import (
    BENCH_BLOWOUT_RB1,
    q4_rush_over_blocked,
    q4_rush_script_multiplier,
    q4_trail_market_rank,
    starter_rb,
    trail_receptions_over_allowed,
)
from ceminiparlays.resources import REPO_ROOT
from ceminiparlays.sunday_card import norm_name

SLATE_DAY = "2026-11-15"
ODDS_PATH = REPO_ROOT / "config" / "odds" / "environment_odds_2026-11-15.csv"
SCRATCH_PATH = REPO_ROOT / "config" / "scratches" / "2026-11-15.csv"
Q4_PATH = REPO_ROOT / "config" / "week10" / "q4_rb_checkdown_2026-11-15.csv"
SCRIPT_PATH = REPO_ROOT / "config" / "week10" / "quarter_script_2026-11-15.csv"
STARTERS_PATH = REPO_ROOT / "config" / "week10" / "qb_starters_2026-11-15.csv"
RATES_PATH = REPO_ROOT / "config" / "week10" / "team_rates_2026-11-15.csv"
CARD_PATH = REPO_ROOT / "data" / "bets" / "2026-11-15_hardrock_card.csv"
DOC_PATH = REPO_ROOT / "docs" / "2026-11-15-sunday-hardrock-card.md"

BANKROLL_CENTS = 1800
SINGLES_FLOOR_CENTS = 1170
PARLAY_CAP_CENTS = 630
TICKET_CAP_CENTS = 250
GAME_CAP_CENTS = 450
PLAYER_CAP_CENTS = 450
TIER1_COUNT = 4
TIER1_CENTS = 175
TIER2_COUNT = 4
TIER2_CENTS = 125
SGP_COUNT = 3
SGP_CENTS = 125
BOOST_CENTS = 125
CROSS_CENTS = 100
REF_PRICE = -110
Q4_RUSH_LINE = 14.5
Q4_REC_LINE = 0.5
PASS_FADE = frozenset({"HOU", "CLE", "BUF", "NYJ"})
WIND_NOTE_GAMES = (
    frozenset({"HOU", "CLE"}),
    frozenset({"BUF", "NYJ"}),
    frozenset({"SF", "DAL"}),
)
WALKER = "kenneth walker"
LOCK = "drew lock"
REF_NOTE = "REF_LADDER_NOT_BOOK; -110 is not a Hard Rock price"
# away, home, kick, munich. Munich stays off unless --include-munich.
SLATE_GAMES = (
    ("NE", "DET", "9:30 AM ET", True),
    ("KC", "ATL", "1:00 PM ET", False),
    ("HOU", "CLE", "1:00 PM ET", False),
    ("MIN", "GB", "1:00 PM ET", False),
    ("JAX", "TEN", "1:00 PM ET", False),
    ("MIA", "IND", "1:00 PM ET", False),
    ("CAR", "NO", "1:00 PM ET", False),
    ("BUF", "NYJ", "1:00 PM ET", False),
    ("SEA", "LV", "4:05 PM ET", False),
    ("LAR", "ARI", "4:05 PM ET", False),
    ("SF", "DAL", "4:25 PM ET", False),
)
# name, team, opp, market, how the mean is built, confirmed scheme note.
FULL_GAME_BOARD = (
    ("Kirk Cousins", "MIN", "GB", "pass_yds", "pass_off", False),
    ("Jordan Love", "GB", "MIN", "pass_yds", "pass_def", False),
    ("Christian McCaffrey", "SF", "DAL", "rush_yds", "rush_blend", True),
    ("C.J. Stroud", "HOU", "CLE", "pass_yds", "pass_def", True),
    ("James Cook III", "BUF", "NYJ", "rush_yds", "rush_blend", False),
    ("Chuba Hubbard", "CAR", "NO", "rush_yds", "rush_blend", False),
    ("Zach Charbonnet", "SEA", "LV", "rush_yds", "rush_blend", False),
    # Bench-blowout RB1s stay off rush_yds_q4. The full-game rush over stays.
    ("Kyren Williams", "LAR", "ARI", "rush_yds", "rush_blend", False),
    ("Bhayshul Tuten", "JAX", "TEN", "rush_yds", "rush_blend", False),
)


@dataclass(frozen=True)
class CardTicket:
    ticket_id: str
    tier: str
    legs: tuple[dict, ...]
    stake_cents: int
    tax_ev: float
    note: str
    joint_p: float = 0.0
    book_implied_p: float = 0.0


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def number(value: object) -> float | None:
    text = str(value or "").strip()
    if not text or text.upper() == "NO_EVIDENCE":
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def median(values: list[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    if count == 0:
        raise ValueError("median of an empty sample")
    mid = count // 2
    if count % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def game_key(leg: dict) -> frozenset[str]:
    return frozenset({str(leg.get("team") or ""), str(leg.get("opp") or "")})


def prop_id(leg: dict) -> tuple[str, str, str]:
    return (str(leg["player_key"]), str(leg["market"]), str(leg["side"]))


def load_blocked(path: Path) -> set[str]:
    """Never-enter tokens plus CONFLICT and RESERVE_VS_HUB labels."""

    names: set[str] = set()
    for row in read_csv(path):
        token = str(row.get("token") or "").strip().lower()
        label = str(row.get("label") or "").upper()
        conflict = "CONFLICT" in label or "RESERVE_VS_HUB" in label
        if token not in OUT_STATUSES and not conflict:
            continue
        player = norm_name(str(row.get("player") or ""))
        if player:
            names.add(player)
    return names


def load_starters(path: Path) -> dict[str, str]:
    starters: dict[str, str] = {}
    for row in read_csv(path):
        team = canonical_team(str(row.get("team") or ""))
        name = str(row.get("starter") or "").strip()
        if team and name:
            starters[team] = name
    return starters


def load_rates(path: Path) -> dict[str, dict[str, float]]:
    rates: dict[str, dict[str, float]] = {}
    for row in read_csv(path):
        team = canonical_team(str(row.get("team") or ""))
        parsed = {key: number(row.get(key)) for key in ("pass_off", "rush_off", "pass_def", "rush_def")}
        if team and all(value is not None for value in parsed.values()):
            rates[team] = {key: float(value) for key, value in parsed.items() if value is not None}
    return rates


def load_odds(path: Path) -> dict[tuple[str, str], dict[str, float]]:
    odds: dict[tuple[str, str], dict[str, float]] = {}
    for row in read_csv(path):
        team = canonical_team(str(row.get("team") or ""))
        opp = canonical_team(str(row.get("opp") or ""))
        spread = number(row.get("spread"))
        implied = number(row.get("implied_total"))
        total = number(row.get("over_under"))
        if team and opp and spread is not None and implied is not None and total is not None:
            odds[(team, opp)] = {"spread": spread, "implied_total": implied, "over_under": total}
    return odds


def slate_meta(include_munich: bool) -> dict[frozenset[str], dict[str, object]]:
    meta: dict[frozenset[str], dict[str, object]] = {}
    for away, home, kick, munich in SLATE_GAMES:
        if munich and not include_munich:
            continue
        meta[frozenset({away, home})] = {
            "away": away,
            "home": home,
            "kick": kick,
            "munich": munich,
            "label": f"{away} @ {home}",
        }
    return meta


def _book_implied(price: int) -> float:
    return 1.0 / american_to_decimal(int(price))


def _price_side(p_over: float) -> tuple[str, float, float, float] | None:
    """Clip one side to the reference ladder. Drop a side that does not pay."""

    try:
        fair_over = fair_over_prob(REF_PRICE, REF_PRICE)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(p_over) or abs(p_over - fair_over) <= 1e-12:
        return None
    if p_over > fair_over:
        side, raw, fair_side = "over", p_over, fair_over
    else:
        side, raw, fair_side = "under", 1.0 - p_over, 1.0 - fair_over
    try:
        model_p = clip_main_line_prob(raw, fair_side)
    except (TypeError, ValueError):
        return None
    ev = leg_ev(model_p, REF_PRICE)
    if ev <= 0.0 or not (0.18 - 1e-9 <= model_p <= 0.78 + 1e-9):
        return None
    return side, model_p, raw, ev


def _wind_review(team: str, opp: str, market: str) -> bool:
    game = frozenset({team, opp})
    if game not in WIND_NOTE_GAMES:
        return False
    return market.startswith("pass") or market in {"interceptions", "first_td"}


def _pass_over_blocked(team: str, market: str, side: str) -> bool:
    if side != "over" or team not in PASS_FADE:
        return False
    return market in {"pass_yds", "pass_yds_q4"}


def _held_out(name: str, market: str, *, allow_walker: bool) -> bool:
    key = norm_name(name)
    if key == WALKER and not allow_walker:
        return True
    if key == LOCK and (market.startswith("pass") or market == "interceptions"):
        return True
    return False


def _leg(
    *,
    player: str,
    team: str,
    opp: str,
    market: str,
    side: str,
    line: float,
    model_p: float,
    raw_p: float,
    ev: float,
    spread: float | None,
    meta: dict[str, object],
    source_note: str,
    family: int,
    rank: int | None = None,
) -> dict:
    return {
        "player_name": player,
        "player_key": norm_name(player),
        "team": team,
        "opp": opp,
        "market": market,
        "side": side,
        "line": float(line),
        "price": REF_PRICE,
        "model_p": float(model_p),
        "raw_p": float(raw_p),
        "ev": float(ev),
        "spread": spread,
        "game_id": f"{meta['away']}@{meta['home']}",
        "game_label": str(meta["label"]),
        "kick_et": str(meta["kick"]),
        "gsis_id": "",
        "source_note": source_note,
        "wind_review": _wind_review(team, opp, market),
        "family": family,
        "target_share_rank": rank,
    }


def _q3_means(path: Path) -> dict[frozenset[str], float]:
    rows = {
        (canonical_team(row["team"]), canonical_team(row["opp"])): row for row in read_csv(path)
    }
    means: dict[frozenset[str], float] = {}
    for away, home, _kick, _munich in SLATE_GAMES:
        away_row = rows.get((away, home))
        home_row = rows.get((home, away))
        if away_row is None or home_row is None:
            continue
        away_for = number(away_row.get("q3_pts_for_pg"))
        away_against = number(away_row.get("q3_pts_against_pg"))
        home_for = number(home_row.get("q3_pts_for_pg"))
        home_against = number(home_row.get("q3_pts_against_pg"))
        if None in {away_for, away_against, home_for, home_against}:
            continue
        estimate = ((away_for + home_against) + (home_for + away_against)) / 2.0
        means[frozenset({away, home})] = float(estimate)
    return means


def _full_game_mean(kind: str, team: str, opp: str, rates: dict[str, dict[str, float]]) -> float | None:
    offense = rates.get(team)
    defense = rates.get(opp)
    if offense is None or defense is None:
        return None
    if kind == "pass_off":
        return offense["pass_off"]
    if kind == "pass_def":
        return defense["pass_def"]
    if kind == "rush_blend":
        return (offense["rush_off"] + defense["rush_def"]) / 2.0
    return None


def build_pools(
    *,
    include_munich: bool,
    allow_questionable_dnp: bool,
    odds_path: Path = ODDS_PATH,
    scratch_path: Path = SCRATCH_PATH,
    q4_path: Path = Q4_PATH,
    script_path: Path = SCRIPT_PATH,
    starters_path: Path = STARTERS_PATH,
    rates_path: Path = RATES_PATH,
) -> dict[str, object]:
    """Price the packet board. A negative-EV side never enters a pool."""

    blocked = load_blocked(scratch_path)
    starters = load_starters(starters_path)
    rates = load_rates(rates_path)
    odds = load_odds(odds_path)
    meta = slate_meta(include_munich)
    included_teams = {team for game in meta for team in game}
    pass_line = median([rates[team]["pass_off"] for team in included_teams if team in rates])
    rush_line = median([rates[team]["rush_off"] for team in included_teams if team in rates])
    q3 = _q3_means(script_path)
    q3_line = median([value for game, value in q3.items() if game in meta])
    tier1: list[dict] = []
    tier2: list[dict] = []
    for name, team, opp, market, kind, confirmed in FULL_GAME_BOARD:
        game = frozenset({team, opp})
        if game not in meta or norm_name(name) in blocked:
            continue
        if _held_out(name, market, allow_walker=allow_questionable_dnp):
            continue
        if market.startswith("pass") and norm_name(name) != norm_name(starters.get(team, "")):
            continue
        mean = _full_game_mean(kind, team, opp, rates)
        posted = odds.get((team, opp))
        if mean is None or posted is None:
            continue
        line = pass_line if market == "pass_yds" else rush_line
        sigma = full_game_yard_sigma(market, line)
        priced = _price_side(normal_over_prob(line, mean, sigma))
        if priced is None or _pass_over_blocked(team, market, priced[0]):
            continue
        side, model_p, raw_p, ev = priced
        note = "LEAGUE_SLATE_MEDIAN_NOT_BOOK"
        if confirmed:
            note = f"{note}; CONFIRMED scheme lean"
        tier2.append(
            _leg(
                player=name,
                team=team,
                opp=opp,
                market=market,
                side=side,
                line=line,
                model_p=model_p,
                raw_p=raw_p,
                ev=ev,
                spread=posted["spread"],
                meta=meta[game],
                source_note=note,
                family=0,
            )
        )
    hou = frozenset({"HOU", "CLE"})
    if hou in meta and hou in q3:
        mean = q3[hou]
        priced = _price_side(normal_over_prob(q3_line, mean, sigma_floor("points", q3_line)))
        posted = odds.get(("HOU", "CLE"))
        if priced is not None and posted is not None:
            side, model_p, raw_p, ev = priced
            note = (
                f"mean {mean:.2f}; reference line is the slate median, not a book total"
            )
            tier2.append(
                _leg(
                    player="HOU at CLE",
                    team="HOU",
                    opp="CLE",
                    market="total_q3",
                    side=side,
                    line=q3_line,
                    model_p=model_p,
                    raw_p=raw_p,
                    ev=ev,
                    spread=posted["spread"],
                    meta=meta[hou],
                    source_note=note,
                    family=0,
                )
            )
    for row in read_csv(q4_path):
        team = canonical_team(str(row.get("team") or ""))
        opp = canonical_team(str(row.get("opp") or ""))
        game = frozenset({team, opp})
        if game not in meta:
            continue
        player = str(row.get("rb") or "").strip()
        if not player or norm_name(player) in blocked:
            continue
        played = number(row.get("games"))
        if played is None or played < 4.0:
            continue
        posted = odds.get((team, opp))
        if posted is None:
            continue
        spread = posted["spread"]
        rank_value = number(row.get("rb_tgt_share_rank"))
        rank = None if rank_value is None else int(rank_value)
        targets = number(row.get("tgt_pg")) or 0.0
        if _held_out(player, "rush_yds_q4", allow_walker=allow_questionable_dnp):
            continue
        starter = starter_rb(player, rank)
        factor = q4_rush_script_multiplier(spread, is_starter_rb=starter)
        rush_rate = number(row.get("q4_rush_yds_pg"))
        if (
            factor == 1.08
            and rush_rate is not None
            and rush_rate > 0.0
            and not q4_rush_over_blocked(spread, is_starter_rb=starter)
        ):
            sigma = sigma_floor("yards", Q4_RUSH_LINE)
            mean = rush_rate * factor
            priced = _price_side(normal_over_prob(Q4_RUSH_LINE, mean, sigma))
            if priced is not None and priced[0] == "over":
                side, model_p, raw_p, ev = priced
                tier1.append(
                    _leg(
                        player=player,
                        team=team,
                        opp=opp,
                        market="rush_yds_q4",
                        side=side,
                        line=Q4_RUSH_LINE,
                        model_p=model_p,
                        raw_p=raw_p,
                        ev=ev,
                        spread=spread,
                        meta=meta[game],
                        source_note="Q4 rush rate times the script factor; line 14.5 is not a book line",
                        family=0,
                        rank=rank,
                    )
                )
        catches = number(row.get("q4_rec_pg"))
        if catches is None or catches <= 0.0:
            continue
        try:
            p_over = poisson_over_prob(catches, Q4_REC_LINE)
        except ValueError:
            continue
        priced = _price_side(p_over)
        if priced is None:
            continue
        side, model_p, raw_p, ev = priced
        lead = factor == 1.08
        trail = trail_receptions_over_allowed(spread, played, targets, rank, player)
        favored_under = spread <= -3.0 and side == "under"
        if side == "over" and trail:
            family = 0
        elif side == "over" and lead:
            family = 0
        elif favored_under:
            family = 1
        else:
            continue
        tier1.append(
            _leg(
                player=player,
                team=team,
                opp=opp,
                market="receptions_q4",
                side=side,
                line=Q4_REC_LINE,
                model_p=model_p,
                raw_p=raw_p,
                ev=ev,
                spread=spread,
                meta=meta[game],
                source_note="Poisson Q4 reception rate; line 0.5 is not a book line",
                family=family,
                rank=rank,
            )
        )
    tier1.sort(key=_tier1_key)
    tier2.sort(key=_tier2_key)
    return {
        "tier1": tier1,
        "tier2": tier2,
        "blocked": blocked,
        "starters": starters,
        "meta": meta,
        "odds": odds,
        "pass_line": pass_line,
        "rush_line": rush_line,
        "q3_line": q3_line,
        "q3_means": q3,
    }


def _tier1_key(leg: dict) -> tuple:
    """Script overs first. A trail yards over ranks behind a trail catch over."""

    market_rank = 0
    if str(leg["market"]) == "rec_yds_q4" and str(leg["side"]) == "over":
        if q4_trail_market_rank(str(leg["market"]), "over", leg.get("spread")) == 2:
            market_rank = 1
    return (
        int(leg["family"]),
        market_rank,
        -float(leg["ev"]),
        -float(leg["raw_p"]),
        str(leg["player_name"]),
    )


def _tier2_key(leg: dict) -> tuple:
    return (-float(leg["ev"]), -float(leg["raw_p"]), str(leg["player_name"]))


def _pair_corr(legs: tuple[dict, ...] | list[dict]) -> tuple[np.ndarray, bool]:
    refs = [
        LegRef(
            player_key=str(leg["player_key"]),
            team=str(leg["team"]),
            opponent=str(leg["opp"]),
            stat_type=str(leg["market"]),
            side=str(leg["side"]),
        )
        for leg in legs
    ]
    try:
        return correlation_matrix(refs), False
    except UnmodeledCorrelationError:
        return np.eye(len(legs)), True


def _note_for(legs: tuple[dict, ...] | list[dict], extra: str = "") -> str:
    parts: list[str] = []
    for leg in legs:
        if leg.get("wind_review") and "[WIND_REVIEW_NOTE]" not in parts:
            parts.append("[WIND_REVIEW_NOTE]")
        source = str(leg.get("source_note") or "")
        if source and source not in parts:
            parts.append(source)
    if extra and extra not in parts:
        parts.append(extra)
    if REF_NOTE not in parts:
        parts.append(REF_NOTE)
    return "; ".join(parts).replace("|", "/")


def _make_ticket(
    ticket_id: str,
    tier: str,
    legs: list[dict],
    stake_cents: int,
    tax_ev: float,
    note: str,
    joint_p: float,
    book_implied_p: float,
) -> CardTicket:
    return CardTicket(
        ticket_id,
        tier,
        tuple(legs),
        stake_cents,
        tax_ev,
        note,
        joint_p,
        book_implied_p,
    )


def _exposure_ok(tickets: list[CardTicket], legs: list[dict], stake: int) -> bool:
    if stake > TICKET_CAP_CENTS:
        return False
    trial = tickets + [_make_ticket("trial", "0", legs, stake, 0.0, "", 0.0, 0.0)]
    if any(cents > GAME_CAP_CENTS for cents in game_exposure(trial).values()):
        return False
    if any(cents > PLAYER_CAP_CENTS for cents in player_exposure(trial).values()):
        return False
    if any(count > MAX_TICKETS_PER_PROP for count in prop_counts(trial).values()):
        return False
    return True


def game_exposure(tickets: list[CardTicket]) -> dict[frozenset[str], int]:
    totals: dict[frozenset[str], int] = defaultdict(int)
    for ticket in tickets:
        games = {game_key(leg) for leg in ticket.legs}
        for game in games:
            totals[game] += ticket.stake_cents
    return totals


def player_exposure(tickets: list[CardTicket]) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for ticket in tickets:
        players = {str(leg["player_key"]) for leg in ticket.legs}
        for player in players:
            totals[player] += ticket.stake_cents
    return totals


def prop_counts(tickets: list[CardTicket]) -> dict[tuple[str, str, str], int]:
    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for ticket in tickets:
        for leg in ticket.legs:
            counts[prop_id(leg)] += 1
    return counts


def _place_singles(
    pool: list[dict],
    count: int,
    stake: int,
    prefix: str,
    tier: str,
    chosen: list[CardTicket],
) -> list[str]:
    placed = 0
    seen: set[tuple[str, str, str]] = set()
    for leg in pool:
        if placed >= count:
            break
        ident = prop_id(leg)
        if ident in seen:
            continue
        if not _exposure_ok(chosen, [leg], stake):
            continue
        placed += 1
        seen.add(ident)
        ticket = _make_ticket(
            f"{prefix}{placed}",
            tier,
            [leg],
            stake,
            float(leg["ev"]),
            _note_for([leg]),
            float(leg["model_p"]),
            _book_implied(REF_PRICE),
        )
        chosen.append(ticket)
    if placed < count:
        return [f"tier {tier} short: {placed} of {count}"]
    return []


def _sgp_candidates(pool: list[dict]) -> list[dict]:
    grouped: dict[frozenset[str], list[dict]] = defaultdict(list)
    for leg in pool:
        grouped[game_key(leg)].append(leg)
    candidates: list[dict] = []
    for game, legs in grouped.items():
        unique: list[dict] = []
        seen: set[tuple[str, str, str]] = set()
        for leg in legs:
            ident = prop_id(leg)
            if ident in seen:
                continue
            seen.add(ident)
            unique.append(leg)
        for size in (2, 3):
            if len(unique) < size:
                continue
            for combo in combinations(unique, size):
                if any(redundant_quarter_pair(left, right) for left, right in combinations(combo, 2)):
                    continue
                corr, unmodeled = _pair_corr(combo)
                prices = [int(leg["price"]) for leg in combo]
                marginals = [float(leg["model_p"]) for leg in combo]
                priced = joint_ticket(marginals, prices, corr)
                tax = float(priced["tax_adjusted_sgp_ev"])
                if tax <= 0.0:
                    continue
                candidates.append(
                    {
                        "game": game,
                        "legs": list(combo),
                        "tax_ev": tax,
                        "raw": sum(float(leg["raw_p"]) for leg in combo),
                        "priced": priced,
                        "unmodeled": unmodeled,
                    }
                )
    candidates.sort(key=lambda item: (-float(item["tax_ev"]), -float(item["raw"]), str(sorted(item["game"]))))
    return candidates


def _place_sgps(pool: list[dict], chosen: list[CardTicket]) -> tuple[list[str], set[tuple[str, str, str]]]:
    used_games: set[frozenset[str]] = set()
    used_props: set[tuple[str, str, str]] = set()
    placed = 0
    for raw in _sgp_candidates(pool):
        if placed >= SGP_COUNT:
            break
        game = raw["game"]
        if game in used_games:
            continue
        idents = [prop_id(leg) for leg in raw["legs"]]
        if any(ident in used_props for ident in idents):
            continue
        if not _exposure_ok(chosen, raw["legs"], SGP_CENTS):
            continue
        placed += 1
        used_games.add(game)
        used_props.update(idents)
        priced = raw["priced"]
        extra = (
            f"gaussian_joint_p={float(priced['gaussian_joint_p']):.6f}; "
            f"t_copula_joint_p={float(priced['t_copula_joint_p']):.6f}"
        )
        if raw["unmodeled"]:
            extra = f"{extra}; UNMODELED_RHO"
        chosen.append(
            _make_ticket(
                f"HR10-SGP-{placed}",
                "3",
                raw["legs"],
                SGP_CENTS,
                float(raw["tax_ev"]),
                _note_for(raw["legs"], extra),
                float(priced["joint_p"]),
                1.0 / float(priced["decimal_sgp"]),
            )
        )
    if placed < SGP_COUNT:
        return [f"tier 3 SGP short: {placed} of {SGP_COUNT}"], used_props
    return [], used_props


def _cross_candidates(pool: list[dict], blocked_props: set[tuple[str, str, str]]) -> list[dict]:
    grouped: dict[frozenset[str], list[dict]] = defaultdict(list)
    for leg in pool:
        if prop_id(leg) in blocked_props:
            continue
        grouped[game_key(leg)].append(leg)
    games = [game for game, legs in grouped.items() if legs]
    candidates: list[dict] = []
    for picked in combinations(games, 3):
        buckets = [grouped[game] for game in picked]
        for combo in _product(buckets):
            corr = np.eye(len(combo))
            prices = [int(leg["price"]) for leg in combo]
            marginals = [float(leg["model_p"]) for leg in combo]
            priced = joint_ticket(marginals, prices, corr)
            tax = float(priced["tax_adjusted_sgp_ev"])
            if tax <= 0.0:
                continue
            candidates.append(
                {
                    "legs": list(combo),
                    "tax_ev": tax,
                    "raw": sum(float(leg["raw_p"]) for leg in combo),
                    "priced": priced,
                }
            )
    candidates.sort(key=lambda item: (-float(item["tax_ev"]), -float(item["raw"])))
    return candidates


def _product(buckets: list[list[dict]]) -> list[tuple[dict, ...]]:
    combos: list[tuple[dict, ...]] = [()]
    for bucket in buckets:
        combos = [(*combo, leg) for combo in combos for leg in bucket]
    return combos


def _place_crosses(
    pool: list[dict],
    chosen: list[CardTicket],
    blocked_props: set[tuple[str, str, str]],
) -> list[str]:
    used: set[tuple[str, str, str]] = set()
    placed: list[tuple[str, int]] = []
    slots = (("HR10-BOOST-1", BOOST_CENTS), ("HR10-CROSS-1", CROSS_CENTS))
    for raw in _cross_candidates(pool, blocked_props):
        if len(placed) >= len(slots):
            break
        idents = [prop_id(leg) for leg in raw["legs"]]
        if any(ident in used for ident in idents):
            continue
        ticket_id, stake = slots[len(placed)]
        if not _exposure_ok(chosen, raw["legs"], stake):
            continue
        used.update(idents)
        placed.append((ticket_id, stake))
        priced = raw["priced"]
        extra = "rho=0; one leg per game"
        chosen.append(
            _make_ticket(
                ticket_id,
                "3",
                raw["legs"],
                stake,
                float(raw["tax_ev"]),
                _note_for(raw["legs"], extra),
                float(priced["joint_p"]),
                1.0 / float(priced["decimal_sgp"]),
            )
        )
    if len(placed) < 2:
        return [f"tier 3 cross short: {len(placed)} of 2"]
    return []


def select_card(tier1: list[dict], tier2: list[dict]) -> tuple[list[CardTicket], list[str]]:
    """Fill 4 + 4 + 3 + 2 tickets. A negative-EV leg never enters."""

    chosen: list[CardTicket] = []
    short: list[str] = []
    short.extend(_place_singles(tier1, TIER1_COUNT, TIER1_CENTS, "HR10-Q4-", "1", chosen))
    short.extend(_place_singles(tier2, TIER2_COUNT, TIER2_CENTS, "HR10-CORE-", "2", chosen))
    sgp_pool = [leg for leg in tier1 if int(leg["family"]) == 0] + list(tier2)
    sgp_short, used = _place_sgps(sgp_pool, chosen)
    short.extend(sgp_short)
    short.extend(_place_crosses(sgp_pool, chosen, used))
    return chosen, short


def verify_card(
    tickets: list[CardTicket],
    blocked: set[str],
    starters: dict[str, str],
    *,
    include_munich: bool,
    allow_questionable_dnp: bool,
) -> list[str]:
    problems: list[str] = []
    if len(tickets) != 13:
        problems.append(f"ticket count {len(tickets)} is not 13")
    total = sum(ticket.stake_cents for ticket in tickets)
    if total != BANKROLL_CENTS:
        problems.append(f"stake sum {total} is not {BANKROLL_CENTS}")
    singles = sum(ticket.stake_cents for ticket in tickets if len(ticket.legs) == 1)
    parlays = total - singles
    if singles < SINGLES_FLOOR_CENTS:
        problems.append(f"singles {singles} are under {SINGLES_FLOOR_CENTS}")
    if parlays > PARLAY_CAP_CENTS:
        problems.append(f"parlays {parlays} are over {PARLAY_CAP_CENTS}")
    for ticket in tickets:
        if ticket.stake_cents > TICKET_CAP_CENTS:
            problems.append(f"{ticket.ticket_id} stake is over the ticket cap")
        if ticket.tax_ev <= 0.0:
            problems.append(f"{ticket.ticket_id} EV is not positive")
        if len(ticket.legs) > 1:
            games = {game_key(leg) for leg in ticket.legs}
            if ticket.ticket_id.startswith("HR10-SGP") and len(games) != 1:
                problems.append(f"{ticket.ticket_id} is not a same-game slip")
            if ticket.ticket_id.startswith(("HR10-BOOST", "HR10-CROSS")) and len(games) != len(ticket.legs):
                problems.append(f"{ticket.ticket_id} repeats a game")
    for game, cents in game_exposure(tickets).items():
        if cents > GAME_CAP_CENTS:
            problems.append(f"game {sorted(game)} exposure {cents} is over {GAME_CAP_CENTS}")
    for player, cents in player_exposure(tickets).items():
        if cents > PLAYER_CAP_CENTS:
            problems.append(f"player {player} exposure {cents} is over {PLAYER_CAP_CENTS}")
    for ident, count in prop_counts(tickets).items():
        if count > MAX_TICKETS_PER_PROP:
            problems.append(f"prop {ident} is on {count} tickets")
    multi: dict[tuple[str, str, str], int] = defaultdict(int)
    for ticket in tickets:
        if len(ticket.legs) < 2:
            continue
        for leg in ticket.legs:
            multi[prop_id(leg)] += 1
    for ident, count in multi.items():
        if count > 1:
            problems.append(f"multi-leg prop {ident} is repeated")
    for ticket in tickets:
        for leg in ticket.legs:
            name = norm_name(str(leg.get("player_name") or ""))
            market = str(leg.get("market") or "")
            team = str(leg.get("team") or "")
            opp = str(leg.get("opp") or "")
            model_p = float(leg["model_p"])
            if not 0.18 - 1e-9 <= model_p <= 0.78 + 1e-9:
                problems.append(f"{name} {market} model_p {model_p:.3f} is outside [0.18, 0.78]")
            if name in blocked:
                problems.append(f"{name} is blocked")
            if name == WALKER and not allow_questionable_dnp:
                problems.append("Kenneth Walker III is on the card")
            if name == LOCK and (market.startswith("pass") or market == "interceptions"):
                problems.append("Drew Lock pass leg is on the card")
            if not include_munich and (team in {"NE", "DET"} or opp in {"NE", "DET"}):
                problems.append(f"{team} at {opp} is a Munich leg")
            if market.startswith("pass") or market == "interceptions":
                starter = norm_name(starters.get(team, ""))
                if name != starter:
                    problems.append(f"{name} is not the {team} starter")
            if market == "rush_yds_q4" and str(leg.get("side")) == "over":
                starter_flag = starter_rb(str(leg.get("player_name") or ""), leg.get("target_share_rank"))
                if name in BENCH_BLOWOUT_RB1 or q4_rush_over_blocked(leg.get("spread"), starter_flag):
                    problems.append(f"{name} rush_yds_q4 over is blocked")
            if _pass_over_blocked(team, market, str(leg.get("side") or "")):
                problems.append(f"{name} pass over is in the wind fade")
    return problems


def build_card(
    *,
    include_munich: bool = False,
    allow_questionable_dnp: bool = False,
    odds_path: Path = ODDS_PATH,
    scratch_path: Path = SCRATCH_PATH,
    q4_path: Path = Q4_PATH,
    script_path: Path = SCRIPT_PATH,
    starters_path: Path = STARTERS_PATH,
    rates_path: Path = RATES_PATH,
) -> tuple[list[CardTicket], list[str], dict[str, object]]:
    pools = build_pools(
        include_munich=include_munich,
        allow_questionable_dnp=allow_questionable_dnp,
        odds_path=odds_path,
        scratch_path=scratch_path,
        q4_path=q4_path,
        script_path=script_path,
        starters_path=starters_path,
        rates_path=rates_path,
    )
    tickets, short = select_card(list(pools["tier1"]), list(pools["tier2"]))
    problems = list(short)
    if not short:
        problems = verify_card(
            tickets,
            set(pools["blocked"]),
            dict(pools["starters"]),
            include_munich=include_munich,
            allow_questionable_dnp=allow_questionable_dnp,
        )
    return tickets, problems, pools


def ledger_rows(tickets: list[CardTicket]) -> list[dict[str, str]]:
    """One row per leg. Multi-leg ``model_prob`` is the ticket joint."""

    rows: list[dict[str, str]] = []
    for ticket in tickets:
        for index, leg in enumerate(ticket.legs, start=1):
            model = float(leg["model_p"]) if len(ticket.legs) == 1 else float(ticket.joint_p)
            rows.append(
                {
                    "ticket_id": ticket.ticket_id,
                    "tier": ticket.tier,
                    "leg_num": str(index),
                    "game_id": str(leg.get("game_id") or ""),
                    "kick_et": str(leg.get("kick_et") or ""),
                    "player_name": str(leg.get("player_name") or ""),
                    "gsis_id": "",
                    "team": canonical_team(str(leg.get("team") or "")),
                    "opp": canonical_team(str(leg.get("opp") or "")),
                    "market": str(leg.get("market") or ""),
                    "side": str(leg.get("side") or ""),
                    "line": f"{float(leg['line']):.2f}",
                    "book_american_odds": str(REF_PRICE),
                    "model_prob": f"{model:.6f}",
                    "tax_adj_ev": f"{ticket.tax_ev:.6f}",
                    "ticket_stake_usd": f"{ticket.stake_cents / 100:.2f}",
                    "t90_flag": ticket.note,
                    "boost_pct": "",
                    "displayed_boosted_payout": "",
                    "off_card": "false",
                    "leg_statuses": "",
                    "leg_model_prob": f"{float(leg['model_p']):.6f}",
                }
            )
    return rows


def write_ledger(tickets: list[CardTicket], path: Path, doc_path: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(LEDGER_COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(ledger_rows(tickets))
    archive_card_copies(path, SLATE_DAY, doc_path=doc_path)


def _leg_text(leg: dict) -> str:
    return (
        f"{leg['player_name']} {leg['market']} {leg['side']} {float(leg['line']):.2f} "
        f"(ref {REF_PRICE})"
    )


def render_markdown(tickets: list[CardTicket], pools: dict[str, object]) -> str:
    singles = sum(ticket.stake_cents for ticket in tickets if len(ticket.legs) == 1)
    parlays = sum(ticket.stake_cents for ticket in tickets if len(ticket.legs) > 1)
    lines = [
        f"# Week 10 Sunday Hard Rock card, {SLATE_DAY}",
        "",
        "Do not submit a bet from this file. The operator types every ticket.",
        "",
        "The stake sum is $18.00. That is the research allocation for this card.",
        "The ticket cap is $2.50. The game cap is $4.50. The player cap is $4.50.",
        f"Singles use ${singles / 100:.2f}. Multi-leg slips use ${parlays / 100:.2f}.",
        "",
        "The number -110 is the reference juice ladder (REF_LADDER_NOT_BOOK).",
        "It is not a captured Hard Rock price. Do not type it as a book price.",
        "Spreads and totals are CLAIMED from config/odds/environment_odds_2026-11-15.csv.",
        "Full-game yard lines are the slate median of team rates (LEAGUE_SLATE_MEDIAN_NOT_BOOK).",
        "The Q3 reference line is the slate median of the two-way estimates, not a book total.",
        "",
        "Munich NE at DET (9:30 AM ET) is off unless you pass --include-munich.",
        "Kenneth Walker III (KC, questionable, Friday DNP) is off unless you pass",
        "--allow-questionable-dnp after the Sunday 11:30 AM ET inactives.",
        "Drew Lock pass legs are off. SEA rush legs can stay while he is the starter.",
        "Domes (CAR at NO, SEA at LV) have no wind fade. A missing wind is not a zero.",
        "Open-air wind of at least 12 mph blocks pass_yds OVER for HOU, CLE, BUF, and NYJ.",
        "A passing leg in HOU at CLE, BUF at NYJ, or SF at DAL carries [WIND_REVIEW_NOTE].",
        "No first_td leg is on this card. The packet has no first_td lean.",
        "",
        "Same-game slips report the Gaussian joint and the Student-t joint (df=5).",
        "When a pair rho is negative, the ticket uses the lower of the two joints.",
        "The grader scores Brier once per settled ticket, not once per leg.",
        "",
        "## Card",
        "",
        "| Ticket | Tier | Game and kick | Legs | Model prob | Tax-adj EV | Stake | Note |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for ticket in tickets:
        labels: list[str] = []
        for leg in ticket.legs:
            label = f"{leg.get('game_label')} {leg.get('kick_et')}".strip()
            if label not in labels:
                labels.append(label)
        legs = "; ".join(_leg_text(leg) for leg in ticket.legs)
        lines.append(
            f"| {ticket.ticket_id} | {ticket.tier} | {'; '.join(labels)} | {legs} | "
            f"{ticket.joint_p:.4f} | {ticket.tax_ev * 100.0:.1f}% | "
            f"${ticket.stake_cents / 100:.2f} | {ticket.note} |"
        )
    lines.extend(["", "## Exposure", "", "| Game | Exposure |", "| --- | ---: |"])
    labeled: dict[str, int] = {}
    for ticket in tickets:
        seen: set[str] = set()
        for leg in ticket.legs:
            label = str(leg.get("game_label") or "")
            if label in seen:
                continue
            seen.add(label)
            labeled[label] = labeled.get(label, 0) + ticket.stake_cents
    for label, cents in sorted(labeled.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {label} | ${cents / 100:.2f} |")
    lines.extend(
        [
            "",
            "## Packet spread and total",
            "",
            "Home spread is the home team's CLAIMED number. A negative number is a favorite.",
            "NE at DET is listed and is not on the default card.",
            "",
            "| Game | Spread | Total | On default card |",
            "| --- | ---: | ---: | --- |",
        ]
    )
    odds = dict(pools.get("odds") or {})
    active = set(pools.get("meta") or {})
    for away, home, kick, munich in SLATE_GAMES:
        posted = odds.get((home, away))
        spread = "" if posted is None else f"{posted['spread']:.1f}"
        total = "" if posted is None else f"{posted['over_under']:.1f}"
        used = "no" if munich or frozenset({away, home}) not in active else "yes"
        lines.append(f"| {away} @ {home} {kick} | {spread} | {total} | {used} |")
    lines.extend(
        [
            "",
            "Q4 rush reference line is 14.5 with sigma 8. The mean is the packet Q4 rate",
            "times the script factor. A bench-blowout RB1 rush_yds_q4 OVER is blocked",
            "(James Cook III, Kyren Williams, Bhayshul Tuten). Use the full-game rush over.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Week 10 $18.00 Hard Rock research card.")
    parser.add_argument("--card", type=Path, default=CARD_PATH)
    parser.add_argument("--doc", type=Path, default=DOC_PATH)
    parser.add_argument("--odds", type=Path, default=ODDS_PATH)
    parser.add_argument("--scratches", type=Path, default=SCRATCH_PATH)
    parser.add_argument(
        "--include-munich",
        action="store_true",
        help="Include NE at DET. The default card leaves the 9:30 AM ET game off.",
    )
    parser.add_argument(
        "--allow-questionable-dnp",
        action="store_true",
        help="Allow Kenneth Walker III after the Sunday 11:30 AM ET inactives.",
    )
    args = parser.parse_args(argv)
    try:
        tickets, problems, pools = build_card(
            include_munich=args.include_munich,
            allow_questionable_dnp=args.allow_questionable_dnp,
            odds_path=args.odds,
            scratch_path=args.scratches,
        )
    except FileNotFoundError as exc:
        print(exc)
        return 2
    if problems:
        print("CARD SHORT")
        for item in problems:
            print(item)
        return 2
    text = render_markdown(tickets, pools)
    args.doc.parent.mkdir(parents=True, exist_ok=True)
    args.doc.write_text(text, encoding="utf-8")
    write_ledger(tickets, args.card, args.doc)
    print(text)
    print(f"wrote {args.card}")
    print(f"wrote {args.doc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
