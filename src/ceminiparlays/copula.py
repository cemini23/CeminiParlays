from __future__ import annotations

from typing import Literal

import numpy as np
from scipy.stats import norm, t

CopulaType = Literal["gaussian", "student_t"]


def nearest_psd(matrix: np.ndarray, eigenvalue_floor: float = 1e-8) -> np.ndarray:
    """Symmetric PSD approximation via eigenvalue flooring."""

    array = np.asarray(matrix, dtype=float)
    if array.ndim != 2 or array.shape[0] != array.shape[1]:
        raise ValueError("matrix must be square")
    symmetric = (array + array.T) / 2.0
    eigenvalues, eigenvectors = np.linalg.eigh(symmetric)
    floored = np.maximum(eigenvalues, eigenvalue_floor)
    psd = (eigenvectors * floored) @ eigenvectors.T
    return (psd + psd.T) / 2.0


def nearest_correlation(matrix: np.ndarray) -> np.ndarray:
    psd = nearest_psd(matrix)
    diagonal = np.sqrt(np.maximum(np.diag(psd), 1e-12))
    corr = psd / np.outer(diagonal, diagonal)
    corr = np.clip((corr + corr.T) / 2.0, -0.999, 0.999)
    np.fill_diagonal(corr, 1.0)
    return corr


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
    chol = np.linalg.cholesky(clean)
    independent = rng.standard_normal(size=(k, n_sims))
    latent = chol @ independent

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
    return {
        "p_all": float(np.mean(hit_counts == k)),
        "p_minus_1": float(np.mean(hit_counts == (k - 1))) if k >= 1 else 0.0,
        "p_minus_2": float(np.mean(hit_counts == (k - 2))) if k >= 2 else 0.0,
        "p_naive": float(np.prod(marginals)),
        "mean_hits": float(np.mean(hit_counts)),
        "clean_correlation": clean,
    }
