"""Authoritative team for a live leg.

The book row is the current team. Both sides are mapped to nflverse codes
before a compare or a team-feature join. A full name, a nickname, and an
old abbreviation all land on the same code. This module does not guess a
team from a player name.
"""

from __future__ import annotations

import json

from ceminiparlays.resources import read_config_text
from ceminiparlays.roster import TEAM_ALIASES, normalize_team

_NAME_TO_CODE: dict[str, str] | None = None
_CODES: set[str] | None = None


def _names() -> dict[str, str]:
    global _NAME_TO_CODE, _CODES
    if _NAME_TO_CODE is None:
        raw = json.loads(read_config_text("nfl_teams.json"))
        _NAME_TO_CODE = {
            str(name).strip().lower(): str(code).strip().upper() for name, code in raw.items()
        }
        _CODES = set(_NAME_TO_CODE.values()) | set(TEAM_ALIASES.values())
    return _NAME_TO_CODE


def canonical_team(value: str) -> str:
    """Map a book label or a feature code onto one nflverse abbreviation."""

    text = (value or "").strip()
    if not text:
        return ""
    names = _names()
    folded = text.lower()
    if folded in names:
        return names[folded]
    code = normalize_team(text)
    if code in (_CODES or set()):
        return code
    last = folded.split()[-1]
    hits = {item for name, item in names.items() if name.split()[-1] == last}
    if len(hits) == 1:
        return next(iter(hits))
    return code


def offensive_team(book_team: str, feature_team: str = "") -> str:
    """Return the team that supplies team-level offense features.

    A non-blank book team wins. A blank book team falls back to the feature
    team. Both values are canonical nflverse codes.
    """

    book = canonical_team(book_team)
    if book:
        return book
    return canonical_team(feature_team)


def teams_disagree(book_team: str, feature_team: str) -> bool:
    """True only when both sides are present and their codes differ."""

    book = canonical_team(book_team)
    feature = canonical_team(feature_team)
    if not book or not feature:
        return False
    return book != feature
