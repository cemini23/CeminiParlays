"""Per-prop closing lines and CLV."""

import json
import math
import statistics
from pathlib import Path

from ceminiparlays.cli import main
from ceminiparlays.closings import line_clv, read_prop_closes, side_implied
from ceminiparlays.clv import clv_report, student_t_sf, summarize

ROOT = Path(__file__).resolve().parents[1]
LEDGER_HEADER = (
    "platform,mode,legs,sides,lines,actuals,stake,multiplier,market,"
    "player_key,bet_over,bet_under,close_over,close_under,close_lines\n"
)


def _write_ledger(tmp_path: Path, body: str, header: str = LEDGER_HEADER) -> Path:
    path = tmp_path / "ledger.csv"
    path.write_text(header + body, encoding="utf-8")
    return path


def _clv_cells(name: str, values: list[float]) -> Path:
    """A ledger that carries explicit ``clv_pp`` cells, one leg each."""

    header = "platform,mode,legs,sides,lines,actuals,stake,multiplier,market,clv_pp\n"
    rows = "".join(
        f"hardrock,parlay,P{index},more,50.5,60,10,+150,pass_yds,{value}\n"
        for index, value in enumerate(values)
    )
    path = Path(name)
    path.write_text(header + rows, encoding="utf-8")
    return path


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


def test_student_t_sf_matches_known_critical_values() -> None:
    # One-sided upper-tail probabilities from the t table.
    assert abs(student_t_sf(2.0, 99) - 0.02412) < 1e-4
    assert abs(student_t_sf(1.0, 1) - 0.25) < 1e-9
    assert abs(student_t_sf(1.812, 10) - 0.05) < 1e-3
    assert student_t_sf(0.0, 40) == 0.5


def test_clv_report_reads_known_clv_cells(tmp_path: Path) -> None:
    """A ledger that carries clv_pp produces the expected mean and t-stat.

    A clv_pp cell is a probability difference (the unit grade writes), so the
    report's ``*_pp`` fields are that value times 100.
    """

    path = _clv_cells(str(tmp_path / "known.csv"), [0.02, 0.04])
    report = clv_report([path])
    assert report["n_legs"] == 2
    assert report["mean_clv_pp"] == 3.0
    assert report["median_clv_pp"] == 3.0
    # stdev of [0.02, 0.04] is 0.0141421; t = 0.03 / (sd / sqrt(2)) = 3.0
    assert abs(report["stdev_clv_pp"] - 1.414214) < 1e-5
    assert abs(report["t_stat"] - 3.0) < 1e-9
    assert report["positive_clv_rate"] == 1.0
    assert report["clv_basis"] == "same_book"


def test_clv_report_aggregates_from_closing_prices(tmp_path: Path) -> None:
    ledger = _write_ledger(
        tmp_path,
        "hardrock,parlay,A|B,more|more,250.5|50.5,300|60,10,+150,"
        "pass_yds|rec_yds,a|b,-110|-120,-110|100,-150|-150,130|130,252.5|52.5\n",
    )
    report = clv_report([ledger])
    bet = side_implied("more", -110, -110)
    close_a = side_implied("more", -150, 130)
    close_b = side_implied("more", -150, 130)
    bet_b = side_implied("more", -120, 100)
    values = [close_a - bet, close_b - bet_b]
    expected_mean_pp = statistics.fmean(values) * 100
    expected_t = statistics.fmean(values) / (
        statistics.stdev(values) / math.sqrt(len(values))
    )
    assert report["n_legs"] == 2
    assert abs(report["mean_clv_pp"] - expected_mean_pp) < 1e-6
    assert abs(report["t_stat"] - expected_t) < 1e-6
    # The legs are grouped by platform, stat_type, and market.
    assert set(report["by_platform"]) == {"hardrock"}
    assert set(report["by_stat_type"]) == {"pass_yds", "rec_yds"}
    assert set(report["by_market"]) == {"pass_yds", "rec_yds"}


def test_clv_report_gate_returns_prove_kill_and_keep_collecting(tmp_path: Path) -> None:
    prove = _clv_cells(str(tmp_path / "prove.csv"), [0.01, 0.03] * 50)
    kill = _clv_cells(str(tmp_path / "kill.csv"), [-0.01, -0.03] * 50)
    keep = _clv_cells(str(tmp_path / "keep.csv"), [0.01] * 20)

    prove_report = clv_report([prove])
    assert prove_report["n_legs"] == 100
    assert prove_report["mean_clv_pp"] == 2.0
    assert prove_report["verdict"] == "PROVE"

    kill_report = clv_report([kill])
    assert kill_report["n_legs"] == 100
    assert kill_report["mean_clv_pp"] == -2.0
    assert kill_report["verdict"] == "KILL"

    keep_report = clv_report([keep])
    assert keep_report["n_legs"] == 20
    assert keep_report["verdict"] == "KEEP COLLECTING"
    assert keep_report["legs_remaining"] == 80


