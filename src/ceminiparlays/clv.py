"""Aggregate CLV across graded ledgers (money path P2).

Ticket P&L cannot prove an edge at a practical sample size. Leg-level closing
line value can: it asks whether the price taken beat the closing price. A
positive mean CLV is the standard proof of skill and resolves long before the
outcomes do.

This module is the decision view that the per-leg math in ``grade.py`` and the
snapshot in ``closings.py`` do not provide on their own. It reads one or more
graded ledgers and reports: how many legs carry CLV, the mean / median / stdev,
the one-sided t-statistic and p-value for mean > 0, a per-platform /
per-stat / per-market breakdown, and a VERDICT: prove, kill, or keep collecting.

Units. A leg's CLV is a probability difference (``closing implied - bet
implied``, the same value ``grade`` computes). Every ``*_pp`` field in the
report is that difference times 100, i.e. percentage points. A leg that beats
the close is positive.

Basis. The report labels where the closing price came from. A close taken from
the same book that was bet is ``same_book`` (the weaker evidence). A close taken
from a different book is ``reference``. No sharp-book fetch is built here; the
report labels what the data already shows. An absent close platform is labeled
``same_book``.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path

from ceminiparlays.closings import line_clv, side_implied
from ceminiparlays.grade import canonical_ledger_market
from ceminiparlays.payouts import normalize_platform

#: A leg's CLV is a probability difference. The report multiplies by this so
#: every ``*_pp`` number is percentage points.
PP = 100.0
#: PROVE when the mean CLV is at least this many percentage points, the
#: t-statistic is at least ``PROVE_T``, and there are at least ``min_legs`` legs.
PROVE_MEAN_PP = 1.5
PROVE_T = 2.0
#: KILL when the mean CLV is at or below this many percentage points.
KILL_MEAN_PP = 0.0
#: Default independent-leg target. About 20-25 legs a week reaches it in 4-5 weeks.
DEFAULT_MIN_LEGS = 100

SAME_BOOK = "same_book"
REFERENCE = "reference"


@dataclass(frozen=True)
class LegCLV:
    """One leg's CLV and the labels the report groups on."""

    platform: str
    stat_type: str
    market: str
    side: str
    #: Probability difference. Positive beats the close.
    clv_pp: float
    #: Signed line move in the bettor's favor, or None when untaped.
    clv_line: float | None
    basis: str


def _split(text: str | None) -> list[str]:
    """Split a ``|``-joined ledger cell. Blank parts are dropped."""

    return [part.strip() for part in (text or "").split("|") if part.strip()]


def _number(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _american(text: str) -> int | None:
    """Parse an American price cell. ``None`` when it is not an integer."""

    value = _number(text)
    return int(value) if value is not None and value == int(value) else None


def _optional_cell(parts: list[str], index: int) -> str:
    return parts[index] if index < len(parts) else ""


def _leg_clv(
    side: str,
    index: int,
    *,
    cells: dict[str, list[str]],
) -> tuple[float | None, float | None]:
    """CLV for one leg from an explicit cell or from the closing prices.

    Prefers an explicit ``clv_pp`` cell (a probability difference, the same
    unit ``grade`` writes) and falls back to de-vigging the bet and close
    two-way markets. Returns ``(clv_pp, clv_line)``; either may be None.
    """

    explicit_pp = _number(_optional_cell(cells["clv_pp"], index))
    explicit_line = _number(_optional_cell(cells["clv_line"], index))

    clv_pp = explicit_pp
    if clv_pp is None:
        bet_over = _american(_optional_cell(cells["bet_over"], index))
        bet_under = _american(_optional_cell(cells["bet_under"], index))
        close_over = _american(_optional_cell(cells["close_over"], index))
        close_under = _american(_optional_cell(cells["close_under"], index))
        bet_implied = side_implied(side, bet_over, bet_under)
        close_implied = side_implied(side, close_over, close_under)
        if bet_implied is not None and close_implied is not None:
            clv_pp = close_implied - bet_implied

    clv_line = explicit_line
    if clv_line is None:
        bet_line = _number(_optional_cell(cells["lines"], index))
        close_line = _number(_optional_cell(cells["close_lines"], index))
        if bet_line is not None and close_line is not None:
            clv_line = line_clv(side, bet_line, close_line)

    return clv_pp, clv_line


def legs_from_row(raw: dict[str, str]) -> list[LegCLV]:
    """Per-leg CLV for one ledger row. Only legs with a CLV are returned.

    A leg whose bet and close prices are blank has no ``clv_pp`` and is not
    counted. The basis is ``reference`` when the row names a closing platform
    that differs from the bet platform, otherwise ``same_book``.
    """

    platform = normalize_platform((raw.get("platform") or "").strip() or "unknown")
    sides = _split(raw.get("sides"))
    cells = {
        "lines": _split(raw.get("lines")),
        "market": _split(raw.get("market")),
        "clv_pp": _split(raw.get("clv_pp")),
        "clv_line": _split(raw.get("clv_line")),
        "bet_over": _split(raw.get("bet_over")),
        "bet_under": _split(raw.get("bet_under")),
        "close_over": _split(raw.get("close_over")),
        "close_under": _split(raw.get("close_under")),
        "close_lines": _split(raw.get("close_lines")),
        "close_platform": _split(raw.get("close_platform")),
    }

    legs: list[LegCLV] = []
    for index, side in enumerate(sides):
        clv_pp, clv_line = _leg_clv(side, index, cells=cells)
        if clv_pp is None:
            continue
        raw_market = _optional_cell(cells["market"], index)
        stat_type = canonical_ledger_market(raw_market)
        close_book = _optional_cell(cells["close_platform"], index)
        basis = (
            REFERENCE
            if close_book and normalize_platform(close_book) != platform
            else SAME_BOOK
        )
        legs.append(
            LegCLV(
                platform=platform,
                stat_type=stat_type,
                market=raw_market or stat_type,
                side=side,
                clv_pp=clv_pp,
                clv_line=clv_line,
                basis=basis,
            )
        )
    return legs


def collect_legs(paths: list[Path]) -> list[LegCLV]:
    """Read every ledger and return the legs that carry a CLV."""

    legs: list[LegCLV] = []
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"Ledger not found: {path}")
        with path.open(newline="", encoding="utf-8") as handle:
            for raw in csv.DictReader(handle):
                legs.extend(legs_from_row(raw))
    return legs


