"""Adversarial split-order search. Pure enumeration, no order path."""

from __future__ import annotations

from ceminiparlays.adversarial import (
    evasion_report,
    find_evasions,
    split_schedules,
)


def _reject_nothing(schedule: tuple[int, ...]) -> bool:
    return False


def _reject_everything(schedule: tuple[int, ...]) -> bool:
    return True


def _reject_four_legs(schedule: tuple[int, ...]) -> bool:
    return len(schedule) >= 4


def test_a_zero_total_returns_an_empty_list_without_raising() -> None:
    assert split_schedules(0, 5) == []


def test_a_negative_total_returns_an_empty_list_without_raising() -> None:
    assert split_schedules(-3, 5) == []


def test_a_non_positive_leg_cap_returns_an_empty_list_without_raising() -> None:
    assert split_schedules(5, 0) == []
    assert split_schedules(5, -1) == []


def test_leg_counts_stay_inside_the_cap_and_sum_to_the_total() -> None:
    total = 9
    max_legs = 4
    schedules = split_schedules(total, max_legs)
    assert schedules
    for schedule in schedules:
        assert 1 <= len(schedule) <= max_legs
        assert sum(schedule) == total
        assert all(leg > 0 for leg in schedule)


def test_no_schedule_carries_more_legs_than_the_total() -> None:
    for schedule in split_schedules(3, 10):
        assert len(schedule) <= 3


def test_every_split_into_the_cap_is_present() -> None:
    assert split_schedules(4, 2) == [
        (4,),
        (1, 3),
        (2, 2),
        (3, 1),
    ]


def test_schedules_are_ordered_by_leg_count_then_lexicographic() -> None:
    schedules = split_schedules(4, 3)
    leg_counts = [len(schedule) for schedule in schedules]
    assert leg_counts == sorted(leg_counts)
    for leg_count in set(leg_counts):
        group = [schedule for schedule in schedules if len(schedule) == leg_count]
        assert group == sorted(group)
    assert schedules[:1] == [(4,)]
    assert schedules[1:4] == [(1, 3), (2, 2), (3, 1)]
    assert schedules[4:] == [(1, 1, 2), (1, 2, 1), (2, 1, 1)]


def test_a_rule_that_rejects_nothing_yields_evasions_for_a_splittable_total() -> None:
    evasions = find_evasions(4, 2, _reject_nothing)
    assert evasions == [(1, 3), (2, 2), (3, 1)]


def test_the_unsplit_schedule_is_never_reported() -> None:
    evasions = find_evasions(5, 4, _reject_nothing)
    assert (5,) not in evasions
    assert all(schedule != (5,) for schedule in evasions)


def test_the_unsplit_schedule_stays_out_even_when_the_rule_accepts_only_it() -> None:
    def rule(schedule: tuple[int, ...]) -> bool:
        return schedule != (5,)

    assert find_evasions(5, 3, rule) == []


def test_a_rule_that_rejects_every_schedule_yields_no_evasions() -> None:
    assert find_evasions(6, 3, _reject_everything) == []
    assert find_evasions(6, 3, _reject_everything) == find_evasions(6, 3, lambda _: True)


def test_evasions_are_the_accepted_schedules_the_rule_actually_kept() -> None:
    evasions = find_evasions(6, 4, _reject_four_legs)
    assert evasions
    assert all(len(schedule) < 4 for schedule in evasions)
    assert all(not _reject_four_legs(schedule) for schedule in evasions)


def test_a_single_leg_cap_has_no_evasions() -> None:
    assert find_evasions(5, 1, _reject_nothing) == []


def test_evasion_report_counts_match_find_evasions() -> None:
    for total in range(0, 8):
        for max_legs in range(0, 5):
            line = evasion_report(total, max_legs, _reject_nothing)
            assert line.startswith(
                f"tested={len(split_schedules(total, max_legs))} "
                f"evasions={len(find_evasions(total, max_legs, _reject_nothing))}"
            )


def test_evasion_report_shows_at_most_three_examples_in_parentheses() -> None:
    line = evasion_report(6, 4, _reject_nothing)
    assert line.startswith("tested=26 evasions=25")
    assert line.count("(") == 3
    assert line.count(")") == 3
    assert "(1, 5)" in line
    assert "\n" not in line


def test_evasion_report_with_no_evasions_has_no_examples() -> None:
    line = evasion_report(6, 3, _reject_everything)
    assert line.startswith("tested=16 evasions=0")
    assert "(" not in line
    assert "\n" not in line


def test_evasion_report_of_a_degenerate_total_is_a_single_line() -> None:
    line = evasion_report(0, 3, _reject_nothing)
    assert line.startswith("tested=0 evasions=0")
    assert "\n" not in line
