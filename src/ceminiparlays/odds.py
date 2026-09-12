from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from scipy.optimize import brentq

DevigMethod = Literal["multiplicative", "additive", "power"]


@dataclass(frozen=True)
class DevigResult:
    p_over: float
    p_under: float
    method: DevigMethod
    k_exponent: float
    market_width_cents: int
    raw_overround: float


def american_to_decimal(odds: int) -> float:
    """Convert American odds to decimal odds."""

    if odds == 0:
        raise ValueError("American odds cannot be zero")
    if odds > 0:
        return 1.0 + (odds / 100.0)
    return 1.0 + (100.0 / abs(odds))


def american_to_implied(odds: int) -> float:
    return 1.0 / american_to_decimal(odds)


def market_width_cents(odds_over: int, odds_under: int) -> int:
    return abs(abs(odds_over) - abs(odds_under))


def _normalize_pair(p_over: float, p_under: float) -> tuple[float, float]:
    total = p_over + p_under
    if total <= 0:
        raise ValueError("de-vig probabilities must be positive")
    return p_over / total, p_under / total


def devig_two_way(
    odds_over: int,
    odds_under: int,
    method: DevigMethod = "power",
) -> DevigResult:
    """Strip vig from a two-way over/under market."""

    pi_over = american_to_implied(odds_over)
    pi_under = american_to_implied(odds_under)
    overround = (pi_over + pi_under) - 1.0
    width = market_width_cents(odds_over, odds_under)

    if overround <= 0:
        p_over, p_under = _normalize_pair(pi_over, pi_under)
        return DevigResult(p_over, p_under, method, 1.0, width, overround)

    if method == "multiplicative":
        p_over, p_under = _normalize_pair(pi_over, pi_under)
        return DevigResult(p_over, p_under, method, 1.0, width, overround)

    if method == "additive":
        half = overround / 2.0
        p_over, p_under = _normalize_pair(pi_over - half, pi_under - half)
        return DevigResult(p_over, p_under, method, 1.0, width, overround)

    if method == "power":

        def objective(k: float) -> float:
            return (pi_over**k) + (pi_under**k) - 1.0

        k_opt = float(brentq(objective, 1.0, 8.0))
        p_over, p_under = _normalize_pair(pi_over**k_opt, pi_under**k_opt)
        return DevigResult(p_over, p_under, method, k_opt, width, overround)

    raise ValueError(f"unknown de-vig method: {method}")
