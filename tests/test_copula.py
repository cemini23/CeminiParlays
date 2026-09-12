import numpy as np

from ceminiparlays.copula import nearest_correlation, simulate_slip
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
