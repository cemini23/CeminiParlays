from __future__ import annotations

import re
import unicodedata

_SUFFIXES = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b", re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def fold_name(value: str) -> str:
    """Fold a display name into an nflverse-style player_key."""

    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("'", "").replace("’", "").replace(".", " ")
    text = _SUFFIXES.sub(" ", text)
    text = _NON_ALNUM.sub("_", text.lower()).strip("_")
    return text


def resolve_player_key(
    name: str,
    overrides: dict[str, str] | None = None,
    existing_key: str | None = None,
) -> str:
    """Prefer an explicit key, then a manual override, then the folded name."""

    if existing_key:
        return str(existing_key).strip()
    folded = fold_name(name)
    if overrides:
        return overrides.get(folded, overrides.get(name, folded))
    return folded
