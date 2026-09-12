from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from math import comb
from pathlib import Path

import numpy as np

from ceminiparlays.copula import exact_joint, nearest_correlation, simulate_slip
from ceminiparlays.correlation import LegRef, correlation_matrix, load_priors
from ceminiparlays.fair import FairResult, p_over_line, side_probability
from ceminiparlays.io import DistRow, LineRow, is_flagged, is_scratched
from ceminiparlays.kelly import slip_kelly
from ceminiparlays.odds import DevigMethod, devig_two_way
from ceminiparlays.payouts import flex_ev, power_ev, resolve_payout

MORE_SIDES = {"more", "over", "higher", "o"}
LESS_SIDES = {"less", "under", "lower", "u"}
STANDARD_LINE_TYPES = {"standard", ""}
#: Warn values that keep a leg out of every combo.
EXCLUDED_WARNS = {
    "dropped",
    "scratch",
    "one-sided-book",
    "integer-line",
    "no-team",
    "book-line-mismatch",
}
#: Scratch is expected (a listed player is out); every other exclusion is a
#: data problem and aborts the default strict rank.
NON_FATAL_EXCLUDES = {"scratch"}
COMBO_BUDGET = 20_000


@dataclass
class EvaluatedLeg:
    line: LineRow
    fair_p: float
    implied_p: float
    edge: float
    source: str
    family: str
    median: float
    warn: str
    p_over_at_median: float = 0.0


@dataclass
class EvaluatedSlip:
    legs: list[EvaluatedLeg]
    p_joint: float
    p_naive: float
    ev: float
    kelly: float
    mode: str
    multiplier: float
    platform: str
    p_all_se: float = 0.0
    p_lo: float = 0.0
    ev_lo: float = 0.0
    multiplier_source: str = "table"
    multiplier_unconfirmed: bool = False
    shade_pp: float = 0.0
    corr_repaired: bool = False
    corr_requested: np.ndarray | None = None
    corr_clean: np.ndarray | None = None
    notes: list[str] = field(default_factory=list)


def _excluded_leg(line: LineRow, implied_p: float, warn: str) -> EvaluatedLeg:
    return EvaluatedLeg(
        line=line,
        fair_p=0.0,
        implied_p=implied_p,
        edge=0.0,
        source="excluded",
        family="",
        median=0.0,
        warn=warn,
        p_over_at_median=0.0,
    )


def fair_for_line(
    line: LineRow,
    dist: DistRow | None,
    method: DevigMethod = "power",
) -> tuple[float, str, FairResult | None]:
    """Prefer operator-entered book odds; fall back to a projected distribution."""

    if line.book_over is not None and line.book_under is not None:
        result = devig_two_way(line.book_over, line.book_under, method=method)
        if line.side in MORE_SIDES:
            p = result.p_over
        elif line.side in LESS_SIDES:
            p = result.p_under
        else:
            raise ValueError(f"unknown side: {line.side}")
        return p, "book_devig", None
    if dist is None:
        raise KeyError(
            f"no distribution for {line.player_key}/{line.stat_type} and no book odds"
        )
    family = dist.family or None
    fair = p_over_line(
        line=line.line,
        median=dist.median,
        sigma=dist.sigma,
        family=family if family in {"lognormal", "normal", "poisson"} else None,
        stat_type=line.stat_type,
    )
    return side_probability(fair, line.side), "distribution", fair


def evaluate_legs(
    lines: list[LineRow],
    distributions: dict[tuple[str, str], DistRow],
    implied_p: float,
    method: DevigMethod = "power",
    allow_integer_lines: bool = False,
) -> tuple[list[EvaluatedLeg], list[EvaluatedLeg]]:
    """Split lines into rankable legs and named exclusions.

    Every path that skips a line appends to ``excluded`` with a warn token, so
    the operator can reconcile CSV in vs card out (I-03 / I-26).
    """

    live: list[EvaluatedLeg] = []
    excluded: list[EvaluatedLeg] = []
    for line in lines:
        dist = distributions.get((line.player_key, line.stat_type))
        if is_scratched(line.injury_status):
            excluded.append(_excluded_leg(line, implied_p, "scratch"))
            continue
        if not line.team or not line.opponent:
            excluded.append(_excluded_leg(line, implied_p, "no-team"))
            continue
        if line.book_line is not None and abs(line.book_line - line.line) > 1e-9:
            excluded.append(_excluded_leg(line, implied_p, "book-line-mismatch"))
            continue
        if (line.book_over is None) != (line.book_under is None):
            excluded.append(_excluded_leg(line, implied_p, "one-sided-book"))
            continue
        if line.book_over is None and dist is None:
            excluded.append(_excluded_leg(line, implied_p, "dropped"))
            continue
        if not allow_integer_lines and float(line.line).is_integer():
            excluded.append(_excluded_leg(line, implied_p, "integer-line"))
            continue
        try:
            fair_p, source, fair = fair_for_line(line, dist, method=method)
        except (KeyError, ValueError):
            excluded.append(_excluded_leg(line, implied_p, "dropped"))
            continue
        warn = "questionable" if is_flagged(line.injury_status) else ""
        family = fair.family if fair else "book"
        if fair is not None and fair.note:
            family = f"{family} ({fair.note})"
        live.append(
            EvaluatedLeg(
                line=line,
                fair_p=fair_p,
                implied_p=implied_p,
                edge=fair_p - implied_p,
                source=source,
                family=family,
                median=fair.median if fair else 0.0,
                warn=warn,
                p_over_at_median=fair.fair_p_at_median if fair else 0.0,
            )
        )
    return live, excluded


