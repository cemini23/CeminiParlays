//! The numeric tail of `ceminiparlays.copula.simulate_slip`.
//!
//! Python owns the RNG (NumPy PCG64) and draws `independent` (`k x n_sims`,
//! row-major) plus, for Student-t, `chi2` (`n_sims`) *after* the normals. This
//! module receives those already-drawn arrays and computes the expensive part:
//! the latent matrix, `norm.ppf`, `t.cdf`, the hit comparisons and the counts.
//! Parity is therefore a property of the arithmetic, not of the RNG stream.

use crate::math::{norm_ppf, t_cdf};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Copula {
    Gaussian,
    StudentT,
}

#[derive(Clone, Copy, Debug)]
pub struct SimResult {
    pub p_all: f64,
    pub p_all_se: f64,
    pub p_minus_1: f64,
    pub p_minus_2: f64,
    pub p_naive: f64,
    pub mean_hits: f64,
}

/// Row-major `chol (k*k)` times row-major `independent (k*n)`.
///
/// The sum over `j` is accumulated in ascending order for every output entry,
/// exactly like the inner loop of a naive triple loop. The loop order is
/// interchanged (leg, then source leg, then simulation) only for cache
/// locality: each destination element still sees `+ c_j * x_j` with `j` in
/// ascending order, so the result is bit-identical to the naive order and no
/// reassociation happens. Non-finite entries are replaced by 0.0, mirroring
/// `np.nan_to_num(latent, nan=0.0, posinf=0.0, neginf=0.0)`.
pub fn latent_matrix(chol: &[f64], k: usize, independent: &[f64], n: usize) -> Vec<f64> {
    let mut latent = vec![0.0f64; k * n];
    for leg in 0..k {
        let row = &chol[leg * k..leg * k + k];
        let dest = &mut latent[leg * n..leg * n + n];
        for (source, &coefficient) in row.iter().enumerate() {
            let src = &independent[source * n..source * n + n];
            for (out, &value) in dest.iter_mut().zip(src.iter()) {
                *out += coefficient * value;
            }
        }
    }
    for value in latent.iter_mut() {
        if !value.is_finite() {
            *value = 0.0;
        }
    }
    latent
}

fn validate(
    marginals: &[f64],
    chol: &[f64],
    independent: &[f64],
    copula: Copula,
    df: f64,
    chi2: &[f64],
) -> Result<(usize, usize), String> {
    let k = marginals.len();
    if k == 0 {
        return Err("need at least one marginal".to_string());
    }
    if chol.len() != k * k {
        return Err(format!(
            "chol must hold k*k={} values, got {}",
            k * k,
            chol.len()
        ));
    }
    if independent.len() % k != 0 {
        return Err(format!(
            "independent must hold k*n_sims values, got {} for k={}",
            independent.len(),
            k
        ));
    }
    let n = independent.len() / k;
    if n == 0 {
        return Err("n_sims must be positive".to_string());
    }
    match copula {
        Copula::Gaussian => {}
        Copula::StudentT => {
            if !df.is_finite() || df <= 0.0 {
                return Err("student-t df must be positive".to_string());
            }
            if chi2.len() != n {
                return Err(format!(
                    "chi2 must hold n_sims={} values, got {}",
                    n,
                    chi2.len()
                ));
            }
        }
    }
    Ok((k, n))
}

