"""Parlay composer: pick tickets from a ranked pool.

``compose_tickets`` is deterministic and file-only: it diversifies games, skips
illegal first-TD pairs, caps repeated ``stat_type`` values when asked, prefers
higher implied team totals when an environment file is present, and filters by
the American odds window. It never submits.
"""

from __future__ import annotations

from itertools import combinations

from ceminiparlays.environment import Environment, env_for
from ceminiparlays.markets import GAME_STATS, is_first_td
from ceminiparlays.odds import american_to_decimal
from ceminiparlays.slips import EvaluatedLeg

#: Largest pool the composer enumerates. 14 choose 5 is still tiny.
COMPOSE_POOL = 14


def _game_key(leg: EvaluatedLeg) -> tuple[str, ...]:
    teams = tuple(sorted({leg.line.team, leg.line.opponent}))
    return teams or (leg.line.player_name,)


def _leg_key(leg: EvaluatedLeg) -> tuple[str, str, str]:
    return (
        leg.line.player_key or leg.line.player_name,
        leg.line.stat_type,
        leg.line.side,
    )


def _leg_decimal(leg: EvaluatedLeg) -> float | None:
    """Single-leg decimal estimate for the odds-window screen."""

    if leg.line.leg_odds is not None:
        try:
            return american_to_decimal(int(leg.line.leg_odds))
        except ValueError:
            return None
    price = leg.line.contract_price
    if price is not None and 0.0 < price < 1.0:
        return 1.0 / price
    if 0.0 < leg.fair_p < 1.0:
        return 1.0 / leg.fair_p
    return None


def estimate_multiplier(legs: list[EvaluatedLeg]) -> tuple[float | None, str, bool]:
    """Estimate a combo decimal from typed prices.

    Returns ``(multiplier, source, unconfirmed)``. ``source`` is ``row``,
    ``slip_odds``, ``leg_odds_naive``, ``fair_naive``, ``conflict`` or ``none``.
    """

    row_ms = sorted(
        {leg.line.displayed_multiplier for leg in legs if leg.line.displayed_multiplier is not None}
    )
    if len(row_ms) > 1:
        return None, "conflict", False
    if row_ms:
        return float(row_ms[0]), "row", False
    slip_odds = [leg.line.slip_odds for leg in legs]
    if all(value is not None for value in slip_odds):
        distinct = sorted({int(value) for value in slip_odds if value is not None})
        if len(distinct) == 1:
            return american_to_decimal(distinct[0]), "slip_odds", False
        return None, "conflict", False
    if any(value is not None for value in slip_odds):
        return None, "conflict", False
    decimals: list[float] = []
    for leg in legs:
        decimal = _leg_decimal(leg)
        if decimal is None:
            return None, "none", False
        decimals.append(decimal)
    product = 1.0
    for decimal in decimals:
        product *= decimal
    if all(leg.line.leg_odds is not None for leg in legs):
        source = "leg_odds_naive"
    elif all(leg.line.contract_price is not None for leg in legs):
        source = "contract_product"
    else:
        source = "fair_naive"
    return product, source, True


def _over_market_cap(
    combo: tuple[EvaluatedLeg, ...],
    max_legs_per_market: int | None,
) -> bool:
    """True when one ``stat_type`` appears more than ``max_legs_per_market`` times.

    ``None`` or any int below 1 is no cap. Count the stored ``stat_type`` string.
    """

    if max_legs_per_market is None or max_legs_per_market < 1:
        return False
    counts: dict[str, int] = {}
    for leg in combo:
        stat = leg.line.stat_type
        counts[stat] = counts.get(stat, 0) + 1
        if counts[stat] > max_legs_per_market:
            return True
    return False


def _in_window(
    multiplier: float,
    min_odds: int | None,
    max_odds: int | None,
) -> bool:
    if min_odds is not None and max_odds is not None:
        if american_to_decimal(min_odds) > american_to_decimal(max_odds) + 1e-12:
            raise ValueError("--min-odds is longer than --max-odds")
    if min_odds is not None and multiplier + 1e-12 < american_to_decimal(min_odds):
        return False
    if max_odds is not None and multiplier > american_to_decimal(max_odds) + 1e-12:
        return False
    return True


def _score(
    legs: list[EvaluatedLeg] | tuple[EvaluatedLeg, ...],
    environment: Environment | None,
) -> tuple[float, float]:
    itt_total = 0.0
    have_itt = False
    for leg in legs:
        row = env_for(environment, leg.line.team, leg.line.opponent)
        if row is not None and row.implied_total is not None:
            itt_total += row.implied_total
            have_itt = True
    fair_total = sum(leg.fair_p for leg in legs)
    return (itt_total if have_itt else 0.0, fair_total)


