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


def _pair_rho(a: LegRef, b: LegRef, priors: dict) -> float:
    if a.player_key == b.player_key and a.stat_type == b.stat_type:
        if _side_sign(a.side) == _side_sign(b.side):
            return 1.0
        return -1.0
    same_team = _same_team(a, b)
    opp = _opponents(a, b)
    raw = 0.0
    if not same_team and not opp:
        raw = float(priors.get("default_cross_game", 0.0))
    else:
        # Exact unordered pair, not set membership. ``{pass_yds, rec_yds}``
        # must not match a ``rec_yds``/``rec_yds`` request (I-02).
        want = tuple(sorted((a.stat_type, b.stat_type)))
        for row in priors.get("pairs", []):
            have = tuple(
                sorted((str(row.get("stat_a") or ""), str(row.get("stat_b") or "")))
            )
            if want != have:
                continue
            if row.get("same_team") and same_team:
                raw = float(row["rho"])
                break
            if row.get("opponents") and opp:
                raw = float(row["rho"])
                break
        else:
            if same_team:
                raw = 0.08
            elif opp:
                raw = 0.05
    return raw * _side_sign(a.side) * _side_sign(b.side)


def correlation_matrix(
    legs: list[LegRef],
    priors: dict | None = None,
    repair: bool = True,
) -> np.ndarray:
    """Correlation matrix for the legs.

    ``repair=False`` returns the raw prior matrix, which lets callers diff it
    against the PSD-repaired matrix and report ``corr_repaired`` (I-23).
    """

    loaded = priors if priors is not None else load_priors()
    n = len(legs)
    matrix = np.eye(n, dtype=float)
    for i in range(n):
        for j in range(i + 1, n):
            rho = _pair_rho(legs[i], legs[j], loaded)
            matrix[i, j] = rho
            matrix[j, i] = rho
    if not repair:
        return matrix
    return nearest_correlation(matrix)