def _slip_label(legs: list[EvaluatedLeg]) -> str:
    return " + ".join(
        f"{leg.line.player_name} {leg.line.side} {leg.line.line} {leg.line.stat_type}"
        for leg in legs
    )


def _combo_names(legs: list[EvaluatedLeg] | tuple[EvaluatedLeg, ...]) -> str:
    return " + ".join(leg.line.player_name for leg in legs)


def rank_slips(
    legs: list[EvaluatedLeg],
    platform: str,
    mode: str,
    slip_size: int,
    n_sims: int = 20_000,
    seed: int = 42,
    displayed_multiplier: float | None = None,
    profile_dir: Path | None = None,
    priors_path: Path | None = None,
    max_slips: int = 25,
    allow_large_enum: bool = False,
    shade_pp: float = 0.0,
    notes: list[str] | None = None,
) -> list[EvaluatedSlip]:
    """Enumerate slip_size combinations and rank by a lower-bound EV.

    Multiplier precedence per combo: agreeing row ``slip_multiplier`` values win
    over the CLI flag; the CLI flag wins over the JSON table; a table-only price
    is marked unconfirmed (I-01 / I-07 / I-14 / I-19).
    """

    if notes is None:
        notes = []
    is_flex = mode.lower() in {"flex"}
    live = [leg for leg in legs if leg.warn not in EXCLUDED_WARNS]
    if len(live) < slip_size or slip_size < 1:
        return []
    total_combos = comb(len(live), slip_size)
    if total_combos > COMBO_BUDGET and not allow_large_enum:
        raise ValueError(
            f"{total_combos} combinations exceed the {COMBO_BUDGET} budget; "
            "raise --max-slips or pass --allow-large-enum"
        )
    priors = load_priors(priors_path)
    ranked: list[EvaluatedSlip] = []
    for combo in combinations(live, slip_size):
        refs = [
            LegRef(
                player_key=leg.line.player_key,
                team=leg.line.team,
                opponent=leg.line.opponent,
                stat_type=leg.line.stat_type,
                side=leg.line.side,
            )
            for leg in combo
        ]
        if any(not ref.team for ref in refs):
            notes.append(f"skip no-team: {_combo_names(combo)}")
            continue
        if len({ref.team for ref in refs}) < 2:
            notes.append(f"skip same-team (two-team rule): {_combo_names(combo)}")
            continue
        if len({ref.player_key for ref in refs}) < slip_size:
            notes.append(
                f"skip same-player multi-stat not supported: {_combo_names(combo)}"
            )
            continue

        row_ms = sorted(
            {
                leg.line.displayed_multiplier
                for leg in combo
                if leg.line.displayed_multiplier is not None
            }
        )
        if len(row_ms) > 1:
            notes.append(
                f"skip conflicting row slip_multiplier {row_ms}: {_combo_names(combo)}"
            )
            continue
        if row_ms:
            multiplier = row_ms[0]
            multiplier_source = "row"
            if (
                displayed_multiplier is not None
                and abs(multiplier - displayed_multiplier) > 1e-9
            ):
                notes.append(
                    f"row M {multiplier} overrides CLI M {displayed_multiplier}: "
                    f"{_combo_names(combo)}"
                )
        elif displayed_multiplier is not None:
            multiplier = displayed_multiplier
            multiplier_source = "cli"
        else:
            multiplier = None
            multiplier_source = "table"
        if multiplier_source == "table" and any(
            leg.line.line_type not in STANDARD_LINE_TYPES for leg in combo
        ):
            notes.append(f"skip alt-needs-m: {_combo_names(combo)}")
            continue

        table = resolve_payout(
            platform,
            mode,
            slip_size,
            displayed_multiplier=multiplier,
            profile_dir=profile_dir,
        )
        price = table.all_hit
        unconfirmed = multiplier_source == "table"

        requested = correlation_matrix(refs, priors, repair=False)
        clean = nearest_correlation(requested)
        max_corr_delta = float(np.max(np.abs(clean - requested)))
        repaired = max_corr_delta > 0.02

        marginals = [
            min(max(leg.fair_p - shade_pp, 1e-9), 1.0 - 1e-9) for leg in combo
        ]
        if is_flex or slip_size > 3:
            sim = simulate_slip(marginals, clean, n_sims=n_sims, seed=seed)
            p_all = float(sim["p_all"])
            p_all_se = float(sim["p_all_se"])
            p_naive = float(sim["p_naive"])
            p_minus_1 = float(sim["p_minus_1"])
            p_minus_2 = float(sim["p_minus_2"])
        else:
            # Power 2-3 legs: deterministic exact Gaussian joint, no MC noise.
            p_all = exact_joint(marginals, clean)
            p_all_se = 0.0
            p_naive = float(np.prod(marginals))
            p_minus_1 = 0.0
            p_minus_2 = 0.0
        p_lo = max(p_all - p_all_se, 0.0)

        slip_notes: list[str] = []
        if is_flex:
            ev = flex_ev(p_all, p_minus_1, p_minus_2, table)
            kelly = 0.0
            slip_notes.append("quarter_kelly=na (flex proxy suppressed)")
            ev_lo = ev
        else:
            ev = power_ev(p_all, price)
            kelly = slip_kelly(p_all, price)
            ev_lo = p_lo * price - 1.0
        if table.note:
            slip_notes.append(table.note)
        if repaired:
            slip_notes.append(f"corr_repaired=yes max_delta={max_corr_delta:.4f}")
        if unconfirmed:
            slip_notes.append("multiplier_unconfirmed=yes (table)")
        if shade_pp:
            slip_notes.append(f"shade_pp={shade_pp:g}")

        ranked.append(
            EvaluatedSlip(
                legs=list(combo),
                p_joint=p_all,
                p_naive=p_naive,
                ev=float(ev),
                kelly=kelly,
                mode=mode,
                multiplier=price,
                platform=platform,
                p_all_se=p_all_se,
                p_lo=p_lo,
                ev_lo=float(ev_lo),
                multiplier_source=multiplier_source,
                multiplier_unconfirmed=unconfirmed,
                shade_pp=shade_pp,
                corr_repaired=repaired,
                corr_requested=requested,
                corr_clean=clean,
                notes=slip_notes,
            )
        )
    ranked.sort(key=lambda item: (item.ev_lo, item.ev), reverse=True)
    return ranked[:max_slips]


