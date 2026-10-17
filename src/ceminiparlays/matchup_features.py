"""Point-in-time offense and defense features for the 2026 week-6 slate.

Every play and every NGS week must satisfy ``prior_to`` against
``(2026, 6)``. Week 6, including the Thursday game already in the 2026
file, is excluded. 2022 pbp and FTN files are not on disk. This loader
does not invent them.

FTN joins pbp on ``game_id`` and an integer ``play_id``. A float play id
stringified as ``40.0`` does not match. NGS is weekly, so it joins on
``(season, week, gsis_id)`` and has no play id.

The loader does not price a leg and does not read a book.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path

from ceminiparlays.matchup_math import TARGET_SEASON, TARGET_WEEK, prior_to, weibull_fit
from ceminiparlays.names import fold_name
from ceminiparlays.roster import normalize_team

CACHE = Path("/Users/claudiobarone/Projects/CeminiDFS/artifacts/cache")
YEARS = (2023, 2024, 2025, 2026)
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_DOME = {"dome", "indoor", "closed"}

PBP_COLS = [
    "game_id",
    "play_id",
    "season",
    "week",
    "season_type",
    "qtr",
    "posteam",
    "defteam",
    "home_team",
    "epa",
    "air_yards",
    "pass_attempt",
    "complete_pass",
    "interception",
    "sack",
    "rush_attempt",
    "passing_yards",
    "rushing_yards",
    "receiving_yards",
    "passer_player_id",
    "passer_player_name",
    "rusher_player_id",
    "rusher_player_name",
    "receiver_player_id",
    "receiver_player_name",
    "kicker_player_id",
    "kicker_player_name",
    "yardline_100",
    "touchdown",
    "td_team",
    "no_huddle",
    "field_goal_result",
    "extra_point_result",
    "roof",
    "fixed_drive",
    "score_differential",
]
FTN_FLAGS = [
    "is_motion",
    "is_play_action",
    "is_no_huddle",
    "is_interception_worthy",
    "is_catchable_ball",
    "is_created_reception",
    "is_qb_fault_sack",
    "n_defense_box",
]
PLAYER_FIELDS = [
    "gsis_id",
    "player_key",
    "full_name",
    "pbp_name",
    "team",
    "initial",
    "last",
    "n_rec",
    "n_rush",
    "n_pass",
    "n_kick",
    "q3_rec_yds_mean",
    "q3_rec_yds_sd",
    "q3_target_share_mean",
    "q4_rec_yds_mean",
    "q4_rec_yds_sd",
    "q4_receptions_mean",
    "q4_receptions_sd",
    "q4_rush_yds_mean",
    "q4_rush_yds_sd",
    "q4_pass_yds_mean",
    "q4_pass_yds_sd",
    "receptions_mean",
    "rush_att_mean",
    "pass_att_mean",
    "pass_cmp_mean",
    "interceptions_mean",
    "fg_mean",
    "kicking_points_mean",
    "kicking_points_sd",
    "ngs_separation",
    "ngs_cpoe",
    "ngs_ryoe",
    "ngs_air_share",
    "ngs_intended_air",
    "deep_target_rate",
    "breakaway_rate",
    "ftn_created_rate",
    "ftn_int_worthy_rate",
    "q4_trail_target_share",
    "weibull_rec_shape",
    "weibull_rec_scale",
    "weibull_rec_n",
    "weibull_rush_shape",
    "weibull_rush_scale",
    "weibull_rush_n",
    "weibull_pass_shape",
    "weibull_pass_scale",
    "weibull_pass_n",
    "q3_receptions_mean",
    "q3_target_n",
    "q3_ypc_mean",
    "q3_ypc_sd",
    "q4_target_n",
    "q4_target_share_mean",
    "q4_ypc_mean",
    "q4_ypc_sd",
    "q4_rush_att_mean",
    "q4_rush_n",
    "q4_rypc_mean",
    "q4_rypc_sd",
    "q4_pass_cmp_mean",
    "q4_pass_n",
    "q4_pypc_mean",
    "q4_pypc_sd",
    "target_n",
    "rush_att_n",
    "pass_att_n",
]
TEAM_FIELDS = [
    "team",
    "n_games",
    "q3_epa_off",
    "q3_epa_allowed",
    "q3_points",
    "q3_points_sd",
    "q4_epa_dropback_allowed",
    "q4_explosive_pass_allowed",
    "explosive_rush_allowed",
    "deep_comp_allowed",
    "light_box_rate",
    "sack_rate",
    "completion_allowed",
    "int_rate",
    "stall_rate",
    "fg_forced_rate",
    "roof",
    "q4_no_huddle",
    "q3_motion",
    "q3_play_action",
    "cushion_allowed",
    "q3_completion_allowed",
    "q4_completion_allowed",
    "q4_rush_ypc_allowed",
    "p0_rec",
    "p0_rush",
    "p0_pass",
]


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


def _initial_last(name: str) -> tuple[str, str]:
    text = str(name or "").replace(".", " ").replace("'", "").replace("’", "")
    parts = [part for part in text.split() if part.lower() not in _SUFFIXES]
    if not parts:
        return "", ""
    return parts[0][0].lower(), fold_name(parts[-1])


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _sd(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    center = sum(values) / len(values)
    var = sum((value - center) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(var)


def _code(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return ""
    return normalize_team(text)


def _series_flag(frame, column: str, pd):
    """0/1 series aligned to ``frame``. A missing column is all zeros."""

    if column not in frame.columns:
        return pd.Series(0, index=frame.index, dtype="float64")
    return _flag(frame[column], pd).astype(float)


def _flag(series, pd):
    if series.dtype == bool:
        return series.fillna(False).astype(int)
    mapped = series.map(
        lambda value: str(value).strip().lower() in {"1", "true", "t", "yes"}
    )
    return mapped.fillna(False).astype(int)


def _prior_frame(frame, target_season: int, target_week: int):
    """Keep regular-season weeks strictly before the target. Week 0 is out."""

    season = frame["season"].astype(int).tolist()
    week = frame["week"].astype(int).tolist()
    mask = [
        1 <= int(one_week) <= 18 and prior_to(int(one_season), int(one_week), target_season, target_week)
        for one_season, one_week in zip(season, week, strict=True)
    ]
    return frame.loc[mask].copy()


def _fit_columns(yards: list[float]) -> tuple[float | None, float | None, int]:
    fitted = weibull_fit(yards)
    if fitted is None:
        return None, None, len([yard for yard in yards if yard > 0])
    return fitted[0], fitted[1], len([yard for yard in yards if yard > 0])


def _load_pbp_year(pd, cache: Path, year: int, target_season: int, target_week: int):
    path = cache / f"pbp_{year}.parquet"
    frame = pd.read_parquet(path, columns=PBP_COLS)
    frame = frame[frame["season_type"].astype(str) == "REG"]
    frame = _prior_frame(frame, target_season, target_week)
    frame["play_id"] = pd.to_numeric(frame["play_id"], errors="coerce").astype("Int64")
    frame = frame[frame["play_id"].notna()].copy()
    for col in ("posteam", "defteam", "home_team", "td_team"):
        frame[col] = frame[col].map(_code)
    return frame


def _load_ftn_year(pd, cache: Path, year: int, target_season: int, target_week: int):
    path = cache / f"ftn_charting_{year}.parquet"
    if not path.exists():
        return None
    frame = pd.read_parquet(
        path,
        columns=["nflverse_game_id", "nflverse_play_id", "season", "week", *FTN_FLAGS],
    )
    frame = _prior_frame(frame, target_season, target_week)
    frame["game_id"] = frame["nflverse_game_id"].astype(str)
    frame["play_id"] = pd.to_numeric(frame["nflverse_play_id"], errors="coerce").astype("Int64")
    frame = frame[frame["play_id"].notna()]
    for col in FTN_FLAGS:
        if col == "n_defense_box":
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        else:
            frame[col] = _flag(frame[col], pd)
    keep = ["game_id", "play_id", *FTN_FLAGS]
    return frame[keep].drop_duplicates(["game_id", "play_id"])


def _join_rate(plays, ftn) -> float:
    if ftn is None or ftn.empty:
        return 0.0
    left = set(zip(ftn["game_id"].astype(str), ftn["play_id"].astype(int), strict=True))
    right = set(
        zip(plays["game_id"].astype(str), plays["play_id"].astype(int), strict=True)
    )
    if not left:
        return 0.0
    return len(left & right) / len(left)


def _team_tables(plays, pd):
    """One offense row and one defense row per team-game."""

    plays = plays[plays["posteam"].astype(str) != ""].copy()
    plays["pass_attempt"] = pd.to_numeric(plays["pass_attempt"], errors="coerce").fillna(0)
    plays["complete_pass"] = pd.to_numeric(plays["complete_pass"], errors="coerce").fillna(0)
    plays["rush_attempt"] = pd.to_numeric(plays["rush_attempt"], errors="coerce").fillna(0)
    plays["interception"] = pd.to_numeric(plays["interception"], errors="coerce").fillna(0)
    plays["sack"] = pd.to_numeric(plays["sack"], errors="coerce").fillna(0)
    plays["qtr"] = pd.to_numeric(plays["qtr"], errors="coerce")
    plays["epa"] = pd.to_numeric(plays["epa"], errors="coerce")
    plays["air_yards"] = pd.to_numeric(plays["air_yards"], errors="coerce")
    plays["receiving_yards"] = pd.to_numeric(plays["receiving_yards"], errors="coerce").fillna(0)
    plays["rushing_yards"] = pd.to_numeric(plays["rushing_yards"], errors="coerce").fillna(0)
    plays["passing_yards"] = pd.to_numeric(plays["passing_yards"], errors="coerce").fillna(0)
    plays["yardline_100"] = pd.to_numeric(plays["yardline_100"], errors="coerce")
    plays["score_differential"] = pd.to_numeric(plays["score_differential"], errors="coerce")
    plays["touchdown"] = pd.to_numeric(plays["touchdown"], errors="coerce").fillna(0)
    plays["fg_made"] = (plays["field_goal_result"].astype(str) == "made").astype(int)
    plays["xp_good"] = (plays["extra_point_result"].astype(str) == "good").astype(int)
    plays["huddle_flag"] = _series_flag(plays, "is_no_huddle", pd)
    pbp_huddle = pd.to_numeric(plays["no_huddle"], errors="coerce")
    plays["huddle_flag"] = plays["huddle_flag"].where(plays["huddle_flag"].notna(), pbp_huddle).fillna(0)
    if "n_defense_box" not in plays.columns:
        plays["n_defense_box"] = float("nan")
    plays["light_box"] = (pd.to_numeric(plays["n_defense_box"], errors="coerce") <= 6).astype(int)
    plays["box_known"] = pd.to_numeric(plays["n_defense_box"], errors="coerce").notna().astype(int)
    plays["deep_comp"] = (
        (plays["complete_pass"] > 0) & (plays["receiving_yards"] >= 20)
    ).astype(int)
    plays["explosive_rush"] = (
        (plays["rush_attempt"] > 0) & (plays["rushing_yards"] >= 15)
    ).astype(int)
    q3 = plays["qtr"] == 3
    q4 = plays["qtr"] == 4
    plays["q3_epa"] = plays["epa"].where(q3)
    plays["q3_play"] = q3.astype(int)
    plays["q3_target"] = ((plays["pass_attempt"] > 0) & q3).astype(int)
    plays["q4_pass"] = ((plays["pass_attempt"] > 0) & q4).astype(int)
    plays["q4_epa_pass"] = plays["epa"].where((plays["pass_attempt"] > 0) & q4)
    plays["motion_q3"] = _series_flag(plays, "is_motion", pd).where(q3)
    plays["pa_q3"] = _series_flag(plays, "is_play_action", pd).where(q3)

    off = (
        plays.groupby(["season", "week", "game_id", "posteam"], dropna=False)
        .agg(
            q3_epa=("q3_epa", "mean"),
            q3_targets=("q3_target", "sum"),
            q3_motion=("motion_q3", "mean"),
            q3_play_action=("pa_q3", "mean"),
        )
        .reset_index()
        .rename(columns={"posteam": "team"})
    )
    q4_off = (
        plays.loc[q4]
        .groupby(["season", "week", "game_id", "posteam"], dropna=False)["huddle_flag"]
        .mean()
        .reset_index()
        .rename(columns={"posteam": "team", "huddle_flag": "q4_no_huddle"})
    )
    off = off.merge(q4_off, on=["season", "week", "game_id", "team"], how="left")

    points = _quarter_points(plays, pd)
    off = off.merge(points, on=["season", "week", "game_id", "team"], how="left")
    off["q3_points"] = off["q3_points"].fillna(0.0)

    defense = (
        plays.groupby(["season", "week", "game_id", "defteam"], dropna=False)
        .agg(
            q3_epa_allowed=("q3_epa", "mean"),
            pass_att=("pass_attempt", "sum"),
            completions=("complete_pass", "sum"),
            deep_comp=("deep_comp", "sum"),
            sacks=("sack", "sum"),
            interceptions=("interception", "sum"),
            rush_att=("rush_attempt", "sum"),
            explosive_rush=("explosive_rush", "sum"),
            light_box=("light_box", "sum"),
            box_known=("box_known", "sum"),
        )
        .reset_index()
        .rename(columns={"defteam": "team"})
    )
    q3_def = (
        plays.loc[q3 & (plays["pass_attempt"] > 0)]
        .groupby(["season", "week", "game_id", "defteam"], dropna=False)
        .agg(q3_pass=("pass_attempt", "sum"), q3_cmp=("complete_pass", "sum"))
        .reset_index()
        .rename(columns={"defteam": "team"})
    )
    q4_def = (
        plays.loc[q4 & (plays["pass_attempt"] > 0)]
        .groupby(["season", "week", "game_id", "defteam"], dropna=False)
        .agg(
            q4_epa_dropback=("epa", "mean"),
            q4_pass=("pass_attempt", "sum"),
            q4_cmp=("complete_pass", "sum"),
            q4_deep=("deep_comp", "sum"),
        )
        .reset_index()
        .rename(columns={"defteam": "team"})
    )
    q4_rush_def = (
        plays.loc[q4 & (plays["rush_attempt"] > 0)]
        .groupby(["season", "week", "game_id", "defteam"], dropna=False)
        .agg(q4_rush_att=("rush_attempt", "sum"), q4_rush_yds=("rushing_yards", "sum"))
        .reset_index()
        .rename(columns={"defteam": "team"})
    )
    defense = defense.merge(q3_def, on=["season", "week", "game_id", "team"], how="left")
    defense = defense.merge(q4_def, on=["season", "week", "game_id", "team"], how="left")
    defense = defense.merge(q4_rush_def, on=["season", "week", "game_id", "team"], how="left")
    stalls = _drive_stalls(plays, pd)
    defense = defense.merge(
        stalls["forced"], on=["season", "week", "game_id", "team"], how="left"
    )
    off = off.merge(stalls["own"], on=["season", "week", "game_id", "team"], how="left")
    return off, defense


def _quarter_points(plays, pd):
    q3 = plays["qtr"] == 3
    td = plays.loc[(plays["touchdown"] > 0) & q3 & (plays["td_team"].astype(str) != "")]
    td_pts = td.groupby(["season", "week", "game_id", "td_team"]).size().rename("td") * 6
    fg = plays.loc[q3 & (plays["fg_made"] > 0) & (plays["posteam"].astype(str) != "")]
    fg_pts = fg.groupby(["season", "week", "game_id", "posteam"]).size().rename("fg") * 3
    xp = plays.loc[q3 & (plays["xp_good"] > 0) & (plays["posteam"].astype(str) != "")]
    xp_pts = xp.groupby(["season", "week", "game_id", "posteam"]).size().rename("xp")
    keys = ["season", "week", "game_id"]
    frame = td_pts.reset_index().rename(columns={"td_team": "team"})
    frame = frame.merge(
        fg_pts.reset_index().rename(columns={"posteam": "team"}),
        on=[*keys, "team"],
        how="outer",
    )
    frame = frame.merge(
        xp_pts.reset_index().rename(columns={"posteam": "team"}),
        on=[*keys, "team"],
        how="outer",
    )
    for col in ("td", "fg", "xp"):
        if col not in frame.columns:
            frame[col] = 0.0
        frame[col] = frame[col].fillna(0.0)
    frame["q3_points"] = frame["td"] + frame["fg"] + frame["xp"]
    return frame[[*keys, "team", "q3_points"]]


def _drive_stalls(plays, pd):
    scoped = plays.dropna(subset=["fixed_drive"]).copy()
    scoped = scoped[scoped["posteam"].astype(str) != ""]
    grouped = scoped.groupby(["season", "week", "game_id", "posteam", "fixed_drive"], dropna=False)
    drives = grouped.agg(
        min_yl=("yardline_100", "min"),
        fg=("fg_made", "max"),
        defense=("defteam", "first"),
    ).reset_index()
    reached = drives[drives["min_yl"] <= 35]
    own = (
        reached.groupby(["season", "week", "game_id", "posteam"], dropna=False)
        .agg(drives_35=("fg", "size"), fg_35=("fg", "sum"))
        .reset_index()
        .rename(columns={"posteam": "team"})
    )
    forced = (
        reached.groupby(["season", "week", "game_id", "defense"], dropna=False)
        .agg(def_drives_35=("fg", "size"), def_fg_35=("fg", "sum"))
        .reset_index()
        .rename(columns={"defense": "team"})
    )
    return {"own": own, "forced": forced}


def _player_games(plays, pd):
    """Per-player game lines. Yards for the tail fit are returned beside them."""

    plays["pass_attempt"] = pd.to_numeric(plays["pass_attempt"], errors="coerce").fillna(0)
    plays["complete_pass"] = pd.to_numeric(plays["complete_pass"], errors="coerce").fillna(0)
    plays["rush_attempt"] = pd.to_numeric(plays["rush_attempt"], errors="coerce").fillna(0)
    plays["air_yards"] = pd.to_numeric(plays["air_yards"], errors="coerce")
    plays["receiving_yards"] = pd.to_numeric(plays["receiving_yards"], errors="coerce").fillna(0)
    plays["rushing_yards"] = pd.to_numeric(plays["rushing_yards"], errors="coerce").fillna(0)
    plays["passing_yards"] = pd.to_numeric(plays["passing_yards"], errors="coerce").fillna(0)
    plays["qtr"] = pd.to_numeric(plays["qtr"], errors="coerce")
    plays["score_differential"] = pd.to_numeric(plays["score_differential"], errors="coerce")
    q3 = plays["qtr"] == 3
    q4 = plays["qtr"] == 4
    trail = plays["score_differential"] < -7
    plays["created_flag"] = _series_flag(plays, "is_created_reception", pd).fillna(0)
    plays["worthy_flag"] = _series_flag(plays, "is_interception_worthy", pd)
    plays["fg_made"] = (plays["field_goal_result"].astype(str) == "made").astype(int)
    plays["xp_good"] = (plays["extra_point_result"].astype(str) == "good").astype(int)

    team_q3 = (
        plays.loc[q3 & (plays["pass_attempt"] > 0)]
        .groupby(["game_id", "posteam"])
        .size()
        .rename("team_q3_targets")
    )
    team_q4 = (
        plays.loc[q4 & (plays["pass_attempt"] > 0)]
        .groupby(["game_id", "posteam"])
        .size()
        .rename("team_q4_targets")
    )

    rec = plays[plays["receiver_player_id"].notna() & (plays["pass_attempt"] > 0)].copy()
    rec["gsis_id"] = rec["receiver_player_id"].astype(str)
    rec = rec[~rec["gsis_id"].isin({"", "nan", "None", "<NA>"})]
    rec["q3_target"] = q3.loc[rec.index].astype(int)
    rec["q4_target"] = q4.loc[rec.index].astype(int)
    rec["q4_trail"] = (q4.loc[rec.index] & trail.loc[rec.index]).astype(int)
    rec["q3_yards"] = rec["receiving_yards"].where(q3.loc[rec.index] & (rec["complete_pass"] > 0), 0)
    rec["q4_yards"] = rec["receiving_yards"].where(q4.loc[rec.index] & (rec["complete_pass"] > 0), 0)
    rec["q3_rec"] = ((rec["complete_pass"] > 0) & q3.loc[rec.index]).astype(int)
    rec["q4_rec"] = ((rec["complete_pass"] > 0) & q4.loc[rec.index]).astype(int)
    rec["deep"] = (rec["air_yards"] >= 20).astype(int)
    rec["catch_yards"] = rec["receiving_yards"].where(rec["complete_pass"] > 0, 0)
    rec_games = rec.groupby(
        ["season", "week", "game_id", "gsis_id", "posteam"], dropna=False
    ).agg(
        pbp_name=("receiver_player_name", "first"),
        targets=("pass_attempt", "sum"),
        receptions=("complete_pass", "sum"),
        rec_yds=("receiving_yards", "sum"),
        q3_targets=("q3_target", "sum"),
        q3_receptions=("q3_rec", "sum"),
        q3_rec_yds=("q3_yards", "sum"),
        q4_targets=("q4_target", "sum"),
        q4_rec_yds=("q4_yards", "sum"),
        q4_receptions=("q4_rec", "sum"),
        q4_trail_targets=("q4_trail", "sum"),
        deep_targets=("deep", "sum"),
        created=("created_flag", "sum"),
        rec_long=("catch_yards", "max"),
    ).reset_index().rename(columns={"posteam": "team"})
    team_q3 = team_q3.reset_index().rename(columns={"posteam": "team"})
    team_q4 = team_q4.reset_index().rename(columns={"posteam": "team"})
    rec_games = rec_games.merge(team_q3, on=["game_id", "team"], how="left")
    rec_games = rec_games.merge(team_q4, on=["game_id", "team"], how="left")

    rush = plays[plays["rusher_player_id"].notna() & (plays["rush_attempt"] > 0)].copy()
    rush["gsis_id"] = rush["rusher_player_id"].astype(str)
    rush = rush[~rush["gsis_id"].isin({"", "nan", "None", "<NA>"})]
    rush["q4_yards"] = rush["rushing_yards"].where(q4.loc[rush.index], 0)
    rush["q4_att"] = q4.loc[rush.index].astype(int)
    rush["breakaway"] = (rush["rushing_yards"] >= 15).astype(int)
    rush["rush_clip"] = rush["rushing_yards"].clip(lower=0)
    rush_games = rush.groupby(
        ["season", "week", "game_id", "gsis_id", "posteam"], dropna=False
    ).agg(
        pbp_name=("rusher_player_name", "first"),
        rush_att=("rush_attempt", "sum"),
        q4_rush_att=("q4_att", "sum"),
        q4_rush_yds=("q4_yards", "sum"),
        breakaways=("breakaway", "sum"),
        rush_yds=("rushing_yards", "sum"),
        rush_long=("rush_clip", "max"),
    ).reset_index().rename(columns={"posteam": "team"})

    passed = plays[plays["passer_player_id"].notna() & (plays["pass_attempt"] > 0)].copy()
    passed["gsis_id"] = passed["passer_player_id"].astype(str)
    passed = passed[~passed["gsis_id"].isin({"", "nan", "None", "<NA>"})]
    passed["q4_yards"] = passed["passing_yards"].where(q4.loc[passed.index], 0)
    passed["q4_att"] = q4.loc[passed.index].astype(int)
    passed["q4_cmp_flag"] = ((passed["complete_pass"] > 0) & q4.loc[passed.index]).astype(int)
    passed["worthy_known"] = passed["worthy_flag"].notna().astype(int)
    passed["cmp_yards"] = passed["passing_yards"].where(passed["complete_pass"] > 0, 0)
    pass_games = passed.groupby(
        ["season", "week", "game_id", "gsis_id", "posteam"], dropna=False
    ).agg(
        pbp_name=("passer_player_name", "first"),
        pass_att=("pass_attempt", "sum"),
        pass_cmp=("complete_pass", "sum"),
        interceptions=("interception", "sum"),
        q4_pass_att=("q4_att", "sum"),
        q4_pass_cmp=("q4_cmp_flag", "sum"),
        q4_pass_yds=("q4_yards", "sum"),
        worthy=("worthy_flag", "sum"),
        worthy_n=("worthy_known", "sum"),
        pass_yds=("passing_yards", "sum"),
        pass_long=("cmp_yards", "max"),
    ).reset_index().rename(columns={"posteam": "team"})

    kicked = plays[plays["kicker_player_id"].notna() & ((plays["fg_made"] > 0) | (plays["xp_good"] > 0) | plays["field_goal_result"].notna() | plays["extra_point_result"].notna())].copy()
    kicked["gsis_id"] = kicked["kicker_player_id"].astype(str)
    kick_games = kicked.groupby(
        ["season", "week", "game_id", "gsis_id", "posteam"], dropna=False
    ).agg(
        pbp_name=("kicker_player_name", "first"),
        fg_made=("fg_made", "sum"),
        xp_good=("xp_good", "sum"),
    ).reset_index().rename(columns={"posteam": "team"})
    kick_games["kicking_points"] = kick_games["fg_made"] * 3 + kick_games["xp_good"]

    yards = {
        "rec": _positive(rec.loc[rec["complete_pass"] > 0], "gsis_id", "receiving_yards"),
        "rush": _positive(rush.loc[rush["rushing_yards"] > 0], "gsis_id", "rushing_yards"),
        "pass": _positive(passed.loc[passed["complete_pass"] > 0], "gsis_id", "passing_yards"),
    }
    caught = rec["complete_pass"] > 0
    carried = rush["rush_attempt"] > 0
    completed = passed["complete_pass"] > 0
    zeros = {
        "rec_n": int(caught.sum()),
        "rec_z": int((caught & (rec["receiving_yards"] <= 0)).sum()),
        "rush_n": int(carried.sum()),
        "rush_z": int((carried & (rush["rushing_yards"] <= 0)).sum()),
        "pass_n": int(completed.sum()),
        "pass_z": int((completed & (passed["passing_yards"] <= 0)).sum()),
    }
    return rec_games, rush_games, pass_games, kick_games, yards, zeros


def _positive(frame, id_col: str, value_col: str) -> dict[str, list[float]]:
    out: dict[str, list[float]] = defaultdict(list)
    if frame.empty:
        return out
    for gsis, values in frame.groupby(id_col)[value_col]:
        out[str(gsis)].extend(float(value) for value in values.tolist() if float(value) > 0)
    return out


def _extend_yards(store: dict[str, list[float]], chunk: dict[str, list[float]]) -> None:
    for gsis, values in chunk.items():
        store[gsis].extend(values)


def _load_ngs(pd, cache: Path, target_season: int, target_week: int):
    frames = []
    specs = (
        ("ngs_receiving", "player_id", ["avg_separation", "avg_yac_above_expectation", "avg_cushion", "percent_share_of_intended_air_yards", "avg_intended_air_yards", "player_display_name", "player_name"]),
        ("ngs_passing", "player_id", ["completion_percentage_above_expectation", "avg_time_to_throw", "avg_intended_air_yards", "player_display_name"]),
        ("ngs_rushing", "player_id", ["rush_yards_over_expected_per_att", "efficiency", "player_display_name", "player_name"]),
    )
    for year in YEARS:
        for prefix, id_col, want in specs:
            path = cache / f"{prefix}_{year}.parquet"
            if not path.exists():
                continue
            import pyarrow.parquet as pq

            have = set(pq.read_schema(path).names)
            id_have = id_col if id_col in have else ("player_gsis_id" if "player_gsis_id" in have else "")
            if not id_have:
                continue
            cols = [col for col in ["season", "week", "team_abbr", id_have, *want] if col in have]
            frame = pd.read_parquet(path, columns=cols)
            frame = _prior_frame(frame, target_season, target_week)
            frame["gsis_id"] = frame[id_have].astype(str)
            frame["source"] = prefix
            if "team_abbr" in frame.columns:
                frame["team"] = frame["team_abbr"].map(_code)
            frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _ngs_player_table(ngs, pd):
    if ngs.empty:
        return pd.DataFrame(columns=["gsis_id"])
    rows = []
    for gsis, group in ngs.groupby("gsis_id"):
        row: dict[str, object] = {"gsis_id": str(gsis)}
        name = ""
        for col in ("player_display_name", "player_name"):
            if col in group.columns:
                picked = group[col].dropna().astype(str)
                picked = picked[picked.str.len() > 0]
                if not picked.empty:
                    name = str(picked.iloc[-1])
        row["full_name"] = name
        row["player_key"] = fold_name(name) if name else ""
        if "team" in group.columns:
            teams = [team for team in group["team"].tolist() if team]
            row["team"] = teams[-1] if teams else ""
        rec = group[group["source"] == "ngs_receiving"] if "source" in group.columns else group
        passed = group[group["source"] == "ngs_passing"] if "source" in group.columns else group.iloc[0:0]
        rushed = group[group["source"] == "ngs_rushing"] if "source" in group.columns else group.iloc[0:0]
        row["ngs_separation"] = _mean(_nums(rec, "avg_separation"))
        row["ngs_air_share"] = _mean(_nums(rec, "percent_share_of_intended_air_yards"))
        row["ngs_cushion"] = _mean(_nums(rec, "avg_cushion"))
        row["ngs_cpoe"] = _mean(_nums(passed, "completion_percentage_above_expectation"))
        row["ngs_ryoe"] = _mean(_nums(rushed, "rush_yards_over_expected_per_att"))
        air = _nums(rec, "avg_intended_air_yards") or _nums(passed, "avg_intended_air_yards")
        row["ngs_intended_air"] = _mean(air)
        rows.append(row)
    return pd.DataFrame(rows)


def _nums(frame, col: str) -> list[float]:
    if frame is None or len(frame) == 0 or col not in frame.columns:
        return []
    values = []
    for value in frame[col].tolist():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            values.append(number)
    return values


def _roll_player(rec, rush, passed, kick, yards, ngs_players, pd) -> list[dict[str, object]]:
    ids = set(rec["gsis_id"]) | set(rush["gsis_id"]) | set(passed["gsis_id"]) | set(kick["gsis_id"])
    ngs_map = {}
    if not ngs_players.empty:
        ngs_map = {str(row.gsis_id): row for row in ngs_players.itertuples(index=False)}
    rows = []
    for gsis in sorted(ids):
        rec_g = rec[rec["gsis_id"] == gsis]
        rush_g = rush[rush["gsis_id"] == gsis]
        pass_g = passed[passed["gsis_id"] == gsis]
        kick_g = kick[kick["gsis_id"] == gsis]
        names = []
        teams = []
        for frame in (rec_g, rush_g, pass_g, kick_g):
            if not frame.empty:
                names.extend(str(name) for name in frame["pbp_name"].dropna().tolist())
                teams.extend(str(team) for team in frame["team"].tolist() if team)
        pbp_name = names[-1] if names else ""
        ngs_row = ngs_map.get(gsis)
        full = str(getattr(ngs_row, "full_name", "") or "") if ngs_row is not None else ""
        key = str(getattr(ngs_row, "player_key", "") or "") if ngs_row is not None else ""
        best = full or pbp_name
        initial, last = _initial_last(best)
        q3_shares = []
        for item in rec_g.itertuples(index=False):
            denom = float(getattr(item, "team_q3_targets", 0) or 0)
            if denom > 0:
                q3_shares.append(float(item.q3_targets) / denom)
        q4_shares = []
        q4_trail = []
        q3_ypc = []
        q4_ypc = []
        q3_recs = []
        for item in rec_g.itertuples(index=False):
            denom = float(getattr(item, "team_q4_targets", 0) or 0)
            if denom > 0:
                q4_shares.append(float(item.q4_targets) / denom)
                q4_trail.append(float(item.q4_trail_targets) / denom)
            q3_got = float(item.q3_receptions)
            q3_recs.append(q3_got)
            if q3_got > 0:
                q3_ypc.append(float(item.q3_rec_yds) / q3_got)
            q4_got = float(item.q4_receptions)
            if q4_got > 0:
                q4_ypc.append(float(item.q4_rec_yds) / q4_got)
        q4_rush_atts = []
        q4_rypc = []
        for item in rush_g.itertuples(index=False):
            att = float(item.q4_rush_att)
            q4_rush_atts.append(att)
            if att > 0:
                q4_rypc.append(float(item.q4_rush_yds) / att)
        q4_pass_cmps = []
        q4_pypc = []
        q4_pass_n = 0.0
        for item in pass_g.itertuples(index=False):
            q4_pass_n += float(item.q4_pass_att)
            got = float(item.q4_pass_cmp)
            q4_pass_cmps.append(got)
            if got > 0:
                q4_pypc.append(float(item.q4_pass_yds) / got)
        deep_rate = None
        if not rec_g.empty and float(rec_g["targets"].sum()) > 0:
            deep_rate = float(rec_g["deep_targets"].sum()) / float(rec_g["targets"].sum())
        created_rate = None
        if not rec_g.empty and float(rec_g["targets"].sum()) > 0:
            created_rate = float(rec_g["created"].sum()) / float(rec_g["targets"].sum())
        breakaway = None
        if not rush_g.empty and float(rush_g["rush_att"].sum()) > 0:
            breakaway = float(rush_g["breakaways"].sum()) / float(rush_g["rush_att"].sum())
        worthy_rate = None
        if not pass_g.empty and float(pass_g["worthy_n"].sum()) > 0:
            worthy_rate = float(pass_g["worthy"].sum()) / float(pass_g["worthy_n"].sum())
        q3_yds = [float(value) for value in rec_g["q3_rec_yds"].tolist()] if not rec_g.empty else []
        q4_yds = [float(value) for value in rec_g["q4_rec_yds"].tolist()] if not rec_g.empty else []
        q4_recs = [float(value) for value in rec_g["q4_receptions"].tolist()] if not rec_g.empty else []
        q4_rush = [float(value) for value in rush_g["q4_rush_yds"].tolist()] if not rush_g.empty else []
        q4_pass = [float(value) for value in pass_g["q4_pass_yds"].tolist()] if not pass_g.empty else []
        kick_pts = [float(value) for value in kick_g["kicking_points"].tolist()] if not kick_g.empty else []
        rec_shape, rec_scale, rec_n = _fit_columns(yards["rec"].get(gsis, []))
        rush_shape, rush_scale, rush_n = _fit_columns(yards["rush"].get(gsis, []))
        pass_shape, pass_scale, pass_n = _fit_columns(yards["pass"].get(gsis, []))
        row = {
            "gsis_id": gsis,
            "player_key": key,
            "full_name": full,
            "pbp_name": pbp_name,
            "team": teams[-1] if teams else "",
            "initial": initial,
            "last": last,
            "n_rec": int(len(rec_g)),
            "n_rush": int(len(rush_g)),
            "n_pass": int(len(pass_g)),
            "n_kick": int(len(kick_g)),
            "q3_rec_yds_mean": _mean(q3_yds),
            "q3_rec_yds_sd": _sd(q3_yds),
            "q3_target_share_mean": _mean(q3_shares),
            "q4_rec_yds_mean": _mean(q4_yds),
            "q4_rec_yds_sd": _sd(q4_yds),
            "q4_receptions_mean": _mean(q4_recs),
            "q4_receptions_sd": _sd(q4_recs),
            "q4_rush_yds_mean": _mean(q4_rush),
            "q4_rush_yds_sd": _sd(q4_rush),
            "q4_pass_yds_mean": _mean(q4_pass),
            "q4_pass_yds_sd": _sd(q4_pass),
            "receptions_mean": _mean([float(v) for v in rec_g["receptions"].tolist()]) if not rec_g.empty else None,
            "rush_att_mean": _mean([float(v) for v in rush_g["rush_att"].tolist()]) if not rush_g.empty else None,
            "pass_att_mean": _mean([float(v) for v in pass_g["pass_att"].tolist()]) if not pass_g.empty else None,
            "pass_cmp_mean": _mean([float(v) for v in pass_g["pass_cmp"].tolist()]) if not pass_g.empty else None,
            "interceptions_mean": _mean([float(v) for v in pass_g["interceptions"].tolist()]) if not pass_g.empty else None,
            "fg_mean": _mean([float(v) for v in kick_g["fg_made"].tolist()]) if not kick_g.empty else None,
            "kicking_points_mean": _mean(kick_pts),
            "kicking_points_sd": _sd(kick_pts),
            "deep_target_rate": deep_rate,
            "breakaway_rate": breakaway,
            "ftn_created_rate": created_rate,
            "ftn_int_worthy_rate": worthy_rate,
            "q4_trail_target_share": _mean(q4_trail),
            "weibull_rec_shape": rec_shape,
            "weibull_rec_scale": rec_scale,
            "weibull_rec_n": rec_n,
            "weibull_rush_shape": rush_shape,
            "weibull_rush_scale": rush_scale,
            "weibull_rush_n": rush_n,
            "weibull_pass_shape": pass_shape,
            "weibull_pass_scale": pass_scale,
            "weibull_pass_n": pass_n,
            "q3_receptions_mean": _mean(q3_recs),
            "q3_target_n": float(rec_g["q3_targets"].sum()) if not rec_g.empty else 0.0,
            "q3_ypc_mean": _mean(q3_ypc),
            "q3_ypc_sd": _sd(q3_ypc),
            "q4_target_n": float(rec_g["q4_targets"].sum()) if not rec_g.empty else 0.0,
            "q4_target_share_mean": _mean(q4_shares),
            "q4_ypc_mean": _mean(q4_ypc),
            "q4_ypc_sd": _sd(q4_ypc),
            "q4_rush_att_mean": _mean(q4_rush_atts),
            "q4_rush_n": float(sum(q4_rush_atts)),
            "q4_rypc_mean": _mean(q4_rypc),
            "q4_rypc_sd": _sd(q4_rypc),
            "q4_pass_cmp_mean": _mean(q4_pass_cmps),
            "q4_pass_n": q4_pass_n,
            "q4_pypc_mean": _mean(q4_pypc),
            "q4_pypc_sd": _sd(q4_pypc),
            "target_n": float(rec_g["targets"].sum()) if not rec_g.empty else 0.0,
            "rush_att_n": float(rush_g["rush_att"].sum()) if not rush_g.empty else 0.0,
            "pass_att_n": float(pass_g["pass_att"].sum()) if not pass_g.empty else 0.0,
        }
        for col in (
            "ngs_separation",
            "ngs_cpoe",
            "ngs_ryoe",
            "ngs_air_share",
            "ngs_intended_air",
        ):
            value = getattr(ngs_row, col, None) if ngs_row is not None else None
            row[col] = None if value is None or (isinstance(value, float) and not math.isfinite(value)) else value
        rows.append(row)
    return rows


def _roll_teams(
    off,
    defense,
    roofs: dict[str, str],
    cushions: dict[str, float],
    zero_rates: dict[str, float],
) -> list[dict[str, object]]:
    teams = sorted(set(off["team"]).union(defense["team"]))
    rows = []
    for team in teams:
        if not team:
            continue
        off_g = off[off["team"] == team]
        def_g = defense[defense["team"] == team]
        q3_points = [float(value) for value in off_g["q3_points"].fillna(0).tolist()] if not off_g.empty else []
        def_rates = _defense_rates(def_g)
        own_stall = None
        if not off_g.empty and "drives_35" in off_g.columns and float(off_g["drives_35"].fillna(0).sum()) > 0:
            own_stall = float(off_g["fg_35"].fillna(0).sum()) / float(off_g["drives_35"].fillna(0).sum())
        rows.append(
            {
                "team": team,
                "n_games": int(len(off_g)),
                "q3_epa_off": _mean(_nums(off_g, "q3_epa")),
                "q3_epa_allowed": _mean(_nums(def_g, "q3_epa_allowed")),
                "q3_points": _mean(q3_points),
                "q3_points_sd": _sd(q3_points),
                "q4_epa_dropback_allowed": def_rates["q4_epa"],
                "q4_explosive_pass_allowed": def_rates["q4_explosive"],
                "explosive_rush_allowed": def_rates["explosive_rush"],
                "deep_comp_allowed": def_rates["deep"],
                "light_box_rate": def_rates["light_box"],
                "sack_rate": def_rates["sack"],
                "completion_allowed": def_rates["completion"],
                "int_rate": def_rates["int"],
                "stall_rate": own_stall,
                "fg_forced_rate": def_rates["fg_forced"],
                "roof": roofs.get(team, ""),
                "q4_no_huddle": _mean(_nums(off_g, "q4_no_huddle")),
                "q3_motion": _mean(_nums(off_g, "q3_motion")),
                "q3_play_action": _mean(_nums(off_g, "q3_play_action")),
                "cushion_allowed": cushions.get(team),
                "q3_completion_allowed": def_rates["q3_completion"],
                "q4_completion_allowed": def_rates["q4_completion"],
                "q4_rush_ypc_allowed": def_rates["q4_rush_ypc"],
                "p0_rec": zero_rates["p0_rec"],
                "p0_rush": zero_rates["p0_rush"],
                "p0_pass": zero_rates["p0_pass"],
            }
        )
    return rows


def _defense_rates(frame) -> dict[str, float | None]:
    keys = (
        "q4_epa",
        "q4_explosive",
        "explosive_rush",
        "deep",
        "light_box",
        "sack",
        "completion",
        "int",
        "fg_forced",
        "q3_completion",
        "q4_completion",
        "q4_rush_ypc",
    )
    if frame.empty:
        return {key: None for key in keys}

    def _sum(column: str) -> float:
        if column not in frame.columns:
            return 0.0
        return float(frame[column].fillna(0).sum())

    att = _sum("pass_att")
    rush = _sum("rush_att")
    box = _sum("box_known")
    drives = _sum("def_drives_35")
    q4_pass = _sum("q4_pass")
    q3_pass = _sum("q3_pass")
    q4_rush_att = _sum("q4_rush_att")
    return {
        "q4_epa": _mean(_nums(frame, "q4_epa_dropback")),
        "q4_explosive": (_sum("q4_deep") / q4_pass) if q4_pass else None,
        "explosive_rush": (_sum("explosive_rush") / rush) if rush else None,
        "deep": (_sum("deep_comp") / att) if att else None,
        "light_box": (_sum("light_box") / box) if box else None,
        "sack": (_sum("sacks") / att) if att else None,
        "completion": (_sum("completions") / att) if att else None,
        "int": (_sum("interceptions") / att) if att else None,
        "fg_forced": (_sum("def_fg_35") / drives) if drives else None,
        "q3_completion": (_sum("q3_cmp") / q3_pass) if q3_pass else None,
        "q4_completion": (_sum("q4_cmp") / q4_pass) if q4_pass else None,
        "q4_rush_ypc": (_sum("q4_rush_yds") / q4_rush_att) if q4_rush_att else None,
    }


def _roofs(plays) -> dict[str, str]:
    roofs: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    scoped = plays[plays["home_team"].astype(str) != ""]
    for team, roof in zip(scoped["home_team"].tolist(), scoped["roof"].tolist(), strict=False):
        text = str(roof or "").strip().lower()
        if text and text != "nan":
            roofs[str(team)][text] += 1
    out = {}
    for team, counts in roofs.items():
        out[team] = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return out


def build_snapshot(
    cache: Path = CACHE,
    players_out: Path | None = None,
    teams_out: Path | None = None,
    target_season: int = TARGET_SEASON,
    target_week: int = TARGET_WEEK,
) -> dict[str, object]:
    """Write the week-lagged player and team tables. Returns join diagnostics."""

    import pandas as pd

    rec_parts = []
    rush_parts = []
    pass_parts = []
    kick_parts = []
    off_parts = []
    def_parts = []
    play_parts = []
    yards: dict[str, dict[str, list[float]]] = {
        "rec": defaultdict(list),
        "rush": defaultdict(list),
        "pass": defaultdict(list),
    }
    rates: dict[str, float] = {}
    missing = []
    zero_tot = {"rec_n": 0, "rec_z": 0, "rush_n": 0, "rush_z": 0, "pass_n": 0, "pass_z": 0}
    for year in YEARS:
        pbp_path = cache / f"pbp_{year}.parquet"
        if not pbp_path.exists():
            missing.append(str(pbp_path.name))
            continue
        plays = _load_pbp_year(pd, cache, year, target_season, target_week)
        plays["game_id"] = plays["game_id"].astype(str)
        ftn = _load_ftn_year(pd, cache, year, target_season, target_week)
        rates[str(year)] = _join_rate(plays, ftn)
        if ftn is not None:
            plays = plays.merge(ftn, on=["game_id", "play_id"], how="left")
        off, defense = _team_tables(plays, pd)
        rec, rush, passed, kick, year_yards, year_zeros = _player_games(plays, pd)
        for key in zero_tot:
            zero_tot[key] += int(year_zeros[key])
        rec_parts.append(rec)
        rush_parts.append(rush)
        pass_parts.append(passed)
        kick_parts.append(kick)
        off_parts.append(off)
        def_parts.append(defense)
        play_parts.append(plays[["season", "week", "posteam", "defteam", "home_team", "roof"]])
        for kind in yards:
            _extend_yards(yards[kind], year_yards[kind])
    if not rec_parts:
        raise ValueError("no prior pbp seasons were on disk")
    rec = pd.concat(rec_parts, ignore_index=True)
    rush = pd.concat(rush_parts, ignore_index=True)
    passed = pd.concat(pass_parts, ignore_index=True)
    kick = pd.concat(kick_parts, ignore_index=True)
    off = pd.concat(off_parts, ignore_index=True)
    defense = pd.concat(def_parts, ignore_index=True)
    plays = pd.concat(play_parts, ignore_index=True)
    ngs = _load_ngs(pd, cache, target_season, target_week)
    ngs_players = _ngs_player_table(ngs, pd)
    # Cushion uses the lagged NGS week and the lagged opponent from pbp.
    cushions = _cushion_from_schedule(plays, ngs, pd) if not ngs.empty else {}
    roofs = _roofs(plays)
    players = _roll_player(rec, rush, passed, kick, yards, ngs_players, pd)

    def _share(zero_key: str, n_key: str) -> float:
        total = zero_tot[n_key]
        if total <= 0:
            return 0.0
        return zero_tot[zero_key] / total

    zero_rates = {
        "p0_rec": _share("rec_z", "rec_n"),
        "p0_rush": _share("rush_z", "rush_n"),
        "p0_pass": _share("pass_z", "pass_n"),
    }
    teams = _roll_teams(off, defense, roofs, cushions, zero_rates)
    players_out = players_out or Path("data/cache/matchup_players_2026w06.csv")
    teams_out = teams_out or Path("data/cache/matchup_teams_2026w06.csv")
    _write(players_out, PLAYER_FIELDS, players)
    _write(teams_out, TEAM_FIELDS, teams)
    return {
        "players": len(players),
        "teams": len(teams),
        "ftn_join_rate": rates,
        "missing_files": missing,
        "absent_2022": True,
        "target": f"{target_season}-w{target_week}",
        "players_out": str(players_out),
        "teams_out": str(teams_out),
    }


def _cushion_from_schedule(plays, ngs, pd) -> dict[str, float]:
    if "avg_cushion" not in ngs.columns:
        return {}
    rec = ngs[ngs["source"] == "ngs_receiving"][["season", "week", "team", "avg_cushion"]].copy()
    rec["avg_cushion"] = pd.to_numeric(rec["avg_cushion"], errors="coerce")
    rec = rec[rec["avg_cushion"].notna() & (rec["team"].astype(str) != "")]
    offense = rec.groupby(["season", "week", "team"], dropna=False)["avg_cushion"].mean().reset_index()
    games = plays[["season", "week", "posteam", "defteam"]].drop_duplicates()
    games = games.rename(columns={"posteam": "offense", "defteam": "defense"})
    joined = games.merge(offense, left_on=["season", "week", "offense"], right_on=["season", "week", "team"], how="inner")
    if joined.empty:
        return {}
    grouped = joined.groupby("defense")["avg_cushion"].mean()
    return {str(team): float(value) for team, value in grouped.items() if str(team)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ceminiparlays.matchup_features")
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--players", type=Path, default=Path("data/cache/matchup_players_2026w06.csv"))
    parser.add_argument("--teams", type=Path, default=Path("data/cache/matchup_teams_2026w06.csv"))
    parser.add_argument("--season", type=int, default=TARGET_SEASON)
    parser.add_argument("--week", type=int, default=TARGET_WEEK)
    args = parser.parse_args(argv)
    summary = build_snapshot(args.cache, args.players, args.teams, args.season, args.week)
    print(
        f"target={summary['target']} players={summary['players']} teams={summary['teams']} "
        f"ftn_join={summary['ftn_join_rate']} missing={summary['missing_files']} absent_2022=yes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
