"""Venue-mix sizing across sportsbooks and prediction markets.

This module extends the quarter-Kelly engine from one venue to a mix. Each
venue carries its own edge, fee, liquidity cap, and correlated-exposure group.
The allocator caps a venue, caps a group, and caps the whole slate, then asserts
that every bound held before it returns.

It does not price a leg and it does not place a bet. The arithmetic is scalar.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from ceminiparlays.kelly import slip_kelly

DEFAULT_TOTAL_CAP_PCT = 0.06
DEFAULT_GROUP_CAP_PCT = 0.045
DEFAULT_KELLY_FRACTION = 0.25
EPS = 1e-9

VENUE_COLUMNS = [
    "venue",
    "group",
    "model_p",
    "decimal_odds",
    "effective_odds",
    "net_edge",
    "kelly_pct",
    "stake_pct",
    "stake_dollars",
    "cap_reason",
]


@dataclass(frozen=True)
class VenueProfile:
    venue: str
    volume_share: float
    parlay_share: float
    fee_rate: float
    max_stake_pct: float
    group: str = ""


@dataclass(frozen=True)
class VenueCandidate:
    venue: str
    model_p: float
    decimal_odds: float


@dataclass(frozen=True)
class VenueStake:
    venue: str
    group: str
    model_p: float
    decimal_odds: float
    effective_odds: float
    net_edge: float
    kelly_pct: float
    stake_pct: float
    stake_dollars: float
    cap_reason: str


@dataclass(frozen=True)
class VenueMixResult:
    stakes: tuple[VenueStake, ...]
    total_pct: float
    total_dollars: float
    addressable_share: dict[str, float]


def effective_odds(decimal_odds: float, fee_rate: float) -> float:
    """Posted decimal price after the venue keeps ``fee_rate`` of the win."""

    price = float(decimal_odds)
    if price <= 1.0:
        return 1.0
    return 1.0 + (price - 1.0) * (1.0 - float(fee_rate))


def addressable_share(profiles: list[VenueProfile]) -> dict[str, float]:
    """Normalized ``volume_share * parlay_share`` per venue.

    An all-zero product returns ``{}``. A duplicate venue raises.
    """

    products: dict[str, float] = {}
    for profile in profiles:
        venue = str(profile.venue)
        if venue in products:
            raise ValueError(f"duplicate venue profile: {venue}")
        products[venue] = float(profile.volume_share) * float(profile.parlay_share)
    total = sum(products.values())
    if total <= 0.0:
        return {}
    return {venue: product / total for venue, product in products.items()}


def venue_kelly(
    candidate: VenueCandidate,
    profile: VenueProfile,
    kelly_fraction: float = DEFAULT_KELLY_FRACTION,
) -> float:
    """Quarter-Kelly on the venue's fee-adjusted decimal price."""

    price = effective_odds(candidate.decimal_odds, profile.fee_rate)
    return slip_kelly(candidate.model_p, price, fraction=kelly_fraction)


def _check_unit(name: str, value: float) -> None:
    if not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{name} must be in [0, 1], got {value}")


def _validate(
    candidates: list[VenueCandidate],
    profiles: list[VenueProfile],
    *,
    bankroll: float,
    total_cap_pct: float,
    group_cap_pct: float,
    kelly_fraction: float,
) -> dict[str, VenueProfile]:
    if float(bankroll) < 0.0:
        raise ValueError("bankroll must be non-negative")
    if not 0.0 < float(total_cap_pct) <= 1.0:
        raise ValueError("total_cap_pct must be in (0, 1]")
    if not 0.0 < float(group_cap_pct) <= 1.0:
        raise ValueError("group_cap_pct must be in (0, 1]")
    if not 0.0 < float(kelly_fraction) <= 1.0:
        raise ValueError("kelly_fraction must be in (0, 1]")
    by_venue: dict[str, VenueProfile] = {}
    for profile in profiles:
        if not str(profile.venue).strip():
            raise ValueError("profile venue must be non-blank")
        _check_unit("volume_share", profile.volume_share)
        _check_unit("parlay_share", profile.parlay_share)
        _check_unit("fee_rate", profile.fee_rate)
        _check_unit("max_stake_pct", profile.max_stake_pct)
        by_venue[str(profile.venue)] = profile
    for candidate in candidates:
        venue = str(candidate.venue)
        if venue not in by_venue:
            raise ValueError(f"candidate has no venue profile: {venue}")
        if not 0.0 < float(candidate.model_p) < 1.0:
            raise ValueError(f"model_p must be in (0, 1) for {venue}")
        if float(candidate.decimal_odds) <= 1.0:
            raise ValueError(f"decimal_odds must exceed 1 for {venue}")
    return by_venue


