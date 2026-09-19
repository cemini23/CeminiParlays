"""Operator-typed game environment (Vegas ITT, roof, weather).

Never scraped. A missing file is an empty map so ``--environment`` stays
optional and the composer still works on lines alone.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
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


def missing_env_games(
    games: Sequence[object],
    environment: Environment,
) -> list[str]:
    """Return ``{away}@{home}`` ids missing either team's env row.

    An empty environment is not a warning: a missing file is skip, same as
    compose. Does not invent ITT.
    """

    if not environment:
        return []
    missing: list[str] = []
    for game in games:
        away = getattr(game, "away", "")
        home = getattr(game, "home", "")
        if (
            env_for(environment, away, home) is None
            or env_for(environment, home, away) is None
        ):
            missing.append(f"{away}@{home}")
    return missing


def env_rows_for_games(
    environment: Environment,
    games: set[tuple[str, ...]],
) -> list[EnvRow]:
    """Unique env rows whose ``(team, opp)`` game is in ``games``.

    ``games`` is a set of ``tuple(sorted({team, opp}))`` keys from composed
    tickets. Empty ``games`` returns ``[]``.
    """

    if not environment or not games:
        return []
    seen: set[tuple[str, str]] = set()
    rows: list[EnvRow] = []
    for row in environment.values():
        if not isinstance(row, EnvRow):
            continue
        key = (row.team, row.opponent)
        if not row.team or not row.opponent or key in seen:
            continue
        if tuple(sorted({row.team, row.opponent})) not in games:
            continue
        seen.add(key)
        rows.append(row)
    rows.sort(key=lambda item: (item.game_id, item.team, item.opponent))
    return rows


def write_compose_itt(
    path: Path,
    *,
    captured_at: str,
    source: str,
    rows: list[EnvRow],
) -> None:
    """Write the bet-time ITT snapshot. Never rewrite from box scores."""

    payload = {
        "captured_at": captured_at,
        "source": source,
        "rows": [
            {
                "team": row.team,
                "opp": row.opponent,
                "game_id": row.game_id,
                "implied_total": row.implied_total,
                "spread": row.spread,
                "roof": row.roof,
                "weather_exposed": row.weather_exposed,
                "wind_mph": row.wind_mph,
                "precip_pop": row.precip_pop,
            }
            for row in rows
        ],
    }
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
