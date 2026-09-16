from pathlib import Path

from ceminiparlays.cli import main
from ceminiparlays.io import LineRow
from ceminiparlays.late_active import late_active_alerts

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
        injury_status="q",
        book_over=-110,
        book_under=-110,
    )
    row.update(overrides)
    return LineRow(**row)  # type: ignore[arg-type]


def test_q_player_later_active_alerts_once(tmp_path: Path) -> None:
    path = tmp_path / "active.csv"
    path.write_text("player_name,status\nMalik Nabers,ACTIVE\n", encoding="utf-8")
    notes = late_active_alerts([_row(), _row()], path)
    assert notes == [
        "OPERATOR_ACTION_REQUIRED: Malik Nabers excluded as q later ACTIVE"
    ]


def test_out_player_later_active_still_alerts(tmp_path: Path) -> None:
    path = tmp_path / "active.csv"
    path.write_text("player_key,status\nmalik_nabers,active\n", encoding="utf-8")
    notes = late_active_alerts([_row(injury_status="out")], path)
    assert "excluded as out later ACTIVE" in notes[0]


def test_healthy_player_does_not_alert(tmp_path: Path) -> None:
    path = tmp_path / "active.csv"
    path.write_text("player_name,status\nMalik Nabers,ACTIVE\n", encoding="utf-8")
    assert late_active_alerts([_row(injury_status="")], path) == []


def test_inactive_status_in_alert_file_does_not_trigger(tmp_path: Path) -> None:
    path = tmp_path / "active.csv"
    path.write_text("player_name,status\nMalik Nabers,inactive\n", encoding="utf-8")
    assert late_active_alerts([_row()], path) == []


def test_compose_alert_late_active_prints_and_exits_zero(tmp_path: Path, capsys) -> None:
    lines = tmp_path / "lines.csv"
    source = (ROOT / "examples" / "sunday_lines.csv").read_text(encoding="utf-8")
    extra = (
        "2026-w01-sun,hardrock,Malik Nabers,,NYG,DAL,rec_yds,69.5,more,standard,,"
        "q,-110,-110,-110,,,,,\n"
    )
    lines.write_text(source + extra, encoding="utf-8")
    alert = tmp_path / "active.csv"
    alert.write_text("player_name,status\nMalik Nabers,ACTIVE\n", encoding="utf-8")
    code = main(
        [
            "compose",
            "--auto",
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
    assert "OPERATOR_ACTION_REQUIRED: Malik Nabers excluded as q later ACTIVE" in out


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