def _row(
    candidate: VenueCandidate,
    profile: VenueProfile,
    *,
    kelly_pct: float,
    stake_pct: float,
    bankroll: float,
    cap_reason: str,
) -> VenueStake:
    price = effective_odds(candidate.decimal_odds, profile.fee_rate)
    return VenueStake(
        venue=str(candidate.venue),
        group=str(profile.group or ""),
        model_p=float(candidate.model_p),
        decimal_odds=float(candidate.decimal_odds),
        effective_odds=price,
        net_edge=float(candidate.model_p) * price - 1.0,
        kelly_pct=float(kelly_pct),
        stake_pct=float(stake_pct),
        stake_dollars=round(float(bankroll) * float(stake_pct), 2),
        cap_reason=cap_reason,
    )


def allocate_venue_mix(
    candidates: list[VenueCandidate],
    profiles: list[VenueProfile],
    *,
    bankroll: float,
    total_cap_pct: float = DEFAULT_TOTAL_CAP_PCT,
    group_cap_pct: float = DEFAULT_GROUP_CAP_PCT,
    kelly_fraction: float = DEFAULT_KELLY_FRACTION,
) -> VenueMixResult:
    """Allocate one bankroll across venues inside every cap."""

    by_venue = _validate(
        candidates,
        profiles,
        bankroll=bankroll,
        total_cap_pct=total_cap_pct,
        group_cap_pct=group_cap_pct,
        kelly_fraction=kelly_fraction,
    )
    shares = addressable_share(profiles)

    kelly: list[float] = []
    edges: list[float] = []
    weights: list[float] = []
    for candidate in candidates:
        profile = by_venue[str(candidate.venue)]
        k = venue_kelly(candidate, profile, kelly_fraction)
        edge = float(candidate.model_p) * effective_odds(
            candidate.decimal_odds, profile.fee_rate
        ) - 1.0
        kelly.append(k)
        edges.append(edge)
        share = shares.get(str(candidate.venue), 1.0) if shares else 1.0
        weights.append(k * share if k > 0.0 and edge > 0.0 else 0.0)

    budget = min(sum(kelly), float(total_cap_pct))
    if budget <= 0.0:
        zeroed = [
            _row(
                candidate,
                by_venue[str(candidate.venue)],
                kelly_pct=kelly[index],
                stake_pct=0.0,
                bankroll=bankroll,
                cap_reason="",
            )
            for index, candidate in enumerate(candidates)
        ]
        zeroed.sort(key=lambda row: (-row.net_edge, row.venue))
        return VenueMixResult(
            stakes=tuple(zeroed),
            total_pct=0.0,
            total_dollars=0.0,
            addressable_share=dict(shares),
        )

    count = len(candidates)
    stake = [0.0] * count
    reason = [""] * count
    weight_total = sum(weights)
    if weight_total <= 0.0:
        weights = list(kelly)
        weight_total = sum(weights)
    active = [index for index in range(count) if weights[index] > 0.0]
    if not active:
        active = list(range(count))
        weights = [1.0] * count
        weight_total = float(count)
    for index in active:
        stake[index] = budget * weights[index] / weight_total

    clamped: set[int] = set()
    for _pass in range(10):
        over = [
            index
            for index in active
            if index not in clamped
            and stake[index] > by_venue[str(candidates[index].venue)].max_stake_pct + EPS
        ]
        if not over:
            break
        for index in over:
            cap = by_venue[str(candidates[index].venue)].max_stake_pct
            stake[index] = cap
            reason[index] = "venue_cap"
            clamped.add(index)
        free = [index for index in active if index not in clamped]
        if not free:
            break
        remaining = budget - sum(stake[index] for index in clamped)
        if remaining <= 0.0:
            for index in free:
                stake[index] = 0.0
            break
        free_weight = sum(weights[index] for index in free)
        if free_weight <= 0.0:
            break
        for index in free:
            stake[index] = remaining * weights[index] / free_weight

    # The cap is a venue cap, not a row cap: several candidates may share a
    # venue, so scale that venue's rows down together.
    rows_by_venue: dict[str, list[int]] = {}
    for index in range(count):
        rows_by_venue.setdefault(str(candidates[index].venue), []).append(index)
    for venue, indices in rows_by_venue.items():
        cap = by_venue[venue].max_stake_pct
        venue_total = sum(stake[index] for index in indices)
        if venue_total <= cap + EPS:
            continue
        scale = cap / venue_total
        for index in indices:
            stake[index] *= scale
            if not reason[index]:
                reason[index] = "venue_cap"

    groups: dict[str, list[int]] = {}
    for index in range(count):
        group = str(by_venue[str(candidates[index].venue)].group or "")
        if not group:
            # An empty group is "not correlated" rather than one shared bucket,
            # so the group cap never collapses unrelated venues together.
            continue
        groups.setdefault(group, []).append(index)
    for group, indices in groups.items():
        total = sum(stake[index] for index in indices)
        if total <= float(group_cap_pct) + EPS:
            continue
        scale = float(group_cap_pct) / total
        for index in indices:
            stake[index] *= scale
            if not reason[index]:
                reason[index] = "group_cap"

    total = sum(stake)
    if total > float(total_cap_pct) + EPS:
        scale = float(total_cap_pct) / total
        for index in range(count):
            stake[index] *= scale
            if not reason[index]:
                reason[index] = "total_cap"

    rows: list[VenueStake] = []
    for index, candidate in enumerate(candidates):
        profile = by_venue[str(candidate.venue)]
        rows.append(
            _row(
                candidate,
                profile,
                kelly_pct=kelly[index],
                stake_pct=stake[index],
                bankroll=bankroll,
                cap_reason=reason[index],
            )
        )

    for index, candidate in enumerate(candidates):
        profile = by_venue[str(candidate.venue)]
        assert 0.0 <= stake[index] <= profile.max_stake_pct + EPS
    for venue, indices in rows_by_venue.items():
        assert sum(stake[index] for index in indices) <= by_venue[venue].max_stake_pct + EPS
    for indices in groups.values():
        assert sum(stake[index] for index in indices) <= float(group_cap_pct) + EPS
    total_pct = sum(stake)
    assert total_pct <= float(total_cap_pct) + EPS
    assert total_pct <= sum(kelly) + EPS

    rows.sort(key=lambda row: (-row.net_edge, row.venue))
    total_dollars = round(sum(row.stake_dollars for row in rows), 2)
    return VenueMixResult(
        stakes=tuple(rows),
        total_pct=total_pct,
        total_dollars=total_dollars,
        addressable_share=dict(shares),
    )


