from pathlib import Path

import pytest

from ceminiparlays.catalog import thin_catalog_games
from ceminiparlays.cli import main
from ceminiparlays.io import LineRow

ROOT = Path(__file__).resolve().parents[1]


def _row(**overrides: object) -> LineRow:
    row = dict(
        slate_id="s",
        platform="hardrock",
        player_name="CHI",
        player_key="",
        team="CHI",
        opponent="CAR",
        stat_type="pass_yds",
        line=244.5,
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


def test_compose_help_has_depth_flags_not_diff_card_booked(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["compose", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--enforce-market-depth" in out
    assert "--allow-thin-catalog" in out
    assert "--alert-late-active" in out
    assert "--diff-card-booked" not in out


def test_yards_only_game_is_thin() -> None:
    thin = thin_catalog_games([_row()])
    assert len(thin) == 1
    assert thin[0].has_moneyline is False
    assert thin[0].has_spread is False


def test_totals_only_does_not_satisfy_depth() -> None:
    thin = thin_catalog_games([_row(stat_type="total", player_name="CHI@CAR")])
    assert len(thin) == 1


def test_h2h_and_spreads_aliases_are_enough() -> None:
    lines = [
        _row(stat_type="h2h", player_name="CHI"),
        _row(stat_type="spreads", player_name="CHI", line=-3.0),
    ]
    assert thin_catalog_games(lines) == []


def test_moneyline_without_spread_is_thin() -> None:
    thin = thin_catalog_games([_row(stat_type="moneyline")])
    assert len(thin) == 1
    assert thin[0].has_moneyline is True
    assert thin[0].has_spread is False


def test_same_game_opposite_sides_share_a_key() -> None:
    lines = [
        _row(team="CHI", opponent="CAR", stat_type="h2h"),
        _row(team="CAR", opponent="CHI", stat_type="spread", line=3.0, player_name="CAR"),
    ]
    assert thin_catalog_games(lines) == []


def test_compose_enforce_market_depth_exits_two_on_yards_only(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "compose",
            "--auto",
            "--enforce-market-depth",
            "--lines",
            str(ROOT / "examples" / "sunday_lines.csv"),
            "--out-dir",
            str(tmp_path / "compose"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 2
    assert "CATALOG_THIN_MANUAL_INPUT_REQUIRED" in out
    assert "BUF@HOU" in out or "HOU@BUF" in out


def test_allow_thin_catalog_prints_note_and_continues(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "compose",
            "--auto",
            "--enforce-market-depth",
            "--allow-thin-catalog",
            "--lines",
            str(ROOT / "examples" / "sunday_lines.csv"),
            "--out-dir",
            str(tmp_path / "compose"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "CATALOG_THIN_MANUAL_INPUT_REQUIRED" in out
    assert "composed=5 requested=5" in out


def test_compose_auto_without_flag_does_not_halt(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "compose",
            "--auto",
            "--lines",
            str(ROOT / "examples" / "sunday_lines.csv"),
            "--out-dir",
            str(tmp_path / "compose"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "CATALOG_THIN_MANUAL_INPUT_REQUIRED" not in out


def test_moneyline_and_spread_rows_do_not_halt(tmp_path: Path, capsys) -> None:
    lines = tmp_path / "lines.csv"
    header = (
        "slate_id,platform,player_name,player_key,team,opp,stat_type,line,side,"
        "line_type,captured_at,injury_status,book_over,book_under,leg_odds\n"
    )
    body = (
        "s,hardrock,Joe Burrow,,CIN,TB,pass_yds,265.5,more,standard,,,-115,-105,-110\n"
        "s,hardrock,Jared Goff,,DET,NO,pass_yds,258.5,more,standard,,,-110,-110,-110\n"
        "s,hardrock,CIN,,CIN,TB,moneyline,,more,standard,,,-175,155,-175\n"
        "s,hardrock,CIN,,CIN,TB,spread,-3.0,more,standard,,,-110,-110,-110\n"
        "s,hardrock,DET,,DET,NO,moneyline,,more,standard,,,-180,150,-180\n"
        "s,hardrock,DET,,DET,NO,spread,-3.5,more,standard,,,-110,-110,-110\n"
    )
    lines.write_text(header + body, encoding="utf-8")
    code = main(
        [
            "compose",
            "--auto",
            "--enforce-market-depth",
            "--lines",
            str(lines),
            "--out-dir",
            str(tmp_path / "compose"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "CATALOG_THIN_MANUAL_INPUT_REQUIRED" not in out
