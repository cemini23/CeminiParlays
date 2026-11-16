"""What a control costs: orders flagged, rate of flags, and legs a cap shrinks.

A control is not free. An aggregate cap that trims two-sided fills and a learned
baseline that flags a large maker's sessions both pay for themselves out of the
orders they touch. A report that names a control without pricing that trade
cannot show whether the control bought anything.

This module prices the trade in one number per rule and in one capped leg list.
It reads sizes and a predicate only. It does not run a control, touch the order
path, or place anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Callable, Sequence

__all__ = ["ControlCost", "measure_cost", "cap_sized_legs", "cost_line"]


@dataclass(frozen=True)
class ControlCost:
    """One rule's measured cost across a batch of orders."""

    rule_name: str
    orders_in: int
    orders_flagged: int
    false_positive_rate: float


def measure_cost(
    rule_name: str,
    orders: Sequence[float],
    rule: Callable[[float], bool],
) -> ControlCost:
    """Count how many ``orders`` ``rule`` flags and derive the resulting rate.

    The rate is ``orders_flagged / orders_in``, or ``0.0`` for an empty batch.
    A rule that raises on one order is read as "not flagged" for that order, so
    measuring a cost can never take the caller down with it.
    """

    flagged = 0
    for size in orders:
        try:
            if rule(size):
                flagged += 1
        except Exception:  # a misbehaving rule must not break the measurement
            continue

    orders_in = len(orders)
    rate = flagged / orders_in if orders_in else 0.0
    return ControlCost(
        rule_name=rule_name,
        orders_in=orders_in,
        orders_flagged=flagged,
        false_positive_rate=rate,
    )


def cap_sized_legs(legs: Sequence[int], cap: float) -> list[int]:
    """Scale ``legs`` down proportionally so their total fits inside ``cap``.

    Legs whose sum is already at or below ``cap`` come back unchanged. Otherwise
    each leg gets its exact proportional quota, truncated, and the whole units
    left over go to the legs with the largest fractional quota (the largest
    remainder method), so the sum lands at ``floor(cap)`` and never above it.
    """

    if cap <= 0:
        raise ValueError(f"cap must be positive, got {cap!r}")

    total = sum(legs)
    if total <= cap:
        return list(legs)

    limit = int(cap)
    quotas = [Fraction(size) * limit / Fraction(total) for size in legs]
    scaled = [quota.numerator // quota.denominator for quota in quotas]
    remainders = [quota - whole for quota, whole in zip(quotas, scaled)]
    leftover = limit - sum(scaled)

    order = sorted(range(len(legs)), key=lambda index: remainders[index], reverse=True)
    for index in order[:leftover]:
        scaled[index] += 1

    return scaled


def cost_line(cost: ControlCost) -> str:
    """Render a cost as one line: name, flags, and rate to three decimals."""

    return (
        f"rule={cost.rule_name} flagged={cost.orders_flagged}/{cost.orders_in} "
        f"false_positive_rate={cost.false_positive_rate:.3f}"
    )
