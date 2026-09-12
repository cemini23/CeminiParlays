from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from ceminiparlays.correlation import LegRef, correlation_matrix, load_priors
from ceminiparlays.copula import simulate_slip
from ceminiparlays.fair import FairResult, p_over_line, side_probability
from ceminiparlays.io import DistRow, LineRow, is_scratched
from ceminiparlays.kelly import slip_kelly
from ceminiparlays.odds import DevigMethod, devig_two_way
from ceminiparlays.payouts import flex_ev, power_ev, resolve_payout


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


def fair_for_line(
    line: LineRow,
    dist: DistRow | None,
    method: DevigMethod = "power",
) -> tuple[float, str, FairResult | None]:
    """Prefer operator-entered book odds; fall back to a projected distribution."""

    if line.book_over is not None and line.book_under is not None:
        result = devig_two_way(line.book_over, line.book_under, method=method)
        if line.side in {"more", "over", "higher", "o"}:
            p = result.p_over
        elif line.side in {"less", "under", "lower", "u"}:
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
) -> list[EvaluatedLeg]:
    evaluated: list[EvaluatedLeg] = []
    for line in lines:
        warn = ""
        if is_scratched(line.injury_status):
            warn = "scratch"
        dist = distributions.get((line.player_key, line.stat_type))
        try:
            fair_p, source, fair = fair_for_line(line, dist, method=method)
        except (KeyError, ValueError):
            warn = warn or "dropped"
            continue
        evaluated.append(
            EvaluatedLeg(
                line=line,
                fair_p=fair_p,
                implied_p=implied_p,
                edge=fair_p - implied_p,
                source=source,
                family=fair.family if fair else "book",
                median=fair.median if fair else 0.0,
                warn=warn,
            )
        )
    return evaluated


def _slip_label(legs: list[EvaluatedLeg]) -> str:
    return " + ".join(
        f"{leg.line.player_name} {leg.line.side} {leg.line.line} {leg.line.stat_type}"
        for leg in legs
    )


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
) -> list[EvaluatedSlip]:
    """Enumerate slip_size combinations and rank by correlation-aware EV."""

    live = [leg for leg in legs if leg.warn != "scratch"]
    if len(live) < slip_size:
        return []
    table = resolve_payout(
        platform,
        mode,
        slip_size,
        displayed_multiplier=displayed_multiplier,
        profile_dir=profile_dir,
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
        teams = {ref.team or f"unknown:{ref.player_key}" for ref in refs}
        if len({ref.team for ref in refs if ref.team}) == 1 and all(ref.team for ref in refs):
            continue
        if len(teams) < 2:
            continue
        keys = [(ref.player_key, ref.stat_type) for ref in refs]
        if len(set(keys)) != len(keys):
            continue
        corr = correlation_matrix(refs, priors)
        sim = simulate_slip(
            [leg.fair_p for leg in combo],
            corr,
            n_sims=n_sims,
            seed=seed,
        )
        if mode.lower() in {"flex"}:
            ev = flex_ev(sim["p_all"], sim["p_minus_1"], sim["p_minus_2"], table)
            kelly = max(0.0, float(ev)) / max(table.all_hit - 1.0, 1e-9) * 0.25
            kelly = min(kelly, 0.05)
        else:
            ev = power_ev(sim["p_all"], table.all_hit)
            kelly = slip_kelly(sim["p_all"], table.all_hit)
        ranked.append(
            EvaluatedSlip(
                legs=list(combo),
                p_joint=float(sim["p_all"]),
                p_naive=float(sim["p_naive"]),
                ev=float(ev),
                kelly=kelly,
                mode=mode,
                multiplier=table.all_hit,
                platform=platform,
            )
        )
    ranked.sort(key=lambda item: item.ev, reverse=True)
    return ranked[:max_slips]


def slip_as_row(slip: EvaluatedSlip, index: int) -> dict[str, object]:
    first = slip.legs[0].line
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
        "p_joint": f"{slip.p_joint:.4f}",
        "p_naive": f"{slip.p_naive:.4f}",
        "implied_p": f"{1.0 / slip.multiplier:.4f}" if slip.mode.lower() not in {"flex"} else "",
        "edge": (
            f"{slip.p_joint - (1.0 / slip.multiplier):.4f}"
            if slip.mode.lower() not in {"flex"}
            else f"{slip.ev:.4f}"
        ),
        "multiplier": slip.multiplier,
        "slip_ev": f"{slip.ev:.4f}",
        "kelly_quarter": f"{slip.kelly:.4f}",
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
    "p_joint",
    "p_naive",
    "implied_p",
    "edge",
    "multiplier",
    "slip_ev",
    "kelly_quarter",
    "do_not_submit",
    "captured_at",
]
