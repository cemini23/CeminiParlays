"""Per-prop closing lines and CLV."""

import json
from pathlib import Path

from ceminiparlays.cli import main
from ceminiparlays.closings import line_clv, read_prop_closes, side_implied

LEDGER_HEADER = (
    "platform,mode,legs,sides,lines,actuals,stake,multiplier,market,"
    "player_key,bet_over,bet_under,close_over,close_under,close_lines\n"
)


def test_line_clv_signs_the_move_for_the_bettor() -> None:
    assert line_clv("more", 250.5, 252.5) == 2.0
    assert line_clv("less", 250.5, 252.5) == -2.0
    assert line_clv("more", 250.5, 248.5) == -2.0
    assert line_clv("less", 250.5, 248.5) == 2.0


def test_side_implied_devigs_the_two_way_market() -> None:
    prob = side_implied("more", -110, -110)
    assert prob is not None and abs(prob - 0.5) < 0.01
    assert side_implied("more", None, -110) is None
    assert side_implied("bogus", -110, -110) is None


def test_read_prop_closes_rejects_a_duplicate_key(tmp_path: Path) -> None:
    path = tmp_path / "closing_props.csv"
    path.write_text(
        "platform,player_key,stat_type,side,line,over,under,captured_at\n"
        "hardrock,alpha,pass_yds,more,252.5,-150,130,t\n"
        "hardrock,alpha,pass_yds,more,252.5,-150,130,t\n",
        encoding="utf-8",
    )
    try:
        read_prop_closes(path)
    except ValueError as exc:
        assert "Duplicate key" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("duplicate key was accepted")


def test_grade_computes_clv_from_the_ledger_cells(tmp_path: Path, capsys) -> None:
    ledger = tmp_path / "ledger.csv"
    ledger.write_text(
        LEDGER_HEADER
        + "hardrock,parlay,Alpha,more,250.5,300,10,+150,pass_yds,"
        "alpha,-110,-110,-150,130,252.5\n",
        encoding="utf-8",
    )
    out = tmp_path / "grade.json"
    code = main(["grade", "--ledger", str(ledger), "--out", str(out)])
    capsys.readouterr()
    assert code == 0
    summary = json.loads(out.read_text(encoding="utf-8"))
    leg = summary["clv_by_ticket"][0]["legs"][0]
    # Bet the over at -110 (0.50); it closes at -150 (about 0.58): a beat.
    assert leg["clv_pp"] > 0.05
    assert leg["clv_line"] == 2.0
    assert summary["clv_mean_pp"] > 0.05


def test_grade_fills_a_blank_close_cell_from_the_closing_snapshot(
    tmp_path: Path, capsys
) -> None:
    ledger = tmp_path / "ledger.csv"
    ledger.write_text(
        LEDGER_HEADER
        + "hardrock,parlay,Alpha,more,250.5,300,10,+150,pass_yds,alpha,-110,-110,,,\n",
        encoding="utf-8",
    )
    closings = tmp_path / "closing_props.csv"
    closings.write_text(
        "platform,player_key,stat_type,side,line,over,under,captured_at\n"
        "hardrock,alpha,pass_yds,more,252.5,-150,130,2026-10-11T17:00:00Z\n",
        encoding="utf-8",
    )
    out = tmp_path / "grade.json"
    code = main(
        ["grade", "--ledger", str(ledger), "--closings", str(closings), "--out", str(out)]
    )
    capsys.readouterr()
    assert code == 0
    summary = json.loads(out.read_text(encoding="utf-8"))
    leg = summary["clv_by_ticket"][0]["legs"][0]
    assert leg["clv_pp"] > 0.05
    assert leg["close_line"] == 252.5


def test_grade_without_prices_has_no_clv_and_does_not_crash(tmp_path: Path, capsys) -> None:
    ledger = tmp_path / "ledger.csv"
    ledger.write_text(
        "platform,mode,legs,sides,lines,actuals,stake,multiplier\n"
        "hardrock,parlay,Alpha,more,250.5,300,10,+150\n",
        encoding="utf-8",
    )
    out = tmp_path / "grade.json"
    code = main(["grade", "--ledger", str(ledger), "--out", str(out)])
    capsys.readouterr()
    assert code == 0
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["clv_by_ticket"] == []
    assert summary["clv_mean_pp"] == 0.0
