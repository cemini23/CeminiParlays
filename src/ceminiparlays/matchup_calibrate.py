"""Settled-outcome calibration and regime correlations.

The window is 2023 through 2026 week 5. 2022 pbp is not on disk.
Synthetic lines are the point-in-time median and, for zero-inflated
markets, a 0.5 line at -114/-114. Quarter lambda is full-game volume
times a shrunk quarter share. This module does not read a book price,
does not apply the live referee factor, and does not submit a bet.

Do not refit k, the clips, or the 250-game floor after the table.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from ceminiparlays.copula import nearest_correlation
from ceminiparlays.half_edge import normal_over_prob, sample_sd
from ceminiparlays.matchup_features import (
    CACHE,
    YEARS,
    _join_rate,
    _load_ftn_year,
    _load_ngs,
    _load_pbp_year,
    _player_games,
    _team_tables,
)
from ceminiparlays.matchup_math import (
    COUNT_MARKETS,
    HURDLE_LINE_MARKETS,
    MIN_GAMES,
    MIN_HIST,
    N_BOOT,
    YPC_SD_FLOOR,
    baseline_volume,
    bh_qvalues,
    bootstrap_ci,
    cell_specs,
    defense_multiplier,
    fair_over_prob,
    gamma_shape_rate,
    hist_verdict,
    hurdle_over_prob,
    interaction,
    one_sided_p,
    poisson_over_prob,
    shrunk,
    sigma_floor,
    split_lambda,
    tail_over_prob,
    weibull_fit,
    z_score,
)
from ceminiparlays.roster import normalize_team

DOME = {"dome", "indoor", "closed"}
MIN_PAIRS = 40
FULL_GAME = ("rec_yds", "rush_yds", "pass_yds", "receptions", "rush_att", "pass_att")
HIST_SEED = {spec.market: 20261018 + index for index, spec in enumerate(cell_specs())}
MARKET_ORDER = [spec.market for spec in cell_specs()]


def _num(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _sd(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    return sample_sd(values) or 0.0


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def _shrunk_z(raw: float, n: int, center: float, scale: float) -> float:
    return z_score(shrunk(n, raw, center), center, scale)


def _brier_delta(prob: float, outcome: float, base: float) -> float:
    return (base - outcome) ** 2 - (prob - outcome) ** 2


class _Acc:
    def __init__(self) -> None:
        self.n = 0
        self.total = 0.0

    def add(self, value: float) -> None:
        self.n += 1
        self.total += float(value)

    def mean(self) -> float | None:
        if self.n <= 0:
            return None
        return self.total / self.n


def _league(accs: list[_Acc]) -> tuple[float, float]:
    means = [item.mean() for item in accs if item.n >= MIN_GAMES and item.mean() is not None]
    if not means:
        return 0.0, 1.0
    center = sum(means) / len(means)
    scale = sample_sd(means) or 0.0
    return float(center), max(float(scale), 1e-6)


def _lines(market: str, values: list[float]) -> list[float]:
    """0.5 plus the point-in-time median. A duplicate 0.5 is not scored twice."""

    chosen: list[float] = []
    if market in HURDLE_LINE_MARKETS:
        chosen.append(0.5)
    med = _median(values)
    if med is None:
        return chosen
    line = float(med)
    half_median = COUNT_MARKETS | {"receptions", "rush_att", "pass_att"}
    if market in half_median and abs(line - round(line)) < 1e-9:
        line = math.floor(line) + 0.5
    if line <= 0.5 + 1e-9 and market in HURDLE_LINE_MARKETS:
        return chosen
    if line <= 0.0:
        return chosen
    chosen.append(line)
    return chosen


def _regime(q4_enter: float | None, q3_epa: float | None, explosive: bool) -> str:
    if q4_enter is not None and q4_enter < -7.0:
        return "q4_trailing_comeback"
    if q3_epa is not None and q3_epa > 0.0:
        return "q3_opening_surge"
    if explosive:
        return "explosive_light_box"
    return "neutral"


def _load(cache: Path) -> dict[str, object]:
    """Read 2023–2026 weeks before 2026 week 6. 2022 is not loaded."""

    import pandas as pd

    rec_parts = []
    rush_parts = []
    pass_parts = []
    kick_parts = []
    off_parts = []
    def_parts = []
    regime_parts = []
    roof_parts = []
    zero_parts = []
    catch_parts = []
    rush_pos_parts = []
    pass_pos_parts = []
    for year in YEARS:
        path = cache / f"pbp_{year}.parquet"
        if not path.exists():
            continue
        plays = _load_pbp_year(pd, cache, year, 2026, 6)
        plays["game_id"] = plays["game_id"].astype(str)
        ftn = _load_ftn_year(pd, cache, year, 2026, 6)
        _join_rate(plays, ftn)
        if ftn is not None:
            plays = plays.merge(ftn, on=["game_id", "play_id"], how="left")
        off, defense = _team_tables(plays, pd)
        rec, rush, passed, kick, _yards, zeros = _player_games(plays, pd)
        del zeros
        rec_parts.append(rec)
        rush_parts.append(rush)
        pass_parts.append(passed)
        kick_parts.append(kick)
        off_parts.append(off)
        def_parts.append(defense)
        regime_parts.append(_regime_frame(plays, pd))
        roof_parts.append(_roof_frame(plays, pd))
        zero_parts.append(_zero_frame(plays, pd))
        catch_parts.append(_play_lists(plays, pd, "receiver_player_id", "receiving_yards", "complete_pass"))
        rush_pos_parts.append(_play_lists(plays, pd, "rusher_player_id", "rushing_yards", "rush_attempt"))
        pass_pos_parts.append(_play_lists(plays, pd, "passer_player_id", "passing_yards", "complete_pass"))
    if not rec_parts:
        raise ValueError("no prior pbp seasons were on disk")
    ngs = _load_ngs(pd, cache, 2026, 6)
    return {
        "rec": pd.concat(rec_parts, ignore_index=True),
        "rush": pd.concat(rush_parts, ignore_index=True),
        "pass": pd.concat(pass_parts, ignore_index=True),
        "kick": pd.concat(kick_parts, ignore_index=True),
        "off": pd.concat(off_parts, ignore_index=True),
        "defense": pd.concat(def_parts, ignore_index=True),
        "regime": pd.concat(regime_parts, ignore_index=True),
        "roof": pd.concat(roof_parts, ignore_index=True),
        "zeros": pd.concat(zero_parts, ignore_index=True),
        "catch": pd.concat(catch_parts, ignore_index=True),
        "rush_pos": pd.concat(rush_pos_parts, ignore_index=True),
        "pass_pos": pd.concat(pass_pos_parts, ignore_index=True),
        "ngs": ngs,
    }


def _play_lists(plays, pd, id_col: str, value_col: str, flag_col: str):
    scoped = plays[plays[id_col].notna() & (plays[flag_col] > 0)][["game_id", id_col, value_col]].copy()
    scoped["gsis_id"] = scoped[id_col].astype(str)
    scoped[value_col] = pd.to_numeric(scoped[value_col], errors="coerce")
    scoped = scoped[scoped[value_col] > 0]
    if scoped.empty:
        return pd.DataFrame(columns=["game_id", "gsis_id", "plays"])
    grouped = scoped.groupby(["game_id", "gsis_id"], dropna=False)[value_col].agg(list).reset_index()
    return grouped.rename(columns={value_col: "plays"})


def _regime_frame(plays, pd):
    work = plays.copy()
    work["qtr"] = pd.to_numeric(work["qtr"], errors="coerce")
    for col in ("receiving_yards", "rushing_yards", "passing_yards", "score_differential", "epa"):
        work[col] = pd.to_numeric(work[col], errors="coerce")
    yds = work[["receiving_yards", "rushing_yards", "passing_yards"]].max(axis=1)
    if "n_defense_box" in work.columns:
        box = pd.to_numeric(work["n_defense_box"], errors="coerce")
    else:
        box = pd.Series(float("nan"), index=work.index)
    explosive = ((box.notna()) & (yds >= 15) & (box <= 6)) | (box.isna() & (yds >= 20))
    work["explosive"] = explosive.fillna(False).astype(int)
    flags = (
        work.groupby(["game_id", "posteam"], dropna=False)["explosive"].max().reset_index()
    )
    q4 = work[work["qtr"] == 4].sort_values("play_id")
    enter = (
        q4.groupby(["game_id", "posteam"], dropna=False)["score_differential"].first().reset_index()
    )
    q3 = work[work["qtr"] == 3]
    epa = q3.groupby(["game_id", "posteam"], dropna=False)["epa"].mean().reset_index()
    out = flags.merge(enter, on=["game_id", "posteam"], how="outer")
    out = out.merge(epa, on=["game_id", "posteam"], how="outer")
    out = out.rename(columns={"posteam": "team", "score_differential": "q4_enter", "epa": "q3_epa"})
    out["team"] = out["team"].map(lambda value: normalize_team(str(value or "")))
    return out[out["team"].astype(str) != ""]


def _roof_frame(plays, pd):
    del pd
    home = plays[plays["home_team"].astype(str) != ""]
    grouped = (
        home.groupby(["season", "week", "game_id", "home_team"], dropna=False)["roof"]
        .first()
        .reset_index()
    )
    grouped["home_team"] = grouped["home_team"].map(lambda value: normalize_team(str(value or "")))
    return grouped


def _zero_frame(plays, pd):
    work = plays.copy()
    for col in ("complete_pass", "rush_attempt", "receiving_yards", "rushing_yards", "passing_yards"):
        work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0)
    rows = []
    for (season, week), frame in work.groupby(["season", "week"], dropna=False):
        caught = frame["complete_pass"] > 0
        carried = frame["rush_attempt"] > 0
        rows.append(
            {
                "season": int(season),
                "week": int(week),
                "rec_n": int(caught.sum()),
                "rec_z": int((caught & (frame["receiving_yards"] <= 0)).sum()),
                "rush_n": int(carried.sum()),
                "rush_z": int((carried & (frame["rushing_yards"] <= 0)).sum()),
                "pass_n": int(caught.sum()),
                "pass_z": int((caught & (frame["passing_yards"] <= 0)).sum()),
            }
        )
    import pandas as pd

    return pd.DataFrame(rows)


def _opp_map(defense) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    # defense rows are from the defense's point of view. The offense is not
    # stored. Opponent is recovered from the paired posteam on player rows
    # below. This map stays empty on purpose when the caller passes rows
    # that already carry ``opp``.
    del defense
    return out


def _attach_opp(frame, plays_opp: dict[tuple[str, str], str]):
    opps = []
    for game_id, team in zip(frame["game_id"].astype(str), frame["team"].astype(str), strict=False):
        opps.append(plays_opp.get((game_id, team), ""))
    frame = frame.copy()
    frame["opp"] = opps
    return frame


def _build_opp(off) -> dict[tuple[str, str], str]:
    """Within one game the other posteam is the opponent."""

    games: dict[str, list[str]] = defaultdict(list)
    for game_id, team in zip(off["game_id"].astype(str), off["team"].astype(str), strict=False):
        team = normalize_team(team)
        if team and team not in games[game_id]:
            games[game_id].append(team)
    out: dict[tuple[str, str], str] = {}
    for game_id, teams in games.items():
        if len(teams) != 2:
            continue
        out[(game_id, teams[0])] = teams[1]
        out[(game_id, teams[1])] = teams[0]
    return out


def run_calibration(cache: Path = CACHE) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Return the history table and the regime-rho document."""

    loaded = _load(cache)
    import pandas as pd

    off = loaded["off"]
    defense = loaded["defense"]
    assert isinstance(off, pd.DataFrame)
    assert isinstance(defense, pd.DataFrame)
    opp = _build_opp(off)
    bundles = _bundles(loaded, opp, pd)
    return _walk(bundles)


