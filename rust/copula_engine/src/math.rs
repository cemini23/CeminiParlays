//! Special functions needed by the copula Monte Carlo tail.
//!
//! Both routines are self-contained so the crate keeps `pyo3` as its only
//! dependency. The accuracy targets are set by `tests/test_copula_rust_parity.py`
//! and are measured against SciPy, not asserted by construction.

const SQRT_2PI: f64 = 2.5066282746310005;

/// Lanczos numerator coefficients (g = 607/128). Relative accuracy ~1e-15.
const LANCZOS_COEF: [f64; 14] = [
    57.156_235_665_862_92,
    -59.597_960_355_475_49,
    14.136_097_974_741_746,
    -0.491_913_816_097_620_2,
    3.399_464_998_481_189e-5,
    4.652_362_892_704_858e-5,
    -9.837_447_530_487_956e-5,
    1.580_887_032_249_125e-4,
    -2.102_644_417_241_048_8e-4,
    2.174_396_181_152_126_5e-4,
    -1.643_181_065_367_639e-4,
    8.441_822_398_385_275e-5,
    -2.619_083_840_158_140_8e-5,
    3.689_918_265_953_162_5e-6,
];

/// `ln Gamma(x)` for `x > 0` (Lanczos, ~1e-15 relative).
fn ln_gamma(x: f64) -> f64 {
    let mut y = x;
    let mut series = 0.999_999_999_999_997_1;
    for coefficient in LANCZOS_COEF {
        y += 1.0;
        series += coefficient / y;
    }
    let tmp = x + 5.2421875;
    (x + 0.5) * tmp.ln() - tmp + (SQRT_2PI * series / x).ln()
}

/// Inverse of the standard normal CDF, Wichura's algorithm AS241 (double
/// precision branch, `PPND16`).
///
/// `p <= 0` returns `-inf` and `p >= 1` returns `+inf`, matching SciPy's
/// `norm.ppf` endpoints. NaN propagates.
pub fn norm_ppf(p: f64) -> f64 {
    if p.is_nan() {
        return f64::NAN;
    }
    if p <= 0.0 {
        return f64::NEG_INFINITY;
    }
    if p >= 1.0 {
        return f64::INFINITY;
    }
    let q = p - 0.5;
    if q.abs() <= 0.425 {
        let r = 0.180625 - q * q;
        let num = ((((((2_509.080_928_730_122_7 * r + 33_430.575_583_588_13) * r
            + 67_265.770_927_008_7)
            * r
            + 45_921.953_931_549_87)
            * r
            + 13_731.693_765_509_46)
            * r
            + 1_971.590_950_306_551_3)
            * r
            + 133.141_667_891_784_38)
            * r
            + 3.387_132_872_796_366_5;
        let den = ((((((5_226.495_278_852_546 * r + 28_729.085_735_721_943) * r
            + 39_307.895_800_092_71)
            * r
            + 21_213.794_301_586_597)
            * r
            + 5_394.196_021_424_751)
            * r
            + 687.187_007_492_057_9)
            * r
            + 42.313_330_701_600_91)
            * r
            + 1.0;
        return q * num / den;
    }
    // Central tail: r = min(p, 1 - p) < 0.075.
    let mut r = if q > 0.0 { 1.0 - p } else { p };
    r = (-r.ln()).sqrt();
    if r <= 5.0 {
        let r = r - 1.6;
        let num = ((((((7.745_450_142_783_414e-4 * r + 0.022_723_844_989_269_184) * r
            + 0.241_780_725_177_450_6)
            * r
            + 1.270_458_252_452_368_4)
            * r
            + 3.647_848_324_763_204_5)
            * r
            + 5.769_497_221_460_691)
            * r
            + 4.630_337_846_156_546)
            * r
            + 1.423_437_110_749_683_5;
        let den = ((((((1.050_750_071_644_416_9e-9 * r + 5.475_938_084_995_345e-4) * r
            + 0.015_198_666_563_616_457)
            * r
            + 0.148_103_976_427_480_08)
            * r
            + 0.689_767_334_985_1)
            * r
            + 1.676_384_830_183_803_8)
            * r
            + 2.053_191_626_637_759)
            * r
            + 1.0;
        return if q < 0.0 { -num / den } else { num / den };
    }
    let r = r - 5.0;
    let num = ((((((2.010_334_399_292_288_1e-7 * r + 2.711_555_568_743_487_6e-5) * r
        + 0.001_242_660_947_388_078_4)
        * r
        + 0.026_532_189_526_576_124)
        * r
        + 0.296_560_571_828_504_87)
        * r
        + 1.784_826_539_917_291_3)
        * r
        + 5.463_784_911_164_114)
        * r
        + 6.657_904_643_501_103;
    let den = ((((((2.044_263_103_389_939_7e-15 * r + 1.421_511_758_316_446e-7) * r
        + 1.846_318_317_510_054_8e-5)
        * r
        + 7.868_691_311_456_133e-4)
        * r
        + 0.014_875_361_290_850_615)
        * r
        + 0.136_929_880_922_735_8)
        * r
        + 0.599_832_206_555_888)
        * r
        + 1.0;
    if q < 0.0 {
        -num / den
    } else {
        num / den
    }
}

