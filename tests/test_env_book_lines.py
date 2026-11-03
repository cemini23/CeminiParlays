"""Book lines fill a blank spread and implied total. A blank spread still fails closed."""

from pathlib import Path

import pytest

from ceminiparlays.cli import _require_environment_fields
from ceminiparlays.environment import env_for, fill_environment_from_book_lines, read_environment


def test_blank_cells_fill_from_the_book_and_typed_cells_stay(tmp_path: Path) -> None:
    path = tmp_path / "environment.csv"
    path.write_text(
        "game_id,team,opp,implied_total,spread,roof\n"
        "G1,BUF,BAL,,,open\n"
        "G1,BAL,BUF,24.0,,open\n",
        encoding="utf-8",
    )
    environment = read_environment(path)
    rows = [
        {"stat_type": "spread", "team": "BUF", "opp": "BAL", "line": "3.5"},
        {"stat_type": "spread", "team": "BAL", "opp": "BUF", "line": "-3.5"},
        {"stat_type": "total", "team": "BUF", "opp": "BAL", "line": "47"},
    ]
    filled = fill_environment_from_book_lines(environment, rows)
    buffalo = env_for(filled, "BUF", "BAL")
    baltimore = env_for(filled, "BAL", "BUF")
    assert buffalo is not None and baltimore is not None
    assert buffalo.spread == 3.5
    assert buffalo.implied_total == pytest.approx(21.75)
    assert baltimore.spread == -3.5
    assert baltimore.implied_total == 24.0


def test_script_market_fails_closed_when_spread_is_blank(tmp_path: Path) -> None:
    """PA-8: a blank spread fails on every written ticket, including rush yards."""

    path = tmp_path / "environment.csv"
    path.write_text(
        "game_id,team,opp,implied_total,spread\nG1,BUF,BAL,24.0,\n",
        encoding="utf-8",
    )
    environment = read_environment(path)

    class _Line:
        team = "BUF"
        opponent = "BAL"
        stat_type = "receptions_q4"

    class _Leg:
        line = _Line()

    for stat in ("receptions_q4", "rush_yds"):
        _Line.stat_type = stat
        with pytest.raises(ValueError, match="blank spread"):
            _require_environment_fields([[_Leg()]], environment)
