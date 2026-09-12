from pathlib import Path

from ceminiparlays.grade import grade_ledger

ROOT = Path(__file__).resolve().parents[1]


def test_grade_example_ledger() -> None:
    summary = grade_ledger(ROOT / "examples" / "ledger.csv")
    assert summary.n_slips == 2
    assert summary.hits == 1
    assert summary.stake == 20.0
    # first slip 10 * (3.5 - 1) = +25; second 10 * (0 - 1) = -10; pnl = 15
    assert abs(summary.pnl - 15.0) < 1e-9


def test_grade_accepts_label_legs_column(tmp_path) -> None:
    path = tmp_path / "ledger.csv"
    path.write_text(
        "platform,mode,legs,sides,lines,actuals,stake,multiplier\n"
        "underdog,standard,Mahomes more 265.5 + Kelce more 62.5,"
        "more|more,265.5|62.5,280|71,10,3.5\n",
        encoding="utf-8",
    )
    summary = grade_ledger(path)
    assert summary.n_slips == 1
    assert summary.hits == 1


def test_grade_rejects_short_actuals(tmp_path) -> None:
    path = tmp_path / "ledger.csv"
    path.write_text(
        "platform,mode,n_legs,sides,lines,actuals,stake,multiplier\n"
        "underdog,standard,3,more|more|more,1|2|3,9|9,10,6.5\n",
        encoding="utf-8",
    )
    try:
        grade_ledger(path)
    except ValueError as exc:
        assert "same length" in str(exc)
    else:
        raise AssertionError("expected ValueError")