/// Continued fraction for the regularized incomplete beta function (Lentz).
fn beta_continued_fraction(a: f64, b: f64, x: f64) -> f64 {
    const MAX_ITERATIONS: usize = 2000;
    const EPS: f64 = 1e-16;
    const TINY: f64 = 1e-300;

    let qab = a + b;
    let qap = a + 1.0;
    let qam = a - 1.0;
    let mut c = 1.0;
    let mut d = 1.0 - qab * x / qap;
    if d.abs() < TINY {
        d = TINY;
    }
    d = 1.0 / d;
    let mut h = d;
    for m in 1..=MAX_ITERATIONS {
        let m = m as f64;
        let m2 = 2.0 * m;
        // Even step.
        let numerator = m * (b - m) * x / ((qam + m2) * (a + m2));
        d = 1.0 + numerator * d;
        if d.abs() < TINY {
            d = TINY;
        }
        c = 1.0 + numerator / c;
        if c.abs() < TINY {
            c = TINY;
        }
        d = 1.0 / d;
        h *= d * c;
        // Odd step.
        let numerator = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2));
        d = 1.0 + numerator * d;
        if d.abs() < TINY {
            d = TINY;
        }
        c = 1.0 + numerator / c;
        if c.abs() < TINY {
            c = TINY;
        }
        d = 1.0 / d;
        let delta = d * c;
        h *= delta;
        if (delta - 1.0).abs() < EPS {
            break;
        }
    }
    h
}

/// Regularized incomplete beta `I_x(a, b)` for `a, b > 0`.
fn regularized_incomplete_beta(a: f64, b: f64, x: f64) -> f64 {
    if x <= 0.0 {
        return 0.0;
    }
    if x >= 1.0 {
        return 1.0;
    }
    let ln_beta = ln_gamma(a + b) - ln_gamma(a) - ln_gamma(b)
        + a * x.ln()
        + b * (1.0 - x).ln();
    let front = ln_beta.exp();
    // The continued fraction converges fastest on the side the switch picks.
    if x < (a + 1.0) / (a + b + 2.0) {
        front * beta_continued_fraction(a, b, x) / a
    } else {
        1.0 - front * beta_continued_fraction(b, a, 1.0 - x) / b
    }
}

/// CDF of Student's t with `df` degrees of freedom.
///
/// Uses the regularized incomplete beta identity
/// `P(T > x) = I_{df/(df+x^2)}(df/2, 1/2) / 2` for `x >= 0`.
pub fn t_cdf(x: f64, df: f64) -> f64 {
    if x.is_nan() || df.is_nan() {
        return f64::NAN;
    }
    if df <= 0.0 {
        return f64::NAN;
    }
    if x == f64::INFINITY {
        return 1.0;
    }
    if x == f64::NEG_INFINITY {
        return 0.0;
    }
    let z = df / (df + x * x);
    let tail = regularized_incomplete_beta(df / 2.0, 0.5, z);
    if x >= 0.0 {
        1.0 - 0.5 * tail
    } else {
        0.5 * tail
    }
}

#[cfg(test)]
mod tests {
    use super::{norm_ppf, t_cdf};

    // Reference values from scipy.stats.norm.ppf (SciPy 1.16, float64 repr).
    const NORM_CASES: [(f64, f64); 7] = [
        (1e-12, -7.034483825301131),
        (1e-9, -5.9978070150076865),
        (1e-3, -3.090232306167813),
        (0.5, 0.0),
        (0.999, 3.090232306167813),
        (0.999999999, 5.997807019601637),
        (0.999999999999, 7.0344869100478356),
    ];

