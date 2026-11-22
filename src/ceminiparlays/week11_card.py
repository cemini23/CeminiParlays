"""Week 11 Saturday Hard Rock research card for a $23.00 bankroll.

The builder reads the Week 11 packet in ``config/week11``. It does not open
a socket, it does not scrape a book, and it does not submit a bet. Fair
American prices are the model breakeven. They are not Hard Rock prices.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from ceminiparlays.book_team import canonical_team
from ceminiparlays.card_sync import default_sync_roots, sync_dated_card
from ceminiparlays.compose import joint_ticket
from ceminiparlays.correlation import LegRef, UnmodeledCorrelationError, correlation_matrix
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
from ceminiparlays.odds import decimal_to_american
from ceminiparlays.q4_checkdown import (
    q4_rush_over_blocked,
    q4_rush_script_multiplier,
    starter_rb,
)
from ceminiparlays.resources import REPO_ROOT
from ceminiparlays.sunday_card import norm_name

SLATE_DAY = "2026-11-22"
WEEK = REPO_ROOT / "config" / "week11"
ENV_PATH = WEEK / "environment.csv"
RATES_PATH = WEEK / "team_rates_2026-11-22.csv"
Q4_PATH = WEEK / "q4_rb_checkdown_2026-11-22.csv"
SCRIPT_PATH = WEEK / "quarter_script_2026-11-22.csv"
STARTERS_PATH = WEEK / "qb_starters_2026-11-22.csv"
SCRATCH_PATH = WEEK / "scratches_2026-11-22.csv"
HOLD_PATH = WEEK / "sunday_t90_watchlist_2026-11-22.csv"
CARD_CSV = WEEK / "hardrock_card_2026-11-22.csv"
CARD_MD = WEEK / "card_2026-11-22.md"
DOC_PATH = REPO_ROOT / "docs" / "2026-11-22-sunday-hardrock-card.md"
BANKROLL_CENTS = 2300
LEG_EXPOSURE_CAP_CENTS = 805
REF_PRICE = -110
Q4_RUSH_LINE = 14.5
Q4_REC_LINE = 0.5
MAX_LEG_REUSE = 1

# id, player, team, opp, market, side, kind, gate.
# gate "" is eligible. "q" is the Sunday T-90 list. "roof" waits on AT&T.
SPECS: tuple[tuple[str, str, str, str, str, str, str, str], ...] = (
    ("johnson_under", "Josh Johnson", "ARI", "KC", "pass_yds", "under", "pass_off", ""),
    ("lawrence_under", "Trevor Lawrence", "JAX", "NYG", "pass_yds", "under", "pass_def", ""),
    ("milton_under", "Joe Milton", "PHI", "PIT", "pass_yds", "under", "pass_blend", ""),
    ("cook_rush", "James Cook III", "BUF", "MIA", "rush_yds", "over", "rush_blend", ""),
    ("swift_rush", "D'Andre Swift", "CHI", "NO", "rush_yds", "over", "rush_blend", ""),
    ("emmett_rush", "Emmett Johnson", "KC", "ARI", "rush_yds", "over", "rush_blend", ""),
    ("coleman_rush", "Jonah Coleman", "DEN", "LV", "rush_yds", "over", "rush_blend", ""),
    ("pollard_rush", "Tony Pollard", "TEN", "DAL", "rush_yds", "over", "rush_blend", ""),
    ("gibbs_q4", "Jahmyr Gibbs", "DET", "TB", "rush_yds_q4", "over", "q4_rush", ""),
    ("warren_q4", "Jaylen Warren", "PIT", "PHI", "rush_yds_q4", "over", "q4_rush", ""),
    ("hubbard_q4", "Chuba Hubbard", "CAR", "BAL", "rush_yds_q4", "over", "q4_rush", ""),
    ("tuten_q4", "Bhayshul Tuten", "JAX", "NYG", "rush_yds_q4", "over", "q4_rush", ""),
    ("javonte_q4", "Javonte Williams", "DAL", "TEN", "rush_yds_q4", "over", "q4_rush", ""),
    ("jeanty_rec", "Ashton Jeanty", "LV", "DEN", "receptions_q4", "over", "q4_rec", ""),
    ("kamara_rec", "Alvin Kamara", "NO", "CHI", "receptions_q4", "over", "q4_rec", ""),
    ("pollard_rec", "Tony Pollard", "TEN", "DAL", "receptions_q4", "over", "q4_rec", ""),
    ("allgeier_rec", "Tyler Allgeier", "ARI", "KC", "receptions_q4", "over", "q4_rec", ""),
    ("phi_q3", "PIT at PHI", "PIT", "PHI", "total_q3", "under", "q3", ""),
    ("dak_over", "Dak Prescott", "DAL", "TEN", "pass_yds", "over", "pass_off", "roof"),
    ("lamb_over", "CeeDee Lamb", "DAL", "TEN", "rec_yds", "over", "no_rate", "roof"),
    ("pickens_over", "George Pickens", "DAL", "TEN", "rec_yds", "over", "no_rate", "roof"),
    ("mayfield_under", "Baker Mayfield", "TB", "DET", "pass_yds", "under", "pass_off", "q"),
)

PLAN: tuple[tuple[str, int, tuple[str, ...]], ...] = (
    ("HR11-1", 500, ("johnson_under", "cook_rush", "gibbs_q4")),
    ("HR11-2", 500, ("lawrence_under", "swift_rush", "hubbard_q4")),
    ("HR11-3", 500, ("emmett_rush", "jeanty_rec")),
    ("HR11-4", 500, ("coleman_rush", "pollard_rush", "kamara_rec")),
    ("HR11-5", 300, ("warren_q4", "phi_q3")),
)


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

    @property
    def ok(self) -> bool:
        return self.reason == "OK"


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


def fair_american(prob: float) -> int:
    """American price at which a bet with this win probability has zero EV."""

    if not 0.0 < prob < 1.0:
        raise ValueError(f"probability out of range: {prob}")
    price = decimal_to_american(1.0 / prob)
    if -100 < price < 100:
        return -100 if prob >= 0.5 else 100
    return price


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
    return {norm_name(str(row.get("player") or "")) for row in read_csv(path)}


def _rates(path: Path) -> dict[str, dict[str, float]]:
    rates: dict[str, dict[str, float]] = {}
    keys = ("pass_off", "rush_off", "pass_def", "rush_def")
    for row in read_csv(path):
        team = canonical_team(str(row.get("team") or ""))
        parsed = {key: number(row.get(key)) for key in keys}
        if team and all(value is not None for value in parsed.values()):
            rates[team] = {key: float(value) for key, value in parsed.items() if value is not None}
    return rates


def _q4_index(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    found: dict[tuple[str, str], dict[str, str]] = {}
    for row in read_csv(path):
        team = canonical_team(str(row.get("team") or ""))
        name = norm_name(str(row.get("rb") or ""))
        if team and name:
            found[(team, name)] = row
    return found


def _script_index(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    found: dict[tuple[str, str], dict[str, str]] = {}
    for row in read_csv(path):
        team = canonical_team(str(row.get("team") or ""))
        opp = canonical_team(str(row.get("opp") or ""))
        if team and opp:
            found[(team, opp)] = row
    return found


def _starters(path: Path) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for row in read_csv(path):
        team = canonical_team(str(row.get("team") or ""))
        if team:
            found[team] = row
    return found


def _env_meta(path: Path) -> dict[str, dict[str, str]]:
    meta: dict[str, dict[str, str]] = {}
    for row in read_csv(path):
        team = canonical_team(str(row.get("team") or ""))
        if not team:
            continue
        game_id = str(row.get("game_id") or "")
        pair = game_id.split("-")[-1]
        away, _, home = pair.partition("@")
        meta[team] = {
            "away": away,
            "home": home,
            "game_id": f"{away}@{home}",
            "spread": str(row.get("spread") or ""),
            "implied_total": str(row.get("implied_total") or ""),
            "roof": str(row.get("roof") or ""),
            "wind_mph": str(row.get("wind_mph") or ""),
            "precip_pop": str(row.get("precip_pop") or ""),
        }
    return meta


def _kick_map(path: Path) -> dict[str, str]:
    kicks: dict[str, str] = {}
    for row in read_csv(path):
        team = canonical_team(str(row.get("team") or ""))
        if team:
            kicks[team] = str(row.get("kickoff_et") or "")
    return kicks


def _q3_means(script: dict[tuple[str, str], dict[str, str]]) -> dict[frozenset[str], float]:
    means: dict[frozenset[str], float] = {}
    seen: set[frozenset[str]] = set()
    for (team, opp), row in script.items():
        game = frozenset({team, opp})
        if game in seen:
            continue
        other = script.get((opp, team))
        if other is None:
            continue
        seen.add(game)
        team_for = number(row.get("q3_pts_for_pg"))
        team_against = number(row.get("q3_pts_against_pg"))
        opp_for = number(other.get("q3_pts_for_pg"))
        opp_against = number(other.get("q3_pts_against_pg"))
        if None in {team_for, team_against, opp_for, opp_against}:
            continue
        estimate = ((float(team_for) + float(opp_against)) + (float(opp_for) + float(team_against))) / 2.0
        means[game] = estimate
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
    if kind == "pass_blend":
        return (offense["pass_off"] + defense["pass_def"]) / 2.0
    if kind == "rush_blend":
        return (offense["rush_off"] + defense["rush_def"]) / 2.0
    return None


def _price_side(p_over: float, side: str) -> tuple[float, float, float] | None:
    fair = fair_over_prob(REF_PRICE, REF_PRICE)
    if side == "over":
        raw, fair_side = p_over, fair
    elif side == "under":
        raw, fair_side = 1.0 - p_over, 1.0 - fair
    else:
        raise ValueError(f"unknown side: {side}")
    if not math.isfinite(raw) or raw <= fair_side:
        return None
    model_p = clip_main_line_prob(raw, fair_side)
    ev = leg_ev(model_p, REF_PRICE)
    if ev <= 0.0:
        return None
    return raw, model_p, ev


def _blank(
    spec: tuple[str, str, str, str, str, str, str, str],
    *,
    reason: str,
    note: str,
    kick: str,
    game_id: str,
    spread: float | None,
    line: float | None = None,
) -> PricedLeg:
    leg_id, player, team, opp, market, side, _kind, _gate = spec
    return PricedLeg(
        leg_id, player, team, opp, market, side, line, None, None, None, None,
        spread, kick, game_id, reason, note,
    )


def _accepted(
    spec: tuple[str, str, str, str, str, str, str, str],
    *,
    line: float,
    raw: float,
    model_p: float,
    ev: float,
    spread: float | None,
    kick: str,
    game_id: str,
    note: str,
    gate: str,
) -> PricedLeg:
    leg_id, player, team, opp, market, side, _kind, _gate = spec
    reason = "OK"
    if gate == "q":
        reason = "SATURDAY_HOLD"
    elif gate == "roof":
        reason = "ROOF_CHECK"
    return PricedLeg(
        leg_id, player, team, opp, market, side, line, model_p, raw, ev,
        fair_american(model_p), spread, kick, game_id, reason, note,
    )


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


def _screen_one(
    spec: tuple[str, str, str, str, str, str, str, str],
    *,
    blocked: set[str],
    rates: dict[str, dict[str, float]],
    q4: dict[tuple[str, str], dict[str, str]],
    q3_means: dict[frozenset[str], float],
    q3_line: float,
    pass_line: float,
    rush_line: float,
    env: dict[str, dict[str, str]],
    kicks: dict[str, str],
    starters: dict[str, dict[str, str]],
) -> PricedLeg:
    leg_id, player, team, opp, market, side, kind, gate = spec
    team = canonical_team(team)
    opp = canonical_team(opp)
    meta = env.get(team, {})
    kick = kicks.get(team, "")
    game_id = str(meta.get("game_id") or f"{team}@{opp}")
    spread = number(meta.get("spread"))
    name = norm_name(player)
    if name in blocked:
        return _blank(spec, reason="HARD_EXCLUDE", note="out, ir, or doubtful", kick=kick, game_id=game_id, spread=spread)
    if market.startswith("pass"):
        failures = qb_check_failures(
            [_blank(spec, reason="", note="", kick=kick, game_id=game_id, spread=spread)],
            starters,
        )
        # Re-check the real name. The blank leg still carries player and market.
        if failures:
            return _blank(spec, reason="FAIL_BACKUP_QB", note=failures[0], kick=kick, game_id=game_id, spread=spread)
    if kind == "no_rate":
        return _blank(
            spec, reason="NO_PLAYER_RATE",
            note="packet has no player receiving-yard rate",
            kick=kick, game_id=game_id, spread=spread,
        )
    if kind in {"pass_off", "pass_def", "pass_blend", "rush_blend"}:
        mean = _full_game_mean(kind, team, opp, rates)
        line = pass_line if market == "pass_yds" else rush_line
        if mean is None:
            return _blank(spec, reason="NO_RATE", note="missing team rate", kick=kick, game_id=game_id, spread=spread, line=line)
        sigma = full_game_yard_sigma(market, line)
        priced = _price_side(normal_over_prob(line, mean, sigma), side)
        note = f"LEAGUE_SLATE_MEDIAN_NOT_BOOK mean={mean:.2f}"
        if leg_id == "coleman_rush":
            note += "; packet names DEN rush, not a back; Q4 row names Jonah Coleman"
        if priced is None:
            return _blank(spec, reason="NO_EDGE", note=note, kick=kick, game_id=game_id, spread=spread, line=line)
        raw, model_p, ev = priced
        return _accepted(
            spec, line=line, raw=raw, model_p=model_p, ev=ev, spread=spread,
            kick=kick, game_id=game_id, note=note, gate=gate,
        )
    if kind == "q4_rush":
        row = q4.get((team, name))
        if row is None:
            return _blank(spec, reason="NO_ROW", note="not in the Q4 table", kick=kick, game_id=game_id, spread=spread)
        played = number(row.get("games")) or 0.0
        if played < 4.0:
            return _blank(spec, reason="SHORT_SAMPLE", note=f"games={played}", kick=kick, game_id=game_id, spread=spread)
        rate = number(row.get("q4_rush_yds_pg"))
        rank_value = number(row.get("rb_tgt_share_rank"))
        rank = None if rank_value is None else int(rank_value)
        starter = starter_rb(player, rank)
        if rate is None or rate <= 0.0:
            return _blank(spec, reason="NO_RATE", note="blank Q4 rush rate", kick=kick, game_id=game_id, spread=spread)
        if q4_rush_over_blocked(spread, is_starter_rb=starter) or (spread is not None and spread <= -8.0):
            return _blank(
                spec, reason="BENCH_BLOWOUT_Q4",
                note="full-game rush only",
                kick=kick, game_id=game_id, spread=spread, line=Q4_RUSH_LINE,
            )
        if spread is not None and spread >= 7.0:
            return _blank(spec, reason="TRAIL_BLOWOUT_Q4", note="no Q4 rush over", kick=kick, game_id=game_id, spread=spread)
        factor = q4_rush_script_multiplier(spread, is_starter_rb=starter)
        if factor is None or factor != 1.08:
            return _blank(spec, reason="NOT_COMPETITIVE_LEAD", note=f"factor={factor}", kick=kick, game_id=game_id, spread=spread)
        mean = rate * factor
        sigma = sigma_floor("yards", Q4_RUSH_LINE)
        priced = _price_side(normal_over_prob(Q4_RUSH_LINE, mean, sigma), side)
        note = f"Q4 rush {rate:.2f} x {factor:.2f}; line 14.5 is not a book line"
        if priced is None:
            return _blank(spec, reason="NO_EDGE", note=note, kick=kick, game_id=game_id, spread=spread, line=Q4_RUSH_LINE)
        raw, model_p, ev = priced
        return _accepted(
            spec, line=Q4_RUSH_LINE, raw=raw, model_p=model_p, ev=ev, spread=spread,
            kick=kick, game_id=game_id, note=note, gate=gate,
        )
    if kind == "q4_rec":
        row = q4.get((team, name))
        if row is None:
            return _blank(spec, reason="NO_ROW", note="not in the Q4 table", kick=kick, game_id=game_id, spread=spread)
        played = number(row.get("games")) or 0.0
        catches = number(row.get("q4_rec_pg"))
        if played < 4.0 or catches is None or catches <= 0.0:
            return _blank(spec, reason="SHORT_SAMPLE", note="Q4 catch rate missing", kick=kick, game_id=game_id, spread=spread)
        if spread is None or spread < 7.0:
            return _blank(spec, reason="NOT_TRAIL", note="trail checkdown needs spread >= 7", kick=kick, game_id=game_id, spread=spread)
        priced = _price_side(poisson_over_prob(catches, Q4_REC_LINE), side)
        note = f"Poisson Q4 rec {catches:.2f}; line 0.5 is not a book line"
        if priced is None:
            return _blank(spec, reason="NO_EDGE", note=note, kick=kick, game_id=game_id, spread=spread, line=Q4_REC_LINE)
        raw, model_p, ev = priced
        return _accepted(
            spec, line=Q4_REC_LINE, raw=raw, model_p=model_p, ev=ev, spread=spread,
            kick=kick, game_id=game_id, note=note, gate=gate,
        )
    if kind == "q3":
        mean = q3_means.get(frozenset({team, opp}))
        if mean is None:
            return _blank(spec, reason="NO_RATE", note="missing Q3 estimate", kick=kick, game_id=game_id, spread=spread)
        sigma = sigma_floor("points", q3_line)
        priced = _price_side(normal_over_prob(q3_line, mean, sigma), side)
        note = f"Q3 mean {mean:.2f}; reference line is the slate median, not a book total"
        if priced is None:
            return _blank(spec, reason="NO_EDGE", note=note, kick=kick, game_id=game_id, spread=spread, line=q3_line)
        raw, model_p, ev = priced
        return _accepted(
            spec, line=q3_line, raw=raw, model_p=model_p, ev=ev, spread=spread,
            kick=kick, game_id=game_id, note=note, gate=gate,
        )
    return _blank(spec, reason="NO_KIND", note=kind, kick=kick, game_id=game_id, spread=spread)


def screen_pool() -> dict[str, PricedLeg]:
    """Price every priority spec. A failed gate stays in the map with a reason."""

    rates = _rates(RATES_PATH)
    blocked = _blocked_names(SCRATCH_PATH)
    hold = _hold_names(HOLD_PATH)
    q4 = _q4_index(Q4_PATH)
    script = _script_index(SCRIPT_PATH)
    q3_means = _q3_means(script)
    q3_line = median(list(q3_means.values()))
    env = _env_meta(ENV_PATH)
    teams = list(env)
    pass_line = median([rates[team]["pass_off"] for team in teams if team in rates])
    rush_line = median([rates[team]["rush_off"] for team in teams if team in rates])
    kicks = _kick_map(STARTERS_PATH)
    starters = _starters(STARTERS_PATH)
    priced: dict[str, PricedLeg] = {}
    for spec in SPECS:
        leg = _screen_one(
            spec,
            blocked=blocked,
            rates=rates,
            q4=q4,
            q3_means=q3_means,
            q3_line=q3_line,
            pass_line=pass_line,
            rush_line=rush_line,
            env=env,
            kicks=kicks,
            starters=starters,
        )
        if norm_name(leg.player) in hold and leg.reason == "OK":
            leg = replace(leg, reason="SATURDAY_HOLD", note="Sunday T-90 watchlist")
        priced[spec[0]] = leg
    return priced


def _pair_corr(legs: list[PricedLeg]) -> tuple[np.ndarray, bool]:
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
    try:
        return correlation_matrix(refs), False
    except UnmodeledCorrelationError:
        return np.eye(len(legs)), True


def _ticket_fair(legs: list[PricedLeg]) -> tuple[float, int, bool, dict[str, object]]:
    corr, unmodeled = _pair_corr(legs)
    prices = [int(leg.fair_american or 0) for leg in legs]
    marginals = [float(leg.model_p or 0.0) for leg in legs]
    joint = joint_ticket(marginals, prices, corr)
    prob = float(joint["joint_p"])
    return prob, fair_american(prob), unmodeled, joint


def build_tickets(pool: dict[str, PricedLeg]) -> list[dict[str, object]]:
    """Build the five Saturday tickets. A missing leg raises."""

    tickets: list[dict[str, object]] = []
    seen: dict[tuple[str, str, str], int] = defaultdict(int)
    for ticket_id, stake_cents, leg_ids in PLAN:
        legs = [pool[leg_id] for leg_id in leg_ids]
        missing = [leg for leg in legs if not leg.ok]
        if missing:
            detail = ", ".join(f"{leg.leg_id}={leg.reason}" for leg in missing)
            raise ValueError(f"{ticket_id} is not a Saturday leg: {detail}")
        if not 2 <= len(legs) <= 3:
            raise ValueError(f"{ticket_id} must have 2 or 3 legs")
        games = {frozenset({leg.team, leg.opp}) for leg in legs}
        same_game = len(games) < len(legs)
        if same_game and stake_cents > 300:
            raise ValueError(f"{ticket_id} same-game stake is above $3")
        first_td: dict[frozenset[str], int] = defaultdict(int)
        for leg in legs:
            if leg.market == "first_td":
                first_td[frozenset({leg.team, leg.opp})] += 1
        if any(count > 1 for count in first_td.values()):
            raise ValueError(f"{ticket_id} pairs two first_td legs from one game")
        joint_p, ticket_fair, unmodeled, joint = _ticket_fair(legs)
        for leg in legs:
            key = (norm_name(leg.player), leg.market, leg.side)
            seen[key] += 1
            if seen[key] > MAX_LEG_REUSE:
                raise ValueError(f"{leg.player} {leg.market} reuse is above {MAX_LEG_REUSE}")
        tickets.append(
            {
                "ticket_id": ticket_id,
                "stake_cents": stake_cents,
                "legs": legs,
                "joint_p": joint_p,
                "gaussian_joint_p": float(joint["gaussian_joint_p"]),
                "t_copula_joint_p": float(joint["t_copula_joint_p"]),
                "fair_american": ticket_fair,
                "same_game": same_game,
                "unmodeled": unmodeled,
            }
        )
    stake = sum(int(ticket["stake_cents"]) for ticket in tickets)
    if stake != BANKROLL_CENTS:
        raise ValueError(f"stake sum {stake} is not {BANKROLL_CENTS}")
    if not 4 <= len(tickets) <= 6:
        raise ValueError(f"ticket count {len(tickets)} is outside 4 to 6")
    exposure: dict[str, int] = defaultdict(int)
    for ticket in tickets:
        stake_cents = int(ticket["stake_cents"])
        players = {norm_name(leg.player) for leg in ticket["legs"]}  # type: ignore[union-attr]
        for player in players:
            exposure[player] += stake_cents
    over = {name: cents for name, cents in exposure.items() if cents > LEG_EXPOSURE_CAP_CENTS}
    if over:
        raise ValueError(f"leg exposure above 35 percent: {over}")
    return tickets


def _money(cents: int) -> str:
    return f"${cents / 100:.2f}"


def _american(price: int | None) -> str:
    if price is None:
        return ""
    if price > 0:
        return f"+{price}"
    return str(price)


def render_csv(tickets: list[dict[str, object]]) -> str:
    fields = [
        "ticket_id", "leg_num", "game_id", "kick_et", "player_name", "team", "opp",
        "market", "side", "line", "fair_american", "model_prob", "raw_prob",
        "ev_vs_ref_minus110", "ticket_stake_usd", "ticket_fair_american",
        "gaussian_joint_p", "t_copula_joint_p", "corr_unmodeled", "note",
    ]
    rows: list[dict[str, str]] = []
    for ticket in tickets:
        legs = ticket["legs"]
        assert isinstance(legs, list)
        for index, leg in enumerate(legs, start=1):
            assert isinstance(leg, PricedLeg)
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
                    "fair_american": _american(leg.fair_american),
                    "model_prob": "" if leg.model_p is None else f"{leg.model_p:.4f}",
                    "raw_prob": "" if leg.raw_p is None else f"{leg.raw_p:.4f}",
                    "ev_vs_ref_minus110": "" if leg.ev_vs_ref is None else f"{leg.ev_vs_ref:.4f}",
                    "ticket_stake_usd": _money(int(ticket["stake_cents"])),
                    "ticket_fair_american": _american(int(ticket["fair_american"])),
                    "gaussian_joint_p": f"{float(ticket['gaussian_joint_p']):.4f}",
                    "t_copula_joint_p": f"{float(ticket['t_copula_joint_p']):.4f}",
                    "corr_unmodeled": "yes" if ticket["unmodeled"] else "no",
                    "note": leg.note,
                }
            )
    from io import StringIO

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _leg_phrase(leg: PricedLeg) -> str:
    line = "" if leg.line is None else f" {leg.line:.2f}"
    price = _american(leg.fair_american)
    return f"{leg.player} {leg.market} {leg.side}{line} (fair {price})"


def render_markdown(tickets: list[dict[str, object]], pool: dict[str, PricedLeg]) -> str:
    lines = [
        "# Week 11 Saturday Hard Rock card, 2026-11-22",
        "",
        "Do not submit a bet from this file. Type every ticket yourself.",
        "The stake sum is $23.00. That is the research allocation for this card.",
        "Each ticket has 2 or 3 legs. Core tickets are $5. The same-game ticket is $3.",
        "No leg is on more than one ticket. No leg stake is above 35 percent of $23.",
        "",
        "Fair American is the model breakeven. It is not a Hard Rock price.",
        "Compare a live Hard Rock price with this fair price before you place a bet.",
        "A full-game yard line is the slate median of team rates. It is not a book line.",
        "The Q4 rush line is 14.5. The Q4 catch line is 0.5. The Q3 line is the slate median.",
        "The number -110 is only the reference ladder for the EV column.",
        "Spreads and totals are CLAIMED from the Week 11 DraftKings environment odds file.",
        "",
        "Questionable players are off this Saturday card. They are in the T-90 list.",
        "DAL pass and catch overs wait on the AT&T roof call Sunday morning.",
        "No first_td leg is on this card. Two first_td legs from one game are never paired.",
        "A rush_yds_q4 over is off when the team spread is -8.0 or lower.",
        "",
        "## Card",
        "",
        "| Ticket | Stake | Legs | Joint model prob | Fair parlay price |",
        "| --- | ---: | --- | ---: | ---: |",
    ]
    for ticket in tickets:
        legs = ticket["legs"]
        assert isinstance(legs, list)
        text = "; ".join(_leg_phrase(leg) for leg in legs)
        lines.append(
            f"| {ticket['ticket_id']} | {_money(int(ticket['stake_cents']))} | {text} "
            f"| {float(ticket['joint_p']):.4f} | {_american(int(ticket['fair_american']))} |"
        )
    lines.extend(["", "## Leg notes", ""])
    for ticket in tickets:
        legs = ticket["legs"]
        assert isinstance(legs, list)
        flag = "yes" if ticket["unmodeled"] else "no"
        lines.append(
            f"- {ticket['ticket_id']} joint gaussian {float(ticket['gaussian_joint_p']):.4f}"
            f" t {float(ticket['t_copula_joint_p']):.4f}. corr_unmodeled {flag}."
        )
        for leg in legs:
            lines.append(f"- {ticket['ticket_id']} {leg.player}: {leg.note}")
    lines.extend(["", "## Sunday T-90 watchlist", "", "Do not put these names on the Saturday card.", ""])
    for row in read_csv(HOLD_PATH):
        lines.append(
            f"- {row['player']} ({row['team']}, {row['pos']}). Status is questionable."
        )
    for leg in pool.values():
        if leg.reason == "SATURDAY_HOLD" and leg.fair_american is not None:
            lines.append(f"- Priced, not staked: {_leg_phrase(leg)}. {leg.note}")
    lines.extend(
        [
            "",
            "Baker Mayfield pass_yds under is a mixed lean. TB pass offense is rank 32.",
            "DET pass defense allows rank 28. Wait for the inactive list.",
            "A Bowers-out Raiders fade is not a Saturday leg. Bowers is questionable.",
            "",
            "## Sunday morning roof check",
            "",
            "AT&T Stadium is retractable. Weather stays exposed until the roof call.",
            "Do not place a DAL pass or catch over on Saturday night.",
            "",
        ]
    )
    for leg_id in ("dak_over", "lamb_over", "pickens_over"):
        leg = pool[leg_id]
        price = _american(leg.fair_american) or "n/a"
        line = "" if leg.line is None else f"{leg.line:.2f}"
        lines.append(f"- {leg.player} {leg.market} {leg.side} {line}: {leg.reason}. Fair {price}. {leg.note}")
    lines.extend(["", "## Screened, not staked", ""])
    staked = {leg.leg_id for ticket in tickets for leg in ticket["legs"]}  # type: ignore[union-attr]
    for leg in pool.values():
        if leg.leg_id in staked or leg.reason in {"SATURDAY_HOLD", "ROOF_CHECK"}:
            continue
        if leg.leg_id in {"lamb_over", "pickens_over", "dak_over"}:
            continue
        label = "passed, not staked" if leg.reason == "OK" else leg.reason
        price = _american(leg.fair_american) or "n/a"
        lines.append(f"- {leg.player} {leg.market} {leg.side}: {label}. Fair {price}. {leg.note}")
    lines.extend(
        [
            "",
            "## Checks",
            "",
            "QB check: every pass leg matches the confirmed starter. FAIL_BACKUP_QB count is 0.",
            "Hard excludes on the card: none.",
            "Roster refresh: the file active_roster_whitelist_2026-11-22.csv is not on this machine.",
            "config/rosters/nfl.json was not rewritten.",
            "Known card names that are in the roster already use the 2026 club.",
            "Unknown names pass the roster gate.",
            "",
            "Desk path /workspace is not on this machine. Copies are in parlays-slate and parlays-recap.",
            "",
        ]
    )
    return "\n".join(lines)


def write_card(pool: dict[str, PricedLeg], tickets: list[dict[str, object]]) -> list[Path]:
    """Write the card and copy it into the slate and recap folders."""

    CARD_CSV.write_text(render_csv(tickets), encoding="utf-8")
    markdown = render_markdown(tickets, pool)
    CARD_MD.write_text(markdown, encoding="utf-8")
    DOC_PATH.write_text(markdown, encoding="utf-8")
    bets = REPO_ROOT / "data" / "bets" / "2026-11-22_hardrock_card.csv"
    bets.write_text(CARD_CSV.read_text(encoding="utf-8"), encoding="utf-8")
    written = sync_dated_card(CARD_CSV, CARD_MD, SLATE_DAY, default_sync_roots())
    return [CARD_CSV, CARD_MD, DOC_PATH, bets, *written]


def main() -> int:
    pool = screen_pool()
    tickets = build_tickets(pool)
    card_legs = [leg for ticket in tickets for leg in ticket["legs"]]  # type: ignore[union-attr]
    failures = qb_check_failures(card_legs, _starters(STARTERS_PATH))
    if failures:
        raise ValueError("QB check failed: " + "; ".join(failures))
    written = write_card(pool, tickets)
    print("QB_CHECK FAIL_BACKUP_QB=0")
    print(f"TICKETS {len(tickets)} STAKE $23.00")
    for path in written:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
