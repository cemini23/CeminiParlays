"""Game-specific correlation perturbations (Delta_rho) from Jev regime scores.

The static prior table cannot know that a tackle is out, that the trench is
lopsided, or that the wind is 22 mph. This module asks Jev four typed score
questions per game, maps each answer to a bounded correlation perturbation,
and hands the perturbed matrix to the existing PSD projector. ``numpy`` and
``scipy`` still own the projection and the copula draws; Jev only routes.

The perturbation is deliberately small and symmetric: at most 0.075 * 2 = 0.15
per regime before the clip. A regime answer can never move a base correlation
past +/-0.85, and a missing game score leaves the base prior untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from ceminiparlays.copula import nearest_correlation
from ceminiparlays.correlation import (
    LegRef,
    _opponents,
    _pair_rho,
    _same_team,
    _side_sign,
    load_priors,
)

Relation = Literal["same_team", "opponents"]

#: Scale handed to every regime question. The project's own score scale.
REGIME_SCALE: tuple[int, ...] = (-2, -1, 0, 1, 2)

#: ``delta_rho = clip(WEIGHT * expected_score * confidence, -DELTA_CLIP, +DELTA_CLIP)``.
WEIGHT = 0.075
DELTA_CLIP = 0.15
RHO_CLIP = 0.85


@dataclass(frozen=True)
class Regime:
    """One game-level question and the leg pairs its answer perturbs.

    ``pairs`` names ``(stat_a, stat_b, relation)`` using the project's stat
    vocabulary (``pass_yds``, ``rec_yds``, ``rush_yds``, ``receptions``,
    ``rush_att``, ``pass_tds``, ``anytime_td``). A regime with no matching leg
    pair changes nothing.
    """

    key: str
    question: str
    pairs: tuple[tuple[str, str, Relation], ...]


#: The four regimes, in the order the spec names them. Each maps a football
#: mechanism onto the stat pairs that co-move when the mechanism fires.
REGIMES: tuple[Regime, ...] = (
    Regime(
        key="pressure_checkdown_funnel",
        question=(
            "Does an offensive-line injury or an opposing pass-rush mismatch force "
            "the quarterback into quick checkdowns and dump-offs this game?"
        ),
        pairs=(
            ("pass_att", "receptions", "same_team"),
            ("pass_yds", "rec_yds", "same_team"),
        ),
    ),
    Regime(
        key="script_abandon_run_early",
        question=(
            "Do the spread, the pace, and the opposing defense push this team's "
            "pass rate over expected into a shootout script?"
        ),
        pairs=(
            ("pass_yds", "rec_yds", "opponents"),
            ("rush_att", "pass_att", "same_team"),
        ),
    ),
    Regime(
        key="red_zone_goal_line_vulture_shift",
        question=(
            "Does a mobile quarterback or a goal-line role shift touchdown equity "
            "away from passing touchdowns and toward rushing scores?"
        ),
        pairs=(("pass_tds", "anytime_td", "same_team"),),
    ),
    Regime(
        key="weather_ground_compression",
        question=(
            "Do wind at or above 15 mph or precipitation compress the passing game "
            "into rushing volume for both teams?"
        ),
        pairs=(
            ("rush_yds", "rush_yds", "opponents"),
            ("pass_yds", "rec_yds", "same_team"),
        ),
    ),
)

REGIME_KEYS: tuple[str, ...] = tuple(regime.key for regime in REGIMES)


@dataclass(frozen=True)
class PairPerturbation:
    """One leg pair's base, perturbed, and final correlation."""

    i: int
    j: int
    rho_base: float
    delta_rho: float
    rho_adj: float
    regimes: tuple[str, ...]


@dataclass(frozen=True)
class Perturbation:
    matrix: np.ndarray
    records: list[PairPerturbation]
    repaired: bool


def game_state(row: Any, notes: list[str] | None = None) -> dict:
    """Assemble the structured state Jev reads for one game.

    ``row`` is an ``environment.EnvRow``. Only the named fields are read, so a
    different row type with the same attributes works too.
    """

    return {
        "implied_total": getattr(row, "implied_total", None),
        "spread": getattr(row, "spread", None),
        "roof": getattr(row, "roof", "") or "",
        "weather_exposed": bool(getattr(row, "weather_exposed", False)),
        "wind_mph": getattr(row, "wind_mph", None),
        "precip_pop": getattr(row, "precip_pop", None),
        "notes": list(notes or []),
    }


def regime_questions() -> list[tuple[str, list[int]]]:
    return [(regime.question, list(REGIME_SCALE)) for regime in REGIMES]


def score_game(client: Any, state: dict) -> dict[str, Any]:
    """Score all four regimes for one game in a single bundled System One call."""

    results = client.score_bundle(state, regime_questions())
    return {regime.key: result for regime, result in zip(REGIMES, results)}


