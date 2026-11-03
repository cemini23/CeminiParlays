from __future__ import annotations

import re
import unicodedata

_SUFFIXES = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b", re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# One sportsbook spelling and the ESPN box-score spelling share a person.
# The key and the value are both loose_name() forms. The value is canonical.
_CANONICAL = {
    "kenneth gainwell": "kenneth gainwell",
    "kenny gainwell": "kenneth gainwell",
    "k gainwell": "kenneth gainwell",
    "kgainwell": "kenneth gainwell",
    "marquise brown": "marquise brown",
    "hollywood brown": "marquise brown",
    "bam knight": "zonovan knight",
    "zonovan knight": "zonovan knight",
    "josh palmer": "joshua palmer",
    "joshua palmer": "joshua palmer",
    "chigoziem okonkwo": "chigoziem okonkwo",
    "chig okonkwo": "chigoziem okonkwo",
}


class AliasRequiredError(LookupError):
    """A box score has one last-name, team, and position match and no alias.

    Grade must not mark the leg void. Add the pair to ``_CANONICAL``.
    """

    def __init__(self, ticket_name: str, box_name: str, team: str, position: str) -> None:
        self.ticket_name = ticket_name
        self.box_name = box_name
        self.team = team
        self.position = position
        super().__init__(
            "AliasRequiredError: "
            f"{ticket_name} matches {box_name} ({team} {position}) "
            "by last name, team, and position. Add the alias. The leg was not voided."
        )


def loose_name(value: str) -> str:
    """Lower-case name. A period becomes a space. A suffix is removed."""

    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("'", "").replace("’", "").replace(".", " ")
    text = _SUFFIXES.sub(" ", text.lower())
    text = _NON_ALNUM.sub(" ", text)
    return " ".join(text.split())


def canonical_person(name: str) -> str:
    """Map a known sportsbook spelling onto one person key."""

    loose = loose_name(name)
    return _CANONICAL.get(loose, loose)


def names_match(left: str, right: str) -> bool:
    """True when two spellings are the same person, including a known alias."""

    a = canonical_person(left)
    b = canonical_person(right)
    return bool(a) and a == b


def alias_fold_keys(name: str) -> list[str]:
    """Folded keys for a name and its canonical alias."""

    keys: list[str] = []
    for text in (name, loose_name(name), canonical_person(name)):
        folded = fold_name(text)
        if folded and folded not in keys:
            keys.append(folded)
    return keys


def unique_box_alias(
    ticket_name: str,
    team: str,
    position: str,
    box_players: list[dict],
) -> str | None:
    """The one final box-score name that shares last name, team, and position.

    ``None`` when an alias already matches, or when the candidate is not unique.
    A blank position does not count.
    """

    if any(names_match(ticket_name, str(player.get("name") or "")) for player in box_players):
        return None
    parts = loose_name(ticket_name).split()
    if not parts:
        return None
    last = parts[-1]
    want_team = str(team or "").strip().upper()
    want_pos = str(position or "").strip().upper()
    if not last or not want_team or not want_pos:
        return None
    hits: list[str] = []
    for player in box_players:
        name = str(player.get("name") or "")
        player_parts = loose_name(name).split()
        if not player_parts or player_parts[-1] != last:
            continue
        if str(player.get("team") or "").strip().upper() != want_team:
            continue
        if str(player.get("position") or "").strip().upper() != want_pos:
            continue
        if name not in hits:
            hits.append(name)
    if len(hits) == 1:
        return hits[0]
    return None


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
