"""The inactive gate reads the card, not only a DFS lineup."""

from pathlib import Path

from ceminiparlays.inactive_gate import check_card_inactives


def _card(path: Path, name: str) -> None:
    path.write_text(
        "ticket_id,player_name,gsis_id,market,team\n"
        f"HR-16,{name},00-0039001,receptions_q4,TEN\n"
        "HR-17,Derrick Henry,00-0039002,rush_yds,BAL\n",
        encoding="utf-8",
    )


def test_inactive_on_the_card_is_flagged(tmp_path: Path) -> None:
    card = tmp_path / "2026-10-25_hardrock_card.csv"
    inactives = tmp_path / "inactives_diff_2026-10-25.csv"
    entered = tmp_path / "entered_tickets_2026-10-25.csv"
    scratches = tmp_path / "scratches.md"
    _card(card, "Tyjae Spears")
    inactives.write_text(
        "player,to_status,label\n"
        "Tyjae Spears,inactive,out\n"
        "Some Backup,not rostered,dfs\n",
        encoding="utf-8",
    )
    entered.write_text(
        "ticket_id,player_name,market\n"
        "HR-16,Tyjae Spears,receptions_q4\n",
        encoding="utf-8",
    )
    scratches.write_text("Tyjae Spears — Out\nDerrick Henry — questionable\n", encoding="utf-8")
    hits = check_card_inactives(card, inactives, entered=entered, scratches=scratches)
    names = {hit.player_name for hit in hits}
    assert names == {"Tyjae Spears"}
    assert any(hit.where == "card" for hit in hits)
    assert any(hit.where == "entered" for hit in hits)
    assert all(hit.status == "inactive" for hit in hits)


def test_questionable_and_not_rostered_stay_clear(tmp_path: Path) -> None:
    card = tmp_path / "2026-11-01_hardrock_card.csv"
    inactives = tmp_path / "inactives.csv"
    _card(card, "Derrick Henry")
    inactives.write_text(
        "player,to_status\nDerrick Henry,questionable\nOther Back,not rostered\n",
        encoding="utf-8",
    )
    assert check_card_inactives(card, inactives) == []
