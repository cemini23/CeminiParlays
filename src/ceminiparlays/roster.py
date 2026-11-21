from __future__ import annotations

import csv
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ceminiparlays.io import LineRow
from ceminiparlays.names import alias_fold_keys, fold_name
from ceminiparlays.resources import REPO_CONFIG, REPO_ROOT, read_config_text

CONFIG_ROSTER_PATH = REPO_CONFIG / "rosters" / "nfl.json"
PACKAGE_ROSTER_PATH = REPO_ROOT / "src" / "ceminiparlays" / "data" / "rosters" / "nfl.json"
_ROSTER_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

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


def _roster_player_index(players: Mapping[str, object]) -> dict[str, str]:
    """Map a folded name and a player key onto the JSON player key."""

    index: dict[str, str] = {}
    for key, entry in players.items():
        if not isinstance(entry, Mapping):
            continue
        for token in (str(key), fold_name(str(key))):
            if token:
                index.setdefault(token.lower(), str(key))
        name = str(entry.get("name") or "")
        for token in (name.lower(), fold_name(name)):
            if token:
                index.setdefault(token, str(key))
    return index


def _date_in_name(path: Path) -> str | None:
    found = _ROSTER_DATE.findall(path.name)
    return found[-1] if found else None


def apply_whitelist_payload(
    payload: Mapping[str, object],
    assignments: Mapping[str, str],
    *,
    retrieved: str | None = None,
) -> tuple[dict, list[str]]:
    """Return an updated roster payload and the team-change lines.

    A known player moves to the whitelist club. A new name is added. The
    input payload is not mutated.
    """

    updated = deepcopy(dict(payload))
    players = updated.get("players")
    if not isinstance(players, dict):
        players = {}
        updated["players"] = players
    index = _roster_player_index(players)
    diff: list[str] = []
    for raw_name, raw_team in assignments.items():
        name = str(raw_name or "").strip()
        team = normalize_team(str(raw_team))
        if not name or not team:
            continue
        match = index.get(name.lower()) or index.get(fold_name(name))
        if match is None:
            key = fold_name(name) or name.lower().replace(" ", "_")
            players[key] = {"name": name, "team": team}
            index[key.lower()] = key
            index[fold_name(name)] = key
            index[name.lower()] = key
            diff.append(f"{key} {name} (new) -> {team}")
            continue
        entry = players.get(match)
        if not isinstance(entry, dict):
            continue
        current = normalize_team(str(entry.get("team") or ""))
        if current == team:
            continue
        shown = str(entry.get("name") or name)
        entry["team"] = team
        diff.append(f"{match} {shown} {current} -> {team}")
    if retrieved:
        updated["retrieved"] = retrieved
    return updated, diff


def refresh_roster_files(
    whitelist: Path,
    targets: list[Path],
) -> list[str]:
    """Write the whitelist clubs into each roster JSON. Return the diff lines.

    The first existing target is the source. Every target receives the same
    text, so ``config/rosters/nfl.json`` and the package copy stay aligned.
    """

    if not targets:
        raise ValueError("refresh-roster needs a roster JSON path")
    source = next((path for path in targets if Path(path).is_file()), None)
    if source is None:
        raise FileNotFoundError(f"roster JSON missing: {targets[0]}")
    payload = json.loads(Path(source).read_text(encoding="utf-8"))
    assignments = active_teams_from_csv(whitelist)
    if not assignments:
        raise ValueError(f"roster whitelist has no player,team rows: {whitelist}")
    updated, diff = apply_whitelist_payload(
        payload,
        assignments,
        retrieved=_date_in_name(Path(whitelist)),
    )
    text = json.dumps(updated, indent=2) + "\n"
    for path in targets:
        resolved = Path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(text, encoding="utf-8")
    return diff


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