def _bundles(loaded, opp: dict[tuple[str, str], str], pd) -> dict[str, object]:
    def _rows(frame, extra: dict[tuple[str, str], list[float]] | None, fields: list[str]) -> list[dict[str, object]]:
        rows = []
        extra = extra or {}
        for record in frame.itertuples(index=False):
            game_id = str(getattr(record, "game_id"))
            team = normalize_team(str(getattr(record, "team") or ""))
            gsis = str(getattr(record, "gsis_id"))
            row: dict[str, object] = {
                "season": int(getattr(record, "season")),
                "week": int(getattr(record, "week")),
                "game_id": game_id,
                "gsis": gsis,
                "team": team,
                "opp": opp.get((game_id, team), ""),
                "plays": list(extra.get((game_id, gsis), [])),
            }
            for field in fields:
                row[field] = _num(getattr(record, field, None))
            rows.append(row)
        rows.sort(key=lambda item: (int(item["season"]), int(item["week"]), str(item["game_id"]), str(item["gsis"])))
        return rows

    catch = {
        (str(game), str(gsis)): list(plays)
        for game, gsis, plays in zip(
            loaded["catch"]["game_id"], loaded["catch"]["gsis_id"], loaded["catch"]["plays"], strict=False
        )
    }
    rush_pos = {
        (str(game), str(gsis)): list(plays)
        for game, gsis, plays in zip(
            loaded["rush_pos"]["game_id"],
            loaded["rush_pos"]["gsis_id"],
            loaded["rush_pos"]["plays"],
            strict=False,
        )
    }
    pass_pos = {
        (str(game), str(gsis)): list(plays)
        for game, gsis, plays in zip(
            loaded["pass_pos"]["game_id"],
            loaded["pass_pos"]["gsis_id"],
            loaded["pass_pos"]["plays"],
            strict=False,
        )
    }
    rec_fields = [
        "q3_targets",
        "q3_receptions",
        "q3_rec_yds",
        "q4_targets",
        "q4_receptions",
        "q4_rec_yds",
        "targets",
        "receptions",
        "rec_yds",
        "rec_long",
        "deep_targets",
        "team_q3_targets",
        "team_q4_targets",
    ]
    rush_fields = ["rush_att", "rush_yds", "q4_rush_att", "q4_rush_yds", "rush_long", "breakaways"]
    pass_fields = [
        "pass_att",
        "pass_cmp",
        "pass_yds",
        "interceptions",
        "q4_pass_att",
        "q4_pass_cmp",
        "q4_pass_yds",
        "pass_long",
        "worthy",
        "worthy_n",
    ]
    kick_fields = ["fg_made", "kicking_points"]
    team_rows = _team_rows(loaded["off"], loaded["defense"], opp)
    return {
        "rec": _rows(loaded["rec"], catch, rec_fields),
        "rush": _rows(loaded["rush"], rush_pos, rush_fields),
        "pass": _rows(loaded["pass"], pass_pos, pass_fields),
        "kick": _rows(loaded["kick"], {}, kick_fields),
        "team": team_rows,
        "regime": _regime_map(loaded["regime"]),
        "roofs": _as_records(loaded["roof"]),
        "zeros": _as_records(loaded["zeros"]),
        "ngs": _ngs_rows(loaded["ngs"], pd),
    }


def _as_records(frame) -> list[dict[str, object]]:
    rows = []
    for record in frame.itertuples(index=False):
        row = {name: getattr(record, name) for name in frame.columns}
        rows.append(row)
    return rows


def _team_rows(off, defense, opp: dict[tuple[str, str], str]) -> list[dict[str, object]]:
    merged = off.merge(defense, on=["season", "week", "game_id", "team"], how="outer")
    rows = []
    fields = [
        "q3_epa",
        "q3_points",
        "q3_epa_allowed",
        "q3_pass",
        "q3_cmp",
        "q4_pass",
        "q4_cmp",
        "q4_deep",
        "q4_epa_dropback",
        "pass_att",
        "completions",
        "deep_comp",
        "sacks",
        "interceptions",
        "rush_att",
        "explosive_rush",
        "q4_rush_att",
        "q4_rush_yds",
        "light_box",
        "box_known",
        "def_drives_35",
        "def_fg_35",
        "drives_35",
        "fg_35",
    ]
    for record in merged.itertuples(index=False):
        game_id = str(getattr(record, "game_id"))
        team = normalize_team(str(getattr(record, "team") or ""))
        if not team:
            continue
        row: dict[str, object] = {
            "season": int(getattr(record, "season")),
            "week": int(getattr(record, "week")),
            "game_id": game_id,
            "team": team,
            "opp": opp.get((game_id, team), ""),
        }
        for field in fields:
            row[field] = _num(getattr(record, field, None))
        rows.append(row)
    rows.sort(key=lambda item: (int(item["season"]), int(item["week"]), str(item["game_id"]), str(item["team"])))
    return rows


