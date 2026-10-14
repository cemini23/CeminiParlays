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


@dataclass(frozen=True)
class MultiwayResult:
    """De-vigged probabilities for an N-way market, in input order."""

    probs: tuple[float, ...]
    method: DevigMethod
    k_exponent: float
    raw_overround: float
    note: str = ""


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


def _power_k_multi(implied: list[float]) -> float:
    """Solve ``sum(pi_i ** k) = 1`` for ``k``. Overround means ``k > 1``."""

    total = sum(implied)
    if total <= 1.0:
        return 1.0

    def objective(k: float) -> float:
        return sum(p**k for p in implied) - 1.0

    # The objective is continuous and strictly decreasing in k, and it straddles
    # zero between k=1 (sum > 1) and a wide upper bracket.
    for high in (8.0, 32.0, 128.0):
        try:
            return float(brentq(objective, 1.0, high))
        except ValueError:  # bracket did not straddle a root
            continue
    raise ValueError("power de-vig could not bracket k for the multiway market")


def devig_multiway(
    odds: list[int] | tuple[int, ...],
    method: DevigMethod = "power",
    *,
    hold_pct: float = 0.0,
) -> MultiwayResult:
    """Strip vig from an N-way market (TD pools, ``first_td`` / ``anytime_td``).

    ``power`` solves ``sum(pi_i ** k) = 1``; ``multiplicative`` normalizes by the
    raw overround; ``additive`` removes an equal share of the overround.

    ``hold_pct`` applies a conservative multiplicative haircut to each de-vigged
    probability. Use it for a one-way pool that may be incomplete (e.g. an
    ``anytime_td`` market with no "No" price): the pool sum can understate the
    true book margin, so a straight normalization would overstate the leg.
    """

    if not odds:
        raise ValueError("devig_multiway needs at least one price")
    implied = [american_to_implied(int(price)) for price in odds]
    total = sum(implied)
    if total <= 0.0:
        raise ValueError("devig_multiway probabilities must be positive")
    overround = total - 1.0
    k_exponent = 1.0
    note = ""

    # A pool whose raw implied probabilities sum to 1 or less has no book margin
    # to strip: the pool is INCOMPLETE (some outcomes are missing). Normalizing
    # it would inflate every leg, so the raw implied probabilities are kept and
    # the optional hold is the only haircut.
    incomplete = total <= 1.0

    if incomplete:
        probs = list(implied)
        note = "pool sum<1 (incomplete); raw implied kept"
    elif method == "multiplicative":
        probs = [p / total for p in implied]
    elif method == "additive":
        shift = overround / len(implied)
        raw = [max(p - shift, 0.0) for p in implied]
        scale = sum(raw) or 1.0
        probs = [p / scale for p in raw]
    elif method == "power":
        k_exponent = _power_k_multi(implied)
        raw = [p**k_exponent for p in implied]
        scale = sum(raw) or 1.0
        probs = [p / scale for p in raw]
    else:
        raise ValueError(f"unknown de-vig method: {method}")

    if hold_pct > 0.0:
        if not 0.0 < hold_pct < 1.0:
            raise ValueError("hold_pct must be between 0 and 1")
        probs = [max(p * (1.0 - hold_pct), 1e-9) for p in probs]
        note = (note + "; " if note else "") + f"one-way pool hold {hold_pct:.2f}"

    return MultiwayResult(
        probs=tuple(probs),
        method=method,
        k_exponent=k_exponent,
        raw_overround=overround,
        note=note,
    )


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