def slip_as_row(slip: EvaluatedSlip, index: int) -> dict[str, object]:
    first = slip.legs[0].line
    is_flex = slip.mode.lower() in {"flex"}
    return {
        "slate_id": first.slate_id,
        "platform": slip.platform,
        "slip_id": f"slip-{index:03d}",
        "mode": slip.mode,
        "legs": _slip_label(slip.legs),
        "player_keys": "|".join(leg.line.player_key for leg in slip.legs),
        "stat_types": "|".join(leg.line.stat_type for leg in slip.legs),
        "sides": "|".join(leg.line.side for leg in slip.legs),
        "lines": "|".join(str(leg.line.line) for leg in slip.legs),
        "fair_ps": "|".join(f"{leg.fair_p:.4f}" for leg in slip.legs),
        "p_over_at_median": "|".join(
            f"{leg.p_over_at_median:.4f}" for leg in slip.legs
        ),
        "p_joint": f"{slip.p_joint:.4f}",
        "p_joint_se": f"{slip.p_all_se:.4f}",
        "p_naive": f"{slip.p_naive:.4f}",
        "implied_p": f"{1.0 / slip.multiplier:.4f}" if not is_flex else "",
        "edge": (
            f"{slip.p_joint - (1.0 / slip.multiplier):.4f}"
            if not is_flex
            else f"{slip.ev:.4f}"
        ),
        "multiplier": slip.multiplier,
        "multiplier_source": slip.multiplier_source,
        "multiplier_unconfirmed": "yes" if slip.multiplier_unconfirmed else "no",
        "slip_ev": f"{slip.ev:.4f}",
        "ev_lo": f"{slip.ev_lo:.4f}",
        "kelly_quarter": f"{slip.kelly:.4f}" if not is_flex else "",
        "shade_pp": slip.shade_pp,
        "notes": "; ".join(slip.notes),
        "do_not_submit": "yes",
        "captured_at": first.captured_at,
    }


EDGE_FIELDS = [
    "slate_id",
    "platform",
    "slip_id",
    "mode",
    "legs",
    "player_keys",
    "stat_types",
    "sides",
    "lines",
    "fair_ps",
    "p_over_at_median",
    "p_joint",
    "p_joint_se",
    "p_naive",
    "implied_p",
    "edge",
    "multiplier",
    "multiplier_source",
    "multiplier_unconfirmed",
    "slip_ev",
    "ev_lo",
    "kelly_quarter",
    "shade_pp",
    "notes",
    "do_not_submit",
    "captured_at",
]
