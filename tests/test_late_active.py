from pathlib import Path

from ceminiparlays.cli import main
from ceminiparlays.io import LineRow
from ceminiparlays.late_active import apply_inactive_scratch, in_game_exit_warnings, read_out_keys

ROOT = Path(__file__).resolve().parents[1]


def _row(**overrides: object) -> LineRow:
    row = dict(
        slate_id="s",
        platform="hardrock",
        player_name="Malik Nabers",
        player_key="",
        team="NYG",
        opponent="DAL",
        stat_type="rec_yds",
        line=69.5,
        side="more",
        line_type="standard",
        captured_at="",
        displayed_multiplier=None,
        injury_status="",
        book_over=-110,
        book_under=-110,
    )
    row.update(overrides)
    return LineRow(**row)  # type: ignore[arg-type]


def test_out_player_is_scratched(tmp_path: Path) -> None:
    path = tmp_path / "inactives.csv"
    path.write_text("player_name,status\nMalik Nabers,INACTIVE\n", encoding="utf-8")
    line = _row()
    scratched = apply_inactive_scratch([line], path)
    assert scratched == ["Malik Nabers"]
    assert line.injury_status == "inactive"


def test_doubtful_and_ir_are_scratched(tmp_path: Path) -> None:
    path = tmp_path / "inactives.csv"
    path.write_text("player_key,status\nmalik_nabers,doubtful\n", encoding="utf-8")
    assert read_out_keys(path) == {"malik_nabers"}
    line = _row()
    apply_inactive_scratch([line], path)
    assert line.injury_status == "inactive"


def test_active_player_is_not_scratched(tmp_path: Path) -> None:
    path = tmp_path / "status.csv"
    path.write_text("player_name,status\nMalik Nabers,ACTIVE\n", encoding="utf-8")
    line = _row()
    assert apply_inactive_scratch([line], path) == []
    assert line.injury_status == ""


def test_already_out_row_keeps_its_status(tmp_path: Path) -> None:
    path = tmp_path / "inactives.csv"
    path.write_text("player_name,status\nMalik Nabers,INACTIVE\n", encoding="utf-8")
    line = _row(injury_status="out")
    assert apply_inactive_scratch([line], path) == []
    assert line.injury_status == "out"


def test_in_game_exit_is_a_warning_only() -> None:
    notes = in_game_exit_warnings([_row(injury_status="exit")])
    assert len(notes) == 1
    assert notes[0].startswith("IN_GAME_EXIT: Malik Nabers")
    assert "review" in notes[0]
    assert "void" not in notes[0]


def test_in_game_exit_tokens_stay_out_of_out_statuses() -> None:
    from ceminiparlays.io import OUT_STATUSES
    from ceminiparlays.late_active import IN_GAME_EXIT_STATUSES

    assert IN_GAME_EXIT_STATUSES == {"exit", "left"}
    assert not (IN_GAME_EXIT_STATUSES & OUT_STATUSES)


def test_in_game_exit_leg_still_grades_on_typed_actual(tmp_path: Path) -> None:
    from ceminiparlays.grade import grade_ledger

    ledger = tmp_path / "ledger.csv"
    ledger.write_text(
        "platform,mode,n_legs,sides,lines,actuals,stake,multiplier\n"
        "hardrock,standard,1,more,69.5,88,5,2.0\n",
        encoding="utf-8",
    )
    summary = grade_ledger(ledger)
    assert summary.hits == 1
    assert abs(summary.pnl - 5.0) < 1e-9


def test_compose_alert_late_active_scratches_the_inactive(tmp_path: Path, capsys) -> None:
    lines = tmp_path / "lines.csv"
    source = (ROOT / "examples" / "sunday_lines.csv").read_text(encoding="utf-8")
    extra = (
        "2026-w01-sun,hardrock,Malik Nabers,,NYG,DAL,rec_yds,69.5,more,standard,,"
        ",-110,-110,-110,,,,,\n"
    )
    lines.write_text(source + extra, encoding="utf-8")
    alert = tmp_path / "inactives.csv"
    alert.write_text("player_name,status\nMalik Nabers,INACTIVE\n", encoding="utf-8")
    code = main(
        [
            "compose",
            "--auto",
            "--allow-rec-line",
            "--lines",
            str(lines),
            "--alert-late-active",
            str(alert),
            "--out-dir",
            str(tmp_path / "compose"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "scratch (late status): Malik Nabers" in out


def test_missing_late_active_file_exits_two(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "nope.csv"
    code = main(
        [
            "compose",
            "--auto",
            "--lines",
            str(ROOT / "examples" / "sunday_lines.csv"),
            "--alert-late-active",
            str(missing),
            "--out-dir",
            str(tmp_path / "compose"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "late-active file missing" in captured.err
    assert str(missing) in captured.err
