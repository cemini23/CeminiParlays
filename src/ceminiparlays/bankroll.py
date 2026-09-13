"""Flat vs quarter-Kelly stake sizing for a composed card.

The Kelly side reuses :func:`ceminiparlays.kelly.slip_kelly`, whose hard cap is
5% of bankroll. Power Kelly semantics are unchanged (I-35).
"""

from __future__ import annotations

from ceminiparlays.kelly import slip_kelly

#: Fraction of bankroll a single ticket may risk at the slip_kelly cap.
KELLY_CAP_FRACTION = 0.05


def flat_stake(bankroll: float, n_tickets: int) -> float:
    """Split the bankroll evenly across ``n_tickets`` tickets."""

    if bankroll < 0:
        raise ValueError("bankroll must be non-negative")
    if n_tickets < 1:
        raise ValueError("n_tickets must be at least 1")
    return round(bankroll / n_tickets, 2)


def kelly_cap_stake(bankroll: float, fraction: float = 0.25) -> float:
    """Per-ticket cap from the existing quarter-Kelly 5% limit."""

    if bankroll < 0:
        raise ValueError("bankroll must be non-negative")
    cap_fraction = slip_kelly(1.0, 2.0, fraction=fraction)
    return round(bankroll * cap_fraction, 2)
