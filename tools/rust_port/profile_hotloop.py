"""Call ``simulate_slip`` in a tight loop so ``fast-anything scan`` sees it.

The CLI-level scan is dominated by interpreter start-up and CSV I/O, so the
copula tail never shows up as hot there. This helper isolates the function the
Rust port replaces, which is the only thing the profiling claim is about.

    fast-anything scan -- python3 tools/rust_port/profile_hotloop.py
"""

from __future__ import annotations

import numpy as np

from ceminiparlays.copula import nearest_correlation, simulate_slip

K = 4
N_SIMS = 20_000
ROUNDS = 40
MARGINALS = [0.62, 0.55, 0.48, 0.58]


def main() -> None:
    corr = nearest_correlation(
        np.array(
            [
                [1.0, 0.4, 0.2, 0.1],
                [0.4, 1.0, 0.3, 0.2],
                [0.2, 0.3, 1.0, 0.4],
                [0.1, 0.2, 0.4, 1.0],
            ]
        )
    )
    for copula in ("gaussian", "student_t"):
        for _ in range(ROUNDS):
            simulate_slip(
                MARGINALS,
                corr,
                copula_type=copula,
                df=5,
                n_sims=N_SIMS,
                seed=42,
                engine="python",
            )


if __name__ == "__main__":
    main()