def compose_tickets(
    live: list[EvaluatedLeg],
    *,
    n_tickets: int,
    sizes: list[int],
    min_odds: int | None,
    max_odds: int | None,
    markets: list[str] | None,
    environment: Environment | None,
    max_legs_per_market: int | None = None,
) -> list[list[EvaluatedLeg]]:
    """Pick up to ``n_tickets`` diversified tickets from ``live``.

    A first pass fills tickets with no shared legs; a second pass lets a card
    reuse an anchor leg to reach ``n_tickets`` (never a duplicate ticket). Each
    ticket uses distinct games. Same-game first-TD pairs never rank. When
    ``max_legs_per_market`` is an int >= 1, a combo where one ``stat_type``
    appears more than that many times is skipped. ``None`` or ``0`` is no cap.
    The odds window uses the best typed estimate (row M → slip_odds → leg_odds
    / fair product).
    """

    if n_tickets < 1:
        raise ValueError("n_tickets must be at least 1")
    market_set = set(markets) if markets else None
    skip_games = bool(market_set) and market_set.isdisjoint(GAME_STATS)
    pool = [
        leg
        for leg in live
        if (market_set is None or leg.line.stat_type in market_set)
        and not (skip_games and leg.line.stat_type in GAME_STATS)
    ]
    if not pool:
        return []
    ordered = sorted(pool, key=lambda leg: _score([leg], environment), reverse=True)
    candidate_pool = ordered[:COMPOSE_POOL]
    tickets: list[list[EvaluatedLeg]] = []
    chosen: set[frozenset[tuple[str, str, str]]] = set()
    for size in sizes:
        if len(tickets) >= n_tickets:
            break
        if size < 1:
            raise ValueError("leg count must be >= 1")
        scored: list[tuple[tuple[float, float], float, tuple[EvaluatedLeg, ...]]] = []
        for combo in combinations(candidate_pool, size):
            if len({_leg_key(leg) for leg in combo}) < size:
                continue
            if len({_game_key(leg) for leg in combo}) < size:
                continue
            first_tds = [leg for leg in combo if is_first_td(leg.line.stat_type)]
            if len(first_tds) > 1 and len({_game_key(leg) for leg in first_tds}) < len(first_tds):
                continue
            if _over_market_cap(combo, max_legs_per_market):
                continue
            multiplier, _source, _unconfirmed = estimate_multiplier(list(combo))
            if multiplier is None or multiplier <= 1.0:
                continue
            if not _in_window(multiplier, min_odds, max_odds):
                continue
            scored.append((_score(list(combo), environment), multiplier, combo))
        scored.sort(key=lambda item: (-item[0][0], -item[0][1], item[1]))
        # Pass 1: no leg appears on two tickets (maximum diversification).
        used: set[tuple[str, str, str]] = set()
        for _score_value, _multiplier, combo in scored:
            if len(tickets) >= n_tickets:
                break
            keys = {_leg_key(leg) for leg in combo}
            if keys & used:
                continue
            tickets.append(list(combo))
            used |= keys
            chosen.add(frozenset(keys))
        # Pass 2: the card is a menu of alternatives, so allow a shared anchor
        # leg to fill the remaining requested tickets (never a duplicate ticket).
        for _score_value, _multiplier, combo in scored:
            if len(tickets) >= n_tickets:
                break
            keys = frozenset(_leg_key(leg) for leg in combo)
            if keys in chosen:
                continue
            tickets.append(list(combo))
            chosen.add(keys)
    return tickets


def player_stat_ticket_counts(tickets: list[list[EvaluatedLeg]]) -> dict[tuple[str, str], int]:
    """Count tickets that carry each ``(player, stat_type)`` pair.

    Same player on yards + ATD is two keys. A player appearing twice on one
    ticket still counts as one ticket for that pair.
    """

    counts: dict[tuple[str, str], int] = {}
    for ticket in tickets:
        seen: set[tuple[str, str]] = set()
        for leg in ticket:
            player = (leg.line.player_key or leg.line.player_name).strip()
            if not player:
                continue
            key = (player, leg.line.stat_type)
            if key in seen:
                continue
            seen.add(key)
            counts[key] = counts.get(key, 0) + 1
    return counts


def concentration_warnings(tickets: list[list[EvaluatedLeg]]) -> list[str]:
    """Warn when the same player appears on two tickets in the same ``stat_type``.

    Yards + ATD on one player is not the same family. Warning only.
    """

    seen: dict[tuple[str, str], str] = {}
    warnings: list[str] = []
    emitted: set[tuple[str, str]] = set()
    for index, ticket in enumerate(tickets, start=1):
        ticket_keys: set[tuple[str, str]] = set()
        for leg in ticket:
            player = (leg.line.player_key or leg.line.player_name).strip()
            if not player:
                continue
            ticket_keys.add((player, leg.line.stat_type))
        for key in ticket_keys:
            prior = seen.get(key)
            if prior is not None and key not in emitted:
                player, stat = key
                warnings.append(
                    f"same-family concentration: {player} {stat} appears on "
                    f"ticket {prior} and ticket {index}"
                )
                emitted.add(key)
            else:
                seen.setdefault(key, str(index))
    return warnings


#: Fill-in ticket CSV columns (a legal lines file for ``rank``).
TICKET_FIELDS = [
    "ticket_id",
    "slate_id",
    "platform",
    "player_name",
    "player_key",
    "team",
    "opp",
    "stat_type",
    "line",
    "side",
    "book_over",
    "book_under",
    "leg_odds",
    "slip_odds",
    "slip_multiplier",
    "contract_price",
    "fair_p",
    "injury_status",
]


def ticket_rows(
    legs: list[EvaluatedLeg],
    ticket_id: str,
    platform: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for leg in legs:
        line = leg.line
        rows.append(
            {
                "ticket_id": ticket_id,
                "slate_id": line.slate_id,
                "platform": platform,
                "player_name": line.player_name,
                "player_key": line.player_key,
                "team": line.team,
                "opp": line.opponent,
                "stat_type": line.stat_type,
                "line": line.line,
                "side": line.side,
                "book_over": line.book_over if line.book_over is not None else "",
                "book_under": line.book_under if line.book_under is not None else "",
                "leg_odds": line.leg_odds if line.leg_odds is not None else "",
                "slip_odds": line.slip_odds if line.slip_odds is not None else "",
                "slip_multiplier": (
                    line.displayed_multiplier if line.displayed_multiplier is not None else ""
                ),
                "contract_price": (
                    line.contract_price if line.contract_price is not None else ""
                ),
                "fair_p": line.fair_p if line.fair_p is not None else "",
                "injury_status": line.injury_status,
            }
        )
    return rows
