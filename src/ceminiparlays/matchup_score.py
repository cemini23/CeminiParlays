"""Score the locked matchup cells against one captured board.

Quarter receiving yards, quarter rushing yards, and quarter passing yards
use the compound Poisson-gamma hurdle. A normal is not used for those
markets or for a reception prop. The live slate is unplayed, so Brier skill
on that slate stays blank. Settled Brier skill is joined from the history
file when ``score_paths`` is given one. This module does not call Jev and
it does not submit a bet.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path

from ceminiparlays.book_team import canonical_team, offensive_team, teams_disagree
from ceminiparlays.half_edge import normal_over_prob, pick_side, sample_sd
from ceminiparlays.matchup_math import (
    MIN_GAMES,
    MIN_PLAYS,
    SHARE_W0,
    YPC_SD_FLOOR,
    baseline_volume,
    bh_qvalues,
    bootstrap_ci,
    cell_specs,
    combine_verdict,
    defense_multiplier,
    fair_over_prob,
    gamma_shape_rate,
    half_line_share,
    hist_verdict,
    hurdle_over_prob,
    implied_count_mean,
    implied_yards_mean,
    interaction,
    leg_ev,
    one_sided_p,
    poisson_over_prob,
    referee_multiplier,
    shrunk,
    sigma_floor,
    slate_floor,
    split_lambda,
    tail_over_prob,
    verdict_for,
    z_score,
)

DOME = {"dome", "indoor", "closed"}
MAIN_LINES = {"standard", "half", "quarter"}
EV_FIELDS = [
    "market",
    "signal",
    "family",
    "n_legs",
    "mean_ev",
    "ci_low",
    "ci_high",
    "boot_p",
    "q_value",
    "brier_skill",
    "logloss_delta",
    "half_line_share",
    "one_leg_ci_low",
    "verdict",
    "reason",
    "dropped",
    "n_hist",
    "delta_brier",
    "hist_ci_low",
    "hist_ci_high",
    "hist_q",
    "live_reason",
]
LEG_FIELDS = [
    "market",
    "signal",
    "player_name",
    "player_key",
    "team",
    "opp",
    "line",
    "side",
    "price",
    "model_p",
    "devig_p",
    "ev",
    "player_z",
    "def_z",
    "adj",
    "player_pct",
    "def_pct",
    "n_prior",
    "commence_time",
    "offense_team",
]

# Column map locked with the cells. A blank required column drops the leg.
_COLUMNS: dict[str, dict[str, object]] = {
    "rec_yds_q3": {
        "scope": "hurdle",
        "n": "n_rec",
        "count": "q3_receptions_mean",
        "opportunities": "q3_target_n",
        "ypc": "q3_ypc_mean",
        "ypc_sd": "q3_ypc_sd",
        "p0": "p0_rec",
        "player": "q3_target_share_mean",
        "defense": "q3_completion_allowed",
        "ypc_player": "ngs_separation",
        "ypc_defense": "q3_epa_allowed",
    },
    "rec_yds_q4": {
        "scope": "hurdle",
        "n": "n_rec",
        "count": "q4_receptions_mean",
        "opportunities": "q4_target_n",
        "ypc": "q4_ypc_mean",
        "ypc_sd": "q4_ypc_sd",
        "p0": "p0_rec",
        "player": "q4_target_share_mean",
        "defense": "q4_completion_allowed",
        "ypc_player": "ngs_separation",
        "ypc_defense": "q4_explosive_pass_allowed",
    },
    "receptions_q4": {
        "scope": "poisson",
        "n": "n_rec",
        "base": "q4_receptions_mean",
        "opportunities": "q4_target_n",
        "player": "q4_target_share_mean",
        "defense": "q4_completion_allowed",
    },
    "rush_yds_q4": {
        "scope": "hurdle",
        "n": "n_rush",
        "count": "q4_rush_att_mean",
        "opportunities": "q4_rush_n",
        "ypc": "q4_rypc_mean",
        "ypc_sd": "q4_rypc_sd",
        "p0": "p0_rush",
        "player": "q4_rush_att_mean",
        "defense": "q4_rush_ypc_allowed",
        "ypc_player": "ngs_ryoe",
        "ypc_defense": "explosive_rush_allowed",
    },
    "pass_yds_q4": {
        "scope": "hurdle",
        "n": "n_pass",
        "count": "q4_pass_cmp_mean",
        "opportunities": "q4_pass_n",
        "ypc": "q4_pypc_mean",
        "ypc_sd": "q4_pypc_sd",
        "p0": "p0_pass",
        "player": "q4_pass_cmp_mean",
        "defense": "q4_completion_allowed",
        "ypc_player": "ngs_intended_air",
        "ypc_defense": "q4_epa_dropback_allowed",
    },
    "rec_longest": {
        "scope": "tail",
        "n": "n_rec",
        "touches": "receptions_mean",
        "prefix": "weibull_rec",
        "player": "deep_target_rate",
        "defense": "deep_comp_allowed",
        "require_def": ("cushion_allowed",),
    },
    "rush_longest": {
        "scope": "tail",
        "n": "n_rush",
        "touches": "rush_att_mean",
        "prefix": "weibull_rush",
        "player": "breakaway_rate",
        "defense": "explosive_rush_allowed",
        "require_def": ("light_box_rate",),
    },
    "pass_longest": {
        "scope": "tail",
        "n": "n_pass",
        "touches": "pass_cmp_mean",
        "prefix": "weibull_pass",
        "player": "ngs_intended_air",
        "defense": "deep_comp_allowed",
        "require_def": ("cushion_allowed",),
    },
    "pass_attempts": {
        "scope": "poisson",
        "n": "n_pass",
        "base": "pass_att_mean",
        "player": "ngs_cpoe",
        "defense": "completion_allowed",
        "require_def": ("sack_rate",),
    },
    "pass_completions": {
        "scope": "poisson",
        "n": "n_pass",
        "base": "pass_cmp_mean",
        "player": "ngs_cpoe",
        "defense": "completion_allowed",
        "require_def": ("sack_rate",),
    },
    "interceptions": {
        "scope": "poisson",
        "n": "n_pass",
        "base": "interceptions_mean",
        "player": "ftn_int_worthy_rate",
        "defense": "int_rate",
        "require_def": ("sack_rate",),
    },
    "field_goals": {
        "scope": "kick",
        "n": "n_kick",
        "base": "fg_mean",
        "player_team": "stall_rate",
        "defense": "fg_forced_rate",
        "weather": True,
    },
    "kicking_points": {
        "scope": "kick_gauss",
        "n": "n_kick",
        "base": "kicking_points_mean",
        "sd": "kicking_points_sd",
        "player_team": "stall_rate",
        "defense": "fg_forced_rate",
        "sigma": "points",
        "weather": True,
    },
    "total_q3": {
        "scope": "game",
        "base": "q3_points",
        "sd": "q3_points_sd",
        "player": "q3_epa_off",
        "defense": "q3_epa_allowed",
        "sigma": "points",
    },
}


def _fmt(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return f"{value:.6f}"
    return str(value)


def _write(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _fmt(row.get(field, "")) for field in fields})


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _num(row: dict[str, str], field: str) -> float | None:
    text = str(row.get(field) or "").strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return value


def _league(rows: list[dict[str, str]], field: str, n_field: str | None) -> tuple[float, float]:
    values = []
    for row in rows:
        if n_field is not None:
            count = _num(row, n_field)
            if count is None or count < MIN_GAMES:
                continue
        value = _num(row, field)
        if value is None:
            continue
        values.append(value)
    if not values:
        return 0.0, 1.0
    center = sum(values) / len(values)
    scale = sample_sd(values) or 0.0
    return center, max(scale, 1e-6)


def _pct(value: float, population: list[float]) -> float:
    if len(population) <= 1:
        return 50.0
    below = sum(1 for item in population if item < value)
    return 100.0 * below / (len(population) - 1)


def _index_players(rows: list[dict[str, str]]) -> tuple[dict[str, dict[str, str]], dict[tuple[str, str], list[dict[str, str]]]]:
    by_key: dict[str, dict[str, str]] = {}
    by_il: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        key = str(row.get("player_key") or "")
        if key and key not in by_key:
            by_key[key] = row
        initial = str(row.get("initial") or "")
        last = str(row.get("last") or "")
        if initial and last:
            by_il.setdefault((initial, last), []).append(row)
    return by_key, by_il


def _initial_last(name: str) -> tuple[str, str]:
    from ceminiparlays.matchup_features import _initial_last as split

    return split(name)


def _find_player(name: str, key: str, by_key, by_il) -> dict[str, str] | None:
    if key and key in by_key:
        return by_key[key]
    initial, last = _initial_last(name)
    found = by_il.get((initial, last), [])
    if len(found) == 1:
        return found[0]
    return None


def _main_rows(rows: list[dict[str, str]], market: str) -> list[dict[str, str]]:
    chosen: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in rows:
        if row.get("stat_type") != market or row.get("line_type") not in MAIN_LINES:
            continue
        slot = (
            str(row.get("commence_time") or ""),
            market,
            str(row.get("player_key") or row.get("player_name") or ""),
        )
        chosen.setdefault(slot, row)
    return [chosen[key] for key in sorted(chosen)]


def _price(text: str) -> int | None:
    try:
        value = int(float(text))
    except (TypeError, ValueError):
        return None
    if value == 0 or -100 < value < 100:
        return None
    return value


# Full-game anchors. The tightest two-way main line wins.
_ANCHOR_STATS = frozenset(
    {
        "receptions",
        "rec_yds",
        "rush_att",
        "rush_yds",
        "pass_completions",
        "pass_yds",
    }
)
# Quarter volume is full-game volume times a shrunk share. These markets
# do not shrink the level toward a starter mean.
_VOLUME: dict[str, dict[str, object]] = {
    "rec_yds_q3": {
        "games": "n_rec",
        "trail": "receptions_mean",
        "parquet": "parquet_receptions_mean",
        "opps_q": "q3_target_n",
        "opps_total": "target_n",
        "parquet_total": "parquet_target_n",
        "count_stat": "receptions",
        "yards_stat": "rec_yds",
        "ypc": ("parquet_ypc", "q3_ypc_mean"),
        "defense": "q3_completion_allowed",
        "epa": "q3_epa_allowed",
        "crew": True,
        "receiving": True,
    },
    "rec_yds_q4": {
        "games": "n_rec",
        "trail": "receptions_mean",
        "parquet": "parquet_receptions_mean",
        "opps_q": "q4_target_n",
        "opps_total": "target_n",
        "parquet_total": "parquet_target_n",
        "count_stat": "receptions",
        "yards_stat": "rec_yds",
        "ypc": ("parquet_ypc", "q4_ypc_mean"),
        "defense": "q4_completion_allowed",
        "epa": "q4_epa_dropback_allowed",
        "crew": True,
        "receiving": True,
    },
    "receptions_q4": {
        "games": "n_rec",
        "trail": "receptions_mean",
        "parquet": "parquet_receptions_mean",
        "opps_q": "q4_target_n",
        "opps_total": "target_n",
        "parquet_total": "parquet_target_n",
        "count_stat": "receptions",
        "yards_stat": "rec_yds",
        "ypc": ("parquet_ypc", "q4_ypc_mean"),
        "defense": "q4_completion_allowed",
        "epa": "q4_epa_dropback_allowed",
        "crew": True,
        "receiving": True,
    },
    "rush_yds_q4": {
        "games": "n_rush",
        "trail": "rush_att_mean",
        "parquet": "parquet_rush_att_mean",
        "opps_q": "q4_rush_n",
        "opps_total": "rush_att_n",
        "parquet_total": "parquet_rush_att_n",
        "count_stat": "rush_att",
        "yards_stat": "rush_yds",
        "ypc": ("parquet_rypc", "q4_rypc_mean"),
        "defense": "q4_rush_ypc_allowed",
        "epa": "",
        "crew": False,
        "receiving": False,
    },
    "pass_yds_q4": {
        "games": "n_pass",
        "trail": "pass_cmp_mean",
        "parquet": "",
        "opps_q": "q4_pass_n",
        "opps_total": "pass_att_n",
        "parquet_total": "parquet_pass_att_n",
        "count_stat": "pass_completions",
        "yards_stat": "pass_yds",
        "ypc": ("q4_pypc_mean",),
        "defense": "q4_completion_allowed",
        "epa": "q4_epa_dropback_allowed",
        "crew": True,
        "receiving": False,
    },
}


def _anchor_index(rows: list[dict[str, str]]) -> dict[tuple[str, str, str], tuple[float, float, float]]:
    """Tightest two-way main line per player, kickoff, and stat."""

    best: dict[tuple[str, str, str], tuple[float, float, float]] = {}
    for row in rows:
        stat = str(row.get("stat_type") or "")
        if stat not in _ANCHOR_STATS or row.get("line_type") not in MAIN_LINES:
            continue
        over = _price(str(row.get("book_over") or ""))
        under = _price(str(row.get("book_under") or ""))
        posted = _num(row, "line")
        if over is None or under is None or posted is None:
            continue
        try:
            fair = fair_over_prob(over, under)
        except (TypeError, ValueError):
            continue
        gap = abs(fair - 0.5)
        slot = (
            str(row.get("commence_time") or ""),
            str(row.get("player_key") or row.get("player_name") or ""),
            stat,
        )
        current = best.get(slot)
        if current is None or gap < current[0]:
            best[slot] = (gap, posted, fair)
    return best


def _vacated_receptions(player: dict[str, str]) -> float:
    """Extra full-game receptions from vacated targets. Zero when absent.

    ``vacated_target_boost`` is extra targets per game, not a multiplier.
    The player's own catch rate converts targets into receptions.
    """

    boost = _num(player, "vacated_target_boost")
    games = _num(player, "parquet_games")
    total = _num(player, "parquet_target_n")
    receptions = _num(player, "parquet_receptions_mean")
    if (
        boost is None
        or boost <= 0.0
        or games is None
        or games <= 0.0
        or total is None
        or total <= 0.0
        or receptions is None
        or receptions <= 0.0
    ):
        return 0.0
    return boost * receptions / (total / games)


def _book_volume(spec: dict[str, object], player: dict[str, str], line_row: dict[str, str], anchors) -> float | None:
    """Book implied mean, then parquet trailing mean, then the local mean."""

    who = str(line_row.get("player_key") or line_row.get("player_name") or "")
    commence = str(line_row.get("commence_time") or "")
    count = anchors.get((commence, who, str(spec["count_stat"])))
    if count is not None:
        _gap, posted, fair = count
        implied = implied_count_mean(posted, fair)
        if implied is not None and implied > 0.0:
            return implied
    yards = anchors.get((commence, who, str(spec["yards_stat"])))
    if yards is not None:
        _gap, posted, fair = yards
        ypc = None
        for field in spec["ypc"]:  # type: ignore[union-attr]
            ypc = _num(player, str(field))
            if ypc is not None and ypc > 0.0:
                break
            ypc = None
        if ypc is not None:
            implied_yards = implied_yards_mean(posted, fair, sigma_floor("yards", posted))
            if implied_yards is not None and implied_yards > 0.0:
                return implied_yards / ypc
    parquet_name = str(spec["parquet"] or "")
    parquet_mean = _num(player, parquet_name) if parquet_name else None
    parquet_games = _num(player, "parquet_games")
    if parquet_mean is not None and parquet_games is not None:
        base = baseline_volume(parquet_games, parquet_mean)
        if base is not None:
            return base
    trail = _num(player, str(spec["trail"]))
    games = _num(player, str(spec["games"]))
    if trail is None or games is None:
        return None
    return baseline_volume(games, trail)


def _opportunity_pair(player: dict[str, str], spec: dict[str, object]) -> tuple[float, float]:
    quarter = _num(player, str(spec["opps_q"])) or 0.0
    total = _num(player, str(spec["opps_total"]))
    if total is None or total <= 0.0:
        total = _num(player, str(spec["parquet_total"]))
    if total is None or total <= 0.0:
        total = quarter / SHARE_W0 if quarter > 0.0 else 0.0
    return quarter, float(total)


def _defense_factor(
    defense: dict[str, str],
    spec: dict[str, object],
    center: float,
    teams: dict[str, dict[str, str]],
) -> float:
    rate = _num(defense, str(spec["defense"]))
    if rate is not None and rate > 0.0 and center > 0.0:
        return defense_multiplier(rate, center, epa=False)
    epa_name = str(spec.get("epa") or "")
    if not epa_name:
        return 1.0
    epa = _num(defense, epa_name)
    values = [value for row in teams.values() if (value := _num(row, epa_name)) is not None]
    if epa is None or not values:
        return 1.0
    return defense_multiplier(epa, sum(values) / len(values), epa=True)


def _split_volume(
    market: str,
    player: dict[str, str],
    line_row: dict[str, str],
    defense: dict[str, str],
    teams: dict[str, dict[str, str]],
    booked: str,
    center: float,
    anchors,
) -> tuple[float, float] | None:
    """Return ``(lambda, defense_shift)``. The shift is ``m_def - 1``."""

    spec = _VOLUME[market]
    base = _book_volume(spec, player, line_row, anchors)
    if base is None:
        return None
    if spec["receiving"]:
        base += _vacated_receptions(player)
    quarter, total = _opportunity_pair(player, spec)
    factor = _defense_factor(defense, spec, center, teams)
    crew = 1.0
    if spec["crew"]:
        offense = teams.get(booked)
        if offense is not None:
            crew = referee_multiplier(_num(offense, "referee_dpi_z"), _num(offense, "referee_holding_z"))
    return split_lambda(base, quarter, total, factor, crew), factor - 1.0


def _z(raw: float, n: int, center: float, scale: float) -> float:
    return z_score(shrunk(n, raw, center), center, scale)


def _indoor(team: str, opp: str, teams: dict[str, dict[str, str]]) -> bool:
    left = teams.get(team)
    right = teams.get(opp)
    if left is None or right is None:
        return False
    def roof_of(row: dict[str, str]) -> str:
        week = str(row.get("week_roof") or "").strip().lower()
        if week:
            return week
        return str(row.get("roof") or "")

    return roof_of(left) in DOME and roof_of(right) in DOME


def _score_cell(
    spec,
    lines: list[dict[str, str]],
    players: list[dict[str, str]],
    teams: dict[str, dict[str, str]],
    by_key,
    by_il,
    anchors,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    columns = _COLUMNS[spec.market]
    scope = str(columns["scope"])
    dropped: dict[str, int] = {}

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    player_field = str(columns.get("player") or columns.get("player_team") or "")
    defense_field = str(columns["defense"])
    n_field = str(columns.get("n") or "n_games")
    if scope == "game":
        p_center, p_scale = _league(list(teams.values()), player_field, "n_games")
        base_center, _base_scale = _league(list(teams.values()), str(columns["base"]), "n_games")
    elif scope in {"kick", "kick_gauss"}:
        p_center, p_scale = _league(list(teams.values()), str(columns["player_team"]), "n_games")
        base_center, _base_scale = _league(players, str(columns["base"]), n_field)
    else:
        p_center, p_scale = _league(players, player_field, n_field)
        base_name = str(columns.get("base") or columns.get("touches") or columns.get("count") or "")
        base_center, _base_scale = _league(players, base_name, n_field)
    d_center, d_scale = _league(list(teams.values()), defense_field, "n_games")
    ypc_center = 0.0
    ypc_p_center, ypc_p_scale = 0.0, 1.0
    ypc_d_center, ypc_d_scale = 0.0, 1.0
    if scope == "hurdle":
        ypc_center, _ypc_scale = _league(players, str(columns["ypc"]), n_field)
        ypc_p_center, ypc_p_scale = _league(players, str(columns.get("ypc_player") or ""), n_field)
        ypc_d_center, ypc_d_scale = _league(
            list(teams.values()), str(columns.get("ypc_defense") or ""), "n_games"
        )
    player_pop = [value for _row in players if (value := _num(_row, player_field)) is not None] if player_field in (players[0] if players else {}) else []
    if scope in {"kick", "kick_gauss", "game"}:
        player_pop = [value for row in teams.values() if (value := _num(row, str(columns.get("player_team") or columns.get("player")))) is not None]
    def_pop = [value for row in teams.values() if (value := _num(row, defense_field)) is not None]

    legs: list[dict[str, object]] = []
    for line_row in _main_rows(lines, spec.market):
        over = _price(str(line_row.get("book_over") or ""))
        under = _price(str(line_row.get("book_under") or ""))
        posted = _num(line_row, "line")
        if over is None or under is None or posted is None:
            drop("bad_price")
            continue
        team = canonical_team(str(line_row.get("team") or ""))
        opp = canonical_team(str(line_row.get("opp") or ""))
        if team and teams.get(offensive_team(team, "")) is None:
            drop("no_offense")
            continue
        defense = teams.get(opp)
        if defense is None or _num(defense, "n_games") is None or float(defense["n_games"]) < MIN_GAMES:
            drop("no_defense")
            continue
        if _num(defense, defense_field) is None:
            drop("missing_defense")
            continue
        for required in columns.get("require_def") or ():
            if _num(defense, str(required)) is None:
                drop("missing_defense")
                defense = None
                break
        if defense is None:
            continue
        if columns.get("weather") and not _indoor(team, opp, teams):
            drop("weather_unknown")
            continue
        built = _leg_prob(
            spec,
            columns,
            line_row,
            posted,
            over,
            under,
            team,
            opp,
            defense,
            players,
            teams,
            by_key,
            by_il,
            p_center,
            p_scale,
            d_center,
            d_scale,
            base_center,
            player_pop,
            def_pop,
            ypc_center,
            ypc_p_center,
            ypc_p_scale,
            ypc_d_center,
            ypc_d_scale,
            drop,
            anchors,
        )
        if built is not None:
            legs.append(built)
    evs = [float(leg["ev"]) for leg in legs]
    n_legs = len(legs)
    mean = sum(evs) / n_legs if n_legs else 0.0
    ci_low: float | None = None
    ci_high: float | None = None
    one_low: float | None = None
    if n_legs >= 2:
        ci_low, ci_high = bootstrap_ci(evs, random.Random(spec.seed))
        order = sorted(legs, key=lambda leg: (-float(leg["ev"]), str(leg["player_key"]), float(leg["line"])))
        reduced = [float(leg["ev"]) for leg in order[1:]]
        if len(reduced) >= 2:
            one_low, _one_high = bootstrap_ci(reduced, random.Random(spec.seed))
        elif len(reduced) == 1:
            one_low = reduced[0]
    elif n_legs == 1:
        ci_low = ci_high = evs[0]
        one_low = None
    lines_used = [float(leg["line"]) for leg in legs]
    summary: dict[str, object] = {
        "market": spec.market,
        "signal": spec.signal,
        "family": spec.family,
        "n_legs": n_legs,
        "mean_ev": mean if n_legs else None,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "boot_p": None,
        "q_value": None,
        "brier_skill": "",
        "logloss_delta": "",
        "half_line_share": half_line_share(lines_used) if n_legs else None,
        "one_leg_ci_low": one_low,
        "verdict": "",
        "reason": "",
        "dropped": ",".join(f"{key}:{dropped[key]}" for key in sorted(dropped)),
        "n_hist": "",
        "delta_brier": "",
        "hist_ci_low": "",
        "hist_ci_high": "",
        "hist_q": "",
        "live_reason": "",
        "_evs": evs,
    }
    return summary, legs


def _leg_prob(
    spec,
    columns,
    line_row,
    posted,
    over,
    under,
    team,
    opp,
    defense,
    players,
    teams,
    by_key,
    by_il,
    p_center,
    p_scale,
    d_center,
    d_scale,
    base_center,
    player_pop,
    def_pop,
    ypc_center,
    ypc_p_center,
    ypc_p_scale,
    ypc_d_center,
    ypc_d_scale,
    drop,
    anchors,
) -> dict[str, object] | None:
    scope = str(columns["scope"])
    def_raw = _num(defense, str(columns["defense"]))
    def_n = int(float(defense["n_games"]))
    if def_raw is None:
        drop("missing_defense")
        return None
    def_z = _z(def_raw, def_n, d_center, d_scale)
    if scope == "game":
        return _game_leg(
            spec, columns, line_row, posted, over, under, team, opp, teams,
            p_center, p_scale, d_center, d_scale, base_center, player_pop, def_pop, drop,
        )
    player = _find_player(str(line_row.get("player_name") or ""), str(line_row.get("player_key") or ""), by_key, by_il)
    if player is None:
        drop("no_player")
        return None
    n_raw = _num(player, str(columns["n"]))
    if n_raw is None or n_raw < MIN_GAMES:
        drop("short_history")
        return None
    n_prior = int(n_raw)
    if scope in {"kick", "kick_gauss"}:
        offense = teams.get(team)
        signal_name = str(columns["player_team"])
        if offense is None or _num(offense, "n_games") is None or float(offense["n_games"]) < MIN_GAMES:
            drop("no_offense")
            return None
        raw_signal = _num(offense, signal_name)
        signal_n = int(float(offense["n_games"]))
    else:
        raw_signal = _num(player, str(columns["player"]))
        signal_n = n_prior
    if raw_signal is None:
        drop("missing_player")
        return None
    player_z = _z(raw_signal, signal_n, p_center, p_scale)
    adj = interaction(player_z, def_z, spec.clip)
    booked = offensive_team(team, str(player.get("team") or ""))
    if teams_disagree(team, booked):
        drop("team_mismatch")
        return None
    if scope == "hurdle":
        return _hurdle_leg(
            spec, columns, player, line_row, posted, over, under, team, opp, defense,
            teams, booked, player_z, def_z, n_prior, d_center, ypc_center,
            ypc_p_center, ypc_p_scale, ypc_d_center, ypc_d_scale,
            _pct(raw_signal, player_pop), _pct(def_raw, def_pop), drop, anchors,
        )
    base_name = str(columns.get("base") or columns.get("touches") or "")
    raw_base = _num(player, base_name)
    if raw_base is None and spec.market not in _VOLUME:
        drop("missing_base")
        return None
    if scope == "poisson" and spec.market in _VOLUME:
        built = _split_volume(spec.market, player, line_row, defense, teams, booked, d_center, anchors)
        if built is None:
            drop("missing_base")
            return None
        lam, volume_adj = built
        if lam <= 0:
            drop("nonpositive_mean")
            return None
        try:
            model_p = poisson_over_prob(lam, posted)
        except ValueError:
            drop("integer_line")
            return None
        return _pack(
            spec, line_row, posted, over, under, team, opp, model_p, player_z, def_z, volume_adj,
            _pct(raw_signal, player_pop), _pct(def_raw, def_pop), n_prior, booked,
        )
    base = shrunk(n_prior, raw_base, base_center)
    mean = base * (1.0 + adj)
    if mean <= 0:
        drop("nonpositive_mean")
        return None
    model_p = _model_p(scope, columns, player, mean, posted, adj, n_prior, base_center, drop)
    if model_p is None:
        return None
    return _pack(
        spec, line_row, posted, over, under, team, opp, model_p, player_z, def_z, adj,
        _pct(raw_signal, player_pop), _pct(def_raw, def_pop), n_prior, booked,
    )


def _ypc_tilt(player, defense, columns, centers, clip: float) -> float:
    """Tilt yards per event only when both NGS and defense inputs exist."""

    player_name = str(columns.get("ypc_player") or "")
    defense_name = str(columns.get("ypc_defense") or "")
    raw_player = _num(player, player_name) if player_name else None
    raw_defense = _num(defense, defense_name) if defense_name else None
    if raw_player is None or raw_defense is None:
        return 0.0
    player_z = z_score(raw_player, centers[0], centers[1])
    defense_z = z_score(raw_defense, centers[2], centers[3])
    return interaction(player_z, defense_z, clip)


def _hurdle_leg(
    spec, columns, player, line_row, posted, over, under, team, opp, defense,
    teams, booked, player_z, def_z, n_prior, d_center, ypc_center,
    ypc_p_center, ypc_p_scale, ypc_d_center, ypc_d_scale, player_pct, def_pct, drop,
    anchors,
):
    """Compound Poisson-gamma price. A normal is not used.

    Lambda is full-game volume times the shrunk quarter share times the
    defense multiplier. The player-by-defense z product does not enter lambda.
    """

    offense = teams.get(booked)
    if offense is None:
        drop("no_offense")
        return None
    ypc = _num(player, str(columns["ypc"]))
    p0 = _num(offense, str(columns["p0"]))
    if ypc is None or p0 is None:
        drop("missing_base")
        return None
    built = _split_volume(spec.market, player, line_row, defense, teams, booked, d_center, anchors)
    if built is None:
        drop("missing_base")
        return None
    lam, adj = built
    if lam < 0:
        drop("nonpositive_mean")
        return None
    tilt = _ypc_tilt(
        player, defense, columns,
        (ypc_p_center, ypc_p_scale, ypc_d_center, ypc_d_scale),
        spec.clip,
    )
    ypc_mean = shrunk(n_prior, ypc, ypc_center) * (1.0 + tilt)
    ypc_sd = _num(player, str(columns["ypc_sd"])) or YPC_SD_FLOOR
    alpha, rate = gamma_shape_rate(ypc_mean, ypc_sd)
    p_gain = min(1.0, max(0.0, 1.0 - float(p0)))
    try:
        model_p = hurdle_over_prob(lam, alpha, rate, posted, p_gain)
    except ValueError:
        drop("missing_base")
        return None
    return _pack(
        spec, line_row, posted, over, under, team, opp, model_p, player_z, def_z, adj,
        player_pct, def_pct, n_prior, booked,
    )


def _model_p(scope, columns, player, mean, posted, adj, n_prior, base_center, drop):
    if scope == "tail":
        prefix = str(columns["prefix"])
        shape = _num(player, f"{prefix}_shape")
        scale = _num(player, f"{prefix}_scale")
        n_plays = _num(player, f"{prefix}_n")
        touches = shrunk(n_prior, _num(player, str(columns["touches"])) or 0.0, base_center)
        if shape is None or scale is None or n_plays is None or n_plays < MIN_PLAYS or touches <= 0:
            drop("weibull")
            return None
        prob = tail_over_prob(shape, scale, posted, touches, adj)
        if prob is None:
            drop("weibull")
            return None
        return prob
    if scope == "poisson" or scope == "kick":
        try:
            return poisson_over_prob(mean, posted)
        except ValueError:
            drop("integer_line")
            return None
    kind = str(columns.get("sigma") or "yards")
    sd = _num(player, str(columns.get("sd") or ""))
    sigma = max(sigma_floor(kind, posted), sd or 0.0)
    return normal_over_prob(posted, mean, sigma)


def _game_leg(
    spec, columns, line_row, posted, over, under, team, opp, teams,
    p_center, p_scale, d_center, d_scale, base_center, player_pop, def_pop, drop,
):
    left = teams.get(team)
    right = teams.get(opp)
    if left is None or right is None:
        drop("no_team")
        return None
    built = []
    for offense, defense in ((left, right), (right, left)):
        n_games = _num(offense, "n_games")
        if n_games is None or n_games < MIN_GAMES:
            drop("short_history")
            return None
        raw_off = _num(offense, str(columns["player"]))
        raw_def = _num(defense, str(columns["defense"]))
        raw_base = _num(offense, str(columns["base"]))
        if raw_off is None or raw_def is None or raw_base is None:
            drop("missing_team")
            return None
        n_int = int(n_games)
        player_z = _z(raw_off, n_int, p_center, p_scale)
        def_z = _z(raw_def, int(float(defense["n_games"])), d_center, d_scale)
        adj = interaction(player_z, def_z, spec.clip)
        part = shrunk(n_int, raw_base, base_center) * (1.0 + adj)
        sd = _num(offense, str(columns["sd"])) or sigma_floor(str(columns["sigma"]), posted)
        built.append((part, sd, player_z, def_z, adj, raw_off, raw_def))
    mean = built[0][0] + built[1][0]
    if mean <= 0:
        drop("nonpositive_mean")
        return None
    sigma = max(sigma_floor(str(columns["sigma"]), posted), math.hypot(built[0][1], built[1][1]))
    model_p = normal_over_prob(posted, mean, sigma)
    return _pack(
        spec, line_row, posted, over, under, team, opp, model_p,
        (built[0][2] + built[1][2]) / 2.0,
        (built[0][3] + built[1][3]) / 2.0,
        (built[0][4] + built[1][4]) / 2.0,
        _pct(built[0][5], player_pop),
        _pct(built[0][6], def_pop),
        int(float(left["n_games"])),
        offensive_team(team, ""),
    )


def _pack(
    spec, line_row, posted, over, under, team, opp, model_p, player_z, def_z, adj,
    player_pct, def_pct, n_prior, offense_name=None,
):
    market_p = fair_over_prob(over, under)
    if spec.family in {"tail", "poisson", "hurdle"} or spec.market == "field_goals":
        if abs(model_p - market_p) <= 1e-12:
            return None
        if model_p > market_p:
            side, prob, price = "over", model_p, over
        else:
            side, prob, price = "under", 1.0 - model_p, under
    else:
        # Gaussian, including kicking points and the Q3 total.
        from_mean_side = None
        # Reconstruct the side from probability vs 0.5 only when the mean rule
        # agrees. The mean rule is sign(model over-prob - 0.5), which matches
        # sign(mean - line) for a symmetric normal.
        if abs(model_p - 0.5) <= 1e-12:
            return None
        from_mean_side = "over" if model_p > 0.5 else "under"
        checked = pick_side(model_p, 0.5)
        if checked != from_mean_side:
            return None
        if from_mean_side == "over":
            side, prob, price = "over", model_p, over
        else:
            side, prob, price = "under", 1.0 - model_p, under
    return {
        "market": spec.market,
        "signal": spec.signal,
        "player_name": line_row.get("player_name") or "",
        "player_key": line_row.get("player_key") or "",
        "team": team,
        "opp": opp,
        "line": posted,
        "side": side,
        "price": price,
        "model_p": prob,
        "devig_p": market_p if side == "over" else 1.0 - market_p,
        "ev": leg_ev(prob, price),
        "player_z": player_z,
        "def_z": def_z,
        "adj": adj,
        "player_pct": player_pct,
        "def_pct": def_pct,
        "n_prior": n_prior,
        "commence_time": line_row.get("commence_time") or "",
        "offense_team": team if offense_name is None else offense_name,
    }


def score_board(
    lines: list[dict[str, str]],
    players: list[dict[str, str]],
    team_rows: list[dict[str, str]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return the EV table and the included legs. Order follows ``CELLS``."""

    teams = {str(row["team"]): row for row in team_rows if row.get("team")}
    by_key, by_il = _index_players(players)
    anchors = _anchor_index(lines)
    summaries = []
    all_legs = []
    for spec in cell_specs():
        summary, legs = _score_cell(spec, lines, players, teams, by_key, by_il, anchors)
        summaries.append(summary)
        all_legs.extend(legs)
    family = [
        row for row in summaries if int(row["n_legs"]) >= slate_floor(str(row["market"]))
    ]
    for row in family:
        evs = list(row["_evs"])
        spec_seed = next(spec.seed for spec in cell_specs() if spec.market == row["market"])
        row["boot_p"] = one_sided_p(evs, random.Random(spec_seed + 17))
    q_values = bh_qvalues([float(row["boot_p"]) for row in family])
    for row, q_value in zip(family, q_values, strict=True):
        row["q_value"] = q_value
    for row in summaries:
        verdict, reason = verdict_for(
            n_legs=int(row["n_legs"]),
            mean_ev=float(row["mean_ev"] or 0.0),
            ci_low=float(row["ci_low"] or 0.0),
            q_value=None if row["q_value"] in ("", None) else float(row["q_value"]),
            one_leg_ci_low=None if row["one_leg_ci_low"] in ("", None) else float(row["one_leg_ci_low"]),
            half_share=float(row["half_line_share"] or 0.0),
            market=str(row["market"]),
        )
        row["verdict"] = verdict
        row["reason"] = reason
        row["live_reason"] = reason
        row.pop("_evs", None)
    all_legs.sort(key=lambda leg: (str(leg["market"]), -float(leg["ev"]), str(leg["player_key"])))
    return summaries, all_legs


