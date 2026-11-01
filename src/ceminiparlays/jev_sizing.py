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


# Week-7 Hard Rock dollar card. Stakes are integer cents. The sum is $25.00.
HARDROCK_BANKROLL_CENTS = 2500
HARDROCK_TICKET_CAP_CENTS = 400
HARDROCK_GAME_CAP_CENTS = 625
HARDROCK_MIN_EV = 0.08
HARDROCK_MODE_B_LO = 200
HARDROCK_MODE_B_HI = 400
_MODE_A_PLAN = (
    ("checkdown", 6, 175),
    ("core", 5, 170),
    ("sgp", 6, 100),
)


@dataclass(frozen=True)
class DollarPlay:
    """One qualifying single or same-game slip. ``ev`` is already after vig."""

    play_id: str
    pool: str
    game_ids: tuple[str, ...]
    player_keys: tuple[str, ...]
    ev: float
    model_p: float
    decimal_odds: float
    priority: int = 1


@dataclass(frozen=True)
class DollarStake:
    play_id: str
    pool: str
    stake_cents: int


def _play_sort(play: DollarPlay) -> tuple[float, int, str]:
    return (-float(play.ev), int(play.priority), play.play_id)


def _exposure_ok(plays: list[DollarPlay], stakes: list[int], cap: int) -> bool:
    exposure: dict[str, int] = {}
    for play, stake in zip(plays, stakes, strict=True):
        for game in play.game_ids:
            exposure[game] = exposure.get(game, 0) + stake
    return all(cents <= cap for cents in exposure.values())


def _kelly_weights(plays: list[DollarPlay]) -> list[float]:
    """``0.25 * f*`` with ``f* = (p * M - 1) / (M - 1)``."""

    weights: list[float] = []
    for play in plays:
        decimal = float(play.decimal_odds)
        if decimal <= 1.0:
            weights.append(0.0)
            continue
        full = (float(play.model_p) * decimal - 1.0) / (decimal - 1.0)
        weights.append(max(0.0, KELLY_FRACTION * full))
    return weights


def _allocate_cents(
    plays: list[DollarPlay],
    *,
    bankroll: int,
    lo: int,
    hi: int,
) -> list[int]:
    """Scale fractional Kelly to ``bankroll`` cents inside ``[lo, hi]``."""

    count = len(plays)
    if count == 0:
        raise ValueError("no plays")
    if count * lo > bankroll or count * hi < bankroll:
        raise ValueError("stake bounds cannot sum to the bankroll")
    weights = _kelly_weights(plays)
    if sum(weights) <= 0.0:
        weights = [1.0] * count
    active = set(range(count))
    assigned = [0] * count
    remaining = bankroll
    for _step in range(count + 2):
        if not active:
            if remaining != 0:
                raise ValueError("could not land on the bankroll")
            return assigned
        weight_sum = sum(weights[index] for index in active)
        if weight_sum <= 0.0:
            raw = {index: remaining / len(active) for index in active}
        else:
            raw = {index: remaining * weights[index] / weight_sum for index in active}
        frozen: list[int] = []
        for index, value in raw.items():
            if value < lo:
                assigned[index] = lo
                remaining -= lo
                frozen.append(index)
            elif value > hi:
                assigned[index] = hi
                remaining -= hi
                frozen.append(index)
        if frozen:
            for index in frozen:
                active.discard(index)
            continue
        floors = {index: int(raw[index]) for index in active}
        for index in active:
            assigned[index] = min(hi, max(lo, floors[index]))
        drift = bankroll - sum(assigned)
        order = sorted(
            active,
            key=lambda index: (-(raw[index] - floors[index]), plays[index].play_id),
        )
        step = 1 if drift > 0 else -1
        guard = 0
        while drift != 0 and guard < bankroll + count:
            guard += 1
            moved = False
            for index in order:
                nxt = assigned[index] + step
                if lo <= nxt <= hi:
                    assigned[index] = nxt
                    drift -= step
                    moved = True
                    if drift == 0:
                        break
            if not moved:
                break
        if drift != 0 or sum(assigned) != bankroll:
            raise ValueError("could not land on the bankroll")
        return assigned
    raise ValueError("could not land on the bankroll")


