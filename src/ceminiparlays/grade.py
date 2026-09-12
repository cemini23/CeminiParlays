from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ceminiparlays.payouts import resolve_payout


@dataclass
class GradeSummary:
    n_slips: int
    hits: int
    hit_rate: float
    stake: float
    pnl: float
    roi: float


def _hits_for_row(raw: dict[str, str]) -> int:
    if raw.get("hits"):
        return int(raw["hits"])
    sides = [part.strip() for part in raw.get("sides", "").split("|") if part.strip()]
    actuals = [float(part) for part in raw.get("actuals", "").split("|") if part.strip()]
    lines = [float(part) for part in raw.get("lines", "").split("|") if part.strip()]
    if len(actuals) != len(sides) or len(lines) != len(sides):
        raise ValueError("sides, lines, and actuals must have the same length")
    hits = 0
    for side, actual, line in zip(sides, actuals, lines, strict=True):
        if side in {"more", "over", "higher", "o"} and actual > line:
            hits += 1
        elif side in {"less", "under", "lower", "u"} and actual < line:
            hits += 1
    return hits


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
            table = resolve_payout(
                raw.get("platform") or "underdog",
                raw.get("mode") or "standard",
                n_legs,
                displayed_multiplier=float(raw["multiplier"]) if raw.get("multiplier") else None,
                profile_dir=profile_dir,
            )
            hit_count = _hits_for_row(raw)
            if hit_count == n_legs:
                hits += 1
            payout = table.multiplier_for_hits(hit_count)
            pnl += stake * (payout - 1.0)
    hit_rate = hits / slips if slips else 0.0
    roi = pnl / stake_total if stake_total else 0.0
    return GradeSummary(slips, hits, hit_rate, stake_total, pnl, roi)


def write_grade(summary: GradeSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(summary), indent=2) + "\n", encoding="utf-8")