def apply_history(summaries: list[dict[str, object]], hist_path: Path | None) -> None:
    """Join settled Brier rows. A missing file fails every market closed."""

    found: dict[str, dict[str, str]] = {}
    if hist_path is not None and Path(hist_path).exists():
        found = {str(row.get("market") or ""): row for row in _read(hist_path)}
    for row in summaries:
        live = (str(row.get("verdict") or ""), str(row.get("reason") or ""))
        row["live_reason"] = live[1]
        hist_row = found.get(str(row.get("market") or ""))
        pair: tuple[str, str] | None = None
        if hist_row is not None:
            n_hist = int(float(hist_row.get("n_hist") or 0))
            delta = float(hist_row.get("delta_brier") or 0)
            ci_low = float(hist_row.get("hist_ci_low") or 0)
            ci_high = float(hist_row.get("hist_ci_high") or 0)
            q_text = str(hist_row.get("hist_q") or hist_row.get("q_value") or "").strip()
            q_value = float(q_text) if q_text else None
            row["n_hist"] = n_hist
            row["delta_brier"] = delta
            row["hist_ci_low"] = ci_low
            row["hist_ci_high"] = ci_high
            row["hist_q"] = "" if q_value is None else q_value
            pair = hist_verdict(n_hist=n_hist, delta_brier=delta, ci_low=ci_low, q_value=q_value)
        verdict, reason = combine_verdict(live, pair)
        row["verdict"] = verdict
        row["reason"] = reason


