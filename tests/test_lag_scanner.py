"""The lag scanner flags a stalled derivative only behind a real EV leg."""

from __future__ import annotations

import csv
from pathlib import Path

from ceminiparlays.lag_scanner import main

HEADER = "stat_type,player_key,line,book_over,book_under,commence_time\n"
PRICE = "-110,-110"
COMMENCE = "2026-10-18T13:00:00Z"
PLAYER = "k_sealver"


def _capture(path: Path, lines: list[str]) -> Path:
    rows = "".join(
        f"{stat_type},{PLAYER},{line},{PRICE},{COMMENCE}\n" for stat_type, line in lines
    )
    path.write_text(HEADER + rows, encoding="utf-8")
    return path


def _legs(path: Path, ev: str) -> Path:
    path.write_text(
        "market,player_key,line,ev\n"
        f"rec_yds_q3,{PLAYER},10.5,{ev}\n",
        encoding="utf-8",
    )
    return path


def _report_rows(out: Path) -> list[dict[str, str]]:
    with out.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_lagging_derivative_flags_with_passing_ev(tmp_path: Path) -> None:
    prev = _capture(tmp_path / "prev.csv", [("rec_yds", "50.5"), ("rec_yds_q3", "10.5")])
    curr = _capture(tmp_path / "curr.csv", [("rec_yds", "54.5"), ("rec_yds_q3", "10.5")])
    legs = _legs(tmp_path / "legs_pass.csv", "0.05")
    out = tmp_path / "flags.csv"

    assert main(["--prev-capture", str(prev), "--curr-capture", str(curr), "--out", str(out), "--legs", str(legs)]) == 0

    rows = _report_rows(out)
    assert len(rows) == 1
    row = rows[0]
    assert row["market"] == "rec_yds_q3"
    assert row["anchor"] == "rec_yds"
    assert float(row["anchor_move"]) == 4.0
    assert float(row["derivative_move"]) == 0.0
    assert float(row["theoretical_move"]) == 1.0
    assert float(row["ev"]) == 0.05
    assert row["commence_time"] == COMMENCE
    assert set(row) == {
        "player_key",
        "market",
        "anchor",
        "anchor_move",
        "derivative_move",
        "theoretical_move",
        "ev",
        "commence_time",
    }


def test_lagging_derivative_flags_nothing_below_ev_threshold(tmp_path: Path) -> None:
    prev = _capture(tmp_path / "prev.csv", [("rec_yds", "50.5"), ("rec_yds_q3", "10.5")])
    curr = _capture(tmp_path / "curr.csv", [("rec_yds", "54.5"), ("rec_yds_q3", "10.5")])
    legs = _legs(tmp_path / "legs_fail.csv", "0.01")
    out = tmp_path / "flags.csv"

    assert main(["--prev-capture", str(prev), "--curr-capture", str(curr), "--out", str(out), "--legs", str(legs)]) == 0

    assert _report_rows(out) == []


def test_no_legs_file_flags_nothing(tmp_path: Path) -> None:
    prev = _capture(tmp_path / "prev.csv", [("rec_yds", "50.5"), ("rec_yds_q3", "10.5")])
    curr = _capture(tmp_path / "curr.csv", [("rec_yds", "54.5"), ("rec_yds_q3", "10.5")])
    out = tmp_path / "flags.csv"

    assert main(["--prev-capture", str(prev), "--curr-capture", str(curr), "--out", str(out)]) == 0

    assert _report_rows(out) == []


def test_following_derivative_flags_nothing(tmp_path: Path) -> None:
    # The derivative tracks its theoretical move of 1.0 exactly.
    prev = _capture(tmp_path / "prev.csv", [("rec_yds", "50.5"), ("rec_yds_q3", "10.5")])
    curr = _capture(tmp_path / "curr.csv", [("rec_yds", "54.5"), ("rec_yds_q3", "11.5")])
    legs = _legs(tmp_path / "legs_pass.csv", "0.05")
    out = tmp_path / "flags.csv"

    assert main(["--prev-capture", str(prev), "--curr-capture", str(curr), "--out", str(out), "--legs", str(legs)]) == 0

    assert _report_rows(out) == []
