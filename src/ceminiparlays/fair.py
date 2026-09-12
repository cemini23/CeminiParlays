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
    """P(stat > line) from a projected median and dispersion."""

    if median <= 0:
        raise ValueError("median must be positive")
    if sigma < 0:
        raise ValueError("sigma must be non-negative")

    resolved = family or choose_family(stat_type, median)
    if resolved == "lognormal":
        cv = sigma / median if median else 0.0
        cv = max(cv, 1e-6)
        sigma_ln = sqrt(log(1.0 + cv * cv))
        # scipy lognorm is parameterized by s=sigma_ln and scale=exp(mu_ln)
        mu_ln = log(median)
        dist = lognorm(s=sigma_ln, scale=exp(mu_ln))
        p_over = float(1.0 - dist.cdf(line))
    elif resolved == "normal":
        p_over = float(1.0 - norm.cdf(line, loc=median, scale=max(sigma, 1e-6)))
    elif resolved == "poisson":
        # Half-point lines have no push. Integer lines: P(over)=P(X>L), push=P(X=L).
        if float(line).is_integer():
            p_over = float(1.0 - poisson.cdf(int(line), mu=median))
        else:
            p_over = float(1.0 - poisson.cdf(int(line), mu=median))
    else:
        raise ValueError(f"unknown family: {resolved}")

    p_over = min(max(p_over, 1e-9), 1.0 - 1e-9)
    return FairResult(
        fair_p_over=p_over,
        fair_p_under=1.0 - p_over,
        median=median,
        sigma=sigma,
        family=resolved,
        line=line,
    )


def side_probability(result: FairResult, side: str) -> float:
    token = side.strip().lower()
    if token in {"more", "over", "higher", "o"}:
        return result.fair_p_over
    if token in {"less", "under", "lower", "u"}:
        return result.fair_p_under
    raise ValueError(f"unknown side: {side}")
