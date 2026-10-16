"""Continuous Bayesian Kelly shrinkage and slate exposure cap.

``jev_gate`` answers "is this ticket coherent?". This module answers "how big".
It upgrades the binary gate into a three-stage sizing controller:

* Stage 1 keeps the fail-closed hard gate. Missing game data, an inactive
  player, an unavailable provider, or a weak coherent probability all block.
* Stage 2 shrinks fractional Kelly by the epistemic confidence.
* Stage 3 caps the whole slate's exposure and scales every ticket down together.

This module does not price a leg and does not place a bet. The operator still
types every ticket. numpy does not appear here: the arithmetic is scalar.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ceminiparlays.jev_client import JevProviderError

COHERENT = "coherent_supported"
CONTRADICTORY = "contradictory_or_unsupported"
CHOICES = [COHERENT, CONTRADICTORY]
PASS = "PASS"
BLOCKED = "BLOCKED"

#: ``p_jev * c_jev`` below this fails the hard gate.
PASS_FLOOR = 0.50
#: The coherent product that earns full Kelly. ``0.50 + 0.35 = 0.85``.
SHRINK_SPAN = 0.35
#: Fraction of full Kelly that a fully-confident ticket may take.
KELLY_FRACTION = 0.25
DEFAULT_TICKET_CAP_PCT = 0.015
DEFAULT_SLATE_PCT = 0.06
INACTIVE_STATE = "pre_game_inactive"

#: Always required for a priced ticket, weather fields only when the game is exposed.
ALWAYS_REQUIRED = ("implied_total", "spread")
WEATHER_REQUIRED = ("wind_mph", "precip_pop")

SIZING_COLUMNS = [
    "ticket_id",
    "gate_status",
    "reason",
    "p_jev",
    "c_jev",
    "shrinkage",
    "raw_kelly_pct",
    "final_stake_pct",
    "jev_provider",
]


@dataclass(frozen=True)
class TicketInput:
    """One candidate ticket handed to the sizing controller."""

    ticket_id: str
    legs: list[dict]
    platform: str = ""
    environment: dict | None = None
    #: ``player -> jev_regime_state``. ``pre_game_inactive`` blocks the ticket.
    regime_flags: dict[str, str] | None = None
    kelly_f_star: float = 0.0


@dataclass(frozen=True)
class TicketSize:
    ticket_id: str
    gate_status: str
    reason: str
    p_jev: float
    c_jev: float
    shrinkage: float
    raw_kelly_pct: float
    final_stake_pct: float
    jev_provider: str

    def as_row(self) -> dict[str, str]:
        return {
            "ticket_id": self.ticket_id,
            "gate_status": self.gate_status,
            "reason": self.reason,
            "p_jev": f"{self.p_jev:.6f}",
            "c_jev": f"{self.c_jev:.6f}",
            "shrinkage": f"{self.shrinkage:.6f}",
            "raw_kelly_pct": f"{self.raw_kelly_pct:.6f}",
            "final_stake_pct": f"{self.final_stake_pct:.6f}",
            "jev_provider": self.jev_provider,
        }


def _clip(value: float, low: float, high: float) -> float:
    return min(max(float(value), low), high)


def shrinkage_factor(p_jev: float, c_jev: float) -> float:
    """Epistemic shrinkage in ``[0, 1]``. Below the floor it is exactly zero."""

    product = float(p_jev) * float(c_jev)
    if product < PASS_FLOOR:
        return 0.0
    return _clip((product - PASS_FLOOR) / SHRINK_SPAN, 0.0, 1.0)


def raw_ticket_stake(
    kelly_f_star: float,
    shrinkage: float,
    ticket_cap_pct: float = DEFAULT_TICKET_CAP_PCT,
) -> float:
    """Fractional Kelly, shrunk, then capped at one ticket's share of bankroll."""

    stake = KELLY_FRACTION * max(float(kelly_f_star), 0.0) * float(shrinkage)
    return min(float(ticket_cap_pct), stake)


def missing_environment_fields(environment: dict | None) -> list[str]:
    """Name every required environment field that is absent or None.

    A dome game is not penalized for wind it does not have: the weather fields
    are only required when ``weather_exposed`` is true.
    """

    if not environment:
        return [*ALWAYS_REQUIRED]
    missing = [key for key in ALWAYS_REQUIRED if environment.get(key) is None]
    if environment.get("weather_exposed"):
        missing.extend(key for key in WEATHER_REQUIRED if environment.get(key) is None)
    return missing


def inactive_players(ticket: TicketInput) -> list[str]:
    """Players whose regime state says they are already inactive at pre-game."""

    flags = ticket.regime_flags or {}
    names = [str(leg.get("player_name") or leg.get("player") or "").strip() for leg in ticket.legs]
    return [
        name
        for name in names
        if name and str(flags.get(name, "")).strip().lower() == INACTIVE_STATE
    ]


