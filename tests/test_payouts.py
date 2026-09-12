from math import isclose, sqrt

from ceminiparlays.payouts import breakeven_per_leg, implied_slip_win, resolve_payout


def test_prizepicks_two_pick_power_breakeven() -> None:
    table = resolve_payout("prizepicks", "power", 2)
    assert table.all_hit == 3.0
    assert isclose(breakeven_per_leg(table.all_hit, 2), 1 / sqrt(3), rel_tol=1e-6)
    assert isclose(implied_slip_win(table.all_hit), 1 / 3, rel_tol=1e-6)


def test_underdog_two_pick_standard_is_richer() -> None:
    ud = resolve_payout("underdog", "standard", 2)
    pp = resolve_payout("prizepicks", "power", 2)
    assert ud.all_hit == 3.5
    assert breakeven_per_leg(ud.all_hit, 2) < breakeven_per_leg(pp.all_hit, 2)


def test_displayed_multiplier_overrides_table() -> None:
    table = resolve_payout("underdog", "standard", 2, displayed_multiplier=2.8)
    assert table.all_hit == 2.8


def test_flex_partial_row() -> None:
    table = resolve_payout("prizepicks", "flex", 5)
    assert table.minus_1 == 2.0
    assert table.minus_2 == 0.4
    assert table.multiplier_for_hits(5) == 10.0
    assert table.multiplier_for_hits(3) == 0.4
    assert table.multiplier_for_hits(2) == 0.0
