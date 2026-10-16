"""Persistent season CLV ledger: one appended row per graded run.

``clv.py`` answers prove-or-kill for the legs it can read. This module keeps
that answer over the season in one file, ``reports/season_clv_ledger.csv``, so
week 9 never starts from a fresh report with no history.

Units. CLV is a probability difference. One basis point is ``0.0001`` of
probability, so ``mean_clv_bps = mean_clv_pp * 100``. ``realized_roi_pct`` is
net P&L over staked cash. ``dfs_handoff_brier_lift`` is positive when the
CeminiDFS distribution predicted the hit better than the closing consensus.
"""

from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass
from pathlib import Path

from ceminiparlays.clv import summarize

#: Probability difference to basis points. ``clv.py`` calls the same unit pp.
BPS = 10_000.0

LEDGER_FIELDS = [
    "run_date",
    "week",
    "n_legs",
    "mean_clv_bps",
    "t_stat",
    "realized_roi_pct",
    "dfs_handoff_brier_lift",
    "n_brier_legs",
    "ledgers",
]


@dataclass(frozen=True)
class BrierPair:
    """One graded leg's two forecasts and the realized outcome.

    ``actual_hit`` is 1.0 for a hit and 0.0 for a miss. A void or push leg has
    no hit and must not be included.
    """

    p_dfs_over: float
    close_fair_prob: float
    actual_hit: float


def brier_delta(pair: BrierPair) -> float:
    """Squared error of the DFS forecast minus that of the closing consensus.

    Positive means the DFS distribution was the worse of the two.
    """

    actual = float(pair.actual_hit)
    dfs = (float(pair.p_dfs_over) - actual) ** 2
    close = (float(pair.close_fair_prob) - actual) ** 2
    return dfs - close


def dfs_handoff_brier_lift(pairs: list[BrierPair]) -> float | None:
    """Mean of ``close error - DFS error``. Positive means the handoff won.

    ``None`` when no leg carries both forecasts, so the ledger cell stays blank
    instead of printing a fake zero.
    """

    if not pairs:
        return None
    return statistics.fmean(-brier_delta(pair) for pair in pairs)


def realized_roi_pct(stake: float, pnl: float) -> float | None:
    """Net P&L over staked cash, in percent. ``None`` when nothing was staked."""

    if not stake or float(stake) <= 0.0:
        return None
    return float(pnl) / float(stake) * 100.0


def ledger_row(
    *,
    week: str,
    legs: list,
    run_date: str,
    stake: float = 0.0,
    pnl: float = 0.0,
    brier_pairs: list[BrierPair] | None = None,
    ledgers: list[Path] | None = None,
) -> dict[str, str]:
    """Build one ledger row from graded legs and the run's realized P&L."""

    report = summarize(legs, ledgers=ledgers)
    n_legs = int(report["n_legs"])
    mean_clv_pp = float(report["mean_clv_pp"])
    lift = dfs_handoff_brier_lift(list(brier_pairs or []))
    roi = realized_roi_pct(stake, pnl)
    return {
        "run_date": run_date,
        "week": str(week),
        "n_legs": str(n_legs),
        "mean_clv_bps": f"{mean_clv_pp * (BPS / 100.0):.6f}",
        "t_stat": f"{float(report['t_stat']):.6f}",
        "realized_roi_pct": "" if roi is None else f"{roi:.6f}",
        "dfs_handoff_brier_lift": "" if lift is None else f"{lift:.6f}",
        "n_brier_legs": str(len(brier_pairs or [])),
        "ledgers": ";".join(str(path) for path in (ledgers or [])),
    }


def append_ledger(path: Path, row: dict[str, str]) -> None:
    """Append one row, writing the header only when the file is new or empty."""

    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not resolved.is_file() or resolved.stat().st_size == 0
    with resolved.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEDGER_FIELDS)
        if needs_header:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in LEDGER_FIELDS})


def read_ledger(path: Path) -> list[dict[str, str]]:
    """Read the season ledger. A missing file is an empty history."""

    resolved = Path(path)
    if not resolved.is_file():
        return []
    with resolved.open(newline="", encoding="utf-8") as handle:
        return [dict(raw) for raw in csv.DictReader(handle)]
