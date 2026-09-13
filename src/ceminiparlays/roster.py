from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ceminiparlays.io import LineRow
from ceminiparlays.names import fold_name
from ceminiparlays.resources import read_config_text

TEAM_ALIASES = {
    "ARI": "ARI",
    "ATL": "ATL",
    "BAL": "BAL",
    "BUF": "BUF",
    "CAR": "CAR",
    "CHI": "CHI",
    "CIN": "CIN",
    "CLE": "CLE",
    "DAL": "DAL",
    "DEN": "DEN",
    "DET": "DET",
    "GB": "GB",
    "GBP": "GB",
    "GNB": "GB",
    "HOU": "HOU",
    "IND": "IND",
    "JAC": "JAX",
    "JAX": "JAX",
    "KC": "KC",
    "KAN": "KC",
    "LA": "LAR",
    "LAR": "LAR",
    "LAC": "LAC",
    "LV": "LV",
    "RAI": "LV",
    "MIA": "MIA",
    "MIN": "MIN",
    "NE": "NE",
    "NWE": "NE",
    "NO": "NO",
    "NOR": "NO",
    "NYG": "NYG",
    "NYJ": "NYJ",
    "PHI": "PHI",
    "PIT": "PIT",
    "SEA": "SEA",
    "SF": "SF",
    "SFO": "SF",
    "TB": "TB",
    "TAM": "TB",
    "TEN": "TEN",
    "OTI": "TEN",
    "WAS": "WAS",
    "WSH": "WAS",
}


@dataclass(frozen=True)
class RosterPlayer:
    player_key: str
    name: str
    team: str


@dataclass
class Roster:
    """Known player → team map. Unknown names pass; a known name on the wrong team does not."""

    season: int
    retrieved: str
    players: dict[str, RosterPlayer]
    aliases: dict[str, str]


def normalize_team(code: str) -> str:
    text = (code or "").strip().upper()
    return TEAM_ALIASES.get(text, text)


def load_roster(path: Path | None = None) -> Roster:
    if path is None:
        raw = json.loads(read_config_text("rosters", "nfl.json"))
    else:
        raw = json.loads(path.read_text(encoding="utf-8"))
    aliases = {str(key).strip().lower(): str(value) for key, value in (raw.get("aliases") or {}).items()}
    players: dict[str, RosterPlayer] = {}
    for key, entry in (raw.get("players") or {}).items():
        if not isinstance(entry, Mapping):
            continue
        team = normalize_team(str(entry.get("team", "")))
        if not team:
            continue
        player_key = str(key)
        players[player_key] = RosterPlayer(
            player_key=player_key,
            name=str(entry.get("name") or player_key),
            team=team,
        )
    return Roster(
        season=int(raw.get("season") or 0),
        retrieved=str(raw.get("retrieved") or ""),
        players=players,
        aliases=aliases,
    )


def lookup_player(line: LineRow, roster: Roster) -> RosterPlayer | None:
    candidates = []
    if line.player_key:
        candidates.append(line.player_key)
        candidates.append(roster.aliases.get(line.player_key.lower(), ""))
    folded = fold_name(line.player_name)
    candidates.append(folded)
    candidates.append(roster.aliases.get(folded, ""))
    candidates.append(roster.aliases.get(line.player_name.strip().lower(), ""))
    for key in candidates:
        if key and key in roster.players:
            return roster.players[key]
    return None


def roster_mismatch(line: LineRow, roster: Roster) -> str | None:
    """Return ``wrong-team`` when a known player is typed on another club.

    Unknown players return ``None`` so a new call-up does not abort the slate.
    """

    found = lookup_player(line, roster)
    if found is None:
        return None
    typed = normalize_team(line.team)
    if not typed:
        return None
    if typed != found.team:
        return "wrong-team"
    return None
