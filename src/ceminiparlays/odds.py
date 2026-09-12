from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from scipy.optimize import brentq

DevigMethod = Literal["multiplicative", "additive", "power"]

BRENTQ_BRACKETS: tuple[tuple[float, float], ...] = ((1.0, 8.0), (0.05, 32.0))


@dataclass(frozen=True)
class DevigResult:
    p_over: float
    p_under: float
    method: DevigMethod
    k_exponent: float
    market_width_cents: int
    raw_overround: float


def american_to_decimal(odds: int) -> float:
    """Convert American odds to decimal odds.

    Only moneyline-style quotes are legal: ``<= -100`` or ``>= +100``.
    """

    if odds == 0:
        raise ValueError("American odds cannot be zero")
    if -100 < odds < 100:
        raise ValueError("American odds must be <= -100 or >= +100")
    if odds > 0:
        return 1.0 + (odds / 100.0)
    return 1.0 + (100.0 / abs(odds))


def decimal_to_american(decimal: float) -> int:
    """Convert a decimal multiplier to the nearest American price."""

    if decimal <= 1.0:
        raise ValueError("decimal odds must be greater than 1")
    if decimal >= 2.0:
        return int(round((decimal - 1.0) * 100.0))
    return int(round(-100.0 / (decimal - 1.0)))


def american_to_implied(odds: int) -> float:
    return 1.0 / american_to_decimal(odds)


def market_width_cents(odds_over: int, odds_under: int) -> int:
    return abs(abs(odds_over) - abs(odds_under))


def _normalize_pair(p_over: float, p_under: float) -> tuple[float, float]:
    total = p_over + p_under
    if total <= 0:
        raise ValueError("de-vig probabilities must be positive")
    return p_over / total, p_under / total


def _power_k(pi_over: float, pi_under: float) -> float:
    def objective(k: float) -> float:
        return (pi_over**k) + (pi_under**k) - 1.0

    last_error: ValueError | None = None
    for low, high in BRENTQ_BRACKETS:
        try:
            return float(brentq(objective, low, high))
        except ValueError as exc:  # bracket did not straddle a root
            last_error = exc
    raise ValueError("power de-vig could not bracket k") from last_error


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
        k_opt = _power_k(pi_over, pi_under)
        p_over, p_under = _normalize_pair(pi_over**k_opt, pi_under**k_opt)
        return DevigResult(p_over, p_under, method, k_opt, width, overround)

    raise ValueError(f"unknown de-vig method: {method}")


def devig_spread(odds_over: int, odds_under: int, unstable_pp: float = 1.5) -> dict[str, float | bool]:
    """Compare all three de-vig methods on one market (I-28).

    Returns each method's ``p_over`` plus the max spread in percentage points.
    A spread above ``unstable_pp`` means the fair P is method-sensitive and the
    operator should not trust a single point estimate.
    """

    power = devig_two_way(odds_over, odds_under, method="power")
    multiplicative = devig_two_way(odds_over, odds_under, method="multiplicative")
    additive = devig_two_way(odds_over, odds_under, method="additive")
    values = [power.p_over, multiplicative.p_over, additive.p_over]
    spread_pp = (max(values) - min(values)) * 100.0
    return {
        "power_p_over": power.p_over,
        "multiplicative_p_over": multiplicative.p_over,
        "additive_p_over": additive.p_over,
        "spread_pp": spread_pp,
        "unstable": spread_pp > unstable_pp,
    }
