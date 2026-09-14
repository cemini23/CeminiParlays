from pathlib import Path

import pytest

from ceminiparlays.grade import grade_ledger

ROOT = Path(__file__).resolve().parents[1]


def test_grade_example_ledger() -> None:
    summary = grade_ledger(ROOT / "examples" / "ledger.csv")
    assert summary.n_slips == 2
    assert summary.hits == 1
    assert summary.stake == 20.0
    # first slip 10 * (3.5 - 1) = +25; second 10 * (0 - 1) = -10; pnl = 15
    assert abs(summary.pnl - 15.0) < 1e-9


def test_grade_accepts_label_legs_column(tmp_path) -> None:
    path = tmp_path / "ledger.csv"
    path.write_text(
        "platform,mode,legs,sides,lines,actuals,stake,multiplier\n"
        "underdog,standard,Mahomes more 265.5 + Kelce more 62.5,"
        "more|more,265.5|62.5,280|71,10,3.5\n",
        encoding="utf-8",
    )
    summary = grade_ledger(path)
    assert summary.n_slips == 1
    assert summary.hits == 1


def test_grade_rejects_short_actuals(tmp_path) -> None:
    path = tmp_path / "ledger.csv"
    path.write_text(
        "platform,mode,n_legs,sides,lines,actuals,stake,multiplier\n"
        "underdog,standard,3,more|more|more,1|2|3,9|9,10,6.5\n",
        encoding="utf-8",
    )
    try:
        grade_ledger(path)
    except ValueError as exc:
        assert "same length" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_grade_push_is_void_not_miss(tmp_path) -> None:
    path = tmp_path / "ledger.csv"
    path.write_text(
        "platform,mode,n_legs,sides,lines,actuals,stake,multiplier\n"
        "underdog,standard,3,more|more|less,10.5|20.5|5.5,30|25|5.5,10,6.5\n",
        encoding="utf-8",
    )
    summary = grade_ledger(path)
    # one exact hit voids; the slip steps down to the 2-leg row at 3.5x
    assert summary.hits == 0
    assert summary.pnl == 25.0


def test_grade_push_refunds_when_no_smaller_row(tmp_path) -> None:
    path = tmp_path / "ledger.csv"
    path.write_text(
        "platform,mode,n_legs,sides,lines,actuals,stake,multiplier\n"
        "underdog,standard,2,more|more,10.5|20.5,30|20.5,10,3.5\n",
        encoding="utf-8",
    )
    summary = grade_ledger(path)
    assert summary.pnl == 0.0


def test_grade_blank_platform_uses_default_sportsbook(tmp_path) -> None:
    path = tmp_path / "ledger.csv"
    path.write_text(
        "platform,mode,n_legs,sides,lines,actuals,stake,multiplier\n"
        ",standard,2,more|more,10.5|20.5,9|9,10,\n",
        encoding="utf-8",
    )
    summary = grade_ledger(path, default_platform="hardrock")
    # sportsbook miss without a price is 0x, not a silent refund
    assert summary.pnl == -10.0


def test_grade_blank_platform_sportsbook_hit_requires_price(tmp_path) -> None:
    path = tmp_path / "ledger.csv"
    path.write_text(
        "platform,mode,n_legs,sides,lines,actuals,stake,multiplier\n"
        ",standard,2,more|more,10.5|20.5,30|40,10,\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no fixed lounge table"):
        grade_ledger(path, default_platform="hardrock")


def test_grade_sportsbook_void_and_miss_is_zero(tmp_path) -> None:
    path = tmp_path / "ledger.csv"
    path.write_text(
        "platform,mode,n_legs,sides,lines,actuals,stake,multiplier\n"
        "hardrock,standard,3,more|more|more,10.5|20.5|5.5,30|20.5|1,10,5.0\n",
        encoding="utf-8",
    )
    summary = grade_ledger(path)
    assert summary.pnl == -10.0


def test_grade_sportsbook_void_all_hits_uses_settled_multiplier(tmp_path) -> None:
    path = tmp_path / "ledger.csv"
    path.write_text(
        "platform,mode,n_legs,sides,lines,actuals,stake,multiplier\n"
        "hardrock,standard,3,more|more|more,10.5|20.5|5.5,30|40|5.5,10,2.6\n",
        encoding="utf-8",
    )
    summary = grade_ledger(path)
    assert abs(summary.pnl - 16.0) < 1e-9


