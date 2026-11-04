"""The matchup score board: the history join, the table, and the file writer."""

from pathlib import Path

from ceminiparlays.matchup_score import apply_history, format_table, score_paths


def test_apply_history_fails_every_market_closed_without_a_file() -> None:
    rows = [{"market": "m", "verdict": "pass", "reason": "live_ok"}]
    apply_history(rows, None)
    assert rows[0]["verdict"] == "fail"
    assert rows[0]["reason"] == "no_hist"
    assert rows[0]["live_reason"] == "live_ok"


def test_apply_history_joins_a_settled_row(tmp_path: Path) -> None:
    hist = tmp_path / "hist.csv"
    hist.write_text(
        "market,n_hist,delta_brier,hist_ci_low,hist_ci_high,hist_q\n"
        "m,300,0.01,0.001,0.02,0.05\n",
        encoding="utf-8",
    )
    rows = [{"market": "m", "verdict": "pass", "reason": "live_ok"}]
    apply_history(rows, hist)
    assert rows[0]["n_hist"] == 300
    assert rows[0]["delta_brier"] == 0.01
    assert rows[0]["verdict"] == "pass"
    assert rows[0]["reason"] == "pass"


def test_apply_history_marks_a_weak_market_failed(tmp_path: Path) -> None:
    hist = tmp_path / "hist.csv"
    hist.write_text("market,n_hist,delta_brier,hist_ci_low,hist_ci_high,hist_q\nm,10,0,,,\n", encoding="utf-8")
    rows = [{"market": "m", "verdict": "pass", "reason": "live_ok"}]
    apply_history(rows, hist)
    assert rows[0]["verdict"] == "fail"
    assert rows[0]["reason"] == "too_few_hist"


def test_format_table_writes_the_header_and_one_line_per_row() -> None:
    lines = format_table(
        [{"market": "m", "signal": "s", "verdict": "pass", "reason": "r"}]
    ).splitlines()
    assert lines[0].startswith("market signal n_slate")
    assert lines[1].split()[0] == "m"
    assert lines[1].split()[-1] == "r"


def test_score_paths_writes_the_summary_and_leg_tables(tmp_path: Path) -> None:
    for name in ("lines", "players", "teams"):
        (tmp_path / f"{name}.csv").write_text("", encoding="utf-8")
    out = tmp_path / "out.csv"
    legs = tmp_path / "legs.csv"
    summaries = score_paths(
        tmp_path / "lines.csv",
        tmp_path / "players.csv",
        tmp_path / "teams.csv",
        out,
        legs,
    )
    assert summaries
    assert all(row["verdict"] == "fail" for row in summaries)
    assert out.exists()
    assert legs.exists()
