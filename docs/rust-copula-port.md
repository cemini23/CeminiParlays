# Rust copula engine: scope, parity contract, and decision

Status: **opt-in, non-default.** The Rust engine is built, parity-verified, and
**slower** than NumPy on this machine. `engine=python` stays the default.

The port changed no Python behaviour: the parity suite, the Kelly invariants and
the full test suite pass with Rust present, and the default path never touches
it.

## Scope

`rust/copula_engine/` is a `cdylib` Python extension
(`ceminiparlays._copula_engine`) that owns **only the numeric tail** of
`ceminiparlays.copula.simulate_slip`:

```text
latent = chol @ independent
gaussian:   hits = latent <= norm.ppf(marginals)
student_t:  uniforms = t.cdf(latent * sqrt(df / chi2), df)
            hits = uniforms <= marginals
counts = sum(hits, axis=0)
p_all, p_all_se, p_minus_1, p_minus_2, p_naive, mean_hits
```

It explicitly does **not** own:

- random number generation (NumPy draws every array, Rust consumes it);
- correlation repair / projection;
- the exact (non-Monte-Carlo) joint probability;
- position sizing or Kelly policy;
- any input/output, HTTP, or CLI work.

The crate depends on `pyo3` only. `math.rs` implements `norm_ppf` (Wichura
AS241 / PPND16) and `t_cdf` (regularized incomplete beta, Lentz continued
fraction) so the extension stays dependency-free.

## What stays in Python, and why

1. **`exact_joint` stays in SciPy.** The multivariate normal CDF is an adaptive
   quadrature with SciPy's `abseps=1e-5` integration floor, and the Student-t
   path uses `multivariate_t.cdf(..., random_state=0)`. Reproducing that
   tolerance and its random-stream behaviour in Rust would create a second,
   subtly different definition of "exact". `exact_joint` is deterministic and
   not on the Monte Carlo hot loop, so there is no speed argument either.
2. **`nearest_correlation` stays in NumPy/LAPACK.** Projection to a strictly
   positive-definite correlation needs `np.linalg.eigh` / `eigvalsh` plus the
   sign-flip and unit-diagonal renormalisation. LAPACK is already the reference
   implementation, and the matrix is tiny (`k <= 6`), so moving it would add
   risk for no measurable win.
3. **The PCG64 RNG stays in Python.** `np.random.default_rng(seed)` (PCG64) is
   the reproducibility contract. Stream identity — draw order, `standard_normal`
   before `chisquare` — is what makes results repeatable across runs and
   machines. The extension receives already-drawn arrays; parity is therefore a
   property of the arithmetic, not of the RNG stream.
4. **Quarter-Kelly stays in Python.** `slip_kelly` / `stake_dollars` encode
   policy (quarter Kelly, 5% cap, rounding), not numerics. Policy belongs in
   reviewable Python next to the tests that pin it.
5. **The Odds API client stays in Python.** `odds_api.py` is a stdlib
   `urllib` client with retries, quota handling, and response normalisation.
   There is nothing numerically hot to port, and a network client is the last
   place to want a second language.

## Build and run

```bash
# Build the cdylib and install it as the platform extension module.
bash tools/rust_port/build_rust.sh

# Opt in per call / per run.
python3 -m ceminiparlays run ... --engine rust
CEMINIPARLAYS_ENGINE=rust python3 -m ceminiparlays rank ...

# Kill switch: forces the Python engine regardless of flag or env var.
FAST_ANYTHING_DISABLE=1 ...
```

`--engine` is attached to the shared rank options, so `rank` and `run` accept it
and `compose` does not. Resolution order (`resolve_engine`):

1. `FAST_ANYTHING_DISABLE=1` → `python`;
2. explicit `engine=` argument;
3. `CEMINIPARLAYS_ENGINE`;
4. `python`.

A missing extension is a hard `RuntimeError` with the build command — never a
silent fallback. `engine="rust"` combined with the kill switch resolves to
`python`.

## Parity contract

For every case in `tests/test_copula_rust_parity.py`:

| Output | Contract |
| --- | --- |
| `p_all`, `p_all_se`, `p_minus_1`, `p_minus_2`, `p_naive`, `mean_hits` | finite, `abs(python - rust) <= 1e-9` |
| count-derived fractions (`p_all`, `p_minus_1`, `p_minus_2`, `mean_hits`) | bit-equal (`==`), not merely close |
| special functions | `norm_ppf` within `1e-9`, `t_cdf` within `1e-10` of SciPy |
| latent matrix | `<= 1e-12` against `np.dot(chol, independent)` |

Bit-equality on the counts follows from identical draws: same `independent`
array, same ascending-order dot product, same comparisons. The only permitted
difference is floating-point rounding in the special functions, and it is
**0.0** on every measured case here.

