from __future__ import annotations

from dataclasses import dataclass

from ceminiparlays.odds import devig_two_way
from ceminiparlays.payouts import resolve_payout


@dataclass(frozen=True)
class PickemGapReport:
    odds_over: int
    odds_under: int
    platform: str
    legs: int
    mode: str
    method: str
    side: str
    displayed_multiplier: float | None
    fair_p: float
    fair_joint: float
    fair_decimal: float
    table_all: float
    gap: float
    note: str

    def __str__(self) -> str:
        lines = [
            "Pick'em gap report",
            f"  odds: {self.odds_over} / {self.odds_under}",
            f"  method: {self.method}",
            f"  side: {self.side}",
            f"  fair_p: {self.fair_p:.6f}",
            f"  fair_joint ({self.legs} legs): {self.fair_joint:.6f}",
            f"  fair_decimal (1 / joint): {self.fair_decimal:.6f}",
            f"  platform: {self.platform} {self.mode} {self.legs}-leg",
            f"  table_all: {self.table_all:.6f}",
            f"  gap (fair_decimal - table_all): {self.gap:.6f}",
        ]
        if self.displayed_multiplier is not None:
            lines.append(f"  displayed_multiplier (unchanged, operator types this): {self.displayed_multiplier:.6f}")
        if self.note:
            lines.append(f"  note: {self.note}")
        return "\n".join(lines)


def pickem_gap(
    odds_over: int,
    odds_under: int,
    platform: str,
    legs: int,
    mode: str = "standard",
    method: str = "power",
    side: str = "over",
    displayed_multiplier: float | None = None,
) -> PickemGapReport:
    """Compare a de-juiced two-way fair price with a fixed pick'em all-hit multiplier.

    Args:
        odds_over: American odds for the over.
        odds_under: American odds for the under.
        platform: "prizepicks" or "underdog".
        legs: Number of legs in the slip.
        mode: Payout mode (standard, power, flex).
        method: De-vig method ("power", "multiplicative", "additive").
        side: "over" or "under" — which de-vigged probability to use for each leg.
        displayed_multiplier: Optional in-app multiplier the operator types.
            This is echoed in the report but does NOT affect the gap calculation,
            which always uses the fixed table value from the platform JSON.

    Returns:
        A PickemGapReport with the fair price, table multiplier, and gap.
    """
    result = devig_two_way(odds_over, odds_under, method=method)

    if side == "over":
        fair_p = result.p_over
    elif side == "under":
        fair_p = result.p_under
    else:
        raise ValueError(f"side must be 'over' or 'under', got {side!r}")

    fair_joint = fair_p**legs
    if fair_joint <= 0:
        fair_decimal = float("inf")
    else:
        fair_decimal = 1.0 / fair_joint

    table = resolve_payout(platform, mode, legs, displayed_multiplier=None)
    table_all = table.all_hit

    gap = fair_decimal - table_all

    note = ""
    if displayed_multiplier is not None:
        note = f"displayed_multiplier={displayed_multiplier:.6f} (operator types this; table value used for gap)"

    return PickemGapReport(
        odds_over=odds_over,
        odds_under=odds_under,
        platform=platform,
        legs=legs,
        mode=mode,
        method=method,
        side=side,
        displayed_multiplier=displayed_multiplier,
        fair_p=fair_p,
        fair_joint=fair_joint,
        fair_decimal=fair_decimal,
        table_all=table_all,
        gap=gap,
        note=note,
    )