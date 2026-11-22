#!/usr/bin/env python3
"""Interleaved Python-vs-Rust timing for the copula numeric tail.

For each of the six reference cases the script does one warm-up call per engine,
then four timed rounds in which the two engines run back to back with the order
alternating, so a drifting machine penalises neither side. The reported number
is the median of the four timed rounds.

The engine is chosen explicitly (``engine="python"`` / ``engine="rust"``); the
``FAST_ANYTHING_DISABLE`` kill switch is refused rather than silently timing the
NumPy path twice. ``max abs diff`` is the largest absolute difference between
the two engines' float outputs for the case, measured on the warm-up results.

The output is a Markdown table plus a verdict. ``RESULT: rust slower`` is
printed when any measured speedup is below 1.00. Missing numbers print ``n/a``;
nothing is fabricated.
"""

from __future__ import annotations

import gc
import sys
import time
from statistics import median
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from ceminiparlays.copula import resolve_engine, simulate_slip  # noqa: E402

SEED = 42
DF = 5.0
RHO = 0.4
WARM_UP = 1
ROUNDS = 4

MARGINALS_BY_K = {
    4: [0.62, 0.55, 0.48, 0.58],
    6: [0.55, 0.60, 0.50, 0.45, 0.62, 0.58],
}

DIFF_KEYS = ("p_all", "p_all_se", "p_minus_1", "p_minus_2", "p_naive", "mean_hits")

CASES = (
    ("gaussian k=4 n=20k", "gaussian", 4, 20_000),
    ("student_t k=4 n=20k", "student_t", 4, 20_000),
    ("student_t k=6 n=20k", "student_t", 6, 20_000),
    ("gaussian k=4 n=200k", "gaussian", 4, 200_000),
    ("student_t k=4 n=200k", "student_t", 4, 200_000),
    ("student_t k=6 n=200k", "student_t", 6, 200_000),
)


def equicorr(k: int, rho: float) -> np.ndarray:
    matrix = np.full((k, k), float(rho))
    np.fill_diagonal(matrix, 1.0)
    return matrix


def run(copula: str, k: int, n_sims: int, engine: str) -> dict:
    return simulate_slip(
        MARGINALS_BY_K[k],
        equicorr(k, RHO),
        copula_type=copula,
        df=DF,
        n_sims=n_sims,
        seed=SEED,
        engine=engine,
    )


def time_ms(copula: str, k: int, n_sims: int, engine: str) -> float:
    started = time.perf_counter()
    run(copula, k, n_sims, engine)
    return (time.perf_counter() - started) * 1000.0


def max_abs_diff(python: dict, rust: dict) -> float:
    return max(abs(float(python[key]) - float(rust[key])) for key in DIFF_KEYS)


def measure(copula: str, k: int, n_sims: int) -> tuple[list[float], list[float], float]:
    python_times: list[float] = []
    rust_times: list[float] = []
    for _ in range(WARM_UP):
        python_result = run(copula, k, n_sims, "python")
        rust_result = run(copula, k, n_sims, "rust")
    difference = max_abs_diff(python_result, rust_result)
    for round_index in range(ROUNDS):
        order = ("python", "rust") if round_index % 2 == 0 else ("rust", "python")
        for engine in order:
            elapsed = time_ms(copula, k, n_sims, engine)
            (python_times if engine == "python" else rust_times).append(elapsed)
    return python_times, rust_times, difference


def _number(value: float | None, suffix: str = "", digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}{suffix}"


def main() -> int:
    if resolve_engine("rust") != "rust":
        sys.stderr.write(
            "bench_port: engine resolution refuses 'rust' (FAST_ANYTHING_DISABLE "
            "is set); refusing to time the NumPy path twice\n"
        )
        return 1

    rows: list[tuple[str, int, int, float | None, float | None, float | None, float | None]] = []
    incomplete = False
    gc.disable()
    try:
        for label, copula, k, n_sims in CASES:
            try:
                python_times, rust_times, difference = measure(copula, k, n_sims)
            except Exception as exc:  # report n/a, never invent a number
                sys.stderr.write(f"bench_port: {label}: {exc}\n")
                incomplete = True
                rows.append((label, k, n_sims, None, None, None, None))
                continue
            python_ms = median(python_times)
            rust_ms = median(rust_times)
            speedup = python_ms / rust_ms if rust_ms > 0.0 else None
            rows.append((label, k, n_sims, python_ms, rust_ms, speedup, difference))
    finally:
        gc.enable()

    print(
        f"Interleaved timing, {WARM_UP} warm-up + {ROUNDS} timed rounds, median. "
        f"seed={SEED}, rho={RHO}, df={DF}."
    )
    print()
    print("| Case | k | n_sims | python ms | rust ms | speedup | max abs diff |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    speedups: list[float] = []
    for label, k, n_sims, python_ms, rust_ms, speedup, difference in rows:
        if speedup is not None:
            speedups.append(speedup)
        diff = "n/a" if difference is None else (
            "0.0" if difference == 0.0 else f"{difference:.3e}"
        )
        print(
            f"| {label} | {k} | {n_sims} | {_number(python_ms)} | "
            f"{_number(rust_ms)} | {_number(speedup, 'x')} | {diff} |"
        )
    print()

    if incomplete or not speedups:
        print("RESULT: incomplete")
        return 1
    if any(speedup < 1.0 for speedup in speedups):
        print("RESULT: rust slower")
    else:
        print("RESULT: rust not slower")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
