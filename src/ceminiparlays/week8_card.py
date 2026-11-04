"""Week-8 Hard Rock research card for an $8.00 bankroll.

The builder reads a captured board and the Week 8 point-in-time cache.
It does not open a socket, it does not invent a price, and it does not
submit a bet. A tier that has no positive-EV play stays empty.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from ceminiparlays.book_team import canonical_team
from ceminiparlays.compose import rank_same_game, redundant_quarter_pair
from ceminiparlays.copula import exact_joint
from ceminiparlays.feature_cache import load_feature_cache
from ceminiparlays.grade_card import LEDGER_COLUMNS, archive_card_copies
from ceminiparlays.half_edge import normal_over_prob
from ceminiparlays.io import OUT_STATUSES
from ceminiparlays.matchup_math import (
    YPC_SD_FLOOR,
    baseline_volume,
    clip_main_line_prob,
    fair_over_prob,
    leg_ev,
    quarter_share,
    sigma_floor,
)
from ceminiparlays.names import fold_name
from ceminiparlays.odds import american_to_decimal
from ceminiparlays.q4_checkdown import CheckdownInputs, price_checkdown
from ceminiparlays.quarter_usage import attach_quarter_counts, reception_over_blocked
from ceminiparlays.resources import REPO_ROOT
from ceminiparlays.sunday_card import norm_name
from ceminiparlays.week7_card import pair_ok

SLATE_DAY = "2026-11-01"
CACHE_DIR = Path("/Users/claudiobarone/Projects/CeminiDFS/data/shared_cache/2026_w08")
LINES_PATH = Path("/tmp/hardrock_nfl_20261101.csv")
SCRATCH_PATH = REPO_ROOT / "config" / "scratches" / "2026-11-01.csv"
CARD_PATH = REPO_ROOT / "data" / "bets" / "2026-11-01_hardrock_card.csv"
DOC_PATH = REPO_ROOT / "docs" / "2026-11-01-sunday-hardrock-card.md"

SUNDAY_KICKS = (
    ("2026-11-01T18:00", "1:00 PM ET"),
    ("2026-11-01T21:05", "4:05 PM ET"),
    ("2026-11-01T21:25", "4:25 PM ET"),
)
PASS_FADE = frozenset({"ATL", "TB", "IND", "JAX"})
Q_WATCH = frozenset(
    {
        "breece hall",
        "dj moore",
        "george pickens",
        "jakobi meyers",
        "jaylen waddle",
    }
)
DNP_WATCH = frozenset({"puka nacua"})
TIER2_MARKETS = frozenset({"rec_yds_q3", "rec_yds_q4", "rush_yds_q4", "pass_yds_q4"})
CHECKDOWN_BOARD = frozenset({"receptions_q4", "rec_yds_q4", "rec_yds_q3"})
FULL_GAME_YARDS = frozenset({"pass_yds", "rush_yds", "rec_yds"})
SKILL = frozenset({"RB", "WR", "TE", "FB"})

TIER1_COUNT = 4
TIER1_CENTS = 100
TIER2_COUNT = 2
TIER2_CENTS = 125
SGP_COUNT = 2
SLIP_CENTS = 50
GAME_CAP_CENTS = 250
TICKET_CAP_CENTS = 175
BANKROLL_CENTS = 800
SINGLES_FLOOR_CENTS = 520
PARLAY_CAP_CENTS = 280
PBP_PATH = Path("/Users/claudiobarone/Projects/CeminiDFS/artifacts/cache/pbp_2026.parquet")
BEFORE_WEEK = 8
FAVORED_SPREAD = -2.0


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


def finite(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def american_int(value: object) -> int | None:
    try:
        number = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if number == 0 or -100 < number < 100:
        return None
    return number


def american_text(price: int) -> str:
    return f"+{price}" if price > 0 else str(price)


def kick_label(commence: str) -> str:
    text = str(commence or "")
    for prefix, label in SUNDAY_KICKS:
        if text.startswith(prefix):
            return label
    return ""


def game_key(leg: dict) -> frozenset[str]:
    return frozenset({str(leg.get("team") or ""), str(leg.get("opp") or "")})


def mean_of(rows: list[dict], field: str) -> float | None:
    values = [value for row in rows if (value := finite(row.get(field))) is not None]
    if not values:
        return None
    return sum(values) / len(values)


def load_never(path: Path) -> set[str]:
    """Names whose token is Out, IR, Inactive, Doubtful, NFI, PUP, or suspended."""

    names: set[str] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            token = str(row.get("token") or "").strip().lower()
            if token not in OUT_STATUSES:
                continue
            player = norm_name(str(row.get("player") or ""))
            if player:
                names.add(player)
    return names


def frame_rows(frame: object) -> list[dict]:
    records = frame.to_dict("records")  # type: ignore[attr-defined]
    clean: list[dict] = []
    for row in records:
        item: dict = {}
        for key, value in row.items():
            if value is None:
                item[key] = None
                continue
            try:
                if value != value:
                    item[key] = None
                    continue
            except TypeError:
                pass
            item[key] = value
        clean.append(item)
    return clean


def _clipped_side(
    p_raw: float,
    fair: float,
    book_over: int,
    book_under: int,
) -> dict | None:
    """Keep the model side only when the clip still beats the book and pays."""

    if p_raw > fair:
        p_over = clip_main_line_prob(p_raw, fair)
        if p_over <= fair:
            return None
        ev = leg_ev(p_over, book_over)
        if ev <= 0.0:
            return None
        return {"side": "over", "model_p": p_over, "fair_p": fair, "ev": ev, "price": book_over}
    p_under_raw = 1.0 - p_raw
    fair_under = 1.0 - fair
    if p_under_raw <= fair_under:
        return None
    p_under = clip_main_line_prob(p_under_raw, fair_under)
    if p_under <= fair_under:
        return None
    ev = leg_ev(p_under, book_under)
    if ev <= 0.0:
        return None
    return {
        "side": "under",
        "model_p": p_under,
        "fair_p": fair_under,
        "ev": ev,
        "price": book_under,
    }


def price_period_yards(
    *,
    games: float,
    rate: float,
    line: float,
    book_over: int,
    book_under: int,
    opps_q: float = 0.0,
    opps_total: float = 0.0,
) -> dict | None:
    """Quarter yards = full-game rate times the Empirical Bayes quarter share.

    Both counts at zero keep the locked 0.25 prior. Sigma is the period floor,
    not the full-game yard floor.
    """

    base = baseline_volume(games, rate)
    if base is None or base <= 0.0:
        return None
    share = quarter_share(float(opps_q), float(opps_total))
    mean = base * share
    if mean <= 0.0 or not math.isfinite(mean):
        return None
    try:
        sigma = sigma_floor("yards", float(line))
        p_raw = normal_over_prob(float(line), mean, sigma)
        fair = fair_over_prob(int(book_over), int(book_under))
    except (TypeError, ValueError):
        return None
    priced = _clipped_side(p_raw, fair, int(book_over), int(book_under))
    if priced is None:
        return None
    priced["w_q_eb"] = share
    return priced


def clip_printed_side(model_p: float, fair_p: float, price: int) -> tuple[float, float] | None:
    """Clip one already-chosen side. Drop the leg when the clip removes the edge."""

    try:
        clipped = clip_main_line_prob(float(model_p), float(fair_p))
    except (TypeError, ValueError):
        return None
    if float(model_p) > float(fair_p) and clipped <= float(fair_p):
        return None
    ev = leg_ev(clipped, int(price))
    if ev <= 0.0:
        return None
    return clipped, ev


def product_ev(legs: list[dict] | tuple[dict, ...]) -> tuple[float, float]:
    """Independent cross-game product. Rho is 0, so the SGP tax does not apply."""

    prob = 1.0
    decimal = 1.0
    for leg in legs:
        prob *= float(leg["model_p"])
        decimal *= american_to_decimal(int(leg["price"]))
    return prob * decimal - 1.0, decimal


def has_quarter_pair(legs: list[dict]) -> bool:
    return any(redundant_quarter_pair(left, right) for left, right in combinations(legs, 2))


def exposure_ok(exposure: dict[frozenset[str], int], legs: list[dict], stake: int) -> bool:
    if stake > TICKET_CAP_CENTS:
        return False
    for key in {game_key(leg) for leg in legs}:
        if exposure.get(key, 0) + stake > GAME_CAP_CENTS:
            return False
    return True


def add_exposure(exposure: dict[frozenset[str], int], legs: list[dict], stake: int) -> None:
    for key in {game_key(leg) for leg in legs}:
        exposure[key] = exposure.get(key, 0) + stake


def _ev_key(leg: dict) -> tuple:
    return (-float(leg["ev"]), str(leg.get("player_key") or ""), str(leg.get("market") or ""))


def _place(
    chosen: list[CardTicket],
    card_legs: list[dict],
    exposure: dict[frozenset[str], int],
    ticket: CardTicket,
) -> bool:
    legs = list(ticket.legs)
    if ticket.tax_ev <= 0.0 or ticket.stake_cents <= 0:
        return False
    if any(float(leg.get("ev") or 0.0) <= 0.0 for leg in legs):
        return False
    if has_quarter_pair(card_legs + legs):
        return False
    if len(legs) > 1 and not all(pair_ok(left, right) for left, right in combinations(legs, 2)):
        return False
    if not exposure_ok(exposure, legs, ticket.stake_cents):
        return False
    chosen.append(ticket)
    card_legs.extend(legs)
    add_exposure(exposure, legs, ticket.stake_cents)
    return True


def _leg_identity(leg: dict) -> tuple[str, str, str, float]:
    """One player prop. A different market, side, or line is a different prop."""

    return (
        str(leg.get("player_key") or ""),
        str(leg.get("market") or ""),
        str(leg.get("side") or ""),
        round(float(leg.get("line") or 0.0), 1),
    )


def _book_implied(price: int) -> float:
    return 1.0 / american_to_decimal(int(price))


def _single_probs(leg: dict) -> tuple[float, float]:
    return float(leg["model_p"]), _book_implied(int(leg["price"]))


def _independent_joint(legs: list[dict]) -> float:
    """Gaussian copula joint at rho 0. Two or more legs."""

    import numpy as np

    marginals = [float(leg["model_p"]) for leg in legs]
    return float(exact_joint(marginals, np.eye(len(legs)), "gaussian"))


def _sgp_probs(raw: dict, legs: list[dict]) -> tuple[float, float]:
    if raw.get("joint_p") is not None:
        joint = float(raw["joint_p"])
    else:
        joint = _independent_joint(legs)
    decimal = raw.get("decimal_sgp")
    if decimal is None:
        decimal = 1.0
        for leg in legs:
            decimal *= american_to_decimal(int(leg["price"]))
    book = 1.0 / float(decimal) if float(decimal) > 0.0 else 0.0
    return joint, book


def _boost_probs(legs: list[dict]) -> tuple[float, float]:
    book = 1.0
    for leg in legs:
        book *= _book_implied(int(leg["price"]))
    return _independent_joint(legs), book


def _make_ticket(
    ticket_id: str,
    tier: str,
    legs: list[dict] | tuple[dict, ...],
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
        float(joint_p),
        float(book_implied_p),
    )


def favored_catch_under(
    *,
    market: str,
    line: float,
    over_p: float,
    book_under: int,
    spread: float | None,
) -> tuple[float, float] | None:
    """Under probability and EV for a favored grinder at receptions_q4 0.5.

    ``None`` when the market, the line, the spread, or the EV does not qualify.
    A non-positive EV is not forced onto the card.
    """

    if market != "receptions_q4" or abs(float(line) - 0.5) > 1e-9:
        return None
    if spread is None or float(spread) > FAVORED_SPREAD:
        return None
    under_p = 1.0 - float(over_p)
    ev = leg_ev(under_p, int(book_under))
    if ev <= 0.0:
        return None
    return under_p, ev


def _best_boost(
    pool: list[dict],
    card_legs: list[dict],
    exposure: dict[frozenset[str], int],
    banned: set[tuple[str, str, str, float]] | None = None,
) -> list[dict] | None:
    """One leg per game. Prefer a 3-leg upside combo, then a 2-leg combo.

    ``banned`` holds props that already sit on another multi-leg ticket.
    """

    blocked = banned or set()
    by_game: dict[frozenset[str], list[dict]] = defaultdict(list)
    for leg in pool:
        if float(leg.get("ev") or 0.0) <= 0.0:
            continue
        if _leg_identity(leg) in blocked:
            continue
        if has_quarter_pair(card_legs + [leg]):
            continue
        by_game[game_key(leg)].append(leg)
    options: list[list[dict]] = []
    for rows in by_game.values():
        ranked = sorted(rows, key=lambda leg: -american_to_decimal(int(leg["price"])))
        kept = ranked[:3]
        if kept:
            options.append(kept)
    best: list[dict] | None = None
    best_decimal = -1.0

    def consider(width: int) -> None:
        nonlocal best, best_decimal
        if len(options) < width:
            return
        for groups in combinations(options, width):
            choices = [list(group) for group in groups]
            # The product of three short lists stays small.
            stacks = [[]]
            for group in choices:
                stacks = [stack + [leg] for stack in stacks for leg in group]
            for combo in stacks:
                if has_quarter_pair(card_legs + combo):
                    continue
                if not all(pair_ok(left, right) for left, right in combinations(combo, 2)):
                    continue
                if not exposure_ok(exposure, combo, SLIP_CENTS):
                    continue
                ev, decimal = product_ev(combo)
                if ev <= 0.0:
                    continue
                if decimal > best_decimal:
                    best = combo
                    best_decimal = decimal

    consider(3)
    if best is None:
        consider(2)
    return best


def _single_ticket(ticket_id: str, tier: str, leg: dict, cents: int) -> CardTicket:
    joint_p, book_p = _single_probs(leg)
    return _make_ticket(
        ticket_id,
        tier,
        (leg,),
        cents,
        float(leg["ev"]),
        str(leg.get("note") or "none"),
        joint_p,
        book_p,
    )


def _tier1_legs(tier1: list[dict]) -> tuple[list[dict], list[dict]]:
    """The reception unders, then the overs, each best EV first."""

    unders = [
        leg
        for leg in tier1
        if leg.get("side") == "under" and leg.get("market") == "receptions_q4"
    ]
    overs = [leg for leg in tier1 if leg.get("side") == "over"]
    unders.sort(key=_ev_key)
    overs.sort(key=_ev_key)
    return unders, overs


def _place_one_under(
    unders: list[dict],
    chosen: list[CardTicket],
    card_legs: list[dict],
    exposure: dict[frozenset[str], int],
    players: set[str],
    index: int,
) -> tuple[int, bool]:
    """At most one reception under enters, and only for a new player."""

    for leg in unders:
        if str(leg.get("player_key") or "") in players:
            continue
        ticket = _single_ticket(f"HR8-Q4-{index}", "1", leg, TIER1_CENTS)
        if _place(chosen, card_legs, exposure, ticket):
            players.add(str(leg.get("player_key") or ""))
            return index + 1, True
    return index, False


def _place_overs(
    overs: list[dict],
    chosen: list[CardTicket],
    card_legs: list[dict],
    exposure: dict[frozenset[str], int],
    players: set[str],
    index: int,
) -> int:
    for leg in overs:
        if index > TIER1_COUNT:
            break
        key = str(leg.get("player_key") or "")
        if not key or key in players:
            continue
        ticket = _single_ticket(f"HR8-Q4-{index}", "1", leg, TIER1_CENTS)
        if _place(chosen, card_legs, exposure, ticket):
            players.add(key)
            index += 1
    return index


def _place_tier1(
    chosen: list[CardTicket],
    card_legs: list[dict],
    exposure: dict[frozenset[str], int],
    tier1: list[dict],
) -> list[str]:
    short: list[str] = []
    players: set[str] = set()
    unders, overs = _tier1_legs(tier1)
    index = 1
    if unders:
        index, placed = _place_one_under(
            unders, chosen, card_legs, exposure, players, index
        )
        if not placed:
            short.append("tier 1 under did not fit")
    index = _place_overs(overs, chosen, card_legs, exposure, players, index)
    tier1_n = sum(1 for ticket in chosen if ticket.tier == "1")
    if tier1_n < TIER1_COUNT:
        short.append(f"tier 1 short: {tier1_n} of {TIER1_COUNT}")
    return short


def _single_identities(chosen: list[CardTicket]) -> set[tuple[str, str]]:
    return {
        (str(leg.get("player_key") or ""), str(leg.get("market") or ""))
        for ticket in chosen
        for leg in ticket.legs
    }


def _place_tier2(
    chosen: list[CardTicket],
    card_legs: list[dict],
    exposure: dict[frozenset[str], int],
    tier2: list[dict],
) -> list[str]:
    short: list[str] = []
    singles = _single_identities(chosen)
    core = 1
    for leg in sorted(tier2, key=_ev_key):
        if core > TIER2_COUNT:
            break
        identity = (str(leg.get("player_key") or ""), str(leg.get("market") or ""))
        if identity in singles:
            continue
        if float(leg.get("model_p") or 0.0) > 0.78:
            continue
        ticket = _single_ticket(f"HR8-CORE-{core}", "2", leg, TIER2_CENTS)
        if _place(chosen, card_legs, exposure, ticket):
            singles.add(identity)
            core += 1
    tier2_n = sum(1 for ticket in chosen if ticket.tier == "2")
    if tier2_n < TIER2_COUNT:
        short.append(f"tier 2 short: {tier2_n} of {TIER2_COUNT}")
    return short


def _sgp_note(raw: dict, legs: list[dict]) -> str:
    note = (
        "SGP tax applied"
        if raw.get("sgp_tax_applied")
        else "naive product; pair rho at or under 0.15"
    )
    extra = [
        str(leg.get("note") or "")
        for leg in legs
        if str(leg.get("note") or "") not in {"", "none"}
    ]
    if extra:
        note = "; ".join([note, *extra])
    return note


def _place_sgps(
    chosen: list[CardTicket],
    card_legs: list[dict],
    exposure: dict[frozenset[str], int],
    sgps: list[dict],
) -> tuple[list[str], set[tuple[str, str, str, float]]]:
    short: list[str] = []
    sgp_n = 1
    seen_sets: set[tuple] = set()
    used_multi: set[tuple[str, str, str, float]] = set()
    for raw in sgps:
        if sgp_n > SGP_COUNT:
            break
        legs = list(raw.get("legs") or [])
        if not 2 <= len(legs) <= 4:
            continue
        try:
            tax_ev = float(raw.get("tax_adjusted_sgp_ev") or 0.0)
        except (TypeError, ValueError):
            continue
        if tax_ev <= 0.0:
            continue
        idents = [_leg_identity(leg) for leg in legs]
        if any(item in used_multi for item in idents):
            continue
        identity = tuple(sorted((item[0], item[1]) for item in idents))
        if identity in seen_sets:
            continue
        joint_p, book_p = _sgp_probs(raw, legs)
        ticket = _make_ticket(
            f"HR8-SGP-{sgp_n}",
            "3",
            legs,
            SLIP_CENTS,
            tax_ev,
            _sgp_note(raw, legs),
            joint_p,
            book_p,
        )
        if _place(chosen, card_legs, exposure, ticket):
            seen_sets.add(identity)
            used_multi.update(idents)
            sgp_n += 1
    placed = sum(1 for ticket in chosen if ticket.ticket_id.startswith("HR8-SGP-"))
    if placed < SGP_COUNT:
        short.append(f"tier 3 SGP short: {placed} of {SGP_COUNT}")
    return short, used_multi


def _place_boost(
    chosen: list[CardTicket],
    card_legs: list[dict],
    exposure: dict[frozenset[str], int],
    boost_pool: list[dict],
    used_multi: set[tuple[str, str, str, float]],
) -> list[str]:
    combo = _best_boost(boost_pool, card_legs, exposure, used_multi)
    if combo is None:
        return ["tier 3 boost combo short"]
    ev, _decimal = product_ev(combo)
    note = "designed for the profit-boost token; displayed payout left blank"
    extra = [
        str(leg.get("note") or "")
        for leg in combo
        if str(leg.get("note") or "") not in {"", "none"}
    ]
    if extra:
        note = "; ".join([note, *dict.fromkeys(extra)])
    joint_p, book_p = _boost_probs(combo)
    ticket = _make_ticket(
        "HR8-BOOST-1", "3", combo, SLIP_CENTS, ev, note, joint_p, book_p
    )
    if not _place(chosen, card_legs, exposure, ticket):
        return ["tier 3 boost combo short"]
    return []


def select_card(
    tier1: list[dict],
    tier2: list[dict],
    sgps: list[dict],
    boost_pool: list[dict],
) -> tuple[list[CardTicket], list[str]]:
    """Fill 4 + 2 + 3 tickets. A negative-EV leg never enters."""

    chosen: list[CardTicket] = []
    card_legs: list[dict] = []
    exposure: dict[frozenset[str], int] = {}
    short: list[str] = []
    short.extend(_place_tier1(chosen, card_legs, exposure, tier1))
    short.extend(_place_tier2(chosen, card_legs, exposure, tier2))
    sgp_short, used_multi = _place_sgps(chosen, card_legs, exposure, sgps)
    short.extend(sgp_short)
    short.extend(_place_boost(chosen, card_legs, exposure, boost_pool, used_multi))
    return chosen, short


def _note(player: str, team: str, opp: str, market: str, roof: str) -> str:
    notes: list[str] = []
    name = norm_name(player)
    if name in Q_WATCH:
        notes.append("Q confirm at inactives")
    if name in DNP_WATCH:
        notes.append("DNP confirm at inactives")
    if market.startswith("pass"):
        notes.append("QB CLAIMED not CONFIRMED")
    if team in PASS_FADE and market.startswith("pass"):
        notes.append("[WIND_REVIEW_NOTE]")
    if team in {"NE", "MIA"} and market.startswith("pass"):
        notes.append("[WIND_REVIEW_NOTE]")
    if frozenset({team, opp}) == frozenset({"ARI", "DAL"}) and roof.strip().lower() in {"", "none", "nan", "tbd"}:
        notes.append("roof TBD confirm at T-90")
    return "; ".join(notes) if notes else "none"


def _base_leg(row: dict, player: dict, meta: dict, market: str, side: str, line: float, price: int, model_p: float, ev: float) -> dict:
    team = canonical_team(str(row.get("team") or ""))
    opp = canonical_team(str(row.get("opp") or ""))
    roof = str(meta.get("roof") or "")
    return {
        "market": market,
        "player_name": str(row.get("player_name") or player.get("player_name") or ""),
        "player_key": str(row.get("player_key") or fold_name(str(player.get("player_name") or ""))),
        "team": team,
        "opp": opp,
        "line": float(line),
        "side": side,
        "price": int(price),
        "model_p": float(model_p),
        "ev": float(ev),
        "game_id": str(meta.get("game_id") or ""),
        "kick_et": str(meta.get("kick_et") or ""),
        "game_label": str(meta.get("label") or ""),
        "gsis_id": str(player.get("player_id") or ""),
        "position": str(player.get("position") or "").upper(),
        "spread": meta.get("spread"),
        "game_total": meta.get("game_total"),
        "targets_per_game": finite(player.get("targets_per_game")) or 0.0,
        "games": finite(player.get("games")) or 0.0,
        "note": _note(
            str(row.get("player_name") or ""),
            team,
            opp,
            market,
            roof,
        ),
    }


def _keep_best(pool: dict[tuple[str, str], dict], leg: dict) -> None:
    key = (str(leg["player_key"]), str(leg["market"]))
    current = pool.get(key)
    if current is None or float(leg["ev"]) > float(current["ev"]):
        pool[key] = leg


def _checkdown_inputs(
    player: dict,
    defense: dict | None,
    league_trail: float,
    league_cushion: float | None,
    league_comp: float | None,
    league_yac: float | None,
    market: str,
    spread: float | None,
    game_total: float | None,
) -> CheckdownInputs:
    quarter = 3 if market.endswith("_q3") else 4
    games = finite(player.get("games")) or 0.0
    targets = finite(player.get("targets_per_game")) or 0.0
    cushion = finite(player.get("avg_cushion"))
    if cushion is None or cushion <= 0.0:
        cushion = None
    # ``trail4_opps`` is not a player quarter-target count. It often exceeds
    # the player's own targets, and that pushes ``quarter_share`` toward 1.
    # Absent count fields keep the locked 0.25 prior.
    if quarter == 3:
        opps_q = finite(player.get("q3_targets"))
    else:
        opps_q = finite(player.get("q4_targets"))
    opps_total = finite(player.get("total_targets"))
    if opps_q is None or opps_total is None:
        opps_q = 0.0
        opps_total = 0.0
    return CheckdownInputs(
        games=games,
        receptions_per_game=finite(player.get("receptions_per_game")) or 0.0,
        rec_yds_per_game=finite(player.get("rec_yds_per_game")) or 0.0,
        targets_per_game=targets,
        opps_q=float(opps_q),
        opps_total=float(opps_total),
        q4_trail_target_share=finite(player.get("q4_trail_target_share")),
        vacated_target_boost=finite(player.get("vacated_target_boost")) or 0.0,
        avg_cushion=cushion,
        def_q4_comp_rate=finite((defense or {}).get("def_q4_comp_rate")),
        def_q4_yac=finite((defense or {}).get("def_q4_yac")),
        league_trail_share=league_trail,
        league_cushion=league_cushion,
        league_comp=league_comp,
        league_yac=league_yac,
        quarter=quarter,
        ypc_sd=YPC_SD_FLOOR,
        p_gain=1.0,
        spread=spread,
        game_total=game_total,
        third_down_route_share=None,
        require_script=quarter == 4 and spread is None,
    )


def build_pools(
    lines: list[dict],
    cache: dict,
    never: set[str],
    plays: list[dict] | None = None,
) -> dict[str, list]:
    """Price the Sunday board. Full-game scheme leans stay off: none are confirmed.

    ``plays`` are local play-by-play rows. Weeks at or after ``BEFORE_WEEK``
    are dropped inside the count join. A missing play list leaves the 0.25 prior.
    """

    players = frame_rows(cache["player_telemetry_pit.parquet"])
    attach_quarter_counts(players, plays or [], before_week=BEFORE_WEEK)
    blocked_names: list[str] = []
    defense_rows = frame_rows(cache["defense_counterpart_pit.parquet"])
    games = frame_rows(cache["game_context_pit.parquet"])
    by_key: dict[str, dict] = {}
    for row in players:
        key = fold_name(str(row.get("player_name") or ""))
        if key:
            by_key[key] = row
    defense_by_team = {
        canonical_team(str(row.get("team") or "")): row
        for row in defense_rows
        if canonical_team(str(row.get("team") or ""))
    }
    rb_rows = [
        row
        for row in players
        if str(row.get("position") or "").upper() == "RB" and (finite(row.get("games")) or 0.0) >= 3.0
    ]
    league_trail = mean_of(rb_rows, "q4_trail_target_share") or 0.0
    league_cushion = mean_of(
        [row for row in rb_rows if (finite(row.get("avg_cushion")) or 0.0) > 0.0],
        "avg_cushion",
    )
    league_comp = mean_of(defense_rows, "def_q4_comp_rate")
    league_yac = mean_of(defense_rows, "def_q4_yac")
    starters: dict[str, str] = {}
    starter_yards: dict[str, float] = {}
    for row in players:
        if str(row.get("position") or "").upper() != "QB":
            continue
        name = norm_name(str(row.get("player_name") or ""))
        if name in never:
            continue
        team = canonical_team(str(row.get("team") or ""))
        yards = finite(row.get("pass_yds_per_game")) or 0.0
        if team and yards >= starter_yards.get(team, -1.0):
            starter_yards[team] = yards
            starters[team] = fold_name(str(row.get("player_name") or ""))

    meta_by_pair: dict[frozenset[str], dict] = {}
    for row in games:
        home = canonical_team(str(row.get("home_team") or ""))
        away = canonical_team(str(row.get("away_team") or ""))
        if not home or not away:
            continue
        roof = row.get("roof")
        roof_text = "" if roof is None else str(roof)
        meta_by_pair[frozenset({home, away})] = {
            "game_id": str(row.get("game_id") or ""),
            "home": home,
            "away": away,
            "roof": roof_text,
            "label": f"{away} @ {home}",
        }
    spreads: dict[tuple[str, str], float] = {}
    totals: dict[frozenset[str], float] = {}
    for row in lines:
        if not kick_label(str(row.get("commence_time") or "")):
            continue
        if str(row.get("line_type") or "") != "standard":
            continue
        team = canonical_team(str(row.get("team") or ""))
        opp = canonical_team(str(row.get("opp") or ""))
        posted = finite(row.get("line"))
        if not team or not opp or posted is None:
            continue
        kind = str(row.get("stat_type") or "")
        if kind == "spread":
            spreads[(team, opp)] = posted
        elif kind == "total":
            totals[frozenset({team, opp})] = posted

    tier1: dict[tuple[str, str], dict] = {}
    tier2: dict[tuple[str, str], dict] = {}
    boost: dict[tuple[str, str], dict] = {}
    sgp_legs: dict[tuple[str, str], dict] = {}
    environment: list[dict] = []
    for key, meta in sorted(meta_by_pair.items(), key=lambda item: item[1]["label"]):
        if not any(kick_label(str(row.get("commence_time") or "")) and frozenset({
            canonical_team(str(row.get("team") or "")),
            canonical_team(str(row.get("opp") or "")),
        }) == key for row in lines):
            continue
        home = meta["home"]
        away = meta["away"]
        environment.append(
            {
                "game": meta["label"],
                "spread_home": spreads.get((home, away)),
                "total": totals.get(key),
                "game_id": meta["game_id"],
            }
        )

    for row in lines:
        kick = kick_label(str(row.get("commence_time") or ""))
        if not kick:
            continue
        market = str(row.get("stat_type") or "")
        if str(row.get("line_type") or "") != "quarter":
            continue
        if market not in CHECKDOWN_BOARD and market not in {"rush_yds_q4", "pass_yds_q4"}:
            continue
        over = american_int(row.get("book_over"))
        under = american_int(row.get("book_under"))
        posted = finite(row.get("line"))
        if over is None or under is None or posted is None:
            continue
        team = canonical_team(str(row.get("team") or ""))
        opp = canonical_team(str(row.get("opp") or ""))
        pair = frozenset({team, opp})
        meta = dict(meta_by_pair.get(pair) or {})
        if not meta:
            continue
        name = norm_name(str(row.get("player_name") or ""))
        if not name or name in never:
            continue
        player_key = str(row.get("player_key") or fold_name(str(row.get("player_name") or "")))
        player = by_key.get(player_key) or by_key.get(fold_name(str(row.get("player_name") or "")))
        if player is None:
            continue
        cache_team = canonical_team(str(player.get("team") or ""))
        if cache_team and team and cache_team != team:
            continue
        position = str(player.get("position") or "").upper()
        games = finite(player.get("games")) or 0.0
        if games < 3.0:
            continue
        spread = spreads.get((team, opp))
        game_total = totals.get(pair)
        meta["kick_et"] = kick
        meta["spread"] = spread
        meta["game_total"] = game_total
        if market in CHECKDOWN_BOARD:
            if position not in SKILL:
                continue
            if market in {"receptions_q4", "rec_yds_q4"} and spread is None:
                continue
            inputs = _checkdown_inputs(
                player,
                defense_by_team.get(opp),
                league_trail,
                league_cushion,
                league_comp,
                league_yac,
                market,
                spread,
                game_total,
            )
            try:
                priced = price_checkdown(inputs, market, posted, over, under)
            except ValueError:
                continue
            if priced is None or priced.ev <= 0.0:
                continue
            share = float(priced.detail.w_q_eb)
            if reception_over_blocked(player, priced.market, priced.side):
                display = str(row.get("player_name") or player.get("player_name") or "")
                if display and display not in blocked_names:
                    blocked_names.append(display)
                replacement = favored_catch_under(
                    market=priced.market,
                    line=priced.line,
                    over_p=priced.model_p,
                    book_under=under,
                    spread=spread,
                )
                if replacement is None:
                    continue
                under_p, under_ev = replacement
                leg = _base_leg(
                    row,
                    player,
                    meta,
                    priced.market,
                    "under",
                    priced.line,
                    under,
                    under_p,
                    under_ev,
                )
                extra = "Q4 clock grinder; reception over blocked"
                if leg["note"] in {"", "none"}:
                    leg["note"] = extra
                else:
                    leg["note"] = f"{leg['note']}; {extra}"
            else:
                leg = _base_leg(
                    row,
                    player,
                    meta,
                    priced.market,
                    priced.side,
                    priced.line,
                    priced.price,
                    priced.model_p,
                    priced.ev,
                )
            leg["player_key"] = player_key or leg["player_key"]
            leg["w_rec_q_eb"] = share
            leg["q4_clock_grinder"] = bool(player.get("q4_clock_grinder"))
            if _tier1_leg(leg):
                _keep_best(tier1, leg)
            if position == "RB" and market in {"receptions_q4", "rec_yds_q4"}:
                _keep_best(boost, leg)
            if market in TIER2_MARKETS:
                clipped = clip_printed_side(priced.model_p, priced.fair_p, priced.price)
                if clipped is not None:
                    model_p, ev = clipped
                    calibrated = dict(leg)
                    calibrated["model_p"] = model_p
                    calibrated["ev"] = ev
                    calibrated["price"] = priced.price
                    calibrated["side"] = priced.side
                    _keep_best(tier2, calibrated)
                    _keep_best(sgp_legs, calibrated)
            elif market == "receptions_q4":
                _keep_best(sgp_legs, leg)
            continue
        if market == "rush_yds_q4" and position not in {"RB", "QB"}:
            continue
        if market == "pass_yds_q4":
            if position != "QB":
                continue
            starter_key = fold_name(str(player.get("player_name") or ""))
            if starters.get(team) != starter_key:
                continue
        rate_field = "pass_yds_per_game" if market == "pass_yds_q4" else "rush_yds_per_game"
        opps_q = 0.0
        opps_total = 0.0
        if market == "rush_yds_q4":
            rush_q = finite(player.get("q4_rush_att"))
            rush_total = finite(player.get("total_rush_att"))
            if rush_q is not None and rush_total is not None:
                opps_q = rush_q
                opps_total = rush_total
        priced_normal = price_period_yards(
            games=games,
            rate=finite(player.get(rate_field)) or 0.0,
            line=posted,
            book_over=over,
            book_under=under,
            opps_q=opps_q,
            opps_total=opps_total,
        )
        if priced_normal is None:
            continue
        if market == "pass_yds_q4" and priced_normal["side"] == "over" and team in PASS_FADE:
            continue
        leg = _base_leg(
            row,
            player,
            meta,
            market,
            priced_normal["side"],
            posted,
            priced_normal["price"],
            priced_normal["model_p"],
            priced_normal["ev"],
        )
        leg["player_key"] = player_key or leg["player_key"]
        leg["w_rush_q4_eb"] = float(priced_normal["w_q_eb"])
        _keep_best(tier2, leg)
        _keep_best(sgp_legs, leg)

    sgp_input = list(sgp_legs.values())
    sgps = [
        ticket
        for ticket in rank_same_game(sgp_input)
        if float(ticket.get("tax_adjusted_sgp_ev") or 0.0) > 0.0
        and 2 <= int(ticket.get("n_legs") or 0) <= 4
    ]
    quarter_players = 0
    for row in players:
        has_targets = finite(row.get("total_targets")) is not None
        has_rushes = finite(row.get("total_rush_att")) is not None
        if has_targets or has_rushes:
            quarter_players += 1
    return {
        "tier1": list(tier1.values()),
        "tier2": list(tier2.values()),
        "sgps": sgps,
        "boost": list(boost.values()),
        "environment": environment,
        "blocked_grinders": blocked_names,
        "counts": {
            "tier1": len(tier1),
            "tier2": len(tier2),
            "sgp_legs": len(sgp_legs),
            "sgps": len(sgps),
            "boost": len(boost),
            "quarter_players": quarter_players,
            "blocked_grinders": len(blocked_names),
        },
    }


def _targets_per_game(leg: dict) -> float:
    return float(leg.get("targets_per_game") or 0.0)


def _qualifying_spread(leg: dict) -> float | None:
    """The spread, when it clears the -4.5 bar. Otherwise None."""

    spread = finite(leg.get("spread"))
    if spread is None or spread < -4.5:
        return None
    return spread


def _reception_q4_leg(side: str, spread: float | None, leg: dict) -> bool:
    if side == "under":
        return True
    if side == "over":
        return spread is not None and _targets_per_game(leg) >= 1.0
    return False


def _tier1_leg(leg: dict) -> bool:
    if str(leg.get("position") or "") != "RB":
        return False
    if float(leg.get("games") or 0.0) < 3.0:
        return False
    if float(leg.get("ev") or 0.0) <= 0.0:
        return False
    market = str(leg.get("market") or "")
    side = str(leg.get("side") or "")
    spread = _qualifying_spread(leg)
    if market == "receptions_q4" and abs(float(leg["line"]) - 0.5) <= 1e-9:
        return _reception_q4_leg(side, spread, leg)
    if market == "rec_yds_q4" and side == "over" and spread is not None:
        return _targets_per_game(leg) >= 1.0
    return False


def stake_cents(tickets: list[CardTicket]) -> int:
    return sum(ticket.stake_cents for ticket in tickets)


def game_exposure(tickets: list[CardTicket]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for ticket in tickets:
        seen: set[str] = set()
        for leg in ticket.legs:
            label = str(leg.get("game_label") or "")
            key = label or " ".join(sorted(game_key(leg)))
            if key in seen:
                continue
            seen.add(key)
            totals[key] = totals.get(key, 0) + ticket.stake_cents
    return totals


def _stake_problems(tickets: list[CardTicket]) -> list[str]:
    problems: list[str] = []
    total = stake_cents(tickets)
    if total != BANKROLL_CENTS:
        problems.append(f"stake cents {total} != {BANKROLL_CENTS}")
    if any(ticket.stake_cents > TICKET_CAP_CENTS for ticket in tickets):
        problems.append("a ticket is over the $1.75 cap")
    for label, cents in game_exposure(tickets).items():
        if cents > GAME_CAP_CENTS:
            problems.append(f"{label} exposure {cents} cents is over the game cap")
    return problems


def _leg_problems(legs: list[dict], never: set[str]) -> list[str]:
    problems: list[str] = []
    if has_quarter_pair(legs):
        problems.append("a same-player receptions_qX and rec_yds_qX pair is on the card")
    for leg in legs:
        if norm_name(str(leg.get("player_name") or "")) in never:
            problems.append(f"never_enter {leg.get('player_name')}")
        market = str(leg.get("market") or "")
        if market in FULL_GAME_YARDS:
            prob = float(leg["model_p"])
            if prob < 0.18 or prob > 0.78:
                problems.append(f"full-game probability {prob} is outside [0.18, 0.78]")
    return problems


def _ticket_problems(tickets: list[CardTicket]) -> list[str]:
    problems: list[str] = []
    for ticket in tickets:
        if ticket.tier == "2":
            for leg in ticket.legs:
                if float(leg["model_p"]) > 0.78:
                    problems.append(f"tier 2 probability {leg['model_p']} is above 0.78")
        if ticket.tax_ev <= 0.0:
            problems.append(f"{ticket.ticket_id} EV is not positive")
    return problems


def _split_problems(tickets: list[CardTicket]) -> list[str]:
    problems: list[str] = []
    single_cents = sum(ticket.stake_cents for ticket in tickets if len(ticket.legs) == 1)
    parlay_cents = sum(ticket.stake_cents for ticket in tickets if len(ticket.legs) > 1)
    if single_cents < SINGLES_FLOOR_CENTS:
        problems.append(
            f"singles {single_cents} cents are under the {SINGLES_FLOOR_CENTS} floor"
        )
    if parlay_cents > PARLAY_CAP_CENTS:
        problems.append(f"parlays {parlay_cents} cents are over the {PARLAY_CAP_CENTS} cap")
    return problems


def _duplicate_problems(tickets: list[CardTicket]) -> list[str]:
    problems: list[str] = []
    seen_multi: set[tuple[str, str, str, float]] = set()
    for ticket in tickets:
        if len(ticket.legs) < 2:
            continue
        for leg in ticket.legs:
            ident = _leg_identity(leg)
            if ident in seen_multi:
                problems.append(f"duplicate multi-leg prop {ident[0]} {ident[1]} {ident[2]}")
            seen_multi.add(ident)
    return problems


def verify_card(tickets: list[CardTicket], never: set[str]) -> list[str]:
    problems: list[str] = []
    problems.extend(_stake_problems(tickets))
    legs = [leg for ticket in tickets for leg in ticket.legs]
    problems.extend(_leg_problems(legs, never))
    problems.extend(_ticket_problems(tickets))
    problems.extend(_split_problems(tickets))
    problems.extend(_duplicate_problems(tickets))
    return problems


def ledger_rows(tickets: list[CardTicket]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for ticket in tickets:
        for index, leg in enumerate(ticket.legs, start=1):
            rows.append(
                {
                    "ticket_id": ticket.ticket_id,
                    "tier": ticket.tier,
                    "leg_num": str(index),
                    "game_id": str(leg.get("game_id") or ""),
                    "kick_et": str(leg.get("kick_et") or ""),
                    "player_name": str(leg.get("player_name") or ""),
                    "gsis_id": str(leg.get("gsis_id") or ""),
                    "team": canonical_team(str(leg.get("team") or "")),
                    "opp": canonical_team(str(leg.get("opp") or "")),
                    "market": str(leg.get("market") or ""),
                    "side": str(leg.get("side") or ""),
                    "line": f"{float(leg['line']):.1f}",
                    "book_american_odds": str(int(leg["price"])),
                    "model_prob": (
                        f"{float(leg['model_p']):.6f}"
                        if len(ticket.legs) == 1
                        else f"{float(ticket.joint_p):.6f}"
                    ),
                    "tax_adj_ev": f"{ticket.tax_ev:.6f}",
                    "ticket_stake_usd": f"{ticket.stake_cents / 100:.2f}",
                    "t90_flag": ticket.note,
                    "boost_pct": "",
                    "displayed_boosted_payout": "",
                    "off_card": "false",
                    "leg_statuses": "",
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
    price = american_text(int(leg["price"]))
    return (
        f"{leg['player_name']} {leg['market']} {leg['side']} {float(leg['line']):.1f} ({price})"
    )


def _book_text(ticket: CardTicket) -> str:
    if len(ticket.legs) == 1:
        return american_text(int(ticket.legs[0]["price"]))
    return " + ".join(american_text(int(leg["price"])) for leg in ticket.legs)


def render_markdown(
    tickets: list[CardTicket],
    environment: list[dict],
    counts: dict,
    blocked: list[str] | None = None,
) -> str:
    lines = [
        f"# Week 8 Sunday Hard Rock card, {SLATE_DAY}",
        "",
        "Do not type a ticket until you check the laptop price. Do not submit a bet from this file.",
        "",
        "The stake sum is $8.00. The ticket cap is $1.75. The game cap is $2.50.",
        "The slate is unplayed. Model EV is not cash.",
        "",
        "## Verdict",
        "",
        (
            "Tier 1 is four $1.00 Q4 RB legs. Tier 2 is two $1.25 quarter legs. "
            "Tier 3 is two $0.50 same-game slips and one $0.50 cross-game combo."
        ),
        "Priced pool: "
        + ", ".join(f"{key} {value}" for key, value in counts.items())
        + ".",
        "No scheme.md row is marked confirmed, so no full-game yard lean is on this card.",
        "total_q3 is not priced. This build has no points model.",
        "Pass overs for ATL, TB, IND, and JAX are off because of the wind fade.",
        (
            "Quarter shares use Empirical Bayes w_rec_q3_eb and w_rec_q4_eb from player target counts. "
            "Rush yards use w_rush_q4_eb."
            if int(counts.get("quarter_players") or 0) > 0
            else "Quarter shares use the 0.25 prior. The cache has no player quarter target counts."
        ),
        "The boost slip leaves displayed_boosted_payout blank. Apply the token on the laptop if it is live.",
    ]
    if blocked:
        lines.append("Q4 clock-grinder reception overs blocked: " + ", ".join(blocked) + ".")
    lines.extend(
        [
        "",
        "## Card",
        "",
        "| Ticket | Tier | Game and kick | Legs | Book price | Model prob | Book implied | Tax-adj EV | Stake | Note |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for ticket in tickets:
        labels = []
        for leg in ticket.legs:
            label = f"{leg.get('game_label')} {leg.get('kick_et')}".strip()
            if label not in labels:
                labels.append(label)
        game = "; ".join(labels)
        legs = "; ".join(_leg_text(leg) for leg in ticket.legs)
        prob = f"{float(ticket.joint_p):.4f}"
        book = f"{float(ticket.book_implied_p):.4f}"
        lines.append(
            "| {ticket} | {tier} | {game} | {legs} | {price} | {prob} | {book} | {ev:.1f}% | ${stake:.2f} | {note} |".format(
                ticket=ticket.ticket_id,
                tier=ticket.tier,
                game=game,
                legs=legs,
                price=_book_text(ticket),
                prob=prob,
                book=book,
                ev=ticket.tax_ev * 100.0,
                stake=ticket.stake_cents / 100.0,
                note=ticket.note,
            )
        )
    lines.extend(["", "## Exposure", "", "| Game | Exposure |", "| --- | ---: |"])
    for label, cents in sorted(game_exposure(tickets).items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {label} | ${cents / 100:.2f} |")
    lines.extend(["", "## Book spread and total used for the script gate", "", "| Game | Home spread | Total |", "| --- | ---: | ---: |"])
    for row in environment:
        spread = row.get("spread_home")
        total = row.get("total")
        spread_text = "" if spread is None else f"{float(spread):.1f}"
        total_text = "" if total is None else f"{float(total):.1f}"
        lines.append(f"| {row['game']} | {spread_text} | {total_text} |")
    lines.extend(
        [
            "",
            "Home spread is the home team's posted Hard Rock number. A negative number is a favorite.",
            "A blank cell would fail a script-dependent Q4 leg closed. No blank cell was filled with a guess.",
            "",
        ]
    )
    return "\n".join(lines)


def read_lines(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_pbp_plays(path: Path | None) -> list[dict]:
    """Read local play-by-play. A missing file leaves the quarter prior in place."""

    if path is None or not Path(path).is_file():
        return []
    import pandas as pd

    frame = pd.read_parquet(path)
    return frame_rows(frame)


def build_from_files(
    lines_path: Path = LINES_PATH,
    cache_dir: Path = CACHE_DIR,
    scratch_path: Path = SCRATCH_PATH,
    pbp_path: Path | None = PBP_PATH,
) -> tuple[list[CardTicket], list[str], dict]:
    if not lines_path.is_file():
        raise FileNotFoundError(f"lines file is missing: {lines_path}")
    if not scratch_path.is_file():
        raise FileNotFoundError(f"scratch file is missing: {scratch_path}")
    loaded = load_feature_cache(cache_dir)
    if loaded.get("status") != "ready":
        raise FileNotFoundError(f"week 8 cache is missing: {cache_dir}")
    never = load_never(scratch_path)
    pools = build_pools(read_lines(lines_path), loaded["frames"], never, load_pbp_plays(pbp_path))
    tickets, short = select_card(pools["tier1"], pools["tier2"], pools["sgps"], pools["boost"])
    problems = []
    if not short:
        problems = verify_card(tickets, never)
    return tickets, short + problems, pools


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Week 8 $8.00 Hard Rock card.")
    parser.add_argument("--lines", type=Path, default=LINES_PATH)
    parser.add_argument("--cache", type=Path, default=CACHE_DIR)
    parser.add_argument("--scratches", type=Path, default=SCRATCH_PATH)
    parser.add_argument("--card", type=Path, default=CARD_PATH)
    parser.add_argument("--doc", type=Path, default=DOC_PATH)
    parser.add_argument("--pbp", type=Path, default=PBP_PATH)
    args = parser.parse_args(argv)
    try:
        tickets, problems, pools = build_from_files(args.lines, args.cache, args.scratches, args.pbp)
    except FileNotFoundError as exc:
        print(exc)
        return 2
    print("counts", pools["counts"])
    if problems:
        print("CARD SHORT")
        for item in problems:
            print(item)
        print("top tier1")
        for leg in sorted(pools["tier1"], key=_ev_key)[:12]:
            print(
                f"  {leg['player_name']} {leg['market']} {leg['side']} {leg['line']} "
                f"ev={leg['ev']:.3f} p={leg['model_p']:.3f} spread={leg.get('spread')}"
            )
        print("top tier2")
        for leg in sorted(pools["tier2"], key=_ev_key)[:8]:
            print(
                f"  {leg['player_name']} {leg['market']} {leg['side']} {leg['line']} "
                f"ev={leg['ev']:.3f} p={leg['model_p']:.3f}"
            )
        print("top sgp", len(pools["sgps"]))
        for ticket in pools["sgps"][:6]:
            names = ", ".join(
                f"{leg['player_name']} {leg['market']} {leg['side']}" for leg in ticket["legs"]
            )
            print(f"  ev={float(ticket['tax_adjusted_sgp_ev']):.3f} {names}")
        return 2
    text = render_markdown(
        tickets,
        pools["environment"],
        pools["counts"],
        pools.get("blocked_grinders") or [],
    )
    args.doc.parent.mkdir(parents=True, exist_ok=True)
    args.doc.write_text(text, encoding="utf-8")
    write_ledger(tickets, args.card, args.doc)
    print(text)
    print(f"wrote {args.card}")
    print(f"wrote {args.doc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
