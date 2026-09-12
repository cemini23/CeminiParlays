from __future__ import annotations

from dataclasses import dataclass
from math import exp, log, sqrt
from typing import Literal

from scipy.stats import lognorm, norm, poisson

StatFamily = Literal["lognormal", "normal", "poisson"]


@dataclass(frozen=True)
class FairResult:
    fair_p_over: float
    fair_p_under: float
    median: float
    sigma: float
    family: StatFamily
    line: float
    fair_p_push: float = 0.0
    fair_p_at_median: float = 0.5
    note: str = ""


def choose_family(stat_type: str, median: float) -> StatFamily:
    """Pick a marginal family from the wiki decision tree."""

    discrete_low = {
        "pass_tds",
        "rush_tds",
        "rec_tds",
        "anytime_td",
        "ints",
        "sacks",
    }
    if stat_type in discrete_low or median < 3:
        return "poisson"
    if stat_type in {"receptions", "pass_att", "pass_cmp", "rush_att"} and median < 8:
        return "poisson"
    if stat_type.endswith("_yds") or stat_type in {"rush_rec_yds", "pass_rush_yds"}:
        return "lognormal"
    return "normal"


def p_over_line(
    line: float,
    median: float,
    sigma: float,
    family: StatFamily | None = None,
    stat_type: str = "",
) -> FairResult:
    """P(stat > line) from a projected median and dispersion.

    Integer Poisson lines keep their push mass in ``fair_p_push``. It is never
    folded into the under side; callers that cannot handle a void must reject
    the leg instead (see ``--allow-integer-lines``).
    """

    if median <= 0:
        raise ValueError("median must be positive")
    if sigma < 0:
        raise ValueError("sigma must be non-negative")

    resolved = family or choose_family(stat_type, median)
    note = ""
    p_push = 0.0
    p_at_median = 0.5

    if resolved == "lognormal":
        # v1 proxy: CV uses the projected median as if it were the mean. A true
        # mean/sigma parameterization would shift every yard probability, so it
        # is deferred; see RESEARCH.md (I-29).
        cv = sigma / median if median else 0.0
        cv = max(cv, 1e-6)
        sigma_ln = sqrt(log(1.0 + cv * cv))
        # scipy lognorm is parameterized by s=sigma_ln and scale=exp(mu_ln)
        mu_ln = log(median)
        dist = lognorm(s=sigma_ln, scale=exp(mu_ln))
        p_over = float(1.0 - dist.cdf(line))
        p_under = 1.0 - p_over
    elif resolved == "normal":
        p_over = float(1.0 - norm.cdf(line, loc=median, scale=max(sigma, 1e-6)))
        p_under = 1.0 - p_over
    elif resolved == "poisson":
        if sigma > 0:
            # mu=median is kept; sigma is not used by the Poisson branch. Flag it
            # loudly instead of silently pretending the dispersion was applied.
            note = "poisson_sigma_ignored"
        if float(line).is_integer():
            level = int(line)
            p_over = float(1.0 - poisson.cdf(level, mu=median))
            p_push = float(poisson.pmf(level, mu=median))
            p_under = 1.0 - p_over - p_push
        else:
            p_over = float(1.0 - poisson.cdf(int(line), mu=median))
            p_under = 1.0 - p_over
        p_at_median = float(1.0 - poisson.cdf(median, mu=median))
    else:
        raise ValueError(f"unknown family: {resolved}")

    eps = 1e-9
    p_over = min(max(p_over, eps), 1.0 - eps)
    p_push = min(max(p_push, 0.0), 1.0)
    if p_push > 0.0:
        p_under = max(1.0 - p_over - p_push, 0.0)
    else:
        p_under = 1.0 - p_over

    return FairResult(
        fair_p_over=p_over,
        fair_p_under=p_under,
        median=median,
        sigma=sigma,
        family=resolved,
        line=line,
        fair_p_push=p_push,
        fair_p_at_median=p_at_median,
        note=note,
    )


def side_probability(result: FairResult, side: str) -> float:
    token = side.strip().lower()
    if token in {"more", "over", "higher", "o"}:
        return result.fair_p_over
    if token in {"less", "under", "lower", "u"}:
        return result.fair_p_under
    raise ValueError(f"unknown side: {side}")
