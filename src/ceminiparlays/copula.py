from __future__ import annotations

import os
from math import sqrt
from typing import Literal

import numpy as np
from scipy.stats import multivariate_normal, multivariate_t, norm, t

CopulaType = Literal["gaussian", "student_t"]

#: Strict positive-definiteness floor used by ``nearest_correlation``. Cholesky
#: and the multivariate normal CDF both reject a matrix whose smallest
#: eigenvalue is not strictly positive, so the guard must be strict.
_PD_EPS = 1e-9

#: Engine names accepted by ``simulate_slip``. ``python`` is NumPy/SciPy and is
#: the contract; ``rust`` is the optional ``_copula_engine`` extension, which is
#: fed the already-drawn random arrays (the RNG never leaves Python).
ENGINES = ("python", "rust")
DEFAULT_ENGINE = "python"
_ENGINE_ENV = "CEMINIPARLAYS_ENGINE"
_KILL_SWITCH_ENV = "FAST_ANYTHING_DISABLE"
_RUST_BUILD_HINT = (
    "the Rust copula engine is not built; run "
    "`bash tools/rust_port/build_rust.sh` (or unset the engine and use "
    "--engine=python)"
)


def resolve_engine(engine: str | None = None) -> str:
    """Pick the ``simulate_slip`` numeric engine.

    Precedence: ``FAST_ANYTHING_DISABLE=1`` forces ``python``; an explicit
    ``engine`` argument wins next; then the ``CEMINIPARLAYS_ENGINE`` environment
    variable; then ``python``. An unknown name is a ``ValueError``.
    """

    if os.environ.get(_KILL_SWITCH_ENV, "").strip() == "1":
        return DEFAULT_ENGINE
    token = engine
    if token is None:
        token = os.environ.get(_ENGINE_ENV) or None
    if token is None:
        return DEFAULT_ENGINE
    normalized = str(token).strip().lower()
    if normalized not in ENGINES:
        raise ValueError(
            f"unsupported engine: {token!r}; choose one of {', '.join(ENGINES)}"
        )
    return normalized


def _load_rust_engine():
    """Import ``_copula_engine`` lazily. A missing build is a hard error."""

    try:
        from ceminiparlays import _copula_engine
    except ImportError as exc:  # pragma: no cover - depends on the build
        raise RuntimeError(_RUST_BUILD_HINT) from exc
    return _copula_engine


def _simulate_slip_rust(
    module,
    marginals: np.ndarray,
    chol: np.ndarray,
    independent: np.ndarray,
    copula_type: str,
    df: float,
    n_sims: int,
    rng: np.random.Generator,
    clean: np.ndarray,
) -> dict[str, float | np.ndarray]:
    """Numeric tail in Rust. ``independent`` and ``chi2`` were drawn here."""

    if copula_type == "gaussian":
        chi2 = np.empty(0, dtype=float)
    elif copula_type == "student_t":
        # Drawn after the normals so the PCG64 stream matches the python path.
        chi2 = rng.chisquare(df=df, size=n_sims)
    else:
        raise ValueError(f"unsupported copula: {copula_type}")
    p_all, p_all_se, p_minus_1, p_minus_2, p_naive, mean_hits = module.simulate_slip(
        np.ascontiguousarray(marginals, dtype=float),
        np.ascontiguousarray(chol, dtype=float).ravel(),
        np.ascontiguousarray(independent, dtype=float).ravel(),
        copula_type,
        float(df),
        np.ascontiguousarray(chi2, dtype=float),
    )
    return {
        "p_all": float(p_all),
        "p_all_se": float(p_all_se),
        "p_minus_1": float(p_minus_1),
        "p_minus_2": float(p_minus_2),
        "p_naive": float(p_naive),
        "mean_hits": float(mean_hits),
        "clean_correlation": clean,
    }


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
    *,
    engine: str | None = None,
) -> dict[str, float | np.ndarray]:
    """Monte Carlo copula: fraction of trials that hit k, k-1, and k-2 legs.

    ``engine`` is resolved by :func:`resolve_engine`: ``None`` means "follow the
    environment" (``CEMINIPARLAYS_ENGINE``, then ``python``), so the default
    behaviour is the NumPy/SciPy path and is the contract. ``engine="rust"``
    keeps the same draws and moves only the numeric tail into the
    ``_copula_engine`` extension; a missing extension raises ``RuntimeError``
    rather than falling back silently.
    """

    if n_sims < 1:
        raise ValueError("n_sims must be positive")
    k = len(marginal_probs)
    if k == 0:
        raise ValueError("need at least one marginal")
    if corr_matrix.shape != (k, k):
        raise ValueError("correlation matrix shape must match legs")

    resolved = resolve_engine(engine)
    rust_module = _load_rust_engine() if resolved == "rust" else None

    rng = np.random.default_rng(seed)
    marginals = np.clip(np.asarray(marginal_probs, dtype=float), 1e-9, 1.0 - 1e-9)
    clean = nearest_correlation(corr_matrix)
    clean = np.nan_to_num(clean, nan=0.0, posinf=0.0, neginf=0.0)
    np.fill_diagonal(clean, 1.0)
    chol = np.linalg.cholesky(clean)
    if not np.isfinite(chol).all():
        chol = np.eye(k)
    independent = rng.standard_normal(size=(k, n_sims))
    if resolved == "rust":
        return _simulate_slip_rust(
            rust_module,
            marginals,
            chol,
            independent,
            copula_type,
            df,
            n_sims,
            rng,
            clean,
        )
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