def student_t_sf(t: float, df: float) -> float:
    """One-sided P(T > t) for a Student's t with ``df`` degrees of freedom.

    Standard-library only. Uses the regularized incomplete beta function.
    """

    if df <= 0:
        return 0.5
    x = df / (df + t * t)
    half = 0.5 * _incomplete_beta(df / 2.0, 0.5, x)
    return half if t >= 0 else 1.0 - half


def _incomplete_beta(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method)."""

    max_iter = 200
    eps = 3e-12
    fpmin = 1e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _six(value: float) -> float:
    return round(value, 6)


def _stats(values: list[float]) -> dict[str, object]:
    """n, mean/median in percentage points, and the positive rate."""

    n = len(values)
    if not values:
        return {
            "n_legs": 0,
            "mean_clv_pp": 0.0,
            "median_clv_pp": 0.0,
            "positive_clv_rate": 0.0,
        }
    return {
        "n_legs": n,
        "mean_clv_pp": _six(statistics.fmean(values) * PP),
        "median_clv_pp": _six(statistics.median(values) * PP),
        "positive_clv_rate": _six(
            sum(1 for value in values if value > 0.0) / n
        ),
    }


def _group(legs: list[LegCLV], key) -> dict[str, dict[str, object]]:
    buckets: dict[str, list[float]] = {}
    for leg in legs:
        name = key(leg) or "unknown"
        buckets.setdefault(name, []).append(leg.clv_pp)
    return {name: _stats(values) for name, values in sorted(buckets.items())}


def _verdict(n_legs: int, mean_pp: float, t_stat: float, min_legs: int) -> str:
    if n_legs >= min_legs and mean_pp >= PROVE_MEAN_PP and t_stat >= PROVE_T:
        return "PROVE"
    if n_legs >= min_legs and mean_pp <= KILL_MEAN_PP:
        return "KILL"
    return "KEEP COLLECTING"


def summarize(
    legs: list[LegCLV],
    *,
    min_legs: int = DEFAULT_MIN_LEGS,
    ledgers: list[Path] | None = None,
) -> dict[str, object]:
    """Build the season CLV report from collected legs."""

    values = [leg.clv_pp for leg in legs]
    n_legs = len(values)
    mean = statistics.fmean(values) if values else 0.0
    median = statistics.median(values) if values else 0.0
    stdev = statistics.stdev(values) if n_legs >= 2 else 0.0
    if n_legs >= 2 and stdev > 0.0:
        t_stat = mean / (stdev / math.sqrt(n_legs))
        p_value = student_t_sf(t_stat, n_legs - 1)
    else:
        t_stat = 0.0
        p_value = 0.0 if mean > 0.0 else (1.0 if mean < 0.0 else 0.5)
    mean_pp = mean * PP
    verdict = _verdict(n_legs, mean_pp, t_stat, min_legs)
    basis_counts: dict[str, int] = {SAME_BOOK: 0, REFERENCE: 0}
    for leg in legs:
        basis_counts[leg.basis] = basis_counts.get(leg.basis, 0) + 1
    if basis_counts.get(REFERENCE, 0) and basis_counts.get(SAME_BOOK, 0):
        basis = "mixed"
    elif basis_counts.get(REFERENCE, 0):
        basis = REFERENCE
    else:
        basis = SAME_BOOK
    return {
        "n_legs": n_legs,
        "min_legs": min_legs,
        "mean_clv_pp": _six(mean_pp),
        "median_clv_pp": _six(median * PP),
        "stdev_clv_pp": _six(stdev * PP),
        "t_stat": _six(t_stat),
        "p_value": _six(p_value),
        "positive_clv_rate": _six(
            sum(1 for value in values if value > 0.0) / n_legs if n_legs else 0.0
        ),
        "verdict": verdict,
        "legs_remaining": max(0, min_legs - n_legs),
        "clv_basis": basis,
        "basis_counts": basis_counts,
        "by_platform": _group(legs, lambda leg: leg.platform),
        "by_stat_type": _group(legs, lambda leg: leg.stat_type),
        "by_market": _group(legs, lambda leg: leg.market),
        "ledgers": [str(path) for path in (ledgers or [])],
    }


def clv_report(
    ledgers: list[Path],
    *,
    min_legs: int = DEFAULT_MIN_LEGS,
) -> dict[str, object]:
    """Read the ledgers and return the season CLV report."""

    return summarize(collect_legs(ledgers), min_legs=min_legs, ledgers=ledgers)


def _basis_line(report: dict[str, object]) -> str:
    counts = report["basis_counts"]
    assert isinstance(counts, dict)
    return (
        f"basis: {report['clv_basis']} "
        f"(reference {counts.get(REFERENCE, 0)}, same_book {counts.get(SAME_BOOK, 0)})"
    )


def _breakdown(title: str, groups: dict[str, dict[str, object]]) -> list[str]:
    lines = [f"{title}:"]
    if not groups:
        lines.append("  (none)")
        return lines
    for name, stats in groups.items():
        lines.append(
            f"  {name}: n={stats['n_legs']} "
            f"mean={stats['mean_clv_pp']:+.2f}pp "
            f"median={stats['median_clv_pp']:+.2f}pp "
            f"positive={stats['positive_clv_rate']:.0%}"
        )
    return lines


def format_clv_report(report: dict[str, object]) -> str:
    """Human-readable season CLV summary."""

    n_legs = report["n_legs"]
    min_legs = report["min_legs"]
    lines = [
        f"CLV report — {n_legs} legs with CLV (target {min_legs})",
        _basis_line(report),
        (
            f"mean {report['mean_clv_pp']:+.2f}pp  "
            f"median {report['median_clv_pp']:+.2f}pp  "
            f"stdev {report['stdev_clv_pp']:.2f}pp"
        ),
        (
            f"t-stat {report['t_stat']:.2f}  "
            f"p(mean>0) {report['p_value']:.4f}  "
            f"positive rate {report['positive_clv_rate']:.0%}"
        ),
    ]
    lines += _breakdown("by platform", report["by_platform"])
    lines += _breakdown("by stat_type", report["by_stat_type"])
    lines += _breakdown("by market", report["by_market"])
    verdict = report["verdict"]
    if verdict == "KEEP COLLECTING":
        remaining = report["legs_remaining"]
        lines.append(
            f"VERDICT: KEEP COLLECTING — {remaining} legs to the {min_legs}-leg gate"
        )
    elif verdict == "PROVE":
        lines.append(
            f"VERDICT: PROVE — mean {report['mean_clv_pp']:+.2f}pp >= "
            f"{PROVE_MEAN_PP:+.1f}pp and t {report['t_stat']:.2f} >= {PROVE_T:.1f} "
            f"at n={n_legs}"
        )
    else:
        lines.append(
            f"VERDICT: KILL — mean {report['mean_clv_pp']:+.2f}pp <= "
            f"{KILL_MEAN_PP:.1f}pp at n={n_legs}"
        )
    return "\n".join(lines)


def write_clv_json(report: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
