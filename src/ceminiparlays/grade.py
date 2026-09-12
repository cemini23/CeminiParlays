from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ceminiparlays.payouts import resolve_payout

MORE_SIDES = {"more", "over", "higher", "o"}
LESS_SIDES = {"less", "under", "lower", "u"}


@dataclass
class GradeSummary:
    n_slips: int
    hits: int
    hit_rate: float
    stake: float
    pnl: float
    roi: float


def _leg_outcomes(raw: dict[str, str]) -> tuple[int, int, int]:
    """Return (hits, misses, voids) for one ledger row.

    ``actual == line`` is a void, not a miss (I-09). A push refunds or drops the
    slip onto the smaller payout row.
    """

    if raw.get("hits"):
        hits = int(raw["hits"])
        n_legs = int(raw.get("n_legs") or raw.get("legs") or hits)
        return hits, max(n_legs - hits, 0), 0
    sides = [part.strip() for part in raw.get("sides", "").split("|") if part.strip()]
    actuals = [float(part) for part in raw.get("actuals", "").split("|") if part.strip()]
    lines = [float(part) for part in raw.get("lines", "").split("|") if part.strip()]
    if len(actuals) != len(sides) or len(lines) != len(sides):
        raise ValueError("sides, lines, and actuals must have the same length")
    hits = misses = voids = 0
    for side, actual, line in zip(sides, actuals, lines, strict=True):
        if actual == line:
            voids += 1
        elif side in MORE_SIDES and actual > line:
            hits += 1
        elif side in LESS_SIDES and actual < line:
            hits += 1
        else:
            misses += 1
    return hits, misses, voids


def grade_ledger(path: Path, profile_dir: Path | None = None) -> GradeSummary:
    slips = 0
    hits = 0
    stake_total = 0.0
    pnl = 0.0
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            slips += 1
            stake = float(raw.get("stake", 1.0) or 1.0)
            stake_total += stake
            raw_legs = raw.get("n_legs") or raw.get("legs") or ""
            try:
                n_legs = int(raw_legs)
            except (TypeError, ValueError):
                n_legs = 0
            if n_legs <= 0:
                n_legs = len([p for p in raw.get("sides", "").split("|") if p.strip()])
            platform = raw.get("platform") or "underdog"
            mode = raw.get("mode") or "standard"
            displayed = float(raw["multiplier"]) if raw.get("multiplier") else None
            hit_count, _miss_count, void_count = _leg_outcomes(raw)
            if hit_count == n_legs:
                hits += 1
            if void_count:
                payout = _void_payout(
                    platform, mode, n_legs, void_count, hit_count, profile_dir
                )
            else:
                table = resolve_payout(
                    platform,
                    mode,
                    n_legs,
                    displayed_multiplier=displayed,
                    profile_dir=profile_dir,
                )
                payout = table.multiplier_for_hits(hit_count)
            pnl += stake * (payout - 1.0)
    hit_rate = hits / slips if slips else 0.0
    roi = pnl / stake_total if stake_total else 0.0
    return GradeSummary(slips, hits, hit_rate, stake_total, pnl, roi)


def _void_payout(
    platform: str,
    mode: str,
    n_legs: int,
    void_count: int,
    hit_count: int,
    profile_dir: Path | None,
) -> float:
    """Payout after voids: step down to the smaller row, else refund the stake."""

    effective_legs = n_legs - void_count
    if effective_legs < 1:
        return 1.0
    try:
        table = resolve_payout(platform, mode, effective_legs, profile_dir=profile_dir)
    except (ValueError, FileNotFoundError):
        return 1.0
    return table.multiplier_for_hits(hit_count)


def write_grade(summary: GradeSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(summary), indent=2) + "\n", encoding="utf-8")