def score_paths(
    lines_path: Path,
    players_path: Path,
    teams_path: Path,
    out: Path,
    legs_out: Path,
    hist_path: Path | None = None,
    frames: dict | None = None,
) -> list[dict[str, object]]:
    players = _read(players_path)
    team_rows = _read(teams_path)
    if frames:
        from ceminiparlays.feature_cache import overlay_pit

        players, team_rows = overlay_pit(players, team_rows, frames)
    summaries, legs = score_board(_read(lines_path), players, team_rows)
    apply_history(summaries, hist_path)
    _write(out, EV_FIELDS, summaries)
    _write(legs_out, LEG_FIELDS, legs)
    return summaries


def format_table(rows: list[dict[str, object]]) -> str:
    header = (
        "market signal n_slate mean_ev ci_low ci_high q "
        "n_hist delta_brier hist_ci_low hist_ci_high hist_q verdict reason"
    )
    body = [header]
    for row in rows:
        body.append(
            " ".join(
                [
                    str(row.get("market") or ""),
                    str(row.get("signal") or ""),
                    str(row.get("n_legs") or "0"),
                    _fmt(row.get("mean_ev")),
                    _fmt(row.get("ci_low")),
                    _fmt(row.get("ci_high")),
                    _fmt(row.get("q_value")),
                    _fmt(row.get("n_hist")),
                    _fmt(row.get("delta_brier")),
                    _fmt(row.get("hist_ci_low")),
                    _fmt(row.get("hist_ci_high")),
                    _fmt(row.get("hist_q")),
                    str(row.get("verdict") or ""),
                    str(row.get("reason") or ""),
                ]
            )
        )
    return "\n".join(body)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ceminiparlays.matchup_score")
    parser.add_argument("--lines", type=Path, required=True)
    parser.add_argument("--players", type=Path, required=True)
    parser.add_argument("--teams", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--legs", type=Path, required=True)
    parser.add_argument("--hist", type=Path, default=None)
    args = parser.parse_args(argv)
    rows = score_paths(args.lines, args.players, args.teams, args.out, args.legs, args.hist)
    print(format_table(rows))
    passed = [str(row["market"]) for row in rows if row["verdict"] == "pass"]
    print("promoted=" + (",".join(passed) if passed else "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
