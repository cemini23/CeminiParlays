from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ceminiparlays.copula import exact_joint
from ceminiparlays.environment import EnvRow


@dataclass(frozen=True)
class WeatherDiscountResult:
    adjusted: float
    note: str


def apply_weather_discount(marginal: float, row: EnvRow) -> WeatherDiscountResult:
    """Apply a weather haircut to a marginal probability.

    Gates (in order):
    1. Indoor roofs (dome, indoor, closed) → no discount.
    2. Retractable-closed roof (retractable_closed, retractable-closed, or retractable with weather_exposed=false) → no discount.
    3. weather_exposed is false → no discount.
    4. weather_exposed is true but both wind_mph and precip_pop are None → no discount, note says fields blank.
    5. Otherwise apply wind + precip haircut (capped at 0.08 total), clip to [1e-9, 1-1e-9].

    Args:
        marginal: The fair probability for one leg (e.g., from devig or a typed median).
        row: EnvRow with roof, weather_exposed, wind_mph, precip_pop.

    Returns:
        WeatherDiscountResult with adjusted marginal and a note describing which gate fired.
    """
    roof = (row.roof or "").strip().lower()

    # Gate 1: indoor roofs
    if roof in {"dome", "indoor", "closed"}:
        return WeatherDiscountResult(
            adjusted=marginal,
            note="WEATHER_NO_DISCOUNT: indoor",
        )

    # Gate 2: retractable-closed
    if roof in {"retractable_closed", "retractable-closed"}:
        return WeatherDiscountResult(
            adjusted=marginal,
            note="WEATHER_NO_DISCOUNT: retractable-closed",
        )
    if roof == "retractable" and not row.weather_exposed:
        return WeatherDiscountResult(
            adjusted=marginal,
            note="WEATHER_NO_DISCOUNT: retractable-closed",
        )

    # Gate 3: not exposed
    if not row.weather_exposed:
        return WeatherDiscountResult(
            adjusted=marginal,
            note="WEATHER_NO_DISCOUNT: not exposed",
        )

    # Gate 4: exposed but both weather fields blank
    wind = row.wind_mph
    precip = row.precip_pop
    if wind is None and precip is None:
        return WeatherDiscountResult(
            adjusted=marginal,
            note="WEATHER_FIELDS_BLANK: marginal unchanged",
        )

    # Gate 5: apply haircut
    # Wind: min(0.04, max(0, wind - 10) * 0.002). None -> 0.
    wind_val = wind if wind is not None else 0.0
    wind_haircut = min(0.04, max(0.0, wind_val - 10.0) * 0.002)

    # Precip: min(0.04, (precip / 25) * 0.01). None -> 0.
    precip_val = precip if precip is not None else 0.0
    precip_haircut = min(0.04, (precip_val / 25.0) * 0.01)

    total_haircut = min(0.08, wind_haircut + precip_haircut)

    adjusted = marginal - total_haircut
    # Clip to avoid 0/1 which breaks norm.ppf
    adjusted = float(np.clip(adjusted, 1e-9, 1.0 - 1e-9))

    note = (
        f"WEATHER_DISCOUNT: haircut_pp={total_haircut:.6f} "
        f"marginal {marginal:.6f} -> {adjusted:.6f}"
    )
    return WeatherDiscountResult(adjusted=adjusted, note=note)


def sgp_from_score_marginals(
    marginals: list[float],
    corr_matrix: np.ndarray,
    rows: list[EnvRow],
    copula_type: str = "gaussian",
) -> tuple[float, list[str]]:
    """Compute an SGP joint probability from score marginals with optional weather discount.

    For each leg, if a corresponding EnvRow is provided, apply_weather_discount is called.
    The (possibly discounted) marginals are then passed to exact_joint.

    Args:
        marginals: List of fair probabilities for each leg (length k).
        corr_matrix: k x k correlation matrix.
        rows: List of EnvRow for each leg. If shorter than marginals, remaining legs
            get no discount. If None or empty, no discounts are applied.
        copula_type: Only "gaussian" is supported for exact_joint.

    Returns:
        Tuple of (joint_probability, list_of_notes). Notes include one per leg that
        went through apply_weather_discount, plus any copula errors.
    """
    if copula_type != "gaussian":
        raise ValueError("sgp_from_score_marginals only supports gaussian copula")

    k = len(marginals)
    if k == 0:
        raise ValueError("need at least one marginal")

    if corr_matrix.shape != (k, k):
        raise ValueError("correlation matrix shape must match marginals")

    adjusted_marginals: list[float] = []
    notes: list[str] = []

    for i, marginal in enumerate(marginals):
        if i < len(rows) and rows[i] is not None:
            result = apply_weather_discount(marginal, rows[i])
            adjusted_marginals.append(result.adjusted)
            notes.append(f"leg {i+1}: {result.note}")
        else:
            adjusted_marginals.append(marginal)
            notes.append(f"leg {i+1}: no env row provided")

    joint = exact_joint(adjusted_marginals, corr_matrix, copula_type=copula_type)
    return joint, notes