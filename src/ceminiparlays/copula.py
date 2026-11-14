from __future__ import annotations

from math import sqrt
from typing import Literal

import numpy as np
from scipy.stats import multivariate_normal, multivariate_t, norm, t

CopulaType = Literal["gaussian", "student_t"]

#: Strict positive-definiteness floor used by ``nearest_correlation``. Cholesky
#: and the multivariate normal CDF both reject a matrix whose smallest
#: eigenvalue is not strictly positive, so the guard must be strict.
_PD_EPS = 1e-9


def nearest_psd(matrix: np.ndarray, eigenvalue_floor: float = 1e-8) -> np.ndarray:
    """Symmetric PSD approximation via eigenvalue flooring."""

    array = np.nan_to_num(np.asarray(matrix, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    if array.ndim != 2 or array.shape[0] != array.shape[1]:
        raise ValueError("matrix must be square")
    symmetric = (array + array.T) / 2.0
    eigenvalues, eigenvectors = np.linalg.eigh(symmetric)
    eigenvalues = np.nan_to_num(eigenvalues, nan=eigenvalue_floor, posinf=1.0, neginf=eigenvalue_floor)
    eigenvectors = np.nan_to_num(eigenvectors, nan=0.0, posinf=0.0, neginf=0.0)
    floored = np.maximum(eigenvalues, float(eigenvalue_floor))
    # ``@`` warns inside Apple BLAS on this product even when every value
    # is finite and the product matches ``np.dot``.
    psd = np.dot(eigenvectors * floored, eigenvectors.T)
    psd = np.nan_to_num(psd, nan=0.0, posinf=0.0, neginf=0.0)
    return (psd + psd.T) / 2.0


def _as_correlation(psd: np.ndarray) -> np.ndarray:
    """Rescale a PSD matrix to a unit-diagonal correlation with off-diagonals in range."""

    corr = (psd + psd.T) / 2.0
    diagonal = np.sqrt(np.maximum(np.diag(corr), 1e-12))
    corr = corr / np.outer(diagonal, diagonal)
    corr = np.clip(corr, -0.999, 0.999)
    np.fill_diagonal(corr, 1.0)
    return corr


def nearest_correlation(matrix: np.ndarray, eigenvalue_floor: float = _PD_EPS) -> np.ndarray:
    floor = float(eigenvalue_floor)
    corr = _as_correlation(nearest_psd(matrix, eigenvalue_floor=max(floor, 1e-8)))
    # Clipping individual off-diagonals, and the unit-diagonal normalization,
    # can leave the matrix slightly indefinite. Re-project until the smallest
    # eigenvalue is STRICTLY positive: ``simulate_slip``'s Cholesky and scipy's
    # multivariate normal CDF both reject a matrix that is only PSD.
    for _ in range(10):
        if float(np.min(np.linalg.eigvalsh(corr))) > floor:
            return corr
        corr = _as_correlation(nearest_psd(corr, eigenvalue_floor=floor))
    # Final guarantee: shift the spectrum up so the matrix stays strictly
    # positive definite while keeping a unit diagonal.
    corr = (corr + corr.T) / 2.0
    smallest = float(np.min(np.linalg.eigvalsh(corr)))
    if smallest <= floor:
        corr = _as_correlation(corr + (floor - smallest) * np.eye(corr.shape[0]))
    return corr


def _copula_kind(copula_type: str) -> str:
    """``t`` is the Student-t alias. Other names stay an error."""

    token = str(copula_type or "").strip().lower().replace("-", "_")
    if token == "gaussian":
        return "gaussian"
    if token in {"t", "student_t"}:
        return "student_t"
    raise ValueError(f"unsupported copula: {copula_type}")


def exact_joint(
    marginal_probs: list[float] | np.ndarray,
    corr_matrix: np.ndarray,
    copula_type: str = "gaussian",
    df: float = 5.0,
) -> float:
    """Exact copula joint hit probability for a small slip.

    The Gaussian path is ``Phi_k(norm.ppf(p), cov=corr)``. The Student-t path
    (``copula_type`` ``t`` or ``student_t``, default ``df=5``) is the
    multivariate-t CDF at ``t.ppf(p, df)``. Deterministic, so it has no Monte
    Carlo noise.
    """

    kind = _copula_kind(copula_type)
    marginals = np.clip(np.asarray(marginal_probs, dtype=float), 1e-9, 1.0 - 1e-9)
    corr = np.asarray(corr_matrix, dtype=float)
    k = len(marginals)
    if corr.shape != (k, k):
        raise ValueError("correlation matrix shape must match marginals")
    # SciPy's multivariate CDF needs a strictly positive-definite covariance. A
    # raw prior matrix (e.g. from ``sgp_from_score_marginals``) can be
    # indefinite, so repair it only when needed, rather than raise inside SciPy
    # (A-03). An already-PD matrix is used as-is so a near-1 correlation is not
    # clipped.
    clean = (corr + corr.T) / 2.0
    np.fill_diagonal(clean, 1.0)
    if float(np.min(np.linalg.eigvalsh(clean))) <= _PD_EPS:
        clean = nearest_correlation(clean)
    if kind == "gaussian":
        thresholds = norm.ppf(marginals)
        return float(multivariate_normal.cdf(thresholds, mean=np.zeros(k), cov=clean))
    degrees = float(df)
    if not np.isfinite(degrees) or degrees <= 0.0:
        raise ValueError("student-t df must be positive")
    thresholds = t.ppf(marginals, degrees)
    # SciPy integrates the t CDF with a random stream. A fixed seed keeps
    # ``t`` and ``student_t`` on the same number.
    return float(
        multivariate_t.cdf(
            thresholds,
            loc=np.zeros(k),
            shape=clean,
            df=degrees,
            random_state=0,
        )
    )


def simulate_slip(
    marginal_probs: list[float],
    corr_matrix: np.ndarray,
    copula_type: CopulaType = "gaussian",
    df: int = 5,
    n_sims: int = 20_000,
    seed: int = 42,
) -> dict[str, float | np.ndarray]:
    """Monte Carlo copula: fraction of trials that hit k, k-1, and k-2 legs."""

    if n_sims < 1:
        raise ValueError("n_sims must be positive")
    k = len(marginal_probs)
    if k == 0:
        raise ValueError("need at least one marginal")
    if corr_matrix.shape != (k, k):
        raise ValueError("correlation matrix shape must match legs")

    rng = np.random.default_rng(seed)
    marginals = np.clip(np.asarray(marginal_probs, dtype=float), 1e-9, 1.0 - 1e-9)
    clean = nearest_correlation(corr_matrix)
    clean = np.nan_to_num(clean, nan=0.0, posinf=0.0, neginf=0.0)
    np.fill_diagonal(clean, 1.0)
    chol = np.linalg.cholesky(clean)
    if not np.isfinite(chol).all():
        chol = np.eye(k)
    independent = rng.standard_normal(size=(k, n_sims))
    # ``@`` on a wide draw warns inside Apple BLAS even when the product is
    # finite. ``np.dot`` is the same product and stays quiet.
    latent = np.dot(chol, independent)
    if not np.isfinite(latent).all():
        latent = np.nan_to_num(latent, nan=0.0, posinf=0.0, neginf=0.0)

    if copula_type == "gaussian":
        gamma = norm.ppf(marginals)
        hits = latent <= gamma[:, None]
    elif copula_type == "student_t":
        chi2 = rng.chisquare(df=df, size=n_sims)
        scaled = latent * np.sqrt(df / chi2)
        uniforms = t.cdf(scaled, df=df)
        hits = uniforms <= marginals[:, None]
    else:
        raise ValueError(f"unsupported copula: {copula_type}")

    hit_counts = np.sum(hits.astype(np.int16), axis=0)
    p_all = float(np.mean(hit_counts == k))
    return {
        "p_all": p_all,
        "p_all_se": float(sqrt(max(p_all * (1.0 - p_all), 0.0) / n_sims)),
        "p_minus_1": float(np.mean(hit_counts == (k - 1))) if k >= 1 else 0.0,
        "p_minus_2": float(np.mean(hit_counts == (k - 2))) if k >= 2 else 0.0,
        "p_naive": float(np.prod(marginals)),
        "mean_hits": float(np.mean(hit_counts)),
        "clean_correlation": clean,
    }
