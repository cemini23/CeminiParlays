from __future__ import annotations


def slip_kelly(p_joint: float, multiplier: float, fraction: float = 0.25) -> float:
    """Fractional Kelly on one all-or-nothing slip.

    f* = (p * M - 1) / (M - 1). Default is quarter Kelly.
    """

    if multiplier <= 1.0:
        return 0.0
    p = min(max(p_joint, 0.0), 1.0)
    full = (p * multiplier - 1.0) / (multiplier - 1.0)
    sized = max(0.0, full) * fraction
    return min(sized, 0.05)


def stake_dollars(bankroll: float, kelly_fraction: float) -> float:
    if bankroll < 0:
        raise ValueError("bankroll must be non-negative")
    return round(bankroll * kelly_fraction, 2)