def bounded_delta(expected_score: float, confidence: float) -> float:
    """Map one regime answer onto a bounded correlation perturbation."""

    scaled = WEIGHT * float(expected_score) * float(confidence)
    return float(np.clip(scaled, -DELTA_CLIP, DELTA_CLIP))


def _relation(a: LegRef, b: LegRef) -> Relation | None:
    if _same_team(a, b):
        return "same_team"
    if _opponents(a, b):
        return "opponents"
    return None


def game_key_for(team: str, opponent: str) -> str:
    """Canonical game key, so away/home order never splits one game in two."""

    return "@".join(sorted({str(team).strip().upper(), str(opponent).strip().upper()}))


def _game_key(a: LegRef, b: LegRef, relation: Relation) -> str:
    if relation == "same_team":
        return game_key_for(a.team, a.opponent)
    return game_key_for(a.team, b.team)


def pair_delta(
    a: LegRef,
    b: LegRef,
    game_scores: dict[str, Any],
) -> tuple[float, tuple[str, ...]]:
    """Sum the bounded deltas of every regime that names this pair.

    ``game_scores`` is one game's ``{regime_key: score_result}``. An unknown or
    missing regime key contributes nothing, which keeps a partial Jev answer
    safe rather than fatal.

    The total carries the legs' side sign, exactly as the base prior does, so a
    regime shift means the same thing on an Over and on an Under.
    """

    relation = _relation(a, b)
    if relation is None:
        return 0.0, ()
    want = tuple(sorted((a.stat_type, b.stat_type)))
    total = 0.0
    fired: list[str] = []
    for regime in REGIMES:
        for stat_a, stat_b, pair_relation in regime.pairs:
            if pair_relation != relation:
                continue
            if tuple(sorted((stat_a, stat_b))) != want:
                continue
            result = game_scores.get(regime.key)
            if result is None:
                continue
            total += bounded_delta(result.expected_score, result.confidence)
            fired.append(regime.key)
            break
    sign = _side_sign(a.side) * _side_sign(b.side)
    return float(np.clip(total * sign, -DELTA_CLIP, DELTA_CLIP)), tuple(fired)


def perturb_matrix(
    base: np.ndarray,
    legs: list[LegRef],
    scores_by_game: dict[str, dict[str, Any]],
) -> tuple[np.ndarray, list[PairPerturbation]]:
    """Add every regime delta to an already-built base matrix.

    ``base`` is the raw prior matrix, so the caller keeps control of when the
    PSD projection runs. Returns the perturbed matrix and one auditable record
    per leg pair.
    """

    n = len(legs)
    out = np.array(base, dtype=float, copy=True)
    records: list[PairPerturbation] = []
    for i in range(n):
        for j in range(i + 1, n):
            base_rho = float(out[i, j])
            relation = _relation(legs[i], legs[j])
            delta = 0.0
            fired: tuple[str, ...] = ()
            if relation is not None:
                scores = scores_by_game.get(_game_key(legs[i], legs[j], relation), {})
                if scores:
                    delta, fired = pair_delta(legs[i], legs[j], scores)
            rho_adj = float(np.clip(base_rho + delta, -RHO_CLIP, RHO_CLIP))
            out[i, j] = out[j, i] = rho_adj
            records.append(
                PairPerturbation(
                    i=i,
                    j=j,
                    rho_base=base_rho,
                    delta_rho=delta,
                    rho_adj=rho_adj,
                    regimes=fired,
                )
            )
    return out, records


def adjusted_correlation(
    legs: list[LegRef],
    scores_by_game: dict[str, dict[str, Any]],
    priors: dict | None = None,
    *,
    allow_unmodeled: bool = False,
) -> Perturbation:
    """Base prior matrix plus Delta_rho, projected onto the nearest correlation.

    ``scores_by_game`` maps ``"AWAY@HOME"`` to one game's regime scores. A pair
    whose game is absent keeps its base correlation, so the caller can run a
    slate where only some games have an environment row.
    """

    loaded = priors if priors is not None else load_priors()
    n = len(legs)
    base = np.eye(n, dtype=float)
    for i in range(n):
        for j in range(i + 1, n):
            rho = _pair_rho(legs[i], legs[j], loaded, allow_unmodeled=allow_unmodeled)
            base[i, j] = base[j, i] = rho
    raw, records = perturb_matrix(base, legs, scores_by_game)
    repaired = nearest_correlation(raw)
    return Perturbation(
        matrix=repaired,
        records=records,
        repaired=not bool(np.allclose(repaired, raw)),
    )


def min_eigenvalue(matrix: np.ndarray) -> float:
    """Smallest eigenvalue of the symmetric part. The PSD guard reads this."""

    symmetric = (np.asarray(matrix, dtype=float) + np.asarray(matrix, dtype=float).T) / 2.0
    return float(np.min(np.linalg.eigvalsh(symmetric)))
