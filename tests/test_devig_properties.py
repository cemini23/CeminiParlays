"""Property tests for the two-way de-vig.

A de-vig that leaks overround is silent: the numbers still look plausible and
every downstream EV inherits the error. These properties generate American
prices and check the sum, the bounds, and monotonicity for each method. There
is no three-way de-vig in this repo, and none is added here.
"""

from __future__ import annotations

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from ceminiparlays.odds import american_to_implied, devig_two_way

METHODS = ("multiplicative", "additive", "power")

AMERICAN = st.one_of(
    st.integers(min_value=-4000, max_value=-100),
    st.integers(min_value=100, max_value=4000),
)


def _overround_positive(odds_over: int, odds_under: int) -> bool:
    return american_to_implied(odds_over) + american_to_implied(odds_under) > 1.0


@settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.filter_too_much])
@given(AMERICAN, AMERICAN)
def test_devig_probabilities_sum_to_one(odds_over: int, odds_under: int) -> None:
    assume(_overround_positive(odds_over, odds_under))
    for method in METHODS:
        result = devig_two_way(odds_over, odds_under, method=method)
        assert abs(result.p_over + result.p_under - 1.0) <= 1e-9


@settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.filter_too_much])
@given(AMERICAN, AMERICAN)
def test_devig_probabilities_are_inside_the_unit_interval(
    odds_over: int, odds_under: int
) -> None:
    assume(_overround_positive(odds_over, odds_under))
    for method in METHODS:
        result = devig_two_way(odds_over, odds_under, method=method)
        assert 0.0 < result.p_over < 1.0
        assert 0.0 < result.p_under < 1.0


@settings(max_examples=250, deadline=None)
@given(
    st.integers(min_value=-4000, max_value=-100),
    st.integers(min_value=-4000, max_value=-100),
    AMERICAN,
)
def test_more_negative_over_odds_cannot_lower_p_over(
    over_a: int, over_b: int, odds_under: int
) -> None:
    # More negative American = higher implied probability. Keep the under fixed
    # and raise only the over side; each method must not lower ``p_over``.
    over_lo, over_hi = max(over_a, over_b), min(over_a, over_b)
    assume(over_hi < over_lo)
    for method in METHODS:
        high_implied = devig_two_way(over_hi, odds_under, method=method)
        low_implied = devig_two_way(over_lo, odds_under, method=method)
        assert high_implied.p_over >= low_implied.p_over - 1e-9
