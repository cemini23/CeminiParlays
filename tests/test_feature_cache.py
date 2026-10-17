"""The feature cache bridge is read-only and fail-closed."""

from __future__ import annotations

from pathlib import Path

import pytest

from ceminiparlays.feature_cache import DEFAULT_DIR, REQUIRED, load_feature_cache, resolve_feature_cache


def test_missing_directory_resolves_to_none(tmp_path: Path) -> None:
    missing = tmp_path / "shared_cache_missing"
    assert resolve_feature_cache(missing) is None


def test_missing_directory_loads_absent(tmp_path: Path) -> None:
    missing = tmp_path / "shared_cache_missing"
    loaded = load_feature_cache(missing)
    assert loaded == {"status": "absent", "path": "", "frames": {}}


def test_partial_directory_resolves_to_none(tmp_path: Path) -> None:
    partial = tmp_path / "partial_cache"
    partial.mkdir()
    (
        partial / REQUIRED[0]
    ).write_bytes(b"parquet-not-really")
    assert resolve_feature_cache(partial) is None


def test_default_dir_constants() -> None:
    assert DEFAULT_DIR.name == "2026_w06"
    assert REQUIRED == (
        "player_telemetry_pit.parquet",
        "defense_counterpart_pit.parquet",
        "game_context_pit.parquet",
    )


def test_overlay_copies_player_volume_and_does_not_invent_a_boost(tmp_path: Path) -> None:
    pandas = pytest.importorskip("pandas")
    from ceminiparlays.feature_cache import overlay_pit

    players = [{"gsis_id": "00-1", "receptions_mean": "1.0", "ngs_separation": "1"}]
    teams = [{"team": "LAR", "q4_completion_allowed": "0.64", "roof": "dome"}]
    frames = {
        "player_telemetry_pit.parquet": pandas.DataFrame(
            [
                {
                    "player_id": "00-1",
                    "games": 10,
                    "receptions_per_game": 2.0,
                    "targets_per_game": 3.0,
                    "carries_per_game": 0.0,
                    "pass_att_per_game": 0.0,
                    "rec_yds_per_game": 16.0,
                    "rush_yds_per_game": 0.0,
                    "avg_separation": 2.5,
                    "cpoe": None,
                    "ryoe": None,
                    "avg_intended_air_yards": None,
                    "vacated_target_boost": 1.5,
                }
            ]
        ),
        "defense_counterpart_pit.parquet": pandas.DataFrame(
            [{"team": "LAR", "def_q4_comp_rate": 0.55, "def_q3_epa": 0.1, "def_q4_dropback_epa": -0.02, "def_sack_rate": 0.07, "def_light_box_rate": 0.4}]
        ),
        "game_context_pit.parquet": pandas.DataFrame(
            [{"home_team": "LAR", "away_team": "ARI", "roof": "dome", "referee_dpi_z": 0.1, "referee_holding_z": -0.2}]
        ),
    }
    out_players, out_teams = overlay_pit(players, teams, frames)
    assert players[0].get("parquet_receptions_mean") is None
    assert out_players[0]["parquet_receptions_mean"] == pytest.approx(2.0)
    assert out_players[0]["parquet_target_n"] == pytest.approx(30.0)
    assert out_players[0]["vacated_target_boost"] == pytest.approx(1.5)
    assert out_players[0]["ngs_separation"] == pytest.approx(2.5)
    assert out_teams[0]["q4_completion_allowed"] == pytest.approx(0.55)
    assert out_teams[0]["week_roof"] == "dome"
    assert out_teams[0]["referee_dpi_z"] == pytest.approx(0.1)
    assert "q3_completion_allowed" not in out_teams[0]
    del tmp_path


def test_blank_path_falls_back_to_default(tmp_path: Path) -> None:
    # A path that is not None is used directly; None means DEFAULT_DIR.
    assert resolve_feature_cache(tmp_path / "still_missing") is None
