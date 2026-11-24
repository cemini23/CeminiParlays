"""Fast pre-lock slip logger: parsing, gates, files, and CLI."""

import csv
from pathlib import Path

import pytest

from ceminiparlays.cli import main
from ceminiparlays.slip_logger import (
    SlipInputError,
    SlipRejected,
    build_leg,
    load_slip_csv,
    log_slip,
    parse_leg_text,
    read_interactive_legs,
    validate_slip,
    write_slip_files,
)

STARTERS = (
    "slate_date,week,team,opp,kickoff_et,event_id,starter,starter_injury_status,"
    "status,backups_hard_exclude\n"
    "2026-11-22,11,BUF,MIA,1:00 PM ET,1,Josh Allen,Active,CONFIRMED,"
    "Kyle Allen (not listed); Shane Buechele (not listed)\n"
)


@pytest.fixture()
def starters(tmp_path: Path) -> Path:
    path = tmp_path / "qb_starters_2026-11-22.csv"
    path.write_text(STARTERS, encoding="utf-8")
    return path


@pytest.fixture()
def scratches_csv(tmp_path: Path) -> Path:
    path = tmp_path / "scratches_2026-11-22.csv"
    path.write_text(
        "player,team,pos,token,source,retrieved,label\n"
        "Dalton Kincaid,BUF,TE,doubtful,src,ret,CLAIMED\n",
        encoding="utf-8",
    )
    return path


def test_parse_leg_text_reads_six_fields() -> None:
    leg = parse_leg_text("Josh Allen|pass_yds|over|249.5|-115|5")
    assert leg.player == "Josh Allen"
    assert leg.market == "pass_yds"
    assert leg.side == "over"
    assert leg.line == pytest.approx(249.5)
    assert leg.book_american_odds == -115
    assert leg.stake == pytest.approx(5.0)
    assert leg.ticket_id == "MANUAL-1"
    assert parse_leg_text("A|rush_yds|more|50|+120|4", ticket_id="X").side == "over"
    assert parse_leg_text("A|rush_yds|less|50|-110|4").side == "under"


def test_parse_leg_text_rejects_bad_cells() -> None:
    with pytest.raises(SlipInputError, match="six pipe-separated"):
        parse_leg_text("Josh Allen|pass_yds|over")
    with pytest.raises(SlipInputError, match="side"):
        parse_leg_text("Josh Allen|pass_yds|maybe|249.5|-115|5")
    with pytest.raises(SlipInputError, match="outside -100 and \\+100"):
        parse_leg_text("Josh Allen|pass_yds|over|249.5|-50|5")
    with pytest.raises(SlipInputError, match="line is blank"):
        parse_leg_text("Josh Allen|pass_yds|over||-115|5")
    with pytest.raises(SlipInputError, match="stake"):
        parse_leg_text("Josh Allen|pass_yds|over|249.5|-115|0")


def test_a_td_market_may_leave_the_line_blank() -> None:
    leg = build_leg("CeeDee Lamb", "anytime_td", "yes", "", "+150", "3")
    assert leg.line == 0.0
    assert leg.side == "over"


def test_load_slip_csv_uses_a_ticket_column(tmp_path: Path) -> None:
    path = tmp_path / "slip.csv"
    path.write_text(
        "ticket_id,player,market,side,line,book_american_odds,stake\n"
        "A,Josh Allen,pass_yds,over,249.5,-115,5\n"
        "A,Dalton Kincaid,receptions,over,3.5,-110,5\n"
        "B,James Cook III,rush_yds,over,62.5,-110,3\n",
        encoding="utf-8",
    )
    legs = load_slip_csv(path)
    assert [leg.ticket_id for leg in legs] == ["A", "A", "B"]


def test_load_slip_csv_fills_a_blank_ticket_id(tmp_path: Path) -> None:
    path = tmp_path / "slip.csv"
    path.write_text(
        "player,market,side,line,book_american_odds,stake\n"
        "Josh Allen,pass_yds,over,249.5,-115,5\n",
        encoding="utf-8",
    )
    legs = load_slip_csv(path, default_ticket_id="SLIP-9")
    assert legs[0].ticket_id == "SLIP-9"


def test_load_slip_csv_rejects_a_missing_column(tmp_path: Path) -> None:
    path = tmp_path / "slip.csv"
    path.write_text("player,market,side\nJosh Allen,pass_yds,over\n", encoding="utf-8")
    with pytest.raises(SlipInputError, match="missing columns"):
        load_slip_csv(path)


def test_validate_slip_passes_a_confirmed_starter(starters: Path) -> None:
    leg = parse_leg_text("Josh Allen|pass_yds|over|249.5|-115|5")
    assert validate_slip([leg], starters=starters) == []


def test_validate_slip_rejects_a_backup_and_an_unknown(starters: Path) -> None:
    backup = parse_leg_text("Kyle Allen|pass_yds|over|199.5|-115|5")
    failures = validate_slip([backup], starters=starters)
    assert len(failures) == 1 and failures[0].startswith("BACKUP_QB")
    unknown = parse_leg_text("Ghost Player|pass_yds|over|199.5|-115|5")
    failures = validate_slip([unknown], starters=starters)
    assert len(failures) == 1 and failures[0].startswith("UNKNOWN_QB")