    // Reference grid from scipy.stats.t.cdf, x in [-40, -10, -3, -1, 0, 1, 3, 10, 40].
    const T_CASES: [(f64, [f64; 9]); 7] = [
        (
            1.0,
            [
                0.007956089912025812,
                0.03172551743055356,
                0.10241638234956672,
                0.24999999999999978,
                0.5,
                0.7500000000000002,
                0.8975836176504333,
                0.9682744825694464,
                0.9920439100879742,
            ],
        ),
        (
            2.0,
            [
                0.0003122073360923703,
                0.004926228511662846,
                0.04773298313335456,
                0.21132486540518713,
                0.5,
                0.7886751345948129,
                0.9522670168666455,
                0.9950737714883371,
                0.9996877926639076,
            ],
        ),
        (
            4.0,
            [
                1.1670081613006347e-06,
                0.00028100181135799556,
                0.019970984035859413,
                0.1869504831500295,
                0.5,
                0.8130495168499705,
                0.9800290159641406,
                0.9997189981886421,
                0.9999988329918387,
            ],
        ),
        (
            5.0,
            [
                9.205981085886476e-08,
                8.547378787148179e-05,
                0.015049623948731284,
                0.18160873382456127,
                0.5,
                0.8183912661754387,
                0.9849503760512688,
                0.9999145262121285,
                0.9999999079401891,
            ],
        ),
        (
            30.0,
            [
                6.863022597203181e-28,
                2.2876257041148126e-11,
                0.002694982032825972,
                0.16265430771301492,
                0.5,
                0.8373456922869851,
                0.997305017967174,
                0.9999999999771237,
                1.0,
            ],
        ),
        (
            80.0,
            [
                5.882560127158186e-55,
                4.832841213761288e-16,
                0.001799198787579179,
                0.16016283515629098,
                0.5,
                0.8398371648437091,
                0.9982008012124208,
                0.9999999999999996,
                1.0,
            ],
        ),
        (
            1000.0,
            [
                5.239426077586736e-210,
                8.335351479300032e-23,
                0.0013833545221190943,
                0.15877620904233627,
                0.5,
                0.8412237909576638,
                0.9986166454778809,
                1.0,
                1.0,
            ],
        ),
    ];

    const XS: [f64; 9] = [-40.0, -10.0, -3.0, -1.0, 0.0, 1.0, 3.0, 10.0, 40.0];

    #[test]
    fn norm_ppf_matches_scipy() {
        for (p, expected) in NORM_CASES {
            let got = norm_ppf(p);
            assert!(
                (got - expected).abs() <= 1e-9,
                "norm_ppf({p}) = {got}, scipy {expected}"
            );
        }
    }

    #[test]
    fn norm_ppf_is_symmetric_and_bounded() {
        assert!(norm_ppf(0.0).is_infinite() && norm_ppf(0.0) < 0.0);
        assert!(norm_ppf(1.0).is_infinite() && norm_ppf(1.0) > 0.0);
        assert!(norm_ppf(f64::NAN).is_nan());
        for p in [0.01, 0.1, 0.25, 0.4] {
            assert!((norm_ppf(p) + norm_ppf(1.0 - p)).abs() <= 1e-9);
        }
        // At 1e-12 the asymmetry is an artefact of `1.0 - 1e-12` not being the
        // float64 image of the complement, not of the routine (SciPy shows the
        // same 3e-6 gap).
        assert!((norm_ppf(1e-12) + norm_ppf(1.0 - 1e-12)).abs() <= 1e-4);
    }

    #[test]
    fn t_cdf_matches_scipy() {
        for (df, row) in T_CASES {
            for (x, expected) in XS.iter().zip(row.iter()) {
                let got = t_cdf(*x, df);
                assert!(
                    (got - expected).abs() <= 1e-10,
                    "t_cdf({x}, {df}) = {got}, scipy {expected}"
                );
            }
        }
    }

    #[test]
    fn t_cdf_is_symmetric_around_half() {
        for df in [1.0, 2.0, 5.0, 30.0, 1000.0] {
            assert!((t_cdf(0.0, df) - 0.5).abs() <= 1e-15);
            for x in [0.1, 1.0, 2.5, 7.0] {
                assert!((t_cdf(-x, df) + t_cdf(x, df) - 1.0).abs() <= 1e-12);
            }
        }
    }

    #[test]
    fn t_cdf_approaches_the_normal_cdf_as_df_grows() {
        // |t_cdf - Phi| shrinks with df; at df=1e6 they are within 1e-4.
        let normal_like = t_cdf(-1.0, 1.0e6);
        assert!((normal_like - 0.15865525393145705).abs() <= 1e-4);
    }
}
