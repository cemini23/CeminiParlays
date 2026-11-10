from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ceminiparlays.io import LineRow
from ceminiparlays.names import alias_fold_keys, fold_name
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
    for folded in alias_fold_keys(line.player_name):
        candidates.append(folded)
        candidates.append(roster.aliases.get(folded, ""))
    candidates.append(roster.aliases.get(line.player_name.strip().lower(), ""))
    for key in candidates:
        if key and key in roster.players:
            return roster.players[key]
    return None


def _assignment_index(assignments: Mapping[str, str]) -> dict[str, str]:
    """Map a name, a folded name, and a player key onto one club code."""

    index: dict[str, str] = {}
    for raw_key, raw_team in assignments.items():
        team = normalize_team(str(raw_team))
        key = str(raw_key or "").strip()
        if not team or not key:
            continue
        index[key.lower()] = team
        folded = fold_name(key)
        if folded:
            index[folded] = team
    return index


def _assigned_team(player: RosterPlayer, index: dict[str, str]) -> str | None:
    candidates = (
        player.player_key,
        player.player_key.lower(),
        fold_name(player.player_key),
        player.name,
        player.name.lower(),
        fold_name(player.name),
    )
    for key in candidates:
        if key and key in index:
            return index[key]
        if key and key.lower() in index:
            return index[key.lower()]
    return None


def apply_active_teams(roster: Roster, assignments: Mapping[str, str]) -> Roster:
    """Return a roster whose current-week club overrides the static file.

    ``assignments`` come from a handoff, a salary file, or telemetry. A name
    that is not on the roster stays unknown. The static JSON file is not
    rewritten. The same object is returned when no club changes.
    """

    index = _assignment_index(assignments)
    if not index:
        return roster
    players = dict(roster.players)
    changed = False
    for key, player in roster.players.items():
        team = _assigned_team(player, index)
        if team is None or team == player.team:
            continue
        players[key] = RosterPlayer(
            player_key=player.player_key,
            name=player.name,
            team=team,
        )
        changed = True
    if not changed:
        return roster
    return Roster(
        season=roster.season,
        retrieved=roster.retrieved,
        players=players,
        aliases=dict(roster.aliases),
    )


def active_teams_from_csv(path: Path | None) -> dict[str, str]:
    """Read ``player`` and ``team`` from a handoff or salary CSV.

    A missing file returns ``{}``. Accepted name columns are ``player``,
    ``player_name``, ``name``, and ``player_key``. Accepted club columns are
    ``team``, ``recent_team``, and ``club``.
    """

    if path is None:
        return {}
    resolved = Path(path)
    if not resolved.is_file():
        return {}
    out: dict[str, str] = {}
    with resolved.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            name = ""
            for key in ("player", "player_name", "name", "player_key"):
                text = str(raw.get(key) or "").strip()
                if text:
                    name = text
                    break
            team = ""
            for key in ("team", "recent_team", "club"):
                text = str(raw.get(key) or "").strip()
                if text:
                    team = text
                    break
            if name and team:
                out[name] = normalize_team(team)
    return out


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
