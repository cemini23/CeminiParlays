"""The cost of a control: flags raised and legs a cap shrinks. No order path."""

from __future__ import annotations

import pytest

from ceminiparlays.control_cost import (
    ControlCost,
    cap_sized_legs,
    cost_line,
    measure_cost,
)


def test_empty_orders_cost_zero_rate() -> None:
    cost = measure_cost("stake-cap", [], lambda size: size > 0)
    assert cost == ControlCost(
        rule_name="stake-cap",
        orders_in=0,
        orders_flagged=0,
        false_positive_rate=0.0,
    )


def test_a_rule_that_flags_everything_rates_one() -> None:
    cost = measure_cost("flag-all", [10.0, 20.0, 30.0], lambda size: True)
    assert cost.orders_in == 3
    assert cost.orders_flagged == 3
    assert cost.false_positive_rate == 1.0


def test_a_rule_that_flags_nothing_rates_zero() -> None:
    cost = measure_cost("flag-none", [10.0, 20.0, 30.0], lambda size: False)
    assert cost.orders_in == 3
    assert cost.orders_flagged == 0
    assert cost.false_positive_rate == 0.0


def test_a_partial_rule_rates_the_flagged_share() -> None:
    cost = measure_cost("big-only", [5, 50, 500, 5], lambda size: size >= 50)
    assert cost.orders_flagged == 2
    assert cost.false_positive_rate == pytest.approx(0.5)


def test_legs_under_the_cap_are_unchanged() -> None:
    legs = [10, 20, 30]
    assert cap_sized_legs(legs, 100) == legs
    assert cap_sized_legs(legs, 60) == legs


def test_legs_over_the_cap_scale_and_never_exceed_it() -> None:
    legs = [10, 20, 70]
    scaled = cap_sized_legs(legs, 50)
    assert len(scaled) == len(legs)
    assert all(isinstance(leg, int) for leg in scaled)
    assert sum(scaled) <= 50
    assert scaled[2] > scaled[1] > scaled[0]


def test_a_tight_cap_leaves_no_leg_above_its_share() -> None:
    scaled = cap_sized_legs([1, 1, 1], 2)
    assert sum(scaled) <= 2
    assert sorted(scaled, reverse=True)[:2] == [1, 1]


def test_cap_at_or_below_zero_raises_value_error() -> None:
    with pytest.raises(ValueError):
        cap_sized_legs([10, 20], 0)
    with pytest.raises(ValueError):
        cap_sized_legs([10, 20], -5)


def test_cost_line_names_the_rule_and_formats_the_rate() -> None:
    cost = measure_cost("stake-cap", [10, 200, 30, 40], lambda size: size > 100)
    line = cost_line(cost)
    assert line == "rule=stake-cap flagged=1/4 false_positive_rate=0.250"
    assert "\n" not in line
