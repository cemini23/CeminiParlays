"""A miss loses the ticket before a void or a pending leg can hold it."""

from pathlib import Path

from ceminiparlays.grade import export_settled_and_hold, grade_ledger
from ceminiparlays.grade_card import grade_rows


def _ledger(path: Path, actuals: str, platform: str = "hardrock") -> None:
    path.write_text(
        "ticket_id,platform,mode,n_legs,sides,lines,actuals,stake,multiplier\n"
        f"T1,{platform},standard,2,more|more,10.5|20.5,{actuals},10,3.0\n",
        encoding="utf-8",
    )


def test_miss_and_pending_is_a_loss_not_a_hold(tmp_path: Path) -> None:
    path = tmp_path / "entered_tickets_2026-10-25.csv"
    _ledger(path, "MISS|PENDING")
    summary = grade_ledger(path)
    assert summary.n_slips == 1
    assert summary.pnl == -10.0
    assert summary.hold_tickets == []
    ledger_out = tmp_path / "ledger_2026-10-25.csv"
    hold_out = tmp_path / "ledger_hold_2026-10-25.csv"
    export_settled_and_hold(path, summary.hold_tickets, ledger_out, hold_out)
    assert "T1" in ledger_out.read_text(encoding="utf-8")
    assert "T1" not in hold_out.read_text(encoding="utf-8")


def test_pending_without_a_miss_is_held(tmp_path: Path) -> None:
    path = tmp_path / "ledger.csv"
    _ledger(path, "PENDING|PENDING")
    summary = grade_ledger(path)
    assert summary.n_slips == 0
    assert summary.stake == 0.0
    assert summary.hold_tickets == ["T1"]


def test_numeric_pickem_push_still_steps_down(tmp_path: Path) -> None:
    path = tmp_path / "ledger.csv"
    path.write_text(
        "platform,mode,n_legs,sides,lines,actuals,stake,multiplier\n"
        "underdog,standard,3,more|more|less,10.5|20.5|5.5,30|25|5.5,10,6.5\n",
        encoding="utf-8",
    )
    summary = grade_ledger(path)
    assert summary.pnl == 25.0
    assert summary.hold_tickets == []


def test_card_loss_with_pending_stays_on_the_ledger() -> None:
    from ceminiparlays.grade_card import LEDGER_COLUMNS

    def row(leg: str, status: str) -> dict[str, str]:
        base = {column: "" for column in LEDGER_COLUMNS}
        base.update(
            {
                "ticket_id": "HR-1",
                "leg_num": leg,
                "player_name": "A" if leg == "1" else "B",
                "market": "rush_yds",
                "side": "over",
                "line": "10.5",
                "book_american_odds": "-110",
                "model_prob": "0.55",
                "ticket_stake_usd": "1.00",
                "leg_status": status,
            }
        )
        return base

    grade = grade_rows([row("1", "miss"), row("2", "pending")], [])
    assert grade.profit == -1.0
    assert len(grade.ledger_rows) == 2
    assert grade.hold_rows == []
