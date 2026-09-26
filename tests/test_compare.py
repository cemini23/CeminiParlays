from ceminiparlays.compare import pickem_gap
from ceminiparlays.payouts import resolve_payout


def test_compare_prizepicks_two_leg_gap() -> None:
    # -110/-110 -> fair_p = 0.5, 2 legs -> fair_joint = 0.25, fair_decimal = 4.0
    # PrizePicks power 2-leg all = 3.0
    # gap = 4.0 - 3.0 = 1.0
    report = pickem_gap(-110, -110, "prizepicks", 2, "power", "power", "over")
    assert abs(report.fair_p - 0.5) < 1e-9
    assert abs(report.fair_joint - 0.25) < 1e-9
    assert abs(report.fair_decimal - 4.0) < 1e-9
    assert report.table_all == 3.0
    assert abs(report.gap - 1.0) < 1e-9


def test_compare_underdog_two_leg_gap() -> None:
    # Same fair price: fair_decimal = 4.0
    # Underdog standard 2-leg all = 3.5
    # gap = 4.0 - 3.5 = 0.5
    report = pickem_gap(-110, -110, "underdog", 2, "standard", "power", "over")
    assert report.table_all == 3.5
    assert abs(report.gap - 0.5) < 1e-9


def test_compare_displayed_multiplier_echoed_but_not_used_in_gap() -> None:
    # displayed_multiplier is echoed in the report but gap uses table value
    report = pickem_gap(
        -110, -110, "underdog", 2, "standard", "power", "over", displayed_multiplier=2.8
    )
    assert report.displayed_multiplier == 2.8
    # gap still uses table 3.5, not 2.8
    assert report.table_all == 3.5
    assert abs(report.gap - 0.5) < 1e-9


def test_compare_resolve_payout_still_uses_displayed_multiplier() -> None:
    # The resolve_payout function itself still honors displayed_multiplier
    table = resolve_payout("underdog", "standard", 2, displayed_multiplier=2.8)
    assert table.all_hit == 2.8


def test_compare_side_under_uses_p_under() -> None:
    # -155 / 120 market
    # p_over ~ 0.58, p_under ~ 0.42
    report = pickem_gap(-155, 120, "prizepicks", 2, "power", "power", "under")
    assert report.side == "under"
    # p_under should be < 0.5
    assert report.fair_p < 0.5
    # fair_decimal should be > 4.0 (since p < 0.5)
    assert report.fair_decimal > 4.0


def test_compare_missing_table_row_raises() -> None:
    # PrizePicks power only goes to 6 legs
    try:
        pickem_gap(-110, -110, "prizepicks", 7, "power", "power", "over")
        assert False, "should have raised"
    except ValueError as exc:
        assert "no 7-leg row" in str(exc)