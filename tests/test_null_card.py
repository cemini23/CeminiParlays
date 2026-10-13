"""compose always writes a card artifact, including a null card."""

import json
from pathlib import Path

from ceminiparlays.cli import main

LINE_COLUMNS = [
    "slate_id",
    "platform",
    "player_name",
    "player_key",
    "team",
    "opp",
    "stat_type",
    "line",
    "side",
    "line_type",
    "captured_at",
    "injury_status",
    "book_over",
    "book_under",
    "slip_multiplier",
    "book_line",
]


def _row(**overrides: str) -> str:
    row = {
        "slate_id": "s",
        "platform": "hardrock",
        "player_name": "P",
        "player_key": "",
        "team": "AAA",
        "opp": "BBB",
        "stat_type": "pass_yds",
        "line": "250.5",
        "side": "more",
        "line_type": "standard",
        "captured_at": "",
        "injury_status": "",
        "book_over": "-110",
        "book_under": "-110",
        "slip_multiplier": "",
        "book_line": "",
    }
    row.update(overrides)
    return ",".join(row[column] for column in LINE_COLUMNS) + "\n"


def _write_lines(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "lines.csv"
    path.write_text(",".join(LINE_COLUMNS) + "\n" + "".join(rows), encoding="utf-8")
    return path


def test_no_rows_writes_a_null_card_and_fails_closed(tmp_path: Path, capsys) -> None:
    lines = _write_lines(tmp_path, [_row(player_key="a")])
    out_dir = tmp_path / "compose"
    code = main(
        [
            "compose",
            "--lines",
            str(lines),
            "--ticket-id",
            "NOPE",
            "--out-dir",
            str(out_dir),
        ]
    )
    out = capsys.readouterr().out
    assert code == 2
    assert "NULL-CARD" in out
    payload = json.loads((out_dir / "card.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "no-rows"
    assert payload["tickets"] == []
    assert payload["n_tickets"] == 0
    assert "NULL CARD" in (out_dir / "card.txt").read_text(encoding="utf-8")


def test_strict_dropped_legs_writes_a_null_card(tmp_path: Path, capsys) -> None:
    # The typed line and the book line disagree: the leg is dropped, strict refuses.
    lines = _write_lines(tmp_path, [_row(player_key="a", book_line="245.5")])
    out_dir = tmp_path / "compose"
    code = main(
        ["compose", "--lines", str(lines), "--no-roster", "--out-dir", str(out_dir)]
    )
    capsys.readouterr()
    assert code == 2
    payload = json.loads((out_dir / "card.json").read_text(encoding="utf-8"))
    assert payload["reason"] == "dropped-legs"
    assert payload["tickets"] == []
    assert payload["dropped"][0]["warn"] == "book-line-mismatch"


def test_a_null_card_puts_every_booked_ticket_off_card(tmp_path: Path, capsys) -> None:
    lines = _write_lines(tmp_path, [_row(player_key="a")])
    out_dir = tmp_path / "compose"
    main(["compose", "--lines", str(lines), "--ticket-id", "NOPE", "--out-dir", str(out_dir)])
    capsys.readouterr()

    ledger = tmp_path / "ledger.csv"
    ledger.write_text(
        "platform,mode,legs,sides,lines,actuals,stake,multiplier,ticket_id,market\n"
        "hardrock,parlay,Alpha,more,250.5,300,10,+150,111111111111111111,pass_yds\n",
        encoding="utf-8",
    )
    out = tmp_path / "grade.json"
    code = main(
        [
            "grade",
            "--ledger",
            str(ledger),
            "--card",
            str(out_dir / "card.json"),
            "--out",
            str(out),
        ]
    )
    capsys.readouterr()
    assert code == 0
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert summary["on_card_pnl"] == 0.0
    assert summary["off_card_pnl"] != 0.0
    assert summary["off_card_tickets"] == ["111111111111111111"]


def test_compose_card_json_carries_the_ticket_id(tmp_path: Path, capsys) -> None:
    lines = _write_lines(
        tmp_path,
        [
            _row(player_key="a", team="AAA", opp="BBB"),
            _row(player_key="b", team="CCC", opp="DDD", stat_type="rush_yds", line="80.5"),
        ],
    )
    out_dir = tmp_path / "compose"
    code = main(
        [
            "compose",
            "--lines",
            str(lines),
            "--no-roster",
            "--legs",
            "2",
            "--n-tickets",
            "1",
            "--out-dir",
            str(out_dir),
        ]
    )
    capsys.readouterr()
    assert code == 0
    payload = json.loads((out_dir / "card.json").read_text(encoding="utf-8"))
    assert payload["tickets"][0]["ticket_id"] == "compose-001"
    assert payload["do_not_submit"] is True
