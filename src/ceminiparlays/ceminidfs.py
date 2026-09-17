"""Read-only CeminiDFS handoff CSV (operator-copied file; no live pipe).

FanDuel FPPG ``projection`` is never a prop fair / yard median. This module
does not call ``read_distributions`` and does not write ``distributions.csv``.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from pathlib import Path

from ceminiparlays.environment import EnvRow, Environment, _optional_float
from ceminiparlays.roster import normalize_team


@dataclass(frozen=True)
class HandoffRow:
    player: str
    team: str
    projection: float | None = None
    lineup_exposure_pct: float | None = None
    game: str = ""
    implied_total: float | None = None


@dataclass(frozen=True)
class Handoff:
    missing: bool
    note: str
    rows: list[HandoffRow]


def load_ceminidfs_handoff(path: Path | str) -> Handoff:
    """Load a local handoff CSV. A missing path is a named skip, not a crash."""

    resolved = Path(path)
    if not resolved.is_file():
        return Handoff(
            missing=True,
            note=f"CEMINIDFS_HANDOFF_MISSING: {path}",
            rows=[],
        )
    rows: list[HandoffRow] = []
    with resolved.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            player = (raw.get("player") or "").strip()
            team = (raw.get("team") or "").strip()
            if not player and not team:
                continue
            rows.append(
                HandoffRow(
                    player=player,
                    team=team,
                    projection=_optional_float(raw.get("projection")),
                    lineup_exposure_pct=_optional_float(raw.get("lineup_exposure_pct")),
                    game=(raw.get("game") or "").strip(),
                    implied_total=_optional_float(raw.get("implied_total")),
                )
            )
    return Handoff(missing=False, note="", rows=rows)


def _game_teams(game: str) -> tuple[str, str] | None:
    parts = [normalize_team(part) for part in game.split("@")]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def _replace_env_row(environment: Environment, old: EnvRow, new: EnvRow) -> None:
    for key, value in list(environment.items()):
        if value is old:
            environment[key] = new


def _put_new_env_row(environment: Environment, row: EnvRow) -> None:
    environment[(row.team, row.opponent)] = row
    if row.game_id:
        environment.setdefault(row.game_id, row)
        environment.setdefault((row.game_id, ""), row)


def merge_implied_totals(environment: Environment, rows: list[HandoffRow]) -> Environment:
    """Fill blank team ITT from handoff rows. Never overwrite roof or weather."""

    out: Environment = dict(environment)
    for row in rows:
        team = normalize_team(row.team)
        teams = _game_teams(row.game)
        if not team or teams is None or row.implied_total is None:
            continue
        away, home = teams
        if team == away:
            opp = home
        elif team == home:
            opp = away
        else:
            continue
        game_id = f"{away}@{home}"
        existing = out.get((team, opp))
        if existing is not None:
            if existing.implied_total is not None:
                continue
            filled = replace(existing, implied_total=row.implied_total)
            _replace_env_row(out, existing, filled)
            continue
        created = EnvRow(
            game_id=game_id,
            team=team,
            opponent=opp,
            implied_total=row.implied_total,
            roof="",
            weather_exposed=False,
        )
        _put_new_env_row(out, created)
    return out


def exposure_notes(rows: list[HandoffRow]) -> list[str]:
    """One research note per player with a numeric lineup exposure."""

    notes: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if row.lineup_exposure_pct is None or not row.player:
            continue
        if row.player in seen:
            continue
        seen.add(row.player)
        notes.append(
            f"ceminidfs exposure: {row.player} lineup_exposure_pct={row.lineup_exposure_pct:g}"
        )
    return notes
