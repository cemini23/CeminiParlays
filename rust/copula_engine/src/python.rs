//! PyO3 surface. Only the four exported names live here; the numerics are in
//! `engine` and `math` so they can be unit-tested without linking libpython.

use pyo3::buffer::PyBuffer;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::engine::{self, Copula};
use crate::math;

/// Copy a float64 sequence into a `Vec<f64>`.
///
/// `PyBuffer` handles NumPy arrays and `memoryview` objects with one memcpy and
/// no per-element Python objects. A plain list has no buffer protocol, so it
/// falls back to the sequence extractor.
fn read_f64(py: Python<'_>, obj: &Bound<'_, PyAny>) -> PyResult<Vec<f64>> {
    if let Ok(buffer) = PyBuffer::<f64>::get(obj) {
        let length = buffer.item_count();
        if length == 0 {
            return Ok(Vec::new());
        }
        if buffer.is_c_contiguous() {
            let mut out = vec![0.0f64; length];
            buffer.copy_to_slice(py, &mut out)?;
            return Ok(out);
        }
    }
    obj.extract::<Vec<f64>>()
}

fn parse_copula(token: &str) -> PyResult<Copula> {
    match token.trim().to_lowercase().replace('-', "_").as_str() {
        "gaussian" => Ok(Copula::Gaussian),
        "t" | "student_t" => Ok(Copula::StudentT),
        other => Err(PyValueError::new_err(format!(
            "unsupported copula: {other}"
        ))),
    }
}

/// `simulate_slip(marginals, chol, independent, copula, df, chi2) -> tuple`
///
/// Returns `(p_all, p_all_se, p_minus_1, p_minus_2, p_naive, mean_hits)`.
/// `chol` is `k*k` row-major from `np.linalg.cholesky`, `independent` is
/// `k*n_sims` row-major, `chi2` is `n_sims` (empty for gaussian).
#[pyfunction]
fn simulate_slip(
    py: Python<'_>,
    marginals: &Bound<'_, PyAny>,
    chol: &Bound<'_, PyAny>,
    independent: &Bound<'_, PyAny>,
    copula: &str,
    df: f64,
    chi2: &Bound<'_, PyAny>,
) -> PyResult<(f64, f64, f64, f64, f64, f64)> {
    let marginals = read_f64(py, marginals)?;
    let chol = read_f64(py, chol)?;
    let independent = read_f64(py, independent)?;
    let chi2 = read_f64(py, chi2)?;
    let kind = parse_copula(copula)?;
    let result = py.detach(move || engine::simulate(&marginals, &chol, &independent, kind, df, &chi2))
        .map_err(PyValueError::new_err)?;
    Ok((
        result.p_all,
        result.p_all_se,
        result.p_minus_1,
        result.p_minus_2,
        result.p_naive,
        result.mean_hits,
    ))
}

/// `latent_matrix(chol, independent, k) -> list[float]`, row-major.
///
/// Exported for parity auditing only: it returns the same values the internal
/// tail uses, including the non-finite to 0.0 mapping.
#[pyfunction]
fn latent_matrix(
    py: Python<'_>,
    chol: &Bound<'_, PyAny>,
    independent: &Bound<'_, PyAny>,
    k: usize,
) -> PyResult<Vec<f64>> {
    let chol = read_f64(py, chol)?;
    let independent = read_f64(py, independent)?;
    if k == 0 {
        return Err(PyValueError::new_err("need at least one marginal"));
    }
    if chol.len() != k * k {
        return Err(PyValueError::new_err(format!(
            "chol must hold k*k={} values, got {}",
            k * k,
            chol.len()
        )));
    }
    if independent.len() % k != 0 {
        return Err(PyValueError::new_err(format!(
            "independent must hold k*n_sims values, got {} for k={k}",
            independent.len()
        )));
    }
    let n = independent.len() / k;
    Ok(py.detach(move || engine::latent_matrix(&chol, k, &independent, n)))
}

/// `norm_ppf(p)` — Wichura AS241 inverse normal CDF.
#[pyfunction]
fn norm_ppf(p: f64) -> f64 {
    math::norm_ppf(p)
}

/// `t_cdf(x, df)` — Student-t CDF via the regularized incomplete beta.
#[pyfunction]
fn t_cdf(x: f64, df: f64) -> f64 {
    math::t_cdf(x, df)
}

#[pymodule]
fn _copula_engine(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    module.add_function(wrap_pyfunction!(simulate_slip, module)?)?;
    module.add_function(wrap_pyfunction!(latent_matrix, module)?)?;
    module.add_function(wrap_pyfunction!(norm_ppf, module)?)?;
    module.add_function(wrap_pyfunction!(t_cdf, module)?)?;
    Ok(())
}
