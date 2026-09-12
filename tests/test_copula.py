import numpy as np
import pytest

from ceminiparlays.copula import exact_joint, nearest_correlation, simulate_slip
from ceminiparlays.payouts import power_ev


def test_positive_correlation_lifts_joint_vs_product() -> None:
    corr = np.array([[1.0, 0.40], [0.40, 1.0]])
    sim = simulate_slip([0.55, 0.55], corr, n_sims=80_000, seed=7)
    assert sim["p_all"] > sim["p_naive"]
    assert 0.34 < sim["p_all"] < 0.40
    ev_naive = power_ev(sim["p_naive"], 3.0)
    ev_joint = power_ev(sim["p_all"], 3.0)
    assert ev_joint > ev_naive


def test_nearest_correlation_repairs_psd() -> None:
    broken = np.array([[1.0, 0.9, 0.9], [0.9, 1.0, -0.9], [0.9, -0.9, 1.0]])
    clean = nearest_correlation(broken)
    assert np.all(np.linalg.eigvalsh(clean) > -1e-8)
    assert np.allclose(np.diag(clean), 1.0)


def test_exact_joint_two_independent_legs_is_point_two_five() -> None:
    joint = exact_joint([0.5, 0.5], np.eye(2))
    assert joint == pytest.approx(0.25, abs=1e-6)


def test_exact_joint_positive_correlation_exceeds_naive() -> None:
    corr = np.array([[1.0, 0.4], [0.4, 1.0]])
    joint = exact_joint([0.55, 0.55], corr)
    assert joint > 0.55 * 0.55


def test_exact_joint_shape_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="shape must match"):
        exact_joint([0.5, 0.5], np.eye(3))


def test_mc_reports_standard_error() -> None:
    sim = simulate_slip([0.5, 0.5], np.eye(2), n_sims=1000, seed=3)
    p = sim["p_all"]
    assert sim["p_all_se"] == pytest.approx((p * (1 - p) / 1000) ** 0.5, rel=1e-9)