def _regime_map(frame) -> dict[tuple[str, str], str]:
    out = {}
    for record in frame.itertuples(index=False):
        team = normalize_team(str(getattr(record, "team") or ""))
        game_id = str(getattr(record, "game_id"))
        explosive = int(_num(getattr(record, "explosive", 0)) or 0) > 0
        out[(game_id, team)] = _regime(
            _num(getattr(record, "q4_enter", None)),
            _num(getattr(record, "q3_epa", None)),
            explosive,
        )
    return out


def _ngs_rows(ngs, pd) -> list[dict[str, object]]:
    if ngs is None or len(ngs) == 0:
        return []
    rows = []
    for record in ngs.itertuples(index=False):
        source = str(getattr(record, "source", ""))
        row = {
            "season": int(getattr(record, "season")),
            "week": int(getattr(record, "week")),
            "gsis": str(getattr(record, "gsis_id")),
            "team": normalize_team(str(getattr(record, "team", "") or "")),
            "source": source,
            "sep": _num(getattr(record, "avg_separation", None)),
            "cpoe": _num(getattr(record, "completion_percentage_above_expectation", None)),
            "ryoe": _num(getattr(record, "rush_yards_over_expected_per_att", None)),
            "air": _num(getattr(record, "avg_intended_air_yards", None)),
            "cushion": _num(getattr(record, "avg_cushion", None)),
        }
        rows.append(row)
    rows.sort(key=lambda item: (int(item["season"]), int(item["week"]), str(item["gsis"]), str(item["source"])))
    del pd
    return rows