def test_clv_report_keeps_collecting_when_the_gate_is_not_met(tmp_path: Path) -> None:
    """n >= min_legs but a mean between the kill and prove bars keeps collecting."""

    path = _clv_cells(str(tmp_path / "mid.csv"), [0.002, 0.008] * 50)
    report = clv_report([path])
    assert report["n_legs"] == 100
    assert report["mean_clv_pp"] == 0.5
    assert report["legs_remaining"] == 0
    assert report["verdict"] == "KEEP COLLECTING"


def test_clv_report_min_legs_overrides_the_target(tmp_path: Path) -> None:
    path = _clv_cells(str(tmp_path / "small.csv"), [0.02, 0.04])
    report = clv_report([path], min_legs=5)
    assert report["min_legs"] == 5
    assert report["legs_remaining"] == 3
    assert report["verdict"] == "KEEP COLLECTING"


def test_clv_report_all_blank_close_is_zero_legs_without_crash(tmp_path: Path) -> None:
    ledger = _write_ledger(
        tmp_path,
        "hardrock,parlay,Caleb Williams|DJ Moore,more|more,224.5|52.5,260|70,10,"
        "+264,pass_yds|rec_yds,caleb_williams|dj_moore,-150|-130,130|-110,,,\n",
    )
    report = clv_report([ledger])
    assert report["n_legs"] == 0
    assert report["mean_clv_pp"] == 0.0
    assert report["t_stat"] == 0.0
    assert report["verdict"] == "KEEP COLLECTING"
    assert report["legs_remaining"] == 100


def test_clv_report_counts_only_legs_that_carry_a_clv(tmp_path: Path) -> None:
    """One leg has a full closing price, one does not. Only the priced leg counts."""

    ledger = _write_ledger(
        tmp_path,
        "hardrock,parlay,A|B,more|more,250.5|50.5,300|60,10,+150,"
        "pass_yds|rec_yds,a|b,-110|-110,-110|-110,-150|,130|,252.5|\n",
    )
    report = clv_report([ledger])
    assert report["n_legs"] == 1
    assert report["positive_clv_rate"] == 1.0


def test_clv_report_labels_a_reference_basis(tmp_path: Path) -> None:
    header = (
        "platform,mode,legs,sides,lines,actuals,stake,multiplier,market,"
        "clv_pp,close_platform\n"
    )
    ledger = _write_ledger(
        tmp_path,
        "hardrock,parlay,A,more,50.5,60,10,+150,pass_yds,0.02,pinnacle\n"
        "hardrock,parlay,B,more,50.5,60,10,+150,pass_yds,0.02,hardrock\n",
        header=header,
    )
    report = clv_report([ledger])
    assert report["clv_basis"] == "mixed"
    assert report["basis_counts"] == {"same_book": 1, "reference": 1}


def test_clv_cli_prints_a_summary_and_json(tmp_path: Path, capsys) -> None:
    ledger = _clv_cells(str(tmp_path / "known.csv"), [0.02, 0.04])
    code = main(["clv", "--ledger", str(ledger)])
    assert code == 0
    text = capsys.readouterr().out
    assert "VERDICT: KEEP COLLECTING" in text
    assert "98 legs to the 100-leg gate" in text

    code = main(["clv", "--ledger", str(ledger), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["n_legs"] == 2
    assert payload["mean_clv_pp"] == 3.0
    assert payload["verdict"] == "KEEP COLLECTING"


def test_clv_cli_writes_out_json(tmp_path: Path, capsys) -> None:
    ledger = _clv_cells(str(tmp_path / "known.csv"), [0.02, 0.04])
    out = tmp_path / "clv.json"
    code = main(["clv", "--ledger", str(ledger), "--out", str(out)])
    assert code == 0
    capsys.readouterr()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["n_legs"] == 2
    assert payload["mean_clv_pp"] == 3.0


def test_clv_cli_example_ledger_does_not_crash(capsys) -> None:
    """Acceptance: the shipped week-5 CLV ledger has blank close cells."""

    code = main(["clv", "--ledger", str(ROOT / "examples" / "ledger_week5_clv.csv")])
    assert code == 0
    assert "KEEP COLLECTING" in capsys.readouterr().out


def test_clv_summarize_of_no_legs_is_stable() -> None:
    report = summarize([])
    assert report["n_legs"] == 0
    assert report["p_value"] == 0.5
    assert report["clv_basis"] == "same_book"
