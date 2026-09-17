from pathlib import Path

import pytest

from ceminiparlays.cli import main
from ceminiparlays.diff import ACCEPTED, BOOKED_WINS, diff_ticket_lines, read_ticket_table

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "examples" / "card_ticket_c.csv"
BOOKED = ROOT / "examples" / "booked_ticket_c.csv"


def test_week1_ticket_c_reports_three_deltas_and_exits_two(capsys) -> None:
    code = main(["diff", "--card", str(CARD), "--booked", str(BOOKED)])
    out = capsys.readouterr().out
    assert code == 2
    assert "ticket C stake: card=5 booked=10" in out
    assert "ticket C lines: card=-175|-180|38.5 booked=-175|-180|39" in out
    assert "ticket C multiplier: card= booked=+367" in out
    assert BOOKED_WINS in out
    assert ACCEPTED not in out


def test_accept_booked_prints_table_and_exits_zero_without_writing(capsys) -> None:
    before = CARD.read_text(encoding="utf-8")
    code = main(
        ["diff", "--card", str(CARD), "--booked", str(BOOKED), "--accept-booked"]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "ticket C stake: card=5 booked=10" in out
    assert "ticket C lines: card=-175|-180|38.5 booked=-175|-180|39" in out
    assert "ticket C multiplier: card= booked=+367" in out
    assert BOOKED_WINS in out
    assert ACCEPTED in out
    assert CARD.read_text(encoding="utf-8") == before


def test_card_only_and_booked_only_ticket_ids_are_deltas(tmp_path: Path, capsys) -> None:
    card = tmp_path / "card.csv"
    booked = tmp_path / "booked.csv"
    card.write_text(
        "ticket_id,stake,lines,multiplier\nA,5,10.5,\nC,5,38.5,\n",
        encoding="utf-8",
    )
    booked.write_text(
        "ticket_id,stake,lines,multiplier\nB,10,11,+100\nC,5,38.5,\n",
        encoding="utf-8",
    )
    code = main(["diff", "--card", str(card), "--booked", str(booked)])
    out = capsys.readouterr().out
    assert code == 2
    assert "ticket A: card only" in out
    assert "ticket B: booked only" in out


def test_optional_sides_delta_when_both_have_the_column(tmp_path: Path) -> None:
    card = read_ticket_table(
        _write(
            tmp_path / "card.csv",
            "ticket_id,stake,lines,multiplier,sides\nC,5,38.5,,ml|under\n",
        )
    )
    booked = read_ticket_table(
        _write(
            tmp_path / "booked.csv",
            "ticket_id,stake,lines,multiplier,sides\nC,5,38.5,,ml|ml|under\n",
        )
    )
    lines = diff_ticket_lines(card, booked)
    assert lines == ["ticket C sides: card=ml|under booked=ml|ml|under"]


def test_matching_tickets_exit_zero(tmp_path: Path, capsys) -> None:
    path = tmp_path / "same.csv"
    path.write_text(
        "ticket_id,stake,lines,multiplier\nC,10,-175|-180|39,+367\n",
        encoding="utf-8",
    )
    code = main(["diff", "--card", str(path), "--booked", str(path)])
    out = capsys.readouterr().out
    assert code == 0
    assert BOOKED_WINS not in out
    assert out.strip() == ""


def test_missing_ticket_id_column_exits_two(tmp_path: Path, capsys) -> None:
    path = tmp_path / "no_id.csv"
    path.write_text("stake,lines,multiplier\n5,38.5,\n", encoding="utf-8")
    code = main(["diff", "--card", str(path), "--booked", str(path)])
    err = capsys.readouterr().err
    assert code == 2
    assert "ticket_id" in err


def test_diff_help_mentions_tg06(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["diff", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "TG-06" in out
    assert "--diff-card-booked" in out


def test_emit_ledger_writes_booked_week1_c(tmp_path: Path, capsys) -> None:
    import csv

    ledger = tmp_path / "ledger.csv"
    before = CARD.read_text(encoding="utf-8")
    code = main(
        [
            "diff",
            "--card",
            str(CARD),
            "--booked",
            str(BOOKED),
            "--accept-booked",
            "--emit-ledger",
            str(ledger),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert f"wrote {ledger}" in out
    assert CARD.read_text(encoding="utf-8") == before
    rows = list(csv.DictReader(ledger.open(encoding="utf-8")))
    assert rows
    assert rows[0]["stake"] == "10"
    assert "39" in rows[0]["lines"]
    assert rows[0]["multiplier"] == "+367"


def test_emit_ledger_without_accept_does_not_write(tmp_path: Path, capsys) -> None:
    ledger = tmp_path / "ledger.csv"
    before = CARD.read_text(encoding="utf-8")
    code = main(
        [
            "diff",
            "--card",
            str(CARD),
            "--booked",
            str(BOOKED),
            "--emit-ledger",
            str(ledger),
        ]
    )
    out = capsys.readouterr().out
    assert code == 2
    assert not ledger.exists()
    assert "--emit-ledger requires --accept-booked" in out
    assert CARD.read_text(encoding="utf-8") == before


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path