def _walk(bundles: dict[str, object]) -> tuple[list[dict[str, object]], dict[str, object]]:
    rec_rows = list(bundles["rec"])  # type: ignore[arg-type]
    rush_rows = list(bundles["rush"])  # type: ignore[arg-type]
    pass_rows = list(bundles["pass"])  # type: ignore[arg-type]
    kick_rows = list(bundles["kick"])  # type: ignore[arg-type]
    team_rows = list(bundles["team"])  # type: ignore[arg-type]
    regime = dict(bundles["regime"])  # type: ignore[arg-type]
    roofs = list(bundles["roofs"])  # type: ignore[arg-type]
    zeros = list(bundles["zeros"])  # type: ignore[arg-type]
    ngs_rows = list(bundles["ngs"])  # type: ignore[arg-type]
    weeks = sorted(
        {
            (int(row["season"]), int(row["week"]))
            for row in [*rec_rows, *rush_rows, *pass_rows, *kick_rows, *team_rows]
        }
    )
    by_week: dict[str, dict[tuple[int, int], list[dict[str, object]]]] = {
        "rec": defaultdict(list),
        "rush": defaultdict(list),
        "pass": defaultdict(list),
        "kick": defaultdict(list),
        "team": defaultdict(list),
    }
    for kind, rows in (
        ("rec", rec_rows),
        ("rush", rush_rows),
        ("pass", pass_rows),
        ("kick", kick_rows),
        ("team", team_rows),
    ):
        for row in rows:
            by_week[kind][(int(row["season"]), int(row["week"]))].append(row)
    zero_by_week = {(int(row["season"]), int(row["week"])): row for row in zeros}
    roof_by_week: dict[tuple[int, int], list[dict[str, object]]] = defaultdict(list)
    for row in roofs:
        roof_by_week[(int(row["season"]), int(row["week"]))].append(row)

    hist: dict[str, list[dict[str, object]]] = defaultdict(list)
    team_hist: dict[str, list[dict[str, object]]] = defaultdict(list)
    acc: dict[str, dict[str, _Acc]] = defaultdict(lambda: defaultdict(_Acc))
    plays: dict[str, list[float]] = defaultdict(list)
    deltas: dict[str, list[float]] = defaultdict(list)
    residuals: dict[str, dict[tuple[str, str], dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    zero_state = {"rec_n": 0, "rec_z": 0, "rush_n": 0, "rush_z": 0, "pass_n": 0, "pass_z": 0}
    roof_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    ngs_index = 0
    ngs_sum: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    cushion_games: list[tuple[str, float]] = []

    base = fair_over_prob(*(-114, -114))
    specs = {spec.market: spec for spec in cell_specs()}

    for season, week in weeks:
        league = _player_league(acc)
        views = {team: _view(rows) for team, rows in team_hist.items()}
        def_league = _defense_league(views)
        cushions = _cushion_now(cushion_games)
        for team, view in views.items():
            view["cushion_allowed"] = cushions.get(team)
        p0 = _p0(zero_state)
        ngs_index = _fold_ngs(ngs_rows, ngs_index, season, week, ngs_sum)
        ngs_mean = _ngs_means(ngs_sum)
        context = {
            "league": league,
            "views": views,
            "def_league": def_league,
            "p0": p0,
            "ngs": ngs_mean,
            "roofs": {team: _modal(counts) for team, counts in roof_counts.items()},
            "base": base,
            "specs": specs,
            "regime": regime,
            "hist": hist,
            "plays": plays,
            "deltas": deltas,
            "residuals": residuals,
            "signals": _signal_pack(hist, ngs_mean),
            "team_hist": team_hist,
        }
        _score_week(by_week["rec"][(season, week)], "rec", context)
        _score_week(by_week["rush"][(season, week)], "rush", context)
        _score_week(by_week["pass"][(season, week)], "pass", context)
        _score_week(by_week["kick"][(season, week)], "kick", context)
        _score_totals(by_week["team"][(season, week)], context)
        for row in by_week["rec"][(season, week)]:
            _remember_rec(hist, acc, plays, row)
        for row in by_week["rush"][(season, week)]:
            _remember_rush(hist, acc, plays, row)
        for row in by_week["pass"][(season, week)]:
            _remember_pass(hist, acc, plays, row)
        for row in by_week["kick"][(season, week)]:
            _remember_kick(hist, acc, row)
        for row in by_week["team"][(season, week)]:
            team_hist[str(row["team"])].append(row)
        _add_zeros(zero_state, zero_by_week.get((season, week)))
        _add_roofs(roof_counts, roof_by_week.get((season, week), []))
        _add_cushions(cushion_games, by_week["team"][(season, week)], ngs_rows, season, week)
        print(f"week {season}-{week}", file=sys.stderr)

    table = _finish_table(deltas)
    rho = _finish_rho(residuals)
    return table, rho


def _modal(counts: dict[str, int]) -> str:
    if not counts:
        return ""
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _p0(state: dict[str, int]) -> dict[str, float]:
    def share(zero_key: str, n_key: str) -> float:
        total = state[n_key]
        if total <= 0:
            return 0.0
        return state[zero_key] / total

    return {
        "p0_rec": share("rec_z", "rec_n"),
        "p0_rush": share("rush_z", "rush_n"),
        "p0_pass": share("pass_z", "pass_n"),
    }


def _add_zeros(state: dict[str, int], row: dict[str, object] | None) -> None:
    if row is None:
        return
    for key in state:
        state[key] += int(row.get(key) or 0)


def _add_roofs(counts: dict[str, dict[str, int]], rows: list[dict[str, object]]) -> None:
    for row in rows:
        team = normalize_team(str(row.get("home_team") or ""))
        roof = str(row.get("roof") or "").strip().lower()
        if team and roof and roof != "nan":
            counts[team][roof] += 1


def _fold_ngs(rows, index: int, season: int, week: int, sums: dict[str, dict[str, float]]) -> int:
    while index < len(rows):
        row = rows[index]
        if (int(row["season"]), int(row["week"])) >= (season, week):
            break
        gsis = str(row["gsis"])
        for field, count_name in (
            ("sep", "n_sep"),
            ("cpoe", "n_cpoe"),
            ("ryoe", "n_ryoe"),
            ("air", "n_air"),
        ):
            value = row.get(field)
            if value is None:
                continue
            sums[gsis][field] += float(value)
            sums[gsis][count_name] += 1.0
        index += 1
    return index


def _ngs_means(sums: dict[str, dict[str, float]]) -> dict[str, dict[str, float | None]]:
    out = {}
    for gsis, total in sums.items():
        row: dict[str, float | None] = {}
        for field, count_name in (
            ("sep", "n_sep"),
            ("cpoe", "n_cpoe"),
            ("ryoe", "n_ryoe"),
            ("air", "n_air"),
        ):
            count = total.get(count_name, 0.0)
            row[field] = (total.get(field, 0.0) / count) if count else None
        out[gsis] = row
    return out


def _cross(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 1.0
    center = sum(values) / len(values)
    scale = sample_sd(values) or 0.0
    return float(center), max(float(scale), 1e-6)


def _pooled(past: list[dict[str, object]], num_key: str, den_key: str) -> float | None:
    den = sum(float(item.get(den_key) or 0.0) for item in past)
    if den <= 0.0:
        return None
    num = sum(float(item.get(num_key) or 0.0) for item in past)
    return num / den


def _ratio_mean(past: list[dict[str, object]], num_key: str, den_key: str) -> float | None:
    values = []
    for item in past:
        den = float(item.get(den_key) or 0.0)
        if den > 0.0:
            values.append(float(item.get(num_key) or 0.0) / den)
    return _mean(values)


def _ypc_of(past: list[dict[str, object]], yards_key: str, count_key: str) -> float | None:
    values = []
    for item in past:
        count = float(item.get(count_key) or 0.0)
        if count > 0.0 and item.get(yards_key) is not None:
            values.append(float(item[yards_key]) / count)
    return _mean(values)


def _eligible(hist: dict[str, list[dict[str, object]]], kind: str):
    suffix = ":" + kind
    for key, past in hist.items():
        if key.endswith(suffix) and len(past) >= MIN_GAMES:
            yield key[: -len(suffix)], past


def _signal_pack(hist, ngs_mean) -> dict[str, tuple[float, float]]:
    """League centers that match the live snapshot cross-section.

    A player enters when the prior game count is at least 4. NGS values
    are not shrunk before the league mean. Yards-per-event means use only
    games that had an event.
    """

    buckets: dict[str, list[float]] = defaultdict(list)
    for gsis, past in _eligible(hist, "rec"):
        share3 = _ratio_mean(past, "q3_targets", "team_q3_targets")
        share4 = _ratio_mean(past, "q4_targets", "team_q4_targets")
        ypc3 = _ypc_of(past, "q3_rec_yds", "q3_receptions")
        ypc4 = _ypc_of(past, "q4_rec_yds", "q4_receptions")
        deep = _pooled(past, "deep_targets", "targets")
        if share3 is not None:
            buckets["q3_share"].append(share3)
        if share4 is not None:
            buckets["q4_share"].append(share4)
        if ypc3 is not None:
            buckets["q3_ypc"].append(ypc3)
        if ypc4 is not None:
            buckets["q4_ypc"].append(ypc4)
        if deep is not None:
            buckets["deep"].append(deep)
        sep = ngs_mean.get(gsis, {}).get("sep")
        if sep is not None:
            buckets["sep"].append(float(sep))
    for gsis, past in _eligible(hist, "rush"):
        ypc = _ypc_of(past, "q4_rush_yds", "q4_rush_att")
        rate = _pooled(past, "breakaways", "rush_att")
        if ypc is not None:
            buckets["q4_rypc"].append(ypc)
        if rate is not None:
            buckets["breakaway"].append(rate)
        ryoe = ngs_mean.get(gsis, {}).get("ryoe")
        if ryoe is not None:
            buckets["ryoe"].append(float(ryoe))
    for gsis, past in _eligible(hist, "pass"):
        ypc = _ypc_of(past, "q4_pass_yds", "q4_pass_cmp")
        worthy = _pooled(past, "worthy", "worthy_n")
        if ypc is not None:
            buckets["q4_pypc"].append(ypc)
        if worthy is not None:
            buckets["worthy"].append(worthy)
        row = ngs_mean.get(gsis, {})
        if row.get("air") is not None:
            buckets["air"].append(float(row["air"]))
        if row.get("cpoe") is not None:
            buckets["cpoe"].append(float(row["cpoe"]))
    names = (
        "q3_share",
        "q4_share",
        "q3_ypc",
        "q4_ypc",
        "q4_rypc",
        "q4_pypc",
        "deep",
        "breakaway",
        "worthy",
        "sep",
        "ryoe",
        "air",
        "cpoe",
    )
    return {name: _cross(buckets[name]) for name in names}


def _cushion_now(games: list[tuple[str, float]]) -> dict[str, float]:
    sums: dict[str, list[float]] = defaultdict(list)
    for team, value in games:
        sums[team].append(value)
    return {team: sum(values) / len(values) for team, values in sums.items() if values}


def _add_cushions(store, team_rows, ngs_rows, season: int, week: int) -> None:
    cushions = {}
    for row in ngs_rows:
        if int(row["season"]) == season and int(row["week"]) == week and row.get("source") == "ngs_receiving":
            if row.get("cushion") is not None and row.get("team"):
                cushions[str(row["team"])] = float(row["cushion"])
    for row in team_rows:
        offense = str(row["team"])
        defense = str(row["opp"])
        if offense in cushions and defense:
            store.append((defense, cushions[offense]))


def _player_league(acc: dict[str, dict[str, _Acc]]) -> dict[str, tuple[float, float]]:
    fields = [
        "q3_rec",
        "q3_share",
        "q3_ypc",
        "q4_rec",
        "q4_share",
        "q4_ypc",
        "q4_rush",
        "q4_rypc",
        "q4_cmp",
        "q4_pypc",
        "receptions",
        "rec_yds",
        "rush_att",
        "pass_att",
        "pass_cmp",
        "interceptions",
        "fg",
        "kick_pts",
        "deep",
        "targets",
        "q3_yds",
        "q4_yds",
        "q4_rush_yds",
        "q4_pass_yds",
        "rush_yds",
        "pass_yds",
    ]
    out = {}
    for field in fields:
        out[field] = _league([bucket[field] for bucket in acc.values() if bucket[field].n])
    return out


def _view(rows: list[dict[str, object]]) -> dict[str, object]:
    def pool(num_key: str, den_key: str) -> float | None:
        num = 0.0
        den = 0.0
        for row in rows:
            den += float(row.get(den_key) or 0.0)
            num += float(row.get(num_key) or 0.0)
        if den <= 0:
            return None
        return num / den

    points = [float(row["q3_points"]) for row in rows if row.get("q3_points") is not None]
    return {
        "n_games": len(rows),
        "q3_epa_off": _mean([float(row["q3_epa"]) for row in rows if row.get("q3_epa") is not None]),
        "q3_epa_allowed": _mean(
            [float(row["q3_epa_allowed"]) for row in rows if row.get("q3_epa_allowed") is not None]
        ),
        "q3_points": _mean(points),
        "q3_points_sd": _sd(points),
        "q3_completion_allowed": pool("q3_cmp", "q3_pass"),
        "q4_completion_allowed": pool("q4_cmp", "q4_pass"),
        "q4_explosive_pass_allowed": pool("q4_deep", "q4_pass"),
        "q4_epa_dropback_allowed": _mean(
            [float(row["q4_epa_dropback"]) for row in rows if row.get("q4_epa_dropback") is not None]
        ),
        "explosive_rush_allowed": pool("explosive_rush", "rush_att"),
        "q4_rush_ypc_allowed": pool("q4_rush_yds", "q4_rush_att"),
        "deep_comp_allowed": pool("deep_comp", "pass_att"),
        "sack_rate": pool("sacks", "pass_att"),
        "completion_allowed": pool("completions", "pass_att"),
        "int_rate": pool("interceptions", "pass_att"),
        "light_box_rate": pool("light_box", "box_known"),
        "fg_forced_rate": pool("def_fg_35", "def_drives_35"),
        "stall_rate": pool("fg_35", "drives_35"),
    }


def _defense_league(views: dict[str, dict[str, object]]) -> dict[str, tuple[float, float]]:
    fields = [
        "q3_epa_off",
        "q3_epa_allowed",
        "q3_points",
        "q3_completion_allowed",
        "q4_completion_allowed",
        "q4_explosive_pass_allowed",
        "q4_epa_dropback_allowed",
        "explosive_rush_allowed",
        "q4_rush_ypc_allowed",
        "deep_comp_allowed",
        "sack_rate",
        "completion_allowed",
        "int_rate",
        "light_box_rate",
        "fg_forced_rate",
        "stall_rate",
        "cushion_allowed",
    ]
    out = {}
    eligible = [view for view in views.values() if int(view["n_games"]) >= MIN_GAMES]
    for field in fields:
        values = [float(view[field]) for view in eligible if view.get(field) is not None]
        if not values:
            out[field] = (0.0, 1.0)
            continue
        center = sum(values) / len(values)
        scale = sample_sd(values) or 0.0
        out[field] = (float(center), max(float(scale), 1e-6))
    return out


def _score_week(rows: list[dict[str, object]], kind: str, context: dict[str, object]) -> None:
    hist = context["hist"]
    assert isinstance(hist, dict)
    for row in rows:
        past = hist[str(row["gsis"]) + ":" + kind]
        if len(past) < MIN_GAMES:
            continue
        if kind == "rec":
            _price_rec(row, past, context)
        elif kind == "rush":
            _price_rush(row, past, context)
        elif kind == "pass":
            _price_pass(row, past, context)
        else:
            _price_kick(row, past, context)


def _defense(row: dict[str, object], context: dict[str, object], *fields: str):
    views = context["views"]
    assert isinstance(views, dict)
    view = views.get(str(row["opp"]))
    if view is None or int(view["n_games"]) < MIN_GAMES:
        return None
    for field in fields:
        if view.get(field) is None:
            return None
    return view


def _record(
    context: dict[str, object],
    row: dict[str, object],
    market: str,
    prob_at,
    actual: float,
    history: list[float],
) -> None:
    lines = _lines(market, history)
    if not lines:
        return
    deltas = context["deltas"]
    residuals = context["residuals"]
    regime = context["regime"]
    base = float(context["base"])
    assert isinstance(deltas, dict)
    assert isinstance(residuals, dict)
    assert isinstance(regime, dict)
    parts = []
    residual = None
    for line in lines:
        prob = prob_at(line)
        if prob is None or not math.isfinite(prob):
            continue
        prob = min(1.0, max(0.0, float(prob)))
        outcome = 1.0 if actual > line else 0.0
        parts.append(_brier_delta(prob, outcome, base))
        if not (market in HURDLE_LINE_MARKETS and abs(line - 0.5) < 1e-9):
            residual = outcome - prob
    if residual is None and parts:
        prob = prob_at(0.5)
        if prob is not None and math.isfinite(prob):
            outcome = 1.0 if actual > 0.5 else 0.0
            residual = outcome - min(1.0, max(0.0, float(prob)))
    if not parts:
        return
    deltas[market].append(sum(parts) / len(parts))
    if residual is None or not math.isfinite(residual):
        return
    label = regime.get((str(row["game_id"]), str(row["team"])), "neutral")
    key = (str(row["gsis"]), str(row["game_id"]))
    residuals[label][key][market] = float(residual)


def _hist_lambda(n_games: int, full_mean: float | None, opps_q: float, opps_total: float, def_rate, league_rate) -> float | None:
    """Full-game volume times the quarter share. No book price. No referee."""

    if full_mean is None:
        return None
    volume = baseline_volume(n_games, full_mean)
    if volume is None:
        return None
    quarter = max(0.0, float(opps_q or 0.0))
    total = float(opps_total or 0.0)
    if total <= 0.0 and quarter > 0.0:
        total = quarter / 0.25
    try:
        rate = float(def_rate)
        league = float(league_rate)
    except (TypeError, ValueError):
        return None
    factor = defense_multiplier(rate, league, epa=False)
    return split_lambda(volume, quarter, total, factor, 1.0)


def _price_rec(row, past, context) -> None:
    ngs = context["ngs"].get(str(row["gsis"]), {})
    p0 = float(context["p0"]["p0_rec"])
    n = len(past)
    q3_yds = [float(item["q3_rec_yds"] or 0.0) for item in past]
    q3_tgt = sum(float(item["q3_targets"] or 0.0) for item in past)
    q3_ypc = [
        float(item["q3_rec_yds"]) / float(item["q3_receptions"])
        for item in past
        if float(item["q3_receptions"] or 0.0) > 0 and item.get("q3_rec_yds") is not None
    ]
    q4_rec = [float(item["q4_receptions"] or 0.0) for item in past]
    q4_yds = [float(item["q4_rec_yds"] or 0.0) for item in past]
    q4_tgt = sum(float(item["q4_targets"] or 0.0) for item in past)
    q4_ypc = [
        float(item["q4_rec_yds"]) / float(item["q4_receptions"])
        for item in past
        if float(item["q4_receptions"] or 0.0) > 0 and item.get("q4_rec_yds") is not None
    ]
    receptions = [float(item["receptions"] or 0.0) for item in past]
    rec_yds = [float(item["rec_yds"] or 0.0) for item in past]
    longs = [float(item["rec_long"] or 0.0) for item in past]
    targets = [float(item["targets"] or 0.0) for item in past]
    deep = []
    deep_n = sum(float(item["deep_targets"] or 0.0) for item in past)
    target_n = sum(targets)
    deep_rate = (deep_n / target_n) if target_n else None
    if deep_rate is not None:
        deep.append(deep_rate)

    def hurdle(opp_sum, ypc_hist, def_field, ypc_def, actual, market):
        if not ypc_hist:
            return
        view = _defense(row, context, def_field)
        if view is None:
            return
        def_center, _def_scale = context["def_league"][def_field]
        ypc_key = "q3_ypc" if "q3" in market else "q4_ypc"
        ypc_center = context["signals"][ypc_key][0]
        tilt = _ypc_tilt(
            ngs.get("sep"),
            view.get(ypc_def),
            context["signals"]["sep"],
            context["def_league"][ypc_def],
            context["specs"][market].clip,
        )
        ypc_sd = _sd(ypc_hist) or YPC_SD_FLOOR
        lam = _hist_lambda(n, _mean(receptions), opp_sum, target_n, view[def_field], def_center)

        def prob_at(line: float) -> float | None:
            if lam is None or lam < 0:
                return None
            mu = shrunk(n, _mean(ypc_hist) or 0.0, ypc_center) * (1.0 + tilt)
            alpha, rate = gamma_shape_rate(mu, ypc_sd)
            try:
                return hurdle_over_prob(lam, alpha, rate, line, 1.0 - p0)
            except ValueError:
                return None

        _record(context, row, market, prob_at, actual, q3_yds if "q3" in market else q4_yds)

    if q3_ypc:
        hurdle(q3_tgt, q3_ypc, "q3_completion_allowed", "q3_epa_allowed", float(row.get("q3_rec_yds") or 0.0), "rec_yds_q3")
    if q4_ypc:
        hurdle(q4_tgt, q4_ypc, "q4_completion_allowed", "q4_explosive_pass_allowed", float(row.get("q4_rec_yds") or 0.0), "rec_yds_q4")
    _price_count(
        context, row, "receptions_q4", q4_rec, _mean(receptions), q4_tgt, target_n,
        "q4_completion_allowed", float(row.get("q4_receptions") or 0.0), n,
    )
    _price_tail(
        context, row, "rec_longest", past, longs, deep_rate, context["signals"]["deep"],
        "deep_comp_allowed", "cushion_allowed", float(row.get("rec_long") or 0.0),
        _mean(receptions), "receptions", n,
    )
    _price_marginal_yards(context, row, "rec_yds", rec_yds, float(row.get("rec_yds") or 0.0), n, "rec_yds")
    _price_marginal_count(context, row, "receptions", receptions, float(row.get("receptions") or 0.0), n, "receptions")


def _ypc_tilt(player_value, defense_value, player_league, defense_league, clip: float) -> float:
    """Match the live tilt. NGS is z-scored raw. A missing side is zero."""

    if player_value is None or defense_value is None:
        return 0.0
    try:
        player_z = z_score(float(player_value), player_league[0], player_league[1])
        defense_z = z_score(float(defense_value), defense_league[0], defense_league[1])
    except ValueError:
        return 0.0
    return interaction(player_z, defense_z, clip)


def _price_count(context, row, market, hist_values, full_mean, opps_q, opps_total, def_field, actual, n):
    view = _defense(row, context, def_field)
    if view is None:
        return
    def_center = context["def_league"][def_field][0]
    lam = _hist_lambda(n, full_mean, opps_q, opps_total, view[def_field], def_center)

    def prob_at(line: float) -> float | None:
        if lam is None or lam <= 0:
            return None
        try:
            return poisson_over_prob(lam, line)
        except ValueError:
            return None

    _record(context, row, market, prob_at, actual, hist_values)


def _price_tail(context, row, market, past, longest, rate, rate_league, def_field, require_field, actual, touches, touch_field, n):
    if rate is None:
        return
    view = _defense(row, context, def_field, require_field)
    if view is None:
        return
    plays = context["plays"]
    assert isinstance(plays, dict)
    positive = list(plays.get(str(row["gsis"]) + ":" + market, []))
    fitted = weibull_fit(positive)
    if fitted is None:
        return
    league = context["league"]
    touch_center, _touch_scale = league[touch_field]
    if touches is None:
        return
    shrunk_touches = shrunk(n, float(touches), touch_center)
    if shrunk_touches <= 0:
        return
    rate_center, rate_scale = rate_league
    def_center, def_scale = context["def_league"][def_field]
    try:
        adj = interaction(
            _shrunk_z(float(rate), n, rate_center, rate_scale),
            _shrunk_z(float(view[def_field]), int(view["n_games"]), def_center, def_scale),
            context["specs"][market].clip,
        )
    except ValueError:
        return
    shape, scale = fitted

    def prob_at(line: float) -> float | None:
        return tail_over_prob(shape, scale, line, shrunk_touches, adj)

    _record(context, row, market, prob_at, actual, longest)
    del past


def _price_marginal_yards(context, row, market, hist_values, actual, n, field) -> None:
    center, _scale = context["league"][field]
    raw = _mean(hist_values)
    if raw is None:
        return
    mean = shrunk(n, raw, center)
    sd = max(sigma_floor("yards", max(mean, 1.0)), _sd(hist_values) or 0.0)

    def prob_at(line: float) -> float | None:
        return normal_over_prob(line, mean, sd)

    _record(context, row, market, prob_at, actual, hist_values)


def _price_marginal_count(context, row, market, hist_values, actual, n, field) -> None:
    center, _scale = context["league"][field]
    raw = _mean(hist_values)
    if raw is None:
        return
    mean = shrunk(n, raw, center)
    if mean <= 0:
        return

    def prob_at(line: float) -> float | None:
        try:
            return poisson_over_prob(mean, line)
        except ValueError:
            return None

    _record(context, row, market, prob_at, actual, hist_values)


def _price_rush(row, past, context) -> None:
    ngs = context["ngs"].get(str(row["gsis"]), {})
    p0 = float(context["p0"]["p0_rush"])
    n = len(past)
    atts = [float(item["q4_rush_att"] or 0.0) for item in past]
    yards = [float(item["q4_rush_yds"] or 0.0) for item in past]
    full_atts = [float(item["rush_att"] or 0.0) for item in past]
    n_opp = sum(atts)
    ypc = [
        float(item["q4_rush_yds"]) / float(item["q4_rush_att"])
        for item in past
        if float(item["q4_rush_att"] or 0.0) > 0 and item.get("q4_rush_yds") is not None
    ]
    if ypc:
        view = _defense(row, context, "q4_rush_ypc_allowed")
        if view is not None:
            def_center = context["def_league"]["q4_rush_ypc_allowed"][0]
            ypc_center = context["signals"]["q4_rypc"][0]
            tilt = _ypc_tilt(
                ngs.get("ryoe"),
                view.get("explosive_rush_allowed"),
                context["signals"]["ryoe"],
                context["def_league"]["explosive_rush_allowed"],
                context["specs"]["rush_yds_q4"].clip,
            )
            ypc_sd = _sd(ypc) or YPC_SD_FLOOR
            lam = _hist_lambda(n, _mean(full_atts), n_opp, sum(full_atts), view["q4_rush_ypc_allowed"], def_center)

            def prob_at(line: float) -> float | None:
                if lam is None or lam < 0:
                    return None
                mu = shrunk(n, _mean(ypc) or 0.0, ypc_center) * (1.0 + tilt)
                alpha, rate = gamma_shape_rate(mu, ypc_sd)
                try:
                    return hurdle_over_prob(lam, alpha, rate, line, 1.0 - p0)
                except ValueError:
                    return None

            _record(context, row, "rush_yds_q4", prob_at, float(row.get("q4_rush_yds") or 0.0), yards)
    rush_att = full_atts
    rush_yds = [float(item["rush_yds"] or 0.0) for item in past]
    _price_marginal_yards(context, row, "rush_yds", rush_yds, float(row.get("rush_yds") or 0.0), n, "rush_yds")
    _price_marginal_count(context, row, "rush_att", rush_att, float(row.get("rush_att") or 0.0), n, "rush_att")
    _price_tail(
        context, row, "rush_longest", past,
        [float(item["rush_long"] or 0.0) for item in past],
        _pooled(past, "breakaways", "rush_att"),
        context["signals"]["breakaway"],
        "explosive_rush_allowed",
        "light_box_rate",
        float(row.get("rush_long") or 0.0),
        _mean(rush_att),
        "rush_att",
        n,
    )


def _price_pass(row, past, context) -> None:
    ngs = context["ngs"].get(str(row["gsis"]), {})
    p0 = float(context["p0"]["p0_pass"])
    n = len(past)
    yards = [float(item["q4_pass_yds"] or 0.0) for item in past]
    full_cmps = [float(item["pass_cmp"] or 0.0) for item in past]
    full_atts = [float(item["pass_att"] or 0.0) for item in past]
    n_opp = sum(float(item["q4_pass_att"] or 0.0) for item in past)
    ypc = [
        float(item["q4_pass_yds"]) / float(item["q4_pass_cmp"])
        for item in past
        if float(item["q4_pass_cmp"] or 0.0) > 0 and item.get("q4_pass_yds") is not None
    ]
    if ypc:
        view = _defense(row, context, "q4_completion_allowed")
        if view is not None:
            def_center = context["def_league"]["q4_completion_allowed"][0]
            tilt = _ypc_tilt(
                ngs.get("air"),
                view.get("q4_epa_dropback_allowed"),
                context["signals"]["air"],
                context["def_league"]["q4_epa_dropback_allowed"],
                context["specs"]["pass_yds_q4"].clip,
            )
            ypc_center = context["signals"]["q4_pypc"][0]
            ypc_sd = _sd(ypc) or YPC_SD_FLOOR
            lam = _hist_lambda(
                n, _mean(full_cmps), n_opp, sum(full_atts), view["q4_completion_allowed"], def_center
            )

            def prob_at(line: float) -> float | None:
                if lam is None or lam < 0:
                    return None
                mu = shrunk(n, _mean(ypc) or 0.0, ypc_center) * (1.0 + tilt)
                alpha, rate = gamma_shape_rate(mu, ypc_sd)
                try:
                    return hurdle_over_prob(lam, alpha, rate, line, 1.0 - p0)
                except ValueError:
                    return None

            _record(context, row, "pass_yds_q4", prob_at, float(row.get("q4_pass_yds") or 0.0), yards)
    att = full_atts
    cmp_ = full_cmps
    ints = [float(item["interceptions"] or 0.0) for item in past]
    yards_all = [float(item["pass_yds"] or 0.0) for item in past]
    _price_volume(context, row, "pass_attempts", att, "pass_att", "completion_allowed", "sack_rate", float(row.get("pass_att") or 0.0), n, ngs)
    _price_volume(context, row, "pass_completions", cmp_, "pass_cmp", "completion_allowed", "sack_rate", float(row.get("pass_cmp") or 0.0), n, ngs)
    _price_interceptions(context, row, past, ints, float(row.get("interceptions") or 0.0), n)
    _price_marginal_count(context, row, "pass_att", att, float(row.get("pass_att") or 0.0), n, "pass_att")
    _price_marginal_yards(context, row, "pass_yds", yards_all, float(row.get("pass_yds") or 0.0), n, "pass_yds")
    _price_tail(
        context, row, "pass_longest", past,
        [float(item["pass_long"] or 0.0) for item in past],
        ngs.get("air"),
        context["signals"]["air"],
        "deep_comp_allowed",
        "cushion_allowed",
        float(row.get("pass_long") or 0.0),
        _mean(cmp_),
        "pass_cmp",
        n,
    )


def _price_volume(context, row, market, hist_values, field, def_field, require_field, actual, n, ngs):
    """Poisson volume. The player signal is shrunk CPOE, matching live."""

    view = _defense(row, context, def_field, require_field)
    if view is None:
        return
    raw = _mean(hist_values)
    player_value = ngs.get("cpoe")
    if raw is None or player_value is None:
        return
    center, scale = context["signals"]["cpoe"]
    try:
        player_z = _shrunk_z(float(player_value), n, center, scale)
        def_center, def_scale = context["def_league"][def_field]
        adj = interaction(
            player_z,
            _shrunk_z(float(view[def_field]), int(view["n_games"]), def_center, def_scale),
            context["specs"][market].clip,
        )
    except ValueError:
        return
    mean = shrunk(n, raw, context["league"][field][0]) * (1.0 + adj)
    if mean <= 0:
        return

    def prob_at(line: float) -> float | None:
        try:
            return poisson_over_prob(mean, line)
        except ValueError:
            return None

    _record(context, row, market, prob_at, actual, hist_values)


def _price_interceptions(context, row, past, hist_values, actual, n) -> None:
    """The signal is the interception-worthy rate. The base is the count."""

    view = _defense(row, context, "int_rate", "sack_rate")
    worthy = _pooled(past, "worthy", "worthy_n")
    raw = _mean(hist_values)
    if view is None or worthy is None or raw is None:
        return
    try:
        player_z = _shrunk_z(worthy, n, *context["signals"]["worthy"])
        defense_z = _shrunk_z(
            float(view["int_rate"]),
            int(view["n_games"]),
            *context["def_league"]["int_rate"],
        )
        adj = interaction(player_z, defense_z, context["specs"]["interceptions"].clip)
    except ValueError:
        return
    mean = shrunk(n, raw, context["league"]["interceptions"][0]) * (1.0 + adj)
    if mean <= 0:
        return

    def prob_at(line: float) -> float | None:
        try:
            return poisson_over_prob(mean, line)
        except ValueError:
            return None

    _record(context, row, "interceptions", prob_at, actual, hist_values)


def _price_kick(row, past, context) -> None:
    roofs = context["roofs"]
    assert isinstance(roofs, dict)
    left = roofs.get(str(row["team"]), "")
    right = roofs.get(str(row["opp"]), "")
    if left not in DOME or right not in DOME:
        return
    view = _defense(row, context, "fg_forced_rate")
    offense = context["views"].get(str(row["team"]))
    stall = None if offense is None else offense.get("stall_rate")
    if view is None or offense is None or stall is None or int(offense["n_games"]) < MIN_GAMES:
        return
    n = len(past)
    try:
        adj = interaction(
            _shrunk_z(float(stall), int(offense["n_games"]), *context["def_league"]["stall_rate"]),
            _shrunk_z(float(view["fg_forced_rate"]), int(view["n_games"]), *context["def_league"]["fg_forced_rate"]),
            context["specs"]["field_goals"].clip,
        )
    except ValueError:
        return
    fg = [float(item["fg_made"] or 0.0) for item in past]
    points = [float(item["kicking_points"] or 0.0) for item in past]
    raw_fg = _mean(fg)
    if raw_fg is not None:
        mean_fg = shrunk(n, raw_fg, context["league"]["fg"][0]) * (1.0 + adj)
        if mean_fg > 0:
            def prob_fg(line: float, mean_fg=mean_fg) -> float | None:
                try:
                    return poisson_over_prob(mean_fg, line)
                except ValueError:
                    return None

            _record(context, row, "field_goals", prob_fg, float(row.get("fg_made") or 0.0), fg)
    raw = _mean(points)
    if raw is None:
        return
    mean = shrunk(n, raw, context["league"]["kick_pts"][0]) * (1.0 + adj)
    if mean <= 0:
        return
    sd = max(sigma_floor("points", max(abs(mean), 1.0)), _sd(points) or 0.0)

    def prob_at(line: float, mean=mean, sd=sd) -> float | None:
        return normal_over_prob(line, mean, sd)

    _record(context, row, "kicking_points", prob_at, float(row.get("kicking_points") or 0.0), points)


def _score_totals(rows: list[dict[str, object]], context: dict[str, object]) -> None:
    by_game: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_game[str(row["game_id"])].append(row)
    views = context["views"]
    assert isinstance(views, dict)
    league = context["def_league"]
    for game_id, sides in sorted(by_game.items()):
        if len(sides) != 2:
            continue
        left, right = sides
        lv = views.get(str(left["team"]))
        rv = views.get(str(right["team"]))
        if lv is None or rv is None:
            continue
        if int(lv["n_games"]) < MIN_GAMES or int(rv["n_games"]) < MIN_GAMES:
            continue
        if lv.get("q3_points") is None or rv.get("q3_points") is None:
            continue
        if lv.get("q3_epa_off") is None or rv.get("q3_epa_off") is None:
            continue
        if rv.get("q3_epa_allowed") is None or lv.get("q3_epa_allowed") is None:
            continue
        parts = []
        sigmas = []
        for offense, defense in ((lv, rv), (rv, lv)):
            off_c, off_s = league["q3_epa_off"]
            def_c, def_s = league["q3_epa_allowed"]
            adj = interaction(
                _shrunk_z(float(offense["q3_epa_off"]), int(offense["n_games"]), off_c, off_s),
                _shrunk_z(float(defense["q3_epa_allowed"]), int(defense["n_games"]), def_c, def_s),
                context["specs"]["total_q3"].clip,
            )
            point_center = league["q3_points"][0]
            part = shrunk(int(offense["n_games"]), float(offense["q3_points"]), point_center) * (1.0 + adj)
            parts.append(part)
            sigmas.append(float(offense.get("q3_points_sd") or sigma_floor("points", 10.0)))
        mean = parts[0] + parts[1]
        if mean <= 0:
            continue
        sigma = max(sigma_floor("points", mean), math.hypot(sigmas[0], sigmas[1]))
        actual = float(left.get("q3_points") or 0.0) + float(right.get("q3_points") or 0.0)
        team_hist = context["team_hist"]
        assert isinstance(team_hist, dict)
        left_pts = [float(item["q3_points"]) for item in team_hist[str(left["team"])] if item.get("q3_points") is not None]
        right_pts = [float(item["q3_points"]) for item in team_hist[str(right["team"])] if item.get("q3_points") is not None]
        if len(left_pts) < MIN_GAMES or len(right_pts) < MIN_GAMES:
            continue
        left_med = _median(left_pts)
        right_med = _median(right_pts)
        if left_med is None or right_med is None:
            continue
        hist_line = left_med + right_med
        if hist_line <= 0.5:
            continue

        def prob_at(line: float, mean=mean, sigma=sigma) -> float:
            return normal_over_prob(line, mean, sigma)

        fake = {
            "game_id": game_id,
            "team": str(left["team"]),
            "gsis": game_id,
            "opp": str(right["team"]),
        }
        _record(context, fake, "total_q3", prob_at, actual, [hist_line])


def _remember_rec(hist, acc, plays, row) -> None:
    bucket = hist[str(row["gsis"]) + ":rec"]
    bucket.append(row)
    store = acc[str(row["gsis"])]
    store["q3_rec"].add(float(row.get("q3_receptions") or 0.0))
    store["q4_rec"].add(float(row.get("q4_receptions") or 0.0))
    store["receptions"].add(float(row.get("receptions") or 0.0))
    store["rec_yds"].add(float(row.get("rec_yds") or 0.0))
    store["q3_yds"].add(float(row.get("q3_rec_yds") or 0.0))
    store["q4_yds"].add(float(row.get("q4_rec_yds") or 0.0))
    store["targets"].add(float(row.get("targets") or 0.0))
    if float(row.get("q3_receptions") or 0.0) > 0 and row.get("q3_rec_yds") is not None:
        store["q3_ypc"].add(float(row["q3_rec_yds"]) / float(row["q3_receptions"]))
    if float(row.get("q4_receptions") or 0.0) > 0 and row.get("q4_rec_yds") is not None:
        store["q4_ypc"].add(float(row["q4_rec_yds"]) / float(row["q4_receptions"]))
    denom3 = float(row.get("team_q3_targets") or 0.0)
    if denom3 > 0:
        store["q3_share"].add(float(row.get("q3_targets") or 0.0) / denom3)
    denom4 = float(row.get("team_q4_targets") or 0.0)
    if denom4 > 0:
        store["q4_share"].add(float(row.get("q4_targets") or 0.0) / denom4)
    target_n = float(row.get("targets") or 0.0)
    if target_n > 0:
        store["deep"].add(float(row.get("deep_targets") or 0.0) / target_n)
    plays[str(row["gsis"]) + ":rec_longest"].extend(float(play) for play in row.get("plays") or [])


def _remember_rush(hist, acc, plays, row) -> None:
    hist[str(row["gsis"]) + ":rush"].append(row)
    store = acc[str(row["gsis"])]
    store["q4_rush"].add(float(row.get("q4_rush_att") or 0.0))
    store["q4_rush_yds"].add(float(row.get("q4_rush_yds") or 0.0))
    store["rush_att"].add(float(row.get("rush_att") or 0.0))
    store["rush_yds"].add(float(row.get("rush_yds") or 0.0))
    if float(row.get("q4_rush_att") or 0.0) > 0 and row.get("q4_rush_yds") is not None:
        store["q4_rypc"].add(float(row["q4_rush_yds"]) / float(row["q4_rush_att"]))
    plays[str(row["gsis"]) + ":rush_longest"].extend(float(play) for play in row.get("plays") or [])


def _remember_pass(hist, acc, plays, row) -> None:
    hist[str(row["gsis"]) + ":pass"].append(row)
    store = acc[str(row["gsis"])]
    store["q4_cmp"].add(float(row.get("q4_pass_cmp") or 0.0))
    store["q4_pass_yds"].add(float(row.get("q4_pass_yds") or 0.0))
    store["pass_att"].add(float(row.get("pass_att") or 0.0))
    store["pass_cmp"].add(float(row.get("pass_cmp") or 0.0))
    store["pass_yds"].add(float(row.get("pass_yds") or 0.0))
    store["interceptions"].add(float(row.get("interceptions") or 0.0))
    if float(row.get("q4_pass_cmp") or 0.0) > 0 and row.get("q4_pass_yds") is not None:
        store["q4_pypc"].add(float(row["q4_pass_yds"]) / float(row["q4_pass_cmp"]))
    plays[str(row["gsis"]) + ":pass_longest"].extend(float(play) for play in row.get("plays") or [])


def _remember_kick(hist, acc, row) -> None:
    hist[str(row["gsis"]) + ":kick"].append(row)
    store = acc[str(row["gsis"])]
    store["fg"].add(float(row.get("fg_made") or 0.0))
    store["kick_pts"].add(float(row.get("kicking_points") or 0.0))


def _fmt(value: object) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return f"{value:.6f}"
    return str(value)


def _finish_table(deltas: dict[str, list[float]]) -> list[dict[str, object]]:
    rows = []
    family = []
    for market in MARKET_ORDER:
        values = deltas.get(market, [])
        n_hist = len(values)
        row: dict[str, object] = {
            "market": market,
            "n_hist": n_hist,
            "delta_brier": "",
            "hist_ci_low": "",
            "hist_ci_high": "",
            "boot_p": "",
            "hist_q": "",
            "verdict": "",
            "reason": "",
        }
        if n_hist >= 2:
            seed = HIST_SEED[market]
            mean = sum(values) / n_hist
            low, high = bootstrap_ci(values, random.Random(seed), N_BOOT)
            p_value = one_sided_p(values, random.Random(seed + 17), N_BOOT)
            row["delta_brier"] = mean
            row["hist_ci_low"] = low
            row["hist_ci_high"] = high
            row["boot_p"] = p_value
            if n_hist >= MIN_HIST:
                family.append(row)
        elif n_hist == 1:
            row["delta_brier"] = values[0]
            row["hist_ci_low"] = values[0]
            row["hist_ci_high"] = values[0]
            row["boot_p"] = 1.0
        rows.append(row)
    q_values = bh_qvalues([float(row["boot_p"]) for row in family])
    for row, q_value in zip(family, q_values, strict=True):
        row["hist_q"] = q_value
    for row in rows:
        q_value = None if row["hist_q"] == "" else float(row["hist_q"])
        delta = 0.0 if row["delta_brier"] == "" else float(row["delta_brier"])
        ci_low = 0.0 if row["hist_ci_low"] == "" else float(row["hist_ci_low"])
        verdict, reason = hist_verdict(
            n_hist=int(row["n_hist"]),
            delta_brier=delta,
            ci_low=ci_low,
            q_value=q_value,
        )
        row["verdict"] = verdict
        row["reason"] = reason
    return rows


def _finish_rho(residuals: dict[str, dict[tuple[str, str], dict[str, float]]]) -> dict[str, object]:
    names = [*MARKET_ORDER, *FULL_GAME]
    index = {name: pos for pos, name in enumerate(names)}
    regimes_out = {}
    for regime in ("q3_opening_surge", "q4_trailing_comeback", "explosive_light_box", "neutral"):
        groups = residuals.get(regime, {})
        pair_values: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
        for markets in groups.values():
            keys = sorted(markets)
            for left_i, left in enumerate(keys):
                for right in keys[left_i + 1 :]:
                    if left not in index or right not in index:
                        continue
                    pair_values[tuple(sorted((left, right)))].append((markets[left], markets[right]))
        matrix = np.eye(len(names), dtype=float)
        counts: dict[tuple[str, str], int] = {}
        for pair, samples in pair_values.items():
            if len(samples) < MIN_PAIRS:
                continue
            rho = _pearson([item[0] for item in samples], [item[1] for item in samples])
            if rho is None:
                continue
            i = index[pair[0]]
            j = index[pair[1]]
            matrix[i, j] = matrix[j, i] = rho
            counts[pair] = len(samples)
        matrix = np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0)
        np.fill_diagonal(matrix, 1.0)
        clean = nearest_correlation(matrix, eigenvalue_floor=1e-6)
        clean = np.nan_to_num(clean, nan=0.0, posinf=0.0, neginf=0.0)
        np.fill_diagonal(clean, 1.0)
        pairs = []
        matchup = set(MARKET_ORDER)
        for i, left in enumerate(names):
            for j in range(i + 1, len(names)):
                right = names[j]
                if left not in matchup and right not in matchup:
                    continue
                key = tuple(sorted((left, right)))
                rho = float(clean[i, j])
                if not math.isfinite(rho):
                    rho = 0.0
                pairs.append(
                    {
                        "stat_a": key[0],
                        "stat_b": key[1],
                        "rho": round(rho, 6),
                        "n": int(counts.get(key, 0)),
                        "source": "empirical" if counts.get(key, 0) >= MIN_PAIRS else "psd_fill",
                    }
                )
        pairs.sort(key=lambda item: (item["stat_a"], item["stat_b"]))
        regimes_out[regime] = {"pairs": pairs}
    return {
        "absent_2022": True,
        "eigenvalue_floor": 1e-6,
        "min_pairs": MIN_PAIRS,
        "explosive_rule": "15yd_and_box_le_6_else_20yd",
        "same_player_only": True,
        "regimes": regimes_out,
    }


def _pearson(left: list[float], right: list[float]) -> float | None:
    n = len(left)
    if n < 2 or n != len(right):
        return None
    mean_l = sum(left) / n
    mean_r = sum(right) / n
    num = 0.0
    var_l = 0.0
    var_r = 0.0
    for one, two in zip(left, right, strict=True):
        dl = one - mean_l
        dr = two - mean_r
        num += dl * dr
        var_l += dl * dl
        var_r += dr * dr
    if var_l <= 0.0 or var_r <= 0.0:
        return None
    rho = num / math.sqrt(var_l * var_r)
    if not math.isfinite(rho):
        return None
    return max(-0.999, min(0.999, rho))


def write_outputs(table: list[dict[str, object]], rho: dict[str, object], hist_path: Path, rho_path: Path) -> None:
    hist_path.parent.mkdir(parents=True, exist_ok=True)
    rho_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "market",
        "n_hist",
        "delta_brier",
        "hist_ci_low",
        "hist_ci_high",
        "boot_p",
        "hist_q",
        "verdict",
        "reason",
    ]
    with hist_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in table:
            writer.writerow({field: _fmt(row.get(field, "")) for field in fields})
    rho_path.write_text(json.dumps(rho, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ceminiparlays.matchup_calibrate")
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--hist", type=Path, default=Path("data/cache/matchup_hist.csv"))
    parser.add_argument("--rho", type=Path, default=Path("config/matchup_regime_rho.json"))
    args = parser.parse_args(argv)
    table, rho = run_calibration(args.cache)
    write_outputs(table, rho, args.hist, args.rho)
    passed = [str(row["market"]) for row in table if row["reason"] == "hist_pass"]
    print(
        "absent_2022=yes "
        + " ".join(f"{row['market']}={row['n_hist']}:{row['reason']}" for row in table)
        + " hist_pass="
        + (",".join(passed) if passed else "none")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