def coherent_question(ticket: TicketInput) -> str:
    legs = "; ".join(
        f"{str(leg.get('player_name') or leg.get('player') or '').strip()} "
        f"{str(leg.get('side') or '').strip()} {leg.get('line')} "
        f"{str(leg.get('stat_type') or '').strip()}"
        for leg in ticket.legs
    )
    env = ticket.environment or {}
    context = (
        f"Implied total {env.get('implied_total')}, spread {env.get('spread')}, "
        f"roof {env.get('roof') or 'unknown'}, wind {env.get('wind_mph')}, "
        f"precipitation probability {env.get('precip_pop')}."
    )
    return (
        f"Is this ticket internally coherent and supported by the game environment? "
        f"Platform: {ticket.platform or 'unknown'}. Legs: {legs}. {context}"
    )


def _blocked(ticket_id: str, reason: str, *, provider: str = "") -> TicketSize:
    return TicketSize(
        ticket_id=ticket_id,
        gate_status=BLOCKED,
        reason=reason,
        p_jev=0.0,
        c_jev=0.0,
        shrinkage=0.0,
        raw_kelly_pct=0.0,
        final_stake_pct=0.0,
        jev_provider=provider,
    )


def _gate_failure(ticket: TicketInput) -> str | None:
    """Stage 1 checks that need no provider call, in fail-closed order."""

    missing = missing_environment_fields(ticket.environment)
    if missing:
        return "missing_environment:" + ",".join(missing)
    inactive = inactive_players(ticket)
    if inactive:
        return "inactive_player:" + ",".join(inactive)
    if not ticket.legs:
        return "no_legs"
    return None


def size_ticket(
    client: Any,
    ticket: TicketInput,
    *,
    ticket_cap_pct: float = DEFAULT_TICKET_CAP_PCT,
) -> TicketSize:
    """Run Stage 1 and Stage 2 for one ticket. No slate cap here."""

    failure = _gate_failure(ticket)
    if failure is not None:
        return _blocked(ticket.ticket_id, failure)
    state = {
        "platform": ticket.platform,
        "environment": ticket.environment or {},
        "regime_flags": ticket.regime_flags or {},
        "legs": ticket.legs,
        "kelly_f_star": ticket.kelly_f_star,
    }
    try:
        result = client.jev_choice(state, coherent_question(ticket), CHOICES)
    except JevProviderError as exc:
        return _blocked(ticket.ticket_id, f"providers_unavailable:{exc}")
    except Exception as exc:  # any client failure fails the gate closed
        return _blocked(ticket.ticket_id, f"providers_unavailable:{exc}")
    p_jev = float(result.probabilities.get(COHERENT, 0.0))
    c_jev = float(result.confidence)
    provider = str(result.provider_used)
    if p_jev * c_jev < PASS_FLOOR:
        return _blocked(ticket.ticket_id, "below_coherence_floor", provider=provider)
    shrinkage = shrinkage_factor(p_jev, c_jev)
    return TicketSize(
        ticket_id=ticket.ticket_id,
        gate_status=PASS,
        reason="",
        p_jev=p_jev,
        c_jev=c_jev,
        shrinkage=shrinkage,
        raw_kelly_pct=raw_ticket_stake(ticket.kelly_f_star, shrinkage, ticket_cap_pct),
        final_stake_pct=0.0,
        jev_provider=provider,
    )


def apply_slate_cap(
    sizes: list[TicketSize], max_slate_pct: float = DEFAULT_SLATE_PCT
) -> list[TicketSize]:
    """Stage 3: scale every passing ticket down so the slate fits the cap."""

    total = sum(size.raw_kelly_pct for size in sizes if size.gate_status == PASS)
    if total <= 0.0 or total <= max_slate_pct:
        return [
            replace(size, final_stake_pct=size.raw_kelly_pct) for size in sizes
        ]
    scale = max_slate_pct / total
    out: list[TicketSize] = []
    for size in sizes:
        if size.gate_status != PASS:
            out.append(size)
            continue
        out.append(replace(size, final_stake_pct=size.raw_kelly_pct * scale))
    return out


def size_tickets(
    client: Any,
    tickets: list[TicketInput],
    *,
    ticket_cap_pct: float = DEFAULT_TICKET_CAP_PCT,
    max_slate_pct: float = DEFAULT_SLATE_PCT,
) -> list[TicketSize]:
    """Stage 1, 2, then 3 across one slate. Fails closed ticket by ticket."""

    sized = [size_ticket(client, ticket, ticket_cap_pct=ticket_cap_pct) for ticket in tickets]
    return apply_slate_cap(sized, max_slate_pct)


def write_sizing_report(path: Path, sizes: list[TicketSize]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SIZING_COLUMNS)
        writer.writeheader()
        for size in sizes:
            writer.writerow(size.as_row())
