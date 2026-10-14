from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ceminiparlays.copula import nearest_correlation
from ceminiparlays.resources import REPO_ROOT, read_config_text

DEFAULT_PRIORS = REPO_ROOT / "config" / "correlation_priors.json"


@dataclass(frozen=True)
class LegRef:
    player_key: str
    team: str
    opponent: str
    stat_type: str
    side: str


def load_priors(path: Path | None = None) -> dict:
    if path is not None:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return json.loads(read_config_text("correlation_priors.json"))


def _same_team(a: LegRef, b: LegRef) -> bool:
    return bool(a.team and a.team == b.team)


def _opponents(a: LegRef, b: LegRef) -> bool:
    if not a.team or not b.team:
        return False
    return a.opponent == b.team or b.opponent == a.team


def _side_sign(side: str) -> int:
    token = side.strip().lower()
    if token in {"more", "over", "higher", "o"}:
        return 1
    if token in {"less", "under", "lower", "u"}:
        return -1
    raise ValueError(f"unknown side: {side}")


class UnmodeledCorrelationError(ValueError):
    """A same-game pair has no explicit prior. Never guess a correlation."""


def _lookup_rho(rows: list[dict], want: tuple[str, str], *, team: bool = False, opp: bool = False):
    """Return the rho of the exact unordered pair, or ``None``.

    Exact unordered pair, not set membership: ``{pass_yds, rec_yds}`` must not
    match a ``rec_yds``/``rec_yds`` request (I-02). With neither ``team`` nor
    ``opp`` the row is matched on the stat pair alone (the ``same_player`` table
    carries no team flag).
    """

    for row in rows:
        have = tuple(sorted((str(row.get("stat_a") or ""), str(row.get("stat_b") or ""))))
        if have != want:
            continue
        if not team and not opp:
            return float(row["rho"])
        if team and row.get("same_team"):
            return float(row["rho"])
        if opp and row.get("opponents"):
            return float(row["rho"])
    return None


def _pair_rho(a: LegRef, b: LegRef, priors: dict, allow_unmodeled: bool = False) -> float:
    if a.player_key == b.player_key and a.stat_type == b.stat_type:
        if _side_sign(a.side) == _side_sign(b.side):
            return 1.0
        return -1.0
    same_team = _same_team(a, b)
    opp = _opponents(a, b)
    if not same_team and not opp:
        raw = float(priors.get("default_cross_game", 0.0))
        return raw * _side_sign(a.side) * _side_sign(b.side)

    want = tuple(sorted((a.stat_type, b.stat_type)))
    same_player = bool(a.player_key and a.player_key == b.player_key)
    raw = None
    if same_player:
        raw = _lookup_rho(priors.get("same_player", []), want)
    if raw is None:
        raw = _lookup_rho(priors.get("pairs", []), want, team=same_team, opp=opp)
    if raw is None:
        if allow_unmodeled:
            raw = 0.08 if same_team else 0.05
        else:
            # A same-game pair with no explicit prior would otherwise be priced
            # from a made-up default and misprice the ticket (A-03). Refuse it.
            raise UnmodeledCorrelationError(
                f"no correlation prior for {a.stat_type}/{b.stat_type} "
                f"({'same_team' if same_team else 'opponents'})"
            )
    return raw * _side_sign(a.side) * _side_sign(b.side)


def correlation_matrix(
    legs: list[LegRef],
    priors: dict | None = None,
    repair: bool = True,
    allow_unmodeled: bool = False,
) -> np.ndarray:
    """Correlation matrix for the legs.

    ``repair=False`` returns the raw prior matrix, which lets callers diff it
    against the PSD-repaired matrix and report ``corr_repaired`` (I-23).
    ``allow_unmodeled`` restores the old guessed fallback for a same-game pair
    with no prior; the default is to refuse it.
    """

    loaded = priors if priors is not None else load_priors()
    n = len(legs)
    matrix = np.eye(n, dtype=float)
    for i in range(n):
        for j in range(i + 1, n):
            rho = _pair_rho(legs[i], legs[j], loaded, allow_unmodeled=allow_unmodeled)
            matrix[i, j] = rho
            matrix[j, i] = rho
    if not repair:
        return matrix
    return nearest_correlation(matrix)
