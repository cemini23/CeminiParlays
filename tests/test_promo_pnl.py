"""Promo capture: terms, expected cash value, and net PnL."""

import json
from pathlib import Path

from ceminiparlays.cli import main

HEADER = (
    "platform,mode,legs,sides,lines,actuals,stake,multiplier,market,stake_kind,"
    "promo_terms,promo_value,promo_settled\n"
)
TERMS = "Up to $10 back as a Bonus Bet if your 2+ leg NFL bet loses"


def _grade(tmp_path: Path, row: str) -> dict:
    ledger = tmp_path / "ledger.csv"
    ledger.write_text(HEADER + row, encoding="utf-8")
    out = tmp_path / "grade.json"
    code = main(["grade", "--ledger", str(ledger), "--out", str(out)])
    assert code == 0
    return json.loads(out.read_text(encoding="utf-8"))


def test_promo_value_lands_in_net_pnl_when_settled(tmp_path: Path, capsys) -> None:
    summary = _grade(
        tmp_path,
        f"hardrock,parlay,Alpha,more,250.5,300,10,+150,pass_yds,cash,{TERMS},7.0,yes\n",
    )
    capsys.readouterr()
    assert summary["cash_pnl"] == 15.0
    assert summary["promo_value"] == 7.0
    assert summary["net_pnl"] == 22.0
    assert summary["promo_confirmed"] is True
    assert not any("PROMO_UNCONFIRMED" in flag for flag in summary["review_flags"])


def test_an_unsettled_promo_is_flagged_and_not_confirmed(tmp_path: Path, capsys) -> None:
    summary = _grade(
        tmp_path,
        f"hardrock,parlay,Alpha,more,250.5,300,10,+150,pass_yds,cash,{TERMS},,\n",
    )
    capsys.readouterr()
    assert summary["promo_confirmed"] is False
    assert summary["promo_value"] == 0.0
    assert summary["net_pnl"] == summary["cash_pnl"]
    assert any("PROMO_UNCONFIRMED" in flag for flag in summary["review_flags"])


def test_no_promo_leaves_net_pnl_equal_to_cash(tmp_path: Path, capsys) -> None:
    summary = _grade(
        tmp_path,
        "hardrock,parlay,Alpha,more,250.5,300,10,+150,pass_yds,cash,,,\n",
    )
    capsys.readouterr()
    assert summary["promo_terms"] == []
    assert summary["promo_confirmed"] is True
    assert summary["net_pnl"] == summary["cash_pnl"]
