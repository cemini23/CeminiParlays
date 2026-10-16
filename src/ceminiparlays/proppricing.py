"""Non-circular prop fair value: split-normal distribution vs a sharp consensus.

Two structural gaps are closed here.

1. A symmetric normal throws away the tail asymmetry in the CeminiDFS handoff.
   A line is priced from a split-normal built on ``(median, p15, p85)``, so an
   injury-limited or committee usage shape keeps its skew.
2. A de-vig against the target book's own two-way price is circular: any "edge"
   it shows is that book's margin, not a disagreement. The market side is a
   power de-vig of every OTHER book, averaged into a consensus that excludes the
   target.

The DFS and market probabilities are blended with a Jev regime weight capped at
0.35, because the handoff distributions have not yet earned more than that until
100 legs of closing-line calibration are proven.
"""

from __future__ import annotations

from dataclasses import dataclass

from scipy.stats import norm

from ceminiparlays.ceminidfs import StatDistribution
from ceminiparlays.fair import p_over_line
from ceminiparlays.odds import devig_two_way
from ceminiparlays.payouts import normalize_platform

#: ``norm.ppf(0.85)``. The scale that puts the 15th/85th percentile at the
#: typed quantiles for each half of a split normal.
Z85 = float(norm.ppf(0.85))
SIGMA_FLOOR = 1e-6

#: Weight cap on the DFS distribution. ``w_dfs = min(CAP, CAP * conf)``.
DFS_WEIGHT_CAP = 0.35
#: One basis point, for the disagreement flag.
BPS = 10_000.0


@dataclass(frozen=True)
class SplitNormal:
    """A two-piece normal: one scale below the median, another above it."""

    median: float
    sigma_low: float
    sigma_high: float

    def cdf(self, x: float) -> float:
        low = max(self.sigma_low, SIGMA_FLOOR)
        high = max(self.sigma_high, SIGMA_FLOOR)
        if x <= self.median:
            return (2.0 * low / (low + high)) * float(norm.cdf((x - self.median) / low))
        tail = float(norm.cdf((x - self.median) / high)) - 0.5
        return (2.0 / (low + high)) * (low * 0.5 + high * tail)

    def p_over(self, line: float) -> float:
        return min(max(1.0 - self.cdf(line), 0.0), 1.0)


def split_normal(median: float, p15: float, p85: float) -> SplitNormal:
    """Build a split normal from a median and its 15th/85th percentiles."""

    if median <= 0.0:
        raise ValueError("median must be positive")
    if not p15 < median < p85:
        raise ValueError("need p15 < median < p85")
    return SplitNormal(
        median=float(median),
        sigma_low=max((median - p15) / Z85, SIGMA_FLOOR),
        sigma_high=max((p85 - median) / Z85, SIGMA_FLOOR),
    )


@dataclass(frozen=True)
class BookQuote:
    book: str
    odds_over: int
    odds_under: int


@dataclass(frozen=True)
class Consensus:
    fair_p_over: float
    books: tuple[str, ...]
    n_books: int


def consensus_fair_p_over(
    quotes: list[BookQuote],
    *,
    target_book: str | None = None,
    method: str = "power",
) -> Consensus | None:
    """Power de-vig every book except the target, then average the fair side.

    Returns ``None`` when no non-target book remains, so a caller never falls
    back to a circular single-book de-vig by accident.
    """

    want = normalize_platform(target_book) if target_book else ""
    values: list[float] = []
    used: list[str] = []
    for quote in quotes:
        book = normalize_platform(quote.book)
        if want and book == want:
            continue
        if quote.odds_over == 0 or quote.odds_under == 0:
            continue
        try:
            result = devig_two_way(quote.odds_over, quote.odds_under, method=method)
        except ValueError:
            continue
        values.append(float(result.p_over))
        used.append(book)
    if not values:
        return None
    return Consensus(
        fair_p_over=sum(values) / len(values),
        books=tuple(used),
        n_books=len(values),
    )


def dfs_weight(jev_regime_conf: float) -> float:
    """Blend weight on the DFS distribution, capped until CLV proves the handoff."""

    confidence = min(max(float(jev_regime_conf), 0.0), 1.0)
    return min(DFS_WEIGHT_CAP, DFS_WEIGHT_CAP * confidence)


def posterior_fair(p_market_fair: float, p_dfs_over: float, jev_regime_conf: float) -> float:
    """Blend the non-circular market fair with the DFS distribution."""

    weight = dfs_weight(jev_regime_conf)
    blended = (1.0 - weight) * float(p_market_fair) + weight * float(p_dfs_over)
    return min(max(blended, 0.0), 1.0)


def disagreement_edge_bps(p_dfs_over: float, p_market_fair: float) -> float:
    """Positive when the handoff is more bullish than the market consensus."""

    return (float(p_dfs_over) - float(p_market_fair)) * BPS


@dataclass(frozen=True)
class PropPrice:
    line: float
    side: str
    p_dfs_over: float
    p_dfs_under: float
    family: str
    p_market_fair: float
    w_dfs: float
    p_fair_posterior: float
    disagreement_edge_bps: float
    consensus_books: tuple[str, ...]


def p_dfs_over(dist: StatDistribution, line: float, stat_type: str = "") -> tuple[float, str]:
    """P(stat > line) from the handoff distribution. Returns ``(prob, family)``.

    A split normal is used when both quantiles are present. Otherwise the
    symmetric fallback reuses ``fair.p_over_line``, so a handoff that carries
    only a median and a sigma still prices.
    """

    stat = stat_type or dist.stat_type
    if dist.has_quantiles and dist.median is not None:
        assert dist.p15 is not None and dist.p85 is not None
        if dist.p15 < dist.median < dist.p85:
            return split_normal(dist.median, dist.p15, dist.p85).p_over(line), "split_normal"
    if dist.median is not None and dist.sigma is not None:
        return p_over_line(line, dist.median, dist.sigma, stat_type=stat).fair_p_over, "symmetric"
    raise ValueError("handoff distribution has neither quantiles nor median+sigma")


def price_prop(
    *,
    dist: StatDistribution | None,
    line: float,
    side: str,
    quotes: list[BookQuote],
    target_book: str | None = None,
    jev_regime_conf: float = 0.0,
    stat_type: str = "",
    method: str = "power",
) -> PropPrice | None:
    """Price one prop. Returns ``None`` when either side cannot be built."""

    consensus = consensus_fair_p_over(quotes, target_book=target_book, method=method)
    if consensus is None:
        return None
    if dist is None:
        return None
    p_over, family = p_dfs_over(dist, line, stat_type=stat_type)
    p_under = 1.0 - p_over
    return PropPrice(
        line=float(line),
        side=side,
        p_dfs_over=p_over,
        p_dfs_under=p_under,
        family=family,
        p_market_fair=consensus.fair_p_over,
        w_dfs=dfs_weight(jev_regime_conf),
        p_fair_posterior=posterior_fair(consensus.fair_p_over, p_over, jev_regime_conf),
        disagreement_edge_bps=disagreement_edge_bps(p_over, consensus.fair_p_over),
        consensus_books=consensus.books,
    )
