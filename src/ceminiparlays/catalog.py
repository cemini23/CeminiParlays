"""Thin-catalog check for compose (TG-04 ``--enforce-market-depth``).

A game on the lines file is thin when it has no moneyline/h2h row or no
spread/spreads row after aliases. Totals-only does not satisfy the check.
"""

from __future__ import annotations

from dataclasses import dataclass

from ceminiparlays.io import LineRow
from ceminiparlays.markets import MARKET_ALIASES

MONEYLINE = "moneyline"
SPREAD = "spread"


@dataclass(frozen=True)
class ThinGame:
    game_key: tuple[str, ...]
    label: str
    has_moneyline: bool
    has_spread: bool


def _canonical_stat(stat_type: str) -> str:
    token = (stat_type or "").strip().lower()
    return MARKET_ALIASES.get(token, token)


def _game_key(team: str, opponent: str) -> tuple[str, ...]:
    return tuple(sorted({team.strip().upper(), opponent.strip().upper()}))


def thin_catalog_games(lines: list[LineRow]) -> list[ThinGame]:
    """Return games on ``lines`` that lack moneyline or spread rows."""

    stats_by_game: dict[tuple[str, ...], set[str]] = {}
    labels: dict[tuple[str, ...], str] = {}
    for row in lines:
        team = (row.team or "").strip()
        opp = (row.opponent or "").strip()
        if not team or not opp:
            continue
        key = _game_key(team, opp)
        stats_by_game.setdefault(key, set()).add(_canonical_stat(row.stat_type))
        labels.setdefault(key, "@".join(key))
    thin: list[ThinGame] = []
    for key, stats in stats_by_game.items():
        has_moneyline = MONEYLINE in stats
        has_spread = SPREAD in stats
        if not has_moneyline or not has_spread:
            thin.append(
                ThinGame(
                    game_key=key,
                    label=labels[key],
                    has_moneyline=has_moneyline,
                    has_spread=has_spread,
                )
            )
    thin.sort(key=lambda item: item.label)
    return thin