/// The Monte Carlo tail: counts of trials that hit `k`, `k-1` and `k-2` legs.
pub fn simulate(
    marginals: &[f64],
    chol: &[f64],
    independent: &[f64],
    copula: Copula,
    df: f64,
    chi2: &[f64],
) -> Result<SimResult, String> {
    let (k, n) = validate(marginals, chol, independent, copula, df, chi2)?;
    let latent = latent_matrix(chol, k, independent, n);

    let mut hit_counts = vec![0u32; n];
    match copula {
        Copula::Gaussian => {
            let thresholds: Vec<f64> = marginals.iter().map(|&p| norm_ppf(p)).collect();
            for leg in 0..k {
                let threshold = thresholds[leg];
                let row = &latent[leg * n..leg * n + n];
                for (count, &value) in hit_counts.iter_mut().zip(row.iter()) {
                    if value <= threshold {
                        *count += 1;
                    }
                }
            }
        }
        Copula::StudentT => {
            let mut scale = vec![0.0f64; n];
            for (out, &draw) in scale.iter_mut().zip(chi2.iter()) {
                *out = (df / draw).sqrt();
            }
            for leg in 0..k {
                let marginal = marginals[leg];
                let row = &latent[leg * n..leg * n + n];
                for ((count, &value), &factor) in
                    hit_counts.iter_mut().zip(row.iter()).zip(scale.iter())
                {
                    let uniform = t_cdf(value * factor, df);
                    if uniform <= marginal {
                        *count += 1;
                    }
                }
            }
        }
    }

    let n_f = n as f64;
    let k_u32 = k as u32;
    let mut all_hits = 0u64;
    let mut minus_1 = 0u64;
    let mut minus_2 = 0u64;
    let mut total_hits = 0u64;
    for &count in &hit_counts {
        if count == k_u32 {
            all_hits += 1;
        }
        if k >= 1 && count == k_u32 - 1 {
            minus_1 += 1;
        }
        if k >= 2 && count == k_u32 - 2 {
            minus_2 += 1;
        }
        total_hits += u64::from(count);
    }
    let p_all = all_hits as f64 / n_f;
    let mut naive = 1.0f64;
    for &marginal in marginals {
        naive *= marginal;
    }
    Ok(SimResult {
        p_all,
        p_all_se: ((p_all * (1.0 - p_all)).max(0.0) / n_f).sqrt(),
        p_minus_1: if k >= 1 {
            minus_1 as f64 / n_f
        } else {
            0.0
        },
        p_minus_2: if k >= 2 {
            minus_2 as f64 / n_f
        } else {
            0.0
        },
        p_naive: naive,
        mean_hits: total_hits as f64 / n_f,
    })
}

#[cfg(test)]
mod tests {
    use super::{latent_matrix, simulate, Copula};

    #[test]
    fn identity_cholesky_copies_the_draws() {
        // k=2, n=3, row-major draws [[1,2,3],[4,5,6]].
        let chol = [1.0, 0.0, 0.0, 1.0];
        let independent = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0];
        let latent = latent_matrix(&chol, 2, &independent, 3);
        assert_eq!(latent, vec![1.0, 2.0, 3.0, 4.0, 5.0, 6.0]);
    }

    #[test]
    fn latent_matches_a_hand_dot_product() {
        let chol = [1.0, 0.0, 0.5, 0.8660254037844386];
        let independent = [1.0, 2.0, 3.0, 4.0];
        // leg 1 = 0.5 * [1, 2] + 0.8660254037844386 * [3, 4]
        let latent = latent_matrix(&chol, 2, &independent, 2);
        assert_eq!(latent[0], 1.0);
        assert_eq!(latent[1], 2.0);
        assert!((latent[2] - (0.5 + 0.8660254037844386 * 3.0)).abs() < 1e-15);
        assert!((latent[3] - (1.0 + 0.8660254037844386 * 4.0)).abs() < 1e-15);
    }

    #[test]
    fn gaussian_counts_are_consistent() {
        let marginals = [0.5, 0.5];
        let chol = [1.0, 0.0, 0.0, 1.0];
        let independent = [0.0, 1.0, 0.0, 1.0];
        let result = simulate(&marginals, &chol, &independent, Copula::Gaussian, 5.0, &[])
            .expect("gaussian simulate");
        // sim 0: latent [0, 0] -> both hit (0 <= 0); sim 1: latent [1, 1] -> none.
        assert_eq!(result.p_all, 0.5);
        assert_eq!(result.p_naive, 0.25);
        assert_eq!(result.mean_hits, 1.0);
        assert_eq!(result.p_minus_1, 0.0);
        // k=2: p_minus_2 is P(exactly zero hits).
        assert_eq!(result.p_minus_2, 0.5);
    }

    #[test]
    fn student_t_needs_chi2() {
        let marginals = [0.5];
        let chol = [1.0];
        let independent = [0.0];
        let err = simulate(&marginals, &chol, &independent, Copula::StudentT, 5.0, &[])
            .expect_err("chi2 is required");
        assert!(err.contains("chi2"));
    }

    #[test]
    fn non_finite_latent_becomes_zero() {
        let chol = [f64::INFINITY];
        let independent = [1.0, 2.0];
        let latent = latent_matrix(&chol, 1, &independent, 2);
        assert_eq!(latent, vec![0.0, 0.0]);
    }
}
