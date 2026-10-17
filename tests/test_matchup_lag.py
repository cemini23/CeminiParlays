"""Locks for the matchup-gate math: lag filter, maxima, Poisson, BH, clip."""

import math

from scipy.stats import poisson

from ceminiparlays.matchup_math import (
    bh_qvalues,
    interaction,
    maxima_over_prob,
    poisson_over_prob,
    prior_to,
)
from ceminiparlays.odds import devig_two_way


def test_prior_to_is_strictly_before_target() -> None:
    """Same week is excluded; the week before and last season are included."""

    assert prior_to(2026, 6, 2026, 6) is False
    assert prior_to(2026, 5, 2026, 6) is True
    assert prior_to(2025, 18, 2026, 6) is True


def test_prior_to_filters_target_week_row() -> None:
    """A row priced for the target week never enters the lag window."""

    rows = [
        (2025, 18, 42.0),
        (2026, 5, 17.0),
        (2026, 6, 999.0),
    ]
    lagged = [
        value
        for season, week, value in rows
        if prior_to(season, week, 2026, 6)
    ]
    assert lagged == [42.0, 17.0]
    assert 999.0 not in lagged


def test_maxima_over_prob_exact_cases() -> None:
    """``1 - F ** n`` at the boundary cases."""

    assert maxima_over_prob(0.5, 2) == 0.75
    assert maxima_over_prob(1.0, 4) == 0.0
    assert maxima_over_prob(0.0, 3) == 1.0


def test_poisson_rejects_integer_line() -> None:
    """Integer lines are a void, not a price."""

    try:
        poisson_over_prob(1.0, 1)
    except ValueError:
        pass
    else:
        raise AssertionError("integer line must raise ValueError")


def test_poisson_half_point_matches_formula() -> None:
    """``P(X > 0.5) = 1 - cdf(floor(0.5)) = 1 - cdf(0)``."""

    assert poisson_over_prob(1.0, 0.5) == 1.0 - poisson.cdf(0, 1)


def test_bh_qvalues_step_largest_rank_first() -> None:
    """BH with the monotone step from largest rank to smallest."""

    raw = bh_qvalues([0.001, 0.04, 0.03, 0.2])
    expected = [0.004, 0.053333, 0.053333, 0.2]
    assert len(raw) == len(expected)
    for got, want in zip(raw, expected, strict=True):
        assert math.isclose(got, want, abs_tol=1e-6)


def test_interaction_clip_locks_both_scales() -> None:
    """The product hits both locked clips and zero."""

    assert interaction(2, 2, 0.15) == 0.15
    assert interaction(2, 2, 0.10) == 0.10
    assert interaction(0, 2, 0.15) == 0.0  # type: ignore[arg-type]


def test_devig_symmetric_dash_beans_is_fair() -> None:
    """A -115/-115 pair de-vigs to an even market."""

    result = devig_two_way(-115, -115)
    assert result.p_over == 0.5
