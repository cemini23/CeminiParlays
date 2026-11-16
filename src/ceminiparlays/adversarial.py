"""Adversarial split-order search.

A rule set that passes a quiet test is not proven compliant. A passing test is
only evidence once a constructed evasion attempt fails to get through it. This
module builds that attempt: it enumerates every way to split an order into
legs and reports the splits that a rule accepts even though no single unsplit
order would have produced them.

The module only enumerates schedules and compares them against a caller's rule.
It does not place orders, it does not grade, and it does not touch the order
path.
"""

from __future__ import annotations

from typing import Callable

#: A rule takes one schedule and returns True when that schedule is rejected.
Rule = Callable[[tuple[int, ...]], bool]


def _compositions(total: int, leg_count: int) -> list[tuple[int, ...]]:
    """Return the positive-leg compositions of ``total`` into exactly ``leg_count`` legs.

    Compositions are ordered lexicographically: the first leg runs upward and
    each remainder is itself lexicographic.
    """

    if leg_count == 1:
        return [(total,)]
    compositions: list[tuple[int, ...]] = []
    # The first leg may use at most ``total - (leg_count - 1)``, leaving one
    # unit for each remaining leg.
    for first in range(1, total - leg_count + 2):
        for rest in _compositions(total - first, leg_count - 1):
            compositions.append((first, *rest))
    return compositions


def split_schedules(total: int, max_legs: int) -> list[tuple[int, ...]]:
    """Return every way to split ``total`` into 1..``max_legs`` positive legs.

    Schedules are ordered by leg count, then lexicographically within a leg
    count. A non-positive ``total`` or ``max_legs`` yields an empty list rather
    than an error, and no schedule ever carries more legs than ``total``.
    """

    if total <= 0 or max_legs <= 0:
        return []

    schedules: list[tuple[int, ...]] = []
    leg_cap = min(max_legs, total)
    for leg_count in range(1, leg_cap + 1):
        schedules.extend(_compositions(total, leg_count))
    return schedules


def _accepted_evasions(
    schedules: list[tuple[int, ...]], total: int, rule: Rule
) -> list[tuple[int, ...]]:
    """Keep the accepted schedules that an unsplit order would not have produced."""

    unsplit = (total,)
    return [schedule for schedule in schedules if schedule != unsplit and not rule(schedule)]


def find_evasions(total: int, max_legs: int, rule: Rule) -> list[tuple[int, ...]]:
    """Return the schedules ``rule`` accepts that an unsplit order would not produce.

    ``rule`` returns True when a schedule is rejected, so this function keeps the
    schedules it returns False for. The unsplit schedule ``(total,)`` is the
    single order itself and is never an evasion, however the rule scores it.
    """

    return _accepted_evasions(split_schedules(total, max_legs), total, rule)


def _format_schedule(schedule: tuple[int, ...]) -> str:
    return "(" + ", ".join(str(leg) for leg in schedule) + ")"


def evasion_report(total: int, max_legs: int, rule: Rule) -> str:
    """Return a one-line summary of the evasion search for ``total`` and ``max_legs``.

    The line begins ``tested=N evasions=M`` and is followed by up to three
    example schedules, each in parentheses. ``N`` counts every schedule tested,
    including the unsplit one.
    """

    schedules = split_schedules(total, max_legs)
    evasions = _accepted_evasions(schedules, total, rule)
    line = f"tested={len(schedules)} evasions={len(evasions)}"
    examples = " ".join(_format_schedule(schedule) for schedule in evasions[:3])
    if examples:
        line = f"{line} examples={examples}"
    return line
