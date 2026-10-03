"""Property tests for the Gaussian/Student-t copula helpers.

``exact_joint`` is deterministic, so the Gaussian claims are properties of the
multivariate normal CDF rather than Monte Carlo noise. The Student-t path stays
on ``simulate_slip`` because ``exact_joint`` rejects a non-Gaussian copula.
"""

from __future__ import annotations

import math

import numpy as np
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ceminiparlays.copula import exact_joint, nearest_correlation, simulate_slip

MARGINALS = st.floats(
    min_value=0.05, max_value=0.95, allow_nan=False, allow_infinity=False
)
RHO = st.floats(min_value=0.0, max_value=0.95, allow_nan=False, allow_infinity=False)
N_SIMS = 200_000

#: Moderate, non-degenerate scenarios. Away from the symmetric and near-zero-rho
#: corners, the df=4 tail dependence is large relative to the Monte Carlo
#: standard error at ``N_SIMS``, so the strict df comparison is a property of
#: the copula rather than of one lucky seed.
T_SCENARIOS = [
    (0.30, 0.60, 0.20),
    (0.35, 0.65, 0.30),
    (0.40, 0.70, 0.25),
    (0.45, 0.70, 0.40),
    (0.30, 0.65, 0.35),
    (0.40, 0.65, 0.40),
]


def _corr(rho: float) -> np.ndarray:
    return np.array([[1.0, rho], [rho, 1.0]])


@settings(max_examples=200, deadline=None)
@given(MARGINALS, MARGINALS, RHO)
def test_gaussian_joint_sits_between_product_and_smaller_marginal(
    p1: float, p2: float, rho: float
) -> None:
    joint = exact_joint([p1, p2], _corr(rho))
    assert joint >= p1 * p2 - 1e-6
    assert joint <= min(p1, p2) + 1e-6


@settings(max_examples=200, deadline=None)
@given(MARGINALS, MARGINALS)
def test_gaussian_joint_at_rho_zero_is_the_product(p1: float, p2: float) -> None:
    joint = exact_joint([p1, p2], _corr(0.0))
    assert abs(joint - p1 * p2) <= 1e-5


@settings(max_examples=150, deadline=None)
@given(MARGINALS, MARGINALS, st.floats(0.0, 0.90), st.floats(1e-3, 0.05))
def test_higher_rho_moves_joint_up_toward_smaller_marginal(
    p1: float, p2: float, rho: float, step: float
) -> None:
    low = exact_joint([p1, p2], _corr(rho))
    high = exact_joint([p1, p2], _corr(rho + step))
    assert high >= low - 1e-9
    # It may approach the smaller marginal but never cross it.
    assert high <= min(p1, p2) + 1e-6


@settings(max_examples=200, deadline=None)
@given(MARGINALS, MARGINALS, st.floats(0.0, 0.94))
def test_rho_step_changes_joint_by_a_finite_amount(
    p1: float, p2: float, rho: float
) -> None:
    delta = exact_joint([p1, p2], _corr(rho + 0.01)) - exact_joint([p1, p2], _corr(rho))
    assert math.isfinite(delta)


@st.composite
def square_matrices(draw: st.DrawFn) -> np.ndarray:
    n = draw(st.integers(min_value=2, max_value=4))
    values = draw(
        st.lists(
            st.floats(-1.0, 1.0, allow_nan=False, allow_infinity=False),
            min_size=n * n,
            max_size=n * n,
        )
    )
    return np.array(values, dtype=float).reshape(n, n)


@settings(max_examples=150, deadline=None)
@given(square_matrices())
def test_nearest_correlation_is_positive_semi_definite(matrix: np.ndarray) -> None:
    corr = nearest_correlation(matrix)
    assert float(np.min(np.linalg.eigvalsh(corr))) >= -1e-8


@settings(max_examples=6, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.sampled_from(T_SCENARIOS), st.integers(min_value=0, max_value=9))
def test_student_t_moves_toward_gaussian_as_df_grows(
    scenario: tuple[float, float, float], seed: int
) -> None:
    p1, p2, rho = scenario
    marginals = [p1, p2]
    corr = _corr(rho)
    gaussian = simulate_slip(
        marginals, corr, copula_type="gaussian", n_sims=N_SIMS, seed=seed
    )["p_all"]
    t4 = simulate_slip(
        marginals, corr, copula_type="student_t", df=4, n_sims=N_SIMS, seed=seed
    )["p_all"]
    t80 = simulate_slip(
        marginals, corr, copula_type="student_t", df=80, n_sims=N_SIMS, seed=seed
    )["p_all"]
    assert abs(t80 - gaussian) < abs(t4 - gaussian)
