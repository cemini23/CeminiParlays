"""Read-only bridge onto the CeminiDFS point-in-time feature cache.

The shared cache is owned by CeminiDFS. This module never writes to it,
never creates directories, and never opens a socket. A cache that is
missing or partial resolves to ``None`` and the load is ``absent``.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_DIR = Path("/Users/claudiobarone/Projects/CeminiDFS/data/shared_cache/2026_w06")
REQUIRED = (
    "player_telemetry_pit.parquet",
    "defense_counterpart_pit.parquet",
    "game_context_pit.parquet",
)


def resolve_feature_cache(path: str | Path | None = None) -> Path | None:
    """Return the cache directory when it exists with every required file.

    The given path is checked first; ``None`` falls back to
    ``DEFAULT_DIR``. The directory is returned only when it exists and all
    three required parquet files are regular files. Nothing is created.
    """

    directory = Path(path) if path is not None else DEFAULT_DIR
    if not directory.is_dir():
        return None
    for name in REQUIRED:
        if not (directory / name).is_file():
            return None
    return directory


def load_feature_cache(path: str | Path | None = None) -> dict:
    """Read the cache frames, or report them as absent.

    A ready cache returns ``{"status": "ready", ...}`` with one dataframe
    per required parquet file. A missing or partial cache returns
    ``{"status": "absent", "path": "", "frames": {}}``. pandas is imported
    inside the function so the module imports without the dependency.
    """

    resolved = resolve_feature_cache(path)
    if resolved is None:
        return {"status": "absent", "path": "", "frames": {}}
    import pandas as pd

    frames = {name: pd.read_parquet(resolved / name) for name in REQUIRED}
    return {"status": "ready", "path": str(resolved), "frames": frames}


def _finite(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def overlay_pit(
    players: list[dict[str, object]],
    teams: list[dict[str, object]],
    frames: dict,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Copy the local rows and overlay the shared point-in-time frames.

    Player volume, NGS, and the defense rates that have a clear twin are
    replaced. Quarter opportunity sums stay on the local row. A missing
    frame leaves that side unchanged. Nothing is written to CeminiDFS.
    """

    copied_players = [dict(row) for row in players]
    copied_teams = [dict(row) for row in teams]
    if not frames:
        return copied_players, copied_teams
    player_frame = frames.get("player_telemetry_pit.parquet")
    defense_frame = frames.get("defense_counterpart_pit.parquet")
    game_frame = frames.get("game_context_pit.parquet")
    by_id: dict[str, dict] = {}
    if player_frame is not None:
        for record in player_frame.to_dict("records"):
            player_id = str(record.get("player_id") or "")
            if player_id:
                by_id[player_id] = record
    for row in copied_players:
        source = by_id.get(str(row.get("gsis_id") or ""))
        if source is None:
            continue
        games = _finite(source.get("games"))
        receptions = _finite(source.get("receptions_per_game"))
        targets = _finite(source.get("targets_per_game"))
        carries = _finite(source.get("carries_per_game"))
        pass_att = _finite(source.get("pass_att_per_game"))
        rec_yds = _finite(source.get("rec_yds_per_game"))
        rush_yds = _finite(source.get("rush_yds_per_game"))
        if receptions is not None:
            row["parquet_receptions_mean"] = receptions
        if carries is not None:
            row["parquet_rush_att_mean"] = carries
        if games is not None:
            row["parquet_games"] = games
        if targets is not None and games is not None:
            row["parquet_target_n"] = targets * games
        if carries is not None and games is not None:
            row["parquet_rush_att_n"] = carries * games
        if pass_att is not None and games is not None:
            row["parquet_pass_att_n"] = pass_att * games
        if receptions is not None and receptions > 0 and rec_yds is not None and rec_yds > 0:
            row["parquet_ypc"] = rec_yds / receptions
        if carries is not None and carries > 0 and rush_yds is not None and rush_yds > 0:
            row["parquet_rypc"] = rush_yds / carries
        for dest, source_name in (
            ("ngs_separation", "avg_separation"),
            ("ngs_cpoe", "cpoe"),
            ("ngs_ryoe", "ryoe"),
            ("ngs_intended_air", "avg_intended_air_yards"),
        ):
            value = _finite(source.get(source_name))
            if value is not None:
                row[dest] = value
        if "vacated_target_boost" in source:
            boost = _finite(source.get("vacated_target_boost"))
            if boost is not None:
                row["vacated_target_boost"] = boost
    by_team: dict[str, dict] = {}
    if defense_frame is not None:
        for record in defense_frame.to_dict("records"):
            code = str(record.get("team") or "").strip().upper()
            if code:
                by_team[code] = record
    for row in copied_teams:
        source = by_team.get(str(row.get("team") or "").strip().upper())
        if source is None:
            continue
        for dest, source_name in (
            ("q3_epa_allowed", "def_q3_epa"),
            ("q4_epa_dropback_allowed", "def_q4_dropback_epa"),
            ("q4_completion_allowed", "def_q4_comp_rate"),
            ("sack_rate", "def_sack_rate"),
            ("light_box_rate", "def_light_box_rate"),
        ):
            value = _finite(source.get(source_name))
            if value is not None:
                row[dest] = value
    if game_frame is not None:
        team_rows = {str(row.get("team") or ""): row for row in copied_teams}
        for record in game_frame.to_dict("records"):
            roof = str(record.get("roof") or "").strip().lower()
            dpi = _finite(record.get("referee_dpi_z"))
            holding = _finite(record.get("referee_holding_z"))
            for code in (str(record.get("home_team") or ""), str(record.get("away_team") or "")):
                row = team_rows.get(code)
                if row is None:
                    continue
                if roof:
                    row["week_roof"] = roof
                if dpi is not None:
                    row["referee_dpi_z"] = dpi
                if holding is not None:
                    row["referee_holding_z"] = holding
    return copied_players, copied_teams