def _fill_pool(
    plays: list[DollarPlay],
    *,
    count: int,
    cents: int,
    used: set[str],
    exposure: dict[str, int],
    cap: int,
) -> list[DollarPlay]:
    picked: list[DollarPlay] = []
    for play in sorted(plays, key=_play_sort):
        if float(play.ev) < HARDROCK_MIN_EV:
            continue
        if any(player in used for player in play.player_keys):
            continue
        if any(exposure.get(game, 0) + cents > cap for game in play.game_ids):
            continue
        picked.append(play)
        used.update(play.player_keys)
        for game in play.game_ids:
            exposure[game] = exposure.get(game, 0) + cents
        if len(picked) == count:
            break
    return picked


def _mode_a(plays: list[DollarPlay]) -> list[DollarStake] | None:
    qualified = [play for play in plays if float(play.ev) >= HARDROCK_MIN_EV]
    games = {game for play in qualified for game in play.game_ids}
    if len(qualified) < 12 or len(games) < 5:
        return None
    used: set[str] = set()
    exposure: dict[str, int] = {}
    stakes: list[DollarStake] = []
    for pool, count, cents in _MODE_A_PLAN:
        group = [play for play in qualified if play.pool == pool]
        picked = _fill_pool(
            group,
            count=count,
            cents=cents,
            used=used,
            exposure=exposure,
            cap=HARDROCK_GAME_CAP_CENTS,
        )
        if len(picked) < count:
            return None
        stakes.extend(
            DollarStake(play_id=play.play_id, pool=pool, stake_cents=cents) for play in picked
        )
    if sum(row.stake_cents for row in stakes) != HARDROCK_BANKROLL_CENTS:
        return None
    return stakes


def _greedy(plays: list[DollarPlay], per_game: int) -> list[DollarPlay]:
    chosen: list[DollarPlay] = []
    counts: dict[str, int] = {}
    used: set[str] = set()
    for play in sorted(plays, key=_play_sort):
        if len(chosen) >= 9:
            break
        if any(player in used for player in play.player_keys):
            continue
        if any(counts.get(game, 0) >= per_game for game in play.game_ids):
            continue
        chosen.append(play)
        used.update(player for player in play.player_keys if player)
        for game in play.game_ids:
            counts[game] = counts.get(game, 0) + 1
    return chosen


def _mode_b(plays: list[DollarPlay]) -> list[DollarStake]:
    qualified = [play for play in plays if float(play.ev) >= HARDROCK_MIN_EV]
    for per_game in (2, 1):
        chosen = _greedy(qualified, per_game)
        for width in range(min(9, len(chosen)), 6, -1):
            trial = chosen[:width]
            try:
                stakes = _allocate_cents(
                    trial,
                    bankroll=HARDROCK_BANKROLL_CENTS,
                    lo=HARDROCK_MODE_B_LO,
                    hi=HARDROCK_MODE_B_HI,
                )
            except ValueError:
                continue
            if not _exposure_ok(trial, stakes, HARDROCK_GAME_CAP_CENTS):
                continue
            return [
                DollarStake(play_id=play.play_id, pool=play.pool, stake_cents=stake)
                for play, stake in zip(trial, stakes, strict=True)
            ]
    raise ValueError("the slate cannot place $25.00 inside the ticket cap and the game cap")


def allocate_hardrock_dollars(plays: list[DollarPlay]) -> tuple[str, list[DollarStake]]:
    """Mode A when the broad template fits. Otherwise Mode B.

    Mode A is 6 checkdown singles at $1.75, 5 core singles at $1.70, and
    6 same-game slips at $1.00. Mode B spreads $25.00 across 7 to 9 plays
    with quarter-Kelly weights, each ticket from $2.00 to $4.00.
    """

    mode_a = _mode_a(plays)
    if mode_a is not None:
        return "A", mode_a
    return "B", _mode_b(plays)
