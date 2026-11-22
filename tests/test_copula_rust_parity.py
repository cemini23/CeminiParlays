"""Parity suite: the Rust numeric tail against the NumPy/SciPy contract.

The Rust engine never owns the RNG. Python draws ``independent`` (and, for
Student-t, ``chi2`` after the normals) with ``np.random.default_rng(seed)`` and
passes the arrays across. Parity is therefore a property of the arithmetic:
the latent matrix, ``norm.ppf``, ``t.cdf``, the comparisons and the counts.

A missing extension must fail this module, not skip it, so the import below
raises ``RuntimeError`` with the build command at collection time.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.stats import norm, t

from ceminiparlays.copula import (
    _load_rust_engine,
    nearest_correlation,
    resolve_engine,
    simulate_slip,
)
from ceminiparlays.kelly import slip_kelly, stake_dollars
from test_copula_properties import _INDEFINITE_MATRIX

pytestmark = pytest.mark.rust_parity

#: Import fails the module (collection error) when the extension is absent.
rust = _load_rust_engine()

SEED = 42
N_SIMS = 20_000
FLOAT_KEYS = ("p_all", "p_all_se", "p_minus_1", "p_minus_2", "p_naive", "mean_hits")
COUNT_KEYS = ("p_all", "p_minus_1", "p_minus_2", "mean_hits")
MARGINALS_BY_K = {
    2: [0.62, 0.55],
    3: [0.62, 0.55, 0.48],
    4: [0.62, 0.55, 0.48, 0.58],
    6: [0.55, 0.60, 0.50, 0.45, 0.62, 0.58],
}
RHOS = [0.0, 0.4, 0.95, 0.999999]
DEGREES = [1, 2, 4, 5, 30, 80]
TAIL_SETS = {
    "lower": [1e-6, 1e-6, 1e-6],
    "middle": [0.5, 0.5, 0.5],
    "upper": [0.999, 0.999, 0.999],
}


def _equicorr(k: int, rho: float) -> np.ndarray:
    matrix = np.full((k, k), float(rho))
    np.fill_diagonal(matrix, 1.0)
    return matrix


#: k=6 with two rows nearly equal, so the correlation is barely positive definite.
_NEAR_EQUAL_K6 = np.array(
    [
        [1.0, 0.5, 0.3, 0.2, 0.1, 0.0],
        [0.5, 1.0, 0.3, 0.2, 0.1, 0.0],
        [0.3, 0.3, 1.0, 0.4, 0.2, 0.1],
        [0.2, 0.2, 0.4, 1.0, 0.3, 0.2],
        [0.1, 0.1, 0.2, 0.3, 1.0, 0.5],
        [0.0, 0.0, 0.1, 0.2, 0.5, 1.0],
    ]
)


def _both_engines(marginals, corr, copula, df=5, n_sims=N_SIMS, seed=SEED):
    python = simulate_slip(
        marginals,
        corr,
        copula_type=copula,
        df=df,
        n_sims=n_sims,
        seed=seed,
        engine="python",
    )
    rust_result = simulate_slip(
        marginals,
        corr,
        copula_type=copula,
        df=df,
        n_sims=n_sims,
        seed=seed,
        engine="rust",
    )
    return python, rust_result


def _assert_parity(python, rust_result, tol=1e-9) -> None:
    for key in FLOAT_KEYS:
        expected = float(python[key])
        got = float(rust_result[key])
        assert math.isfinite(got), f"{key} is not finite: {got}"
        assert abs(expected - got) <= tol, f"{key}: python={expected} rust={got}"
    # Same draws, same comparisons -> identical hit counts, so the count-derived
    # fractions are bit-equal, not merely close.
    for key in COUNT_KEYS:
        assert float(python[key]) == float(rust_result[key]), key


# --------------------------------------------------------------------------- #
# Gaussian: fixed draws, k in {2, 3, 4}, four correlation strengths.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("k", [2, 3, 4])
@pytest.mark.parametrize("rho", RHOS)
def test_gaussian_parity(k: int, rho: float) -> None:
    python, rust_result = _both_engines(
        MARGINALS_BY_K[k], _equicorr(k, rho), "gaussian"
    )
    _assert_parity(python, rust_result)


# --------------------------------------------------------------------------- #
# Latent matrix: the only shared arithmetic primitive, audited directly.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("copula", ["gaussian", "student_t"])
@pytest.mark.parametrize("k", [2, 3, 4, 6])
def test_latent_matrix_parity(copula: str, k: int) -> None:
    rho = 0.4 if copula == "gaussian" else 0.75
    corr = _NEAR_EQUAL_K6 if k == 6 else _equicorr(k, rho)
    clean = nearest_correlation(corr)
    chol = np.linalg.cholesky(clean)
    independent = np.random.default_rng(SEED).standard_normal(size=(k, 5_000))
    expected = np.dot(chol, independent)
    got = np.asarray(
        rust.latent_matrix(chol.ravel(), independent.ravel(), k), dtype=float
    ).reshape(k, 5_000)
    assert got.shape == expected.shape
    assert float(np.max(np.abs(expected - got))) <= 1e-12


# --------------------------------------------------------------------------- #
# Student-t: df grid crossed with lower/middle/upper marginals.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("df", DEGREES)
@pytest.mark.parametrize("tail", list(TAIL_SETS))
def test_student_t_parity(df: int, tail: str) -> None:
    python, rust_result = _both_engines(
        TAIL_SETS[tail], _equicorr(3, 0.4), "student_t", df=df
    )
    _assert_parity(python, rust_result)


# --------------------------------------------------------------------------- #
# Near-singular and indefinite correlations must stay finite and in parity.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("copula", ["gaussian", "student_t"])
@pytest.mark.parametrize("rho", [1.0 - 1e-7, -(1.0 - 1e-7)])
def test_near_singular_rho_parity(copula: str, rho: float) -> None:
    python, rust_result = _both_engines([0.55, 0.60], _equicorr(2, rho), copula)
    _assert_parity(python, rust_result)


@pytest.mark.parametrize("copula", ["gaussian", "student_t"])
def test_indefinite_matrix_parity(copula: str) -> None:
    python, rust_result = _both_engines(
        [0.5, 0.5, 0.5, 0.5], _INDEFINITE_MATRIX, copula
    )
    _assert_parity(python, rust_result)


@pytest.mark.parametrize("copula", ["gaussian", "student_t"])
def test_k6_nearly_equal_rows_parity(copula: str) -> None:
    python, rust_result = _both_engines(
        MARGINALS_BY_K[6], _NEAR_EQUAL_K6, copula
    )
    _assert_parity(python, rust_result)


# --------------------------------------------------------------------------- #
# Direct tail calls on arrays drawn once in Python: proves the RNG stays here.
# --------------------------------------------------------------------------- #
def test_rust_tail_matches_numpy_on_fixed_gaussian_arrays() -> None:
    k, n = 4, 5_000
    marginals = np.clip(np.array(MARGINALS_BY_K[k]), 1e-9, 1.0 - 1e-9)
    clean = nearest_correlation(_equicorr(k, 0.4))
    chol = np.linalg.cholesky(clean)
    independent = np.random.default_rng(7).standard_normal(size=(k, n))
    got = rust.simulate_slip(
        marginals, chol.ravel(), independent.ravel(), "gaussian", 5.0, np.empty(0)
    )
    latent = np.dot(chol, independent)
    hits = latent <= norm.ppf(marginals)[:, None]
    counts = np.sum(hits.astype(np.int16), axis=0)
    p_all = float(np.mean(counts == k))
    expected = (
        p_all,
        float(math.sqrt(max(p_all * (1.0 - p_all), 0.0) / n)),
        float(np.mean(counts == k - 1)),
        float(np.mean(counts == k - 2)),
        float(np.prod(marginals)),
        float(np.mean(counts)),
    )
    for value, want in zip(got, expected):
        assert abs(float(value) - want) <= 1e-9


def test_rust_tail_matches_numpy_on_fixed_student_t_arrays() -> None:
    k, n, df = 3, 5_000, 5.0
    marginals = np.clip(np.array([0.30, 0.45, 0.60]), 1e-9, 1.0 - 1e-9)
    clean = nearest_correlation(_equicorr(k, 0.4))
    chol = np.linalg.cholesky(clean)
    rng = np.random.default_rng(11)
    independent = rng.standard_normal(size=(k, n))
    chi2 = rng.chisquare(df=df, size=n)
    got = rust.simulate_slip(
        marginals, chol.ravel(), independent.ravel(), "student_t", df, chi2
    )
    latent = np.dot(chol, independent)
    uniforms = t.cdf(latent * np.sqrt(df / chi2), df=df)
    hits = uniforms <= marginals[:, None]
    counts = np.sum(hits.astype(np.int16), axis=0)
    p_all = float(np.mean(counts == k))
    expected = (
        p_all,
        float(math.sqrt(max(p_all * (1.0 - p_all), 0.0) / n)),
        float(np.mean(counts == k - 1)),
        float(np.mean(counts == k - 2)),
        float(np.prod(marginals)),
        float(np.mean(counts)),
    )
    for value, want in zip(got, expected):
        assert abs(float(value) - want) <= 1e-9


# --------------------------------------------------------------------------- #
# Deterministic special functions against SciPy.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "p", [1e-12, 1e-9, 1e-3, 0.5, 1.0 - 1e-3, 1.0 - 1e-9, 1.0 - 1e-12]
)
def test_norm_ppf_matches_scipy(p: float) -> None:
    got = rust.norm_ppf(p)
    want = float(norm.ppf(p))
    assert abs(got - want) <= 1e-9, f"norm_ppf({p}) = {got}, scipy {want}"


@pytest.mark.parametrize("df", [1, 2, 4, 5, 30, 80, 1000])
def test_t_cdf_matches_scipy(df: int) -> None:
    for x in (-40.0, -10.0, -3.0, -1.0, 0.0, 1.0, 3.0, 10.0, 40.0):
        got = rust.t_cdf(x, float(df))
        want = float(t.cdf(x, float(df)))
        assert abs(got - want) <= 1e-10, f"t_cdf({x}, {df}) = {got}, scipy {want}"


# --------------------------------------------------------------------------- #
# Engine resolution: explicit wins, the env var is the fallback, the kill
# switch forces python. No silent fallback to python for a missing extension.
# --------------------------------------------------------------------------- #
def test_resolve_engine_precedence(monkeypatch) -> None:
    monkeypatch.delenv("FAST_ANYTHING_DISABLE", raising=False)
    monkeypatch.delenv("CEMINIPARLAYS_ENGINE", raising=False)
    assert resolve_engine(None) == "python"
    assert resolve_engine("rust") == "rust"
    assert resolve_engine("python") == "python"
    monkeypatch.setenv("CEMINIPARLAYS_ENGINE", "rust")
    assert resolve_engine(None) == "rust"
    assert resolve_engine("python") == "python"
    monkeypatch.setenv("FAST_ANYTHING_DISABLE", "1")
    assert resolve_engine("rust") == "python"
    monkeypatch.delenv("FAST_ANYTHING_DISABLE")
    monkeypatch.delenv("CEMINIPARLAYS_ENGINE")
    with pytest.raises(ValueError):
        resolve_engine("cuda")


# --------------------------------------------------------------------------- #
# Kelly invariants: the Python policy, fed with Rust p_all values.
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def rust_cases() -> list[tuple[str, dict]]:
    cases = [
        ("gauss-2", [0.62, 0.55], _equicorr(2, 0.0), "gaussian", 5),
        ("gauss-3", [0.62, 0.55, 0.48], _equicorr(3, 0.4), "gaussian", 5),
        ("gauss-4", [0.62, 0.55, 0.48, 0.58], _equicorr(4, 0.95), "gaussian", 5),
        ("t-3-df1", [0.55, 0.50, 0.45], _equicorr(3, 0.4), "student_t", 1),
        ("t-4-df5", [0.62, 0.55, 0.48, 0.58], _equicorr(4, 0.4), "student_t", 5),
        ("t-3-tail", [1e-6, 0.5, 0.999], _equicorr(3, 0.4), "student_t", 30),
    ]
    return [
        (
            label,
            simulate_slip(
                marginals,
                corr,
                copula_type=copula,
                df=df,
                n_sims=N_SIMS,
                seed=SEED,
                engine="rust",
            ),
        )
        for label, marginals, corr, copula, df in cases
    ]


@pytest.mark.kelly_invariant
def test_kelly_on_rust_outputs_is_finite_and_capped(rust_cases) -> None:
    for label, result in rust_cases:
        value = slip_kelly(float(result["p_all"]), 12.0)
        assert math.isfinite(value), label
        assert 0.0 <= value <= 0.05, label


@pytest.mark.kelly_invariant
def test_kelly_multiplier_at_or_below_one_returns_zero(rust_cases) -> None:
    p_all = float(rust_cases[0][1]["p_all"])
    for multiplier in (1.0, 0.5, 0.0, -3.0):
        assert slip_kelly(p_all, multiplier) == 0.0


@pytest.mark.kelly_invariant
def test_kelly_quarter_fraction_is_min_of_quarter_and_cap(rust_cases) -> None:
    for label, result in rust_cases:
        p = float(result["p_all"])
        for multiplier in (1.5, 2.5, 12.23, 100.0):
            full = (p * multiplier - 1.0) / (multiplier - 1.0)
            want = min(max(full, 0.0) * 0.25, 0.05)
            assert slip_kelly(p, multiplier) == pytest.approx(want, abs=1e-15), label


@pytest.mark.kelly_invariant
def test_stake_dollars_is_in_range_and_rounded(rust_cases) -> None:
    for bankroll in (0.0, 1.0, 25.0, 1_000.0):
        for _label, result in rust_cases:
            kelly = slip_kelly(float(result["p_all"]), 12.0)
            stake = stake_dollars(bankroll, kelly)
            assert 0.0 <= stake <= bankroll
            assert stake == round(stake, 2)


@pytest.mark.kelly_invariant
def test_stake_dollars_raises_on_negative_bankroll() -> None:
    with pytest.raises(ValueError):
        stake_dollars(-1.0, 0.02)


@pytest.mark.kelly_invariant
def test_bankroll_zero_gives_zero_stake(rust_cases) -> None:
    for _label, result in rust_cases:
        kelly = slip_kelly(float(result["p_all"]), 12.0)
        assert stake_dollars(0.0, kelly) == 0.0


@pytest.mark.kelly_invariant
def test_rust_p_all_has_no_nan_or_inf(rust_cases) -> None:
    for label, result in rust_cases:
        p_all = float(result["p_all"])
        assert math.isfinite(p_all), label
        assert 0.0 <= p_all <= 1.0, label


@pytest.mark.parametrize(
    ("p_joint", "multiplier"),
    [
        (float("nan"), 12.0),
        (float("inf"), 12.0),
        (0.5, float("nan")),
        (0.5, float("inf")),
        (float("nan"), float("nan")),
        (float("inf"), float("inf")),
        (-1.0, 12.0),
        (2.0, 12.0),
    ],
)
@pytest.mark.kelly_invariant
def test_slip_kelly_nan_and_inf_inputs_stay_finite_and_capped(
    p_joint: float, multiplier: float
) -> None:
    value = slip_kelly(p_joint, multiplier)
    assert math.isfinite(value)
    assert 0.0 <= value <= 0.05