def test_grade_sportsbook_void_all_hits_without_multiplier_raises(tmp_path) -> None:
    path = tmp_path / "ledger.csv"
    path.write_text(
        "platform,mode,n_legs,sides,lines,actuals,stake,multiplier\n"
        "hardrock,standard,3,more|more|more,10.5|20.5|5.5,30|40|5.5,10,\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="settled reduced-ticket multiplier"):
        grade_ledger(path)


def test_grade_week1_hardrock_ledger() -> None:
    summary = grade_ledger(ROOT / "examples" / "ledger_week1_hardrock.csv")
    assert summary.n_slips == 5
    assert summary.hits == 2
    assert summary.stake == 40.0
    assert abs(summary.pnl - 26.07) < 0.02
    assert round(summary.pnl, 2) == 26.07


def test_grade_atd_yes_yes_american_is_hit_not_void(tmp_path) -> None:
    path = tmp_path / "ledger.csv"
    path.write_text(
        "platform,mode,n_legs,sides,lines,actuals,stake,multiplier\n"
        "hardrock,standard,3,yes|yes|yes,yes|yes|yes,yes|yes|yes,5,+288\n",
        encoding="utf-8",
    )
    summary = grade_ledger(path)
    assert summary.hits == 1
    assert abs(summary.pnl - 14.40) < 1e-9
    assert abs(summary.pnl - 1435.0) > 1.0


def test_grade_atd_yes_yes_paid_is_hit(tmp_path) -> None:
    path = tmp_path / "ledger.csv"
    path.write_text(
        "platform,mode,n_legs,sides,lines,actuals,stake,multiplier,paid\n"
        "hardrock,standard,3,yes|yes|yes,yes|yes|yes,yes|yes|yes,5,,19.40\n",
        encoding="utf-8",
    )
    summary = grade_ledger(path)
    assert summary.hits == 1
    assert abs(summary.pnl - 14.40) < 1e-9


def test_grade_ml_and_under_is_hit(tmp_path) -> None:
    path = tmp_path / "ledger.csv"
    path.write_text(
        "platform,mode,n_legs,sides,lines,actuals,stake,multiplier\n"
        "hardrock,standard,3,ml|ml|under,-175|-180|39,win|win|33,10,+367\n",
        encoding="utf-8",
    )
    summary = grade_ledger(path)
    assert summary.hits == 1
    assert abs(summary.pnl - 36.70) < 1e-9


def test_grade_numeric_half_point_is_hit_not_void(tmp_path) -> None:
    path = tmp_path / "ledger.csv"
    path.write_text(
        "platform,mode,n_legs,sides,lines,actuals,stake,multiplier\n"
        "hardrock,standard,1,over,47.5,48,5,2.0\n",
        encoding="utf-8",
    )
    summary = grade_ledger(path)
    assert summary.hits == 1
    assert abs(summary.pnl - 5.0) < 1e-9


def test_grade_win_vs_win_is_hit_not_void(tmp_path) -> None:
    path = tmp_path / "ledger.csv"
    path.write_text(
        "platform,mode,n_legs,sides,lines,actuals,stake,multiplier\n"
        "hardrock,standard,1,ml,-175,win,5,2.0\n",
        encoding="utf-8",
    )
    summary = grade_ledger(path)
    assert summary.hits == 1
    assert abs(summary.pnl - 5.0) < 1e-9


def test_grade_accepts_optional_ticket_market_stake_kind(tmp_path) -> None:
    path = tmp_path / "ledger.csv"
    path.write_text(
        "ticket_id,market,stake_kind,platform,mode,legs,sides,lines,actuals,stake,multiplier,note\n"
        "t1,pass_yds,cash,underdog,standard,2,more|more,10.5|20.5,30|40,10,3.5,hello\n"
        "t2,anytime_td,bonus,underdog,standard,2,more|more,0.5|0.5,1|0,5,3.5,world\n",
        encoding="utf-8",
    )
    summary = grade_ledger(path)
    assert summary.n_slips == 2
    assert summary.bonus_stake == 5.0
    assert summary.ticket_ids == ["t1", "t2"]
    assert summary.markets == ["pass_yds", "anytime_td"]
    assert summary.stake_kinds == ["cash", "bonus"]
