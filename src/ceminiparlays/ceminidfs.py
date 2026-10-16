"""Read-only CeminiDFS handoff CSV (operator-copied file; no live pipe).

FanDuel FPPG ``projection`` is never a prop fair / yard median. This module
does not call ``read_distributions`` and does not write ``distributions.csv``.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from pathlib import Path

from ceminiparlays.environment import EnvRow, Environment, _optional_float
from ceminiparlays.names import fold_name
from ceminiparlays.roster import normalize_team


#: Stat prefixes carrying a disaggregated distribution in the handoff CSV.
#: Each expands to ``<prefix>_median``, ``<prefix>_sigma``, ``<prefix>_p15``,
#: and ``<prefix>_p85``.
DISTRIBUTION_PREFIXES = ("pass_yds", "rush_yds", "rec_yds", "receptions")


@dataclass(frozen=True)
class StatDistribution:
    """One stat's projected distribution from the disaggregated handoff columns.

    ``p15`` and ``p85`` carry the asymmetry the median and sigma alone cannot:
    an injury-limited or committee backfield is skewed, and a symmetric normal
    would price the tail wrong. Either quantile may be absent; the split-normal
    then falls back on sigma.
    """

    stat_type: str
    median: float | None = None
    sigma: float | None = None
    p15: float | None = None
    p85: float | None = None

    @property
    def has_quantiles(self) -> bool:
        return self.p15 is not None and self.p85 is not None


@dataclass(frozen=True)
class HandoffRow:
    player: str
    team: str
    projection: float | None = None
    lineup_exposure_pct: float | None = None
    game: str = ""
    implied_total: float | None = None
    distributions: tuple[StatDistribution, ...] = ()

    def distribution_for(self, stat_type: str) -> StatDistribution | None:
        wanted = (stat_type or "").strip().lower()
        for dist in self.distributions:
            if dist.stat_type == wanted:
                return dist
        return None


def _distributions_from(raw: dict) -> tuple[StatDistribution, ...]:
    out: list[StatDistribution] = []
    for prefix in DISTRIBUTION_PREFIXES:
        median = _optional_float(raw.get(f"{prefix}_median"))
        sigma = _optional_float(raw.get(f"{prefix}_sigma"))
        p15 = _optional_float(raw.get(f"{prefix}_p15"))
        p85 = _optional_float(raw.get(f"{prefix}_p85"))
        if median is None and sigma is None and p15 is None and p85 is None:
            continue
        out.append(
            StatDistribution(stat_type=prefix, median=median, sigma=sigma, p15=p15, p85=p85)
        )
    return tuple(out)


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
                    distributions=_distributions_from(raw),
                )
            )
    return Handoff(missing=False, note="", rows=rows)


def distribution_index(handoff: "Handoff | None") -> dict[tuple[str, str], StatDistribution]:
    """Map ``(folded player name, stat_type)`` to one distribution.

    A ledger and a lines file name a player by ``player_key``; the handoff names
    them in display form. Both sides fold through ``fold_name`` to join.
    ``None`` and a missing file both give an empty index.
    """

    if handoff is None or handoff.missing:
        return {}
    index: dict[tuple[str, str], StatDistribution] = {}
    for row in handoff.rows:
        key = fold_name(row.player)
        if not key:
            continue
        for dist in row.distributions:
            index.setdefault((key, dist.stat_type), dist)
    return index


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
