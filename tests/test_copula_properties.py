"""Property tests for the Gaussian/Student-t copula helpers.

``exact_joint`` is deterministic, so the Gaussian claims are properties of the
multivariate normal CDF rather than Monte Carlo noise. The Student-t path stays
on ``simulate_slip`` because ``exact_joint`` rejects a non-Gaussian copula.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
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
def test_higher_rho_never_lowers_joint_and_never_exceeds_smaller_marginal(
    p1: float, p2: float, rho: float, step: float
) -> None:
    low = exact_joint([p1, p2], _corr(rho))
    high = exact_joint([p1, p2], _corr(rho + step))
    assert high >= low - 1e-9
    # It may approach the smaller marginal but never cross it.
    assert high <= min(p1, p2) + 1e-6


@settings(max_examples=200, deadline=None)
@given(MARGINALS, MARGINALS, st.floats(0.0, 0.94))
def test_higher_rho_step_does_not_lower_joint(
    p1: float, p2: float, rho: float
) -> None:
    delta = exact_joint([p1, p2], _corr(rho + 0.01)) - exact_joint([p1, p2], _corr(rho))
    assert delta >= -1e-12


@pytest.mark.parametrize("p1, p2", [(0.20, 0.80), (0.30, 0.60), (0.10, 0.90)])
def test_joint_approaches_smaller_marginal_as_rho_goes_to_one(p1: float, p2: float) -> None:
    # Asymmetric pairs: the gap is O(sqrt(1 - rho)) but small enough at these
    # marginals that a fixed absolute bound holds. Close marginals need the
    # convergence test below instead.
    for rho in (0.99, 0.999):
        joint = exact_joint([p1, p2], _corr(rho))
        assert abs(joint - min(p1, p2)) <= 1e-4


def test_joint_gap_shrinks_toward_min_marginal_for_symmetric_pairs() -> None:
    # The Gaussian-copula joint tends to min(p1, p2) as rho -> 1, but the gap is
    # O(sqrt(1 - rho)), so it shrinks slowly when the two marginals are close.
    # Assert monotone shrinkage, not a fixed absolute tolerance.
    gaps = [
        abs(exact_joint([0.5, 0.5], _corr(rho)) - 0.5)
        for rho in (0.90, 0.99, 0.999, 0.9999)
    ]
    assert all(a > b for a, b in zip(gaps, gaps[1:]))
    assert 0.0 < gaps[-1] < 3e-3


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
def test_nearest_correlation_is_positive_definite(matrix: np.ndarray) -> None:
    corr = nearest_correlation(matrix)
    assert float(np.min(np.linalg.eigvalsh(corr))) > 0


#: Reproducer for the PSD-guard defect: the smallest eigenvalue was -1.16e-9,
#: so Cholesky and the multivariate normal CDF both raised on the output.
_INDEFINITE_MATRIX = np.array(
    [
        [0.7269640219873539, 0.11588504729418059, 0.4839917306043495, -0.007491767882153999],
        [-0.9605856174556551, 0.33975068832180444, -0.015694276799716134, 0.8636917566326356],
        [0.5235072585744627, -0.16082528756892933, -0.5018161080625936, -0.5504949583047589],
        [-0.3952072749399689, 0.8737550871273578, 0.36408366399359293, -0.4749664652355181],
    ]
)


def test_nearest_correlation_returns_strictly_positive_definite_matrix() -> None:
    corr = nearest_correlation(_INDEFINITE_MATRIX)
    assert float(np.min(np.linalg.eigvalsh(corr))) > 0
    np.linalg.cholesky(corr)  # Must not raise.


def test_simulate_slip_accepts_an_almost_indefinite_matrix() -> None:
    result = simulate_slip([0.5, 0.5, 0.5, 0.5], _INDEFINITE_MATRIX, n_sims=200, seed=3)
    assert math.isfinite(result["p_all"])


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
