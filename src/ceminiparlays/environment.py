"""Operator-typed game environment (Vegas ITT, roof, weather).

Never scraped. A missing file is an empty map so ``--environment`` stays
optional and the composer still works on lines alone.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from ceminiparlays.roster import normalize_team

TRUTHY = {"1", "true", "yes", "y", "t", "exposed"}


def _optional_float(value: str | None) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in TRUTHY


@dataclass(frozen=True)
class EnvRow:
    game_id: str
    team: str
    opponent: str
    implied_total: float | None = None
    spread: float | None = None
    roof: str = ""
    weather_exposed: bool = False
    wind_mph: float | None = None
    precip_pop: float | None = None


#: Keyed by ``(team, opp)`` and by ``game_id`` (both the bare id and a
#: ``(game_id, "")`` tuple) so either lookup style works.
Environment = dict[tuple[str, str] | str, EnvRow]


def read_environment(path: Path | None) -> Environment:
    """Read ``environment.csv``. A missing / ``None`` path returns ``{}``."""

    if path is None:
        return {}
    resolved = Path(path)
    if not resolved.is_file():
        return {}
    out: Environment = {}
    with resolved.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            team = normalize_team(raw.get("team", ""))
            opponent = normalize_team(raw.get("opp", raw.get("opponent", "")))
            game_id = (raw.get("game_id") or "").strip()
            roof = (raw.get("roof") or "").strip().lower()
            row = EnvRow(
                game_id=game_id,
                team=team,
                opponent=opponent,
                implied_total=_optional_float(raw.get("implied_total")),
                spread=_optional_float(raw.get("spread")),
                roof=roof,
                weather_exposed=_truthy(raw.get("weather_exposed")),
                wind_mph=_optional_float(raw.get("wind_mph")),
                precip_pop=_optional_float(raw.get("precip_pop")),
            )
            if team and opponent:
                out[(team, opponent)] = row
            if game_id:
                # One game_id maps to two team rows; keep the first (away) so the
                # fallback key is stable. Per-team lookups stay authoritative.
                out.setdefault((game_id, ""), row)
                out.setdefault(game_id, row)
    return out


def env_for(
    environment: Environment | None,
    team: str,
    opponent: str = "",
    game_id: str = "",
) -> EnvRow | None:
    """Look up one team-game by ``(team, opp)`` first, then by ``game_id``."""

    if not environment:
        return None
    team_key = normalize_team(team)
    opp_key = normalize_team(opponent)
    for key in ((team_key, opp_key), (game_id, ""), game_id):
        if not key or not key[0]:
            continue
        row = environment.get(key)
        if row is not None:
            return row
    return None
