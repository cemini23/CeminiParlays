"""The calibration outputs: the settled history table and the rho document."""

import json
from pathlib import Path

import pytest

from ceminiparlays.matchup_calibrate import run_calibration, write_outputs

HISTORY_HEADER = (
    "market,n_hist,delta_brier,hist_ci_low,hist_ci_high,boot_p,hist_q,verdict,reason"
)


def test_write_outputs_writes_the_history_table_and_the_rho_document(
    tmp_path: Path,
) -> None:
    hist = tmp_path / "nested" / "hist.csv"
    rho = tmp_path / "nested" / "rho.json"
    write_outputs(
        [
            {
                "market": "rec_yds_q3",
                "n_hist": 300,
                "delta_brier": 0.01,
                "verdict": "pass",
                "reason": "hist_pass",
            }
        ],
        {"a": 1},
        hist,
        rho,
    )
    lines = hist.read_text(encoding="utf-8").splitlines()
    assert lines[0] == HISTORY_HEADER
    assert lines[1].startswith("rec_yds_q3,300,0.010000")
    assert lines[1].endswith("pass,hist_pass")
    assert json.loads(rho.read_text(encoding="utf-8")) == {"a": 1}


def test_write_outputs_leaves_a_missing_cell_blank(tmp_path: Path) -> None:
    hist = tmp_path / "hist.csv"
    write_outputs([{"market": "m"}], {}, hist, tmp_path / "rho.json")
    row = hist.read_text(encoding="utf-8").splitlines()[1]
    assert row == "m" + "," * (len(HISTORY_HEADER.split(",")) - 1)


def test_run_calibration_returns_the_table_and_the_rho_document(tmp_path: Path) -> None:
    pytest.importorskip("pandas")
    table, rho = run_calibration(cache=tmp_path)
    assert isinstance(table, list)
    assert isinstance(rho, dict)