The suite fails — and must fail — when the extension is absent, so a skipped
parity run is impossible. `tests/conftest.py` additionally turns a run that
collects zero tests into a failure.

Coverage: Gaussian `k in {2,3,4}` × four correlations including `0.999999`,
Student-t `df in {1,2,4,5,30,80}` × lower/middle/upper tails, near-singular
`rho = ±(1 - 1e-7)`, an indefinite matrix, `k = 6` with nearly equal rows,
direct tail calls on Python-drawn arrays, the special functions against SciPy,
and engine-resolution precedence. **78 parity tests, 15 of them Kelly
invariants** (`-m kelly_invariant`).

## Measured performance

Interleaved timing, 1 warm-up + 4 timed rounds, median, this machine
(`tools/rust_port/bench_port.py`, seed 42, `rho=0.4`, `df=5`):

| Case | k | n_sims | python ms | rust ms | speedup | max abs diff |
| --- | --- | --- | --- | --- | --- | --- |
| gaussian k=4 n=20k | 4 | 20000 | 0.51 | 0.69 | 0.74x | 0.0 |
| student_t k=4 n=20k | 4 | 20000 | 7.61 | 8.84 | 0.86x | 0.0 |
| student_t k=6 n=20k | 6 | 20000 | 11.25 | 13.21 | 0.85x | 0.0 |
| gaussian k=4 n=200k | 4 | 200000 | 4.24 | 6.46 | 0.66x | 0.0 |
| student_t k=4 n=200k | 4 | 200000 | 76.17 | 89.16 | 0.85x | 0.0 |
| student_t k=6 n=200k | 6 | 200000 | 111.86 | 131.99 | 0.85x | 0.0 |

`RESULT: rust slower`. Re-measure with `bench_port.py`; do not trust these
numbers on another machine. The result is architectural, not a tuning accident:

- NumPy/SciPy operate on contiguous arrays through BLAS and vectorised C, and
  `norm.ppf`/`t.cdf` on an array are far cheaper per element than a Rust scalar
  loop over a FFI boundary;
- the port crosses the boundary once per call, with three array copies in
  (`marginals`, `chol`, `independent`) and one tuple out;
- `t_cdf` is a per-element continued fraction — the Student-t cases are the
  ones where SciPy's compiled `stdtr` has the largest edge.

Neither side was tuned to fake a result; the port is correct parity-first code.

## Licence and lint posture

- Linked packages: `pyo3`, `pyo3-ffi`, `libc`, `once_cell`, `portable-atomic` —
  all `MIT OR Apache-2.0`.
- Host-only (build / proc-macro, not shipped): `heck`, `proc-macro2`,
  `pyo3-build-config`, `pyo3-macros`, `pyo3-macros-backend`, `quote`, `syn`,
  `target-lexicon`, `unicode-ident`. `target-lexicon` is
  `Apache-2.0 WITH LLVM-exception`; `unicode-ident` is
  `(MIT OR Apache-2.0) AND Unicode-3.0`.
- **Operator decision (2026-11-22):** the two host-only exceptions above are
  accepted. They are build-time only and do not ship in `_copula_engine`.
- No copyleft, no non-commercial terms. `tools/rust_port/check_licenses.py`
  enforces this and exits non-zero on any GPL/AGPL/LGPL/SSPL or non-commercial
  licence anywhere, or on a linked package outside the allowlist.
- `cargo clippy -- -D warnings` is clean.

## Verification

```bash
bash tools/rust_port/build_rust.sh
python3 -m pytest tests/test_copula_rust_parity.py -q          # 78 passed
python3 -m pytest tests/test_copula_rust_parity.py -m kelly_invariant -q  # 15 passed
python3 tools/rust_port/verify_port.py    # PARITY_OK parity_tests=78 kelly_invariant_tests=15 total_passed=78
python3 tools/rust_port/check_licenses.py # LICENSES_OK, no linked violation
python3 tools/rust_port/bench_port.py     # markdown table, RESULT: rust slower
cargo clippy --manifest-path rust/copula_engine/Cargo.toml -- -D warnings
python3 -m pytest tests/ -q               # 973 passed
```

## Decision

**Keep `engine=python` as the default.** The Rust engine is opt-in
(`--engine rust` / `CEMINIPARLAYS_ENGINE=rust`) and serves as a second,
independent implementation of the numeric contract: a parity reference that can
catch a regression in the NumPy path, and a head start if the hot loop ever
moves off Python. It is not a performance win on this hardware, so nothing
defaults to it, and `FAST_ANYTHING_DISABLE=1` can always force the Python path.

Revisit if the tail gains a vectorised Rust dependency (e.g. a SIMD `t_cdf`
budget), if the FFI copies are removed with a zero-copy buffer protocol, or if
the workload grows to where a batched, single-crossing design amortises better
than per-call SciPy.
