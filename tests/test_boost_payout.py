"""A won boosted ticket pays the displayed cash, not the unboosted product."""

from pathlib import Path

from ceminiparlays.grade import grade_ledger
from ceminiparlays.grade_card import LEDGER_COLUMNS, archive_card_copies, grade_rows


def test_displayed_boost_replaces_the_table_profit(tmp_path: Path) -> None:
    path = tmp_path / "ledger.csv"
    path.write_text(
        "ticket_id,platform,mode,n_legs,sides,lines,actuals,stake,multiplier,displayed_boosted_payout\n"
        "B1,hardrock,standard,2,more|more,10.5|20.5,30|40,10,3.0,25\n",
        encoding="utf-8",
    )
    summary = grade_ledger(path)
    assert summary.hits == 1
    assert summary.pnl == 15.0


def test_card_boost_profit_and_archive_copy(tmp_path: Path) -> None:
    row = {column: "" for column in LEDGER_COLUMNS}
    row.update(
        {
            "ticket_id": "B2",
            "leg_num": "1",
            "player_name": "A",
            "market": "pass_yds_q4",
            "side": "over",
            "line": "40.5",
            "book_american_odds": "-110",
            "model_prob": "0.60",
            "ticket_stake_usd": "1.00",
            "displayed_boosted_payout": "3.50",
            "boost_pct": "20",
            "off_card": "false",
            "leg_status": "win",
        }
    )
    grade = grade_rows([row], [])
    assert grade.profit == 2.50
    card = tmp_path / "2026-11-01_hardrock_card.csv"
    card.write_text("ticket_id\nB2\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    written = archive_card_copies(card, "2026-11-01", workspace=workspace)
    assert len(written) == 2
    assert written[0].name == "compose_card_2026-11-01.csv"
    assert written[1].name == "hardrock_card_2026-11-01.csv"
    assert archive_card_copies(card, "2026-11-01", workspace=tmp_path / "missing") == []
