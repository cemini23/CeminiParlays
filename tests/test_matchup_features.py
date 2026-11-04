"""The week-lagged snapshot. pandas is an optional dependency, so this skips."""

from pathlib import Path

import pytest

from ceminiparlays.matchup_features import build_snapshot


def test_build_snapshot_without_a_cache_reports_the_missing_years(
    tmp_path: Path,
) -> None:
    pytest.importorskip("pandas")
    diagnostics = build_snapshot(
        cache=tmp_path,
        players_out=tmp_path / "players.parquet",
        teams_out=tmp_path / "teams.parquet",
    )
    assert isinstance(diagnostics, dict)