def _required(fields: list[str], column: str) -> None:
    if column not in fields:
        raise ValueError(f"CSV missing column: {column}")


def _number(raw: dict, column: str) -> float:
    try:
        return float(str(raw.get(column) or "").strip())
    except ValueError as exc:
        raise ValueError(f"column {column} is not a number: {raw.get(column)!r}") from exc


def read_venue_profiles(path: Path) -> list[VenueProfile]:
    """Read venue profiles from CSV. A missing file or a bad value raises."""

    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"venue profile CSV missing: {resolved}")
    profiles: list[VenueProfile] = []
    with resolved.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        for column in ("venue", "volume_share", "parlay_share", "fee_rate", "max_stake_pct"):
            _required(fields, column)
        for raw in reader:
            venue = str(raw.get("venue") or "").strip()
            if not venue:
                raise ValueError("venue profile has a blank venue")
            volume_share = _number(raw, "volume_share")
            parlay_share = _number(raw, "parlay_share")
            fee_rate = _number(raw, "fee_rate")
            max_stake_pct = _number(raw, "max_stake_pct")
            for name, value in (
                ("volume_share", volume_share),
                ("parlay_share", parlay_share),
                ("fee_rate", fee_rate),
                ("max_stake_pct", max_stake_pct),
            ):
                _check_unit(name, value)
            profiles.append(
                VenueProfile(
                    venue=venue,
                    volume_share=volume_share,
                    parlay_share=parlay_share,
                    fee_rate=fee_rate,
                    max_stake_pct=max_stake_pct,
                    group=str(raw.get("group") or "").strip(),
                )
            )
    return profiles


def read_candidates(path: Path) -> list[VenueCandidate]:
    """Read venue candidates from CSV. An optional ``ticket_id`` is ignored."""

    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"candidate CSV missing: {resolved}")
    candidates: list[VenueCandidate] = []
    with resolved.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        for column in ("venue", "model_p", "decimal_odds"):
            _required(fields, column)
        for raw in reader:
            venue = str(raw.get("venue") or "").strip()
            if not venue:
                raise ValueError("candidate has a blank venue")
            model_p = _number(raw, "model_p")
            decimal_odds = _number(raw, "decimal_odds")
            if not 0.0 < model_p < 1.0:
                raise ValueError(f"model_p must be in (0, 1) for {venue}")
            if decimal_odds <= 1.0:
                raise ValueError(f"decimal_odds must exceed 1 for {venue}")
            candidates.append(
                VenueCandidate(
                    venue=venue,
                    model_p=model_p,
                    decimal_odds=decimal_odds,
                )
            )
    return candidates


def write_venue_mix(path: Path, result: VenueMixResult) -> None:
    """Write one CSV row per stake, sorted exactly as the result carries them."""

    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=VENUE_COLUMNS)
        writer.writeheader()
        for stake in result.stakes:
            writer.writerow(
                {
                    "venue": stake.venue,
                    "group": stake.group,
                    "model_p": f"{stake.model_p:.6f}",
                    "decimal_odds": f"{stake.decimal_odds:.6f}",
                    "effective_odds": f"{stake.effective_odds:.6f}",
                    "net_edge": f"{stake.net_edge:.6f}",
                    "kelly_pct": f"{stake.kelly_pct:.6f}",
                    "stake_pct": f"{stake.stake_pct:.6f}",
                    "stake_dollars": f"{stake.stake_dollars:.2f}",
                    "cap_reason": stake.cap_reason,
                }
            )
