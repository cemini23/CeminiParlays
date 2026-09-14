"""Legal market tokens and TD helpers.

Phase 1 turns ``stat_type`` into an operator-selectable market family. The tokens
here are the only ones ``--markets`` accepts; anything else is a typo, not a
silent filter (a dropped leg is worse than a refused flag).
"""

from __future__ import annotations

from collections.abc import Iterable

#: Yardage props (the ``--auto`` default family).
YARDS_STATS = frozenset({"pass_yds", "rush_yds", "rec_yds"})
#: Discrete touchdown props. No Gaussian median; fair P needs a typed value.
TD_STATS = frozenset({"first_td", "anytime_td"})
#: Non-yard counting props that the fair model already supports.
COUNT_STATS = frozenset({"receptions", "rush_att", "pass_tds"})
#: Game markets (Odds API h2h / spreads / totals). Compose ``--auto`` skips these.
GAME_STATS = frozenset({"moneyline", "spread", "total"})

LEGAL_MARKETS = frozenset(YARDS_STATS | TD_STATS | COUNT_STATS | GAME_STATS)

#: Odds API keys and short names map onto GAME_STATS tokens.
MARKET_ALIASES = {
    "h2h": "moneyline",
    "moneyline": "moneyline",
    "spreads": "spread",
    "spread": "spread",
    "totals": "total",
    "total": "total",
}

#: Hard-coded ``--auto`` market family (ROADMAP defaults table). Yards only.
AUTO_MARKETS = ("pass_yds", "rush_yds", "rec_yds")

FIRST_TD = "first_td"
ANYTIME_TD = "anytime_td"


def is_first_td(stat_type: str) -> bool:
    return (stat_type or "").strip().lower() == FIRST_TD


def is_td_market(stat_type: str) -> bool:
    return (stat_type or "").strip().lower() in TD_STATS


def _tokens(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.split(",")
    else:
        parts = list(value)
    out: list[str] = []
    for part in parts:
        token = str(part).strip().lower()
        if token and token not in out:
            out.append(token)
    return out


def parse_markets(value: str | Iterable[str] | None) -> list[str]:
    """Parse a comma list of ``--markets`` tokens, refusing unknown ones."""

    tokens = _tokens(value)
    canonical: list[str] = []
    unknown: list[str] = []
    for token in tokens:
        mapped = MARKET_ALIASES.get(token, token)
        if mapped not in LEGAL_MARKETS:
            unknown.append(token)
        elif mapped not in canonical:
            canonical.append(mapped)
    if unknown:
        raise ValueError(
            f"unknown --markets token(s): {', '.join(unknown)}; "
            f"legal: {', '.join(sorted(LEGAL_MARKETS))}"
        )
    return canonical
