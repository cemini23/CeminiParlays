from math import isclose, sqrt

import pytest

from ceminiparlays.payouts import (
    breakeven_per_leg,
    implied_slip_win,
    normalize_platform,
    resolve_payout,
)


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


def test_zero_multiplier_is_rejected_not_treated_as_missing() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        resolve_payout("underdog", "standard", 2, displayed_multiplier=0.0)
    with pytest.raises(ValueError, match="must be positive"):
        resolve_payout("underdog", "standard", 2, displayed_multiplier=-1.0)


def test_sportsbook_multiplier_must_be_greater_than_one() -> None:
    with pytest.raises(ValueError, match="greater than 1"):
        resolve_payout("hardrock", "standard", 2, displayed_multiplier=1.0)
    with pytest.raises(ValueError, match="greater than 1"):
        resolve_payout("fanduel", "standard", 2, displayed_multiplier=0.5)


def test_flex_partial_row() -> None:
    table = resolve_payout("prizepicks", "flex", 5)
    assert table.minus_1 == 2.0
    assert table.minus_2 == 0.4
    assert table.multiplier_for_hits(5) == 10.0
    assert table.multiplier_for_hits(3) == 0.4
    assert table.multiplier_for_hits(2) == 0.0


def test_flex_notes_table_partials() -> None:
    table = resolve_payout("prizepicks", "flex", 5)
    assert "flex_partials=table" in table.note


def test_missing_underdog_flex_two_leg_message() -> None:
    with pytest.raises(ValueError) as excinfo:
        resolve_payout("underdog", "flex", 2)
    message = str(excinfo.value)
    assert "Underdog flex has no 2-leg row" in message
    assert "Use standard or slip-size 3+" in message


def test_missing_prizepicks_flex_two_leg_message() -> None:
    with pytest.raises(ValueError, match="PrizePicks flex has no 2-leg row"):
        resolve_payout("prizepicks", "flex", 2)


def test_hardrock_requires_a_displayed_price() -> None:
    with pytest.raises(ValueError, match="no fixed lounge table"):
        resolve_payout("hardrock", "standard", 2)


def test_hardrock_accepts_alias_and_displayed_odds_as_decimal() -> None:
    table = resolve_payout("hr", "standard", 2, displayed_multiplier=2.6)
    assert table.platform == "hardrock"
    assert table.all_hit == 2.6


def test_hardrock_rejects_flex() -> None:
    with pytest.raises(ValueError, match="Flex Parlay is not modeled"):
        resolve_payout("hardrock", "flex", 3, displayed_multiplier=3.0)


def test_fanduel_requires_a_displayed_price() -> None:
    with pytest.raises(ValueError, match="no fixed lounge table"):
        resolve_payout("fanduel", "standard", 2)


def test_draftkings_requires_a_displayed_price() -> None:
    with pytest.raises(ValueError, match="no fixed lounge table"):
        resolve_payout("draftkings", "standard", 2)


def test_sportsbook_aliases_fd_and_dk() -> None:
    assert normalize_platform("fd") == "fanduel"
    assert normalize_platform("dk") == "draftkings"
    table = resolve_payout("fd", "standard", 2, displayed_multiplier=2.5)
    assert table.platform == "fanduel"
    assert table.all_hit == 2.5
    table = resolve_payout("dk", "standard", 2, displayed_multiplier=2.7)
    assert table.platform == "draftkings"
    assert table.all_hit == 2.7


def test_fanduel_and_draftkings_reject_flex() -> None:
    with pytest.raises(ValueError, match="Flex Parlay is not modeled"):
        resolve_payout("fanduel", "flex", 3, displayed_multiplier=3.0)
    with pytest.raises(ValueError, match="Flex Parlay is not modeled"):
        resolve_payout("draftkings", "flex", 3, displayed_multiplier=3.0)


def test_missing_prizepicks_power_seven_leg_message() -> None:
    with pytest.raises(ValueError) as excinfo:
        resolve_payout("prizepicks", "power", 7)
    message = str(excinfo.value)
    assert "PrizePicks power has no 7-leg row" in message
    assert "slip-size 2-6" in message