def test_validate_slip_needs_a_starters_file_for_a_pass_leg() -> None:
    leg = parse_leg_text("Josh Allen|pass_yds|over|249.5|-115|5")
    failures = validate_slip([leg])
    assert failures == ["QB_STARTERS_MISSING Josh Allen pass_yds"]


def test_a_non_pass_leg_does_not_need_the_starters_file() -> None:
    leg = parse_leg_text("James Cook III|rush_yds|over|62.5|-110|5")
    assert validate_slip([leg]) == []


def test_validate_slip_rejects_a_scratched_name(scratches_csv: Path, starters: Path) -> None:
    leg = parse_leg_text("Dalton Kincaid|receptions|over|3.5|-110|5")
    failures = validate_slip([leg], starters=starters, scratches=scratches_csv)
    assert len(failures) == 1
    assert failures[0].startswith("SCRATCH Dalton Kincaid") and "doubtful" in failures[0]


def test_validate_slip_reads_a_scratches_markdown(tmp_path: Path) -> None:
    path = tmp_path / "scratches.md"
    path.write_text("# Scratches\n\nDalton Kincaid (BUF, TE) - doubtful\n", encoding="utf-8")
    leg = parse_leg_text("Dalton Kincaid|receptions|over|3.5|-110|5")
    failures = validate_slip([leg], scratches=path)
    assert failures and failures[0].startswith("SCRATCH")


def test_log_slip_writes_and_syncs_both_files(tmp_path: Path, starters: Path) -> None:
    legs = [
        parse_leg_text("Josh Allen|pass_yds|over|249.5|-115|5", ticket_id="SLIP-1"),
        parse_leg_text("James Cook III|rush_yds|over|62.5|-110|5", ticket_id="SLIP-1"),
    ]
    out_dir = tmp_path / "out"
    roots = [tmp_path / "parlays-slate", tmp_path / "parlays-recap"]
    card, entered, synced = log_slip(
        legs,
        slate_date="2026-11-22",
        out_dir=out_dir,
        starters=starters,
        sync_roots=roots,
    )
    assert card.name == "hardrock_card_2026-11-22.csv"
    assert entered.name == "entered_tickets_2026-11-22.csv"
    assert len(synced) == 4
    for root in roots:
        assert (root / "2026-11-22" / card.name).is_file()
        assert (root / "2026-11-22" / entered.name).is_file()
    with entered.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["player_name"] for row in rows] == ["Josh Allen", "James Cook III"]
    assert [row["leg_num"] for row in rows] == ["1", "2"]
    assert rows[0]["ticket_id"] == "SLIP-1"
    assert rows[0]["american_odds"] == "-115"
    with card.open(newline="", encoding="utf-8") as handle:
        card_rows = list(csv.DictReader(handle))
    assert card_rows[0]["stat_type"] == "pass_yds"
    assert card_rows[0]["book_over"] == "-115"
    assert card_rows[0]["book_under"] == ""
    assert card_rows[1]["book_under"] == ""


def test_log_slip_rejects_before_any_write(tmp_path: Path, starters: Path) -> None:
    legs = [parse_leg_text("Kyle Allen|pass_yds|over|199.5|-115|5")]
    out_dir = tmp_path / "out"
    with pytest.raises(SlipRejected) as caught:
        log_slip(legs, slate_date="2026-11-22", out_dir=out_dir, starters=starters)
    assert caught.value.failures[0].startswith("BACKUP_QB")
    assert not out_dir.exists()


def test_write_slip_files_needs_no_validation(tmp_path: Path) -> None:
    legs = [parse_leg_text("Ghost Player|receptions|over|2.5|+100|2")]
    card, entered = write_slip_files(tmp_path, "2026-11-22", legs)
    assert card.is_file() and entered.is_file()


def test_interactive_legs_stop_on_a_blank_line() -> None:
    answers = iter(["Josh Allen|pass_yds|over|249.5|-115|5", ""])
    legs = read_interactive_legs(prompt=lambda _text: next(answers))
    assert len(legs) == 1
    assert legs[0].player == "Josh Allen"


def test_cli_log_slip_writes_and_exits_zero(
    tmp_path: Path, starters: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "log-slip",
            "--leg",
            "Josh Allen|pass_yds|over|249.5|-115|5",
            "--date",
            "2026-11-22",
            "--starters",
            str(starters),
            "--out-dir",
            str(tmp_path / "out"),
            "--sync-dirs",
            str(tmp_path / "parlays-slate"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "SLIP_OK legs=1 date=2026-11-22" in out
    assert (tmp_path / "out" / "hardrock_card_2026-11-22.csv").is_file()
    assert (tmp_path / "parlays-slate" / "2026-11-22" / "entered_tickets_2026-11-22.csv").is_file()


def test_cli_log_slip_exits_two_on_a_rejected_leg(
    tmp_path: Path, starters: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "log-slip",
            "--leg",
            "Kyle Allen|pass_yds|over|199.5|-115|5",
            "--date",
            "2026-11-22",
            "--starters",
            str(starters),
            "--out-dir",
            str(tmp_path / "out"),
            "--sync-dirs",
            str(tmp_path / "parlays-slate"),
        ]
    )
    assert code == 2
    assert "SLIP_REJECT BACKUP_QB Kyle Allen pass_yds" in capsys.readouterr().out
    assert not (tmp_path / "out").exists()
