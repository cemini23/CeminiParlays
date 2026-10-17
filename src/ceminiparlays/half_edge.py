"""Half and quarter rate versus the posted full-game line.

The rules below were locked on 2026-10-17 before any slate score.

Train on nflverse regular-season plays with ``game_date`` before 2026-10-18.
Half is ``qtr`` in {1, 2}. Quarter 1 is ``qtr == 1``. A game counts only when
the full-game stat clears its floor: pass yards 50, rush yards 15, receiving
yards 15, receptions 2, team points 1. The period stat is capped at the full
stat, so a share stays in 0 to 1.

The player share is the unweighted mean of those game shares. The league
share is the unweighted mean of the same game shares across players. Shrink
with k = 8: ``(n * raw + 8 * league) / (n + 8)``. A split is real when
``n >= 8`` and ``abs(shrunk - league) > sample_sd / sqrt(n)``. Otherwise the
leg is dropped.

Model mean = full-game balanced line times the shrunk share. ``P(over)`` is
``1 - Phi((posted_line - mean) / sigma)`` with no continuity correction.
Sigma is the max of the player's period-stat sample sd and a floor:
yards ``max(8, 0.25 * full_line)``, receptions ``max(0.6, 0.25 * posted_line)``,
points ``max(3.5, 0.25 * full_line)``.

The side is the sign of ``mean - posted_line``. A tie is dropped. The side
is never the higher of the two EVs. EV is ``p_side * decimal(posted American)
- 1``. De-vig is not the payout.

Only these markets are scored: ``pass_yds_h1``, ``rush_yds_h1``,
``rec_yds_h1``, ``receptions_h1``, ``pass_yds_q1``, ``rush_yds_q1``,
``rec_yds_q1``, ``receptions_q1``, ``team_total_h1``, ``total_h1``.
A market passes only when it has at least 20 legs, mean EV is above 0, the
leg-bootstrap 95 percent CI lower bound is above 0, and the game-cluster
bootstrap lower bound is above 0. The leg generator is
``random.Random(20261017)``. The cluster generator is
``random.Random(20261018)``. Each uses 2000 draws. The percentile is linear
on ``(n - 1) * p``. A game total needs a real split from both teams. The
model share is the average of those two shrunk shares.

NGS weekly means are joined for the report. They are not used in the price.
This module does not import ``jev_client``. Jev does not price a leg.
``jev_gate`` stays fail-closed.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ceminiparlays.names import fold_name
from ceminiparlays.odds import american_to_decimal
from ceminiparlays.roster import normalize_team

CUTOFF = "2026-10-18"
SHRINK_K = 8.0
MIN_GAMES = 8
MIN_LEGS = 20
N_BOOT = 2000
LEG_SEED = 20261017
CLUSTER_SEED = 20261018
YARD_SIGMA_FLOOR = 8.0
RECEPTION_SIGMA_FLOOR = 0.6
POINT_SIGMA_FLOOR = 3.5
TIE_EPS = 1e-9

FLOORS = {
    "pass_yds": 50.0,
    "rush_yds": 15.0,
    "rec_yds": 15.0,
    "receptions": 2.0,
    "team_points": 1.0,
}
YARD_STATS = frozenset({"pass_yds", "rush_yds", "rec_yds"})
GATE_MARKETS = (
    "pass_yds_h1",
    "rush_yds_h1",
    "rec_yds_h1",
    "receptions_h1",
    "pass_yds_q1",
    "rush_yds_q1",
    "rec_yds_q1",
    "receptions_q1",
    "team_total_h1",
    "total_h1",
)
_PERIOD = {
    "pass_yds_h1": ("pass_yds", "h1"),
    "rush_yds_h1": ("rush_yds", "h1"),
    "rec_yds_h1": ("rec_yds", "h1"),
    "receptions_h1": ("receptions", "h1"),
    "pass_yds_q1": ("pass_yds", "q1"),
    "rush_yds_q1": ("rush_yds", "q1"),
    "rec_yds_q1": ("rec_yds", "q1"),
    "receptions_q1": ("receptions", "q1"),
    "team_total_h1": ("team_points", "h1"),
    "total_h1": ("team_points", "h1"),
}
SHARE_FIELDS = [
    "stat",
    "gsis_id",
    "player_key",
    "match_initial",
    "match_last",
    "pbp_name",
    "full_name",
    "team",
    "n_games",
    "raw_share",
    "share_sd",
    "share_se",
    "shrunk_share",
    "league_share",
    "sigma_h1",
    "q1_n_games",
    "q1_raw_share",
    "q1_share_sd",
    "q1_share_se",
    "q1_shrunk_share",
    "q1_league_share",
    "sigma_q1",
    "ngs_avg_separation",
    "ngs_catch_percentage",
    "ngs_avg_yac_above_expectation",
    "ngs_cpoe",
]
EV_FIELDS = [
    "market",
    "n_legs",
    "mean_ev",
    "ci_low",
    "ci_high",
    "cluster_ci_low",
    "cluster_ci_high",
    "verdict",
    "reason",
]
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
_PBP_COLUMNS = [
    "game_id",
    "game_date",
    "season_type",
    "qtr",
    "posteam",
    "home_team",
    "away_team",
    "total_home_score",
    "total_away_score",
    "passer_player_id",
    "passer_player_name",
    "passing_yards",
    "rusher_player_id",
    "rusher_player_name",
    "rushing_yards",
    "receiver_player_id",
    "receiver_player_name",
    "receiving_yards",
    "complete_pass",
]
_DEFAULT_PBP = (
    Path("/Users/claudiobarone/Projects/CeminiDFS/artifacts/cache/pbp_2025.parquet"),
    Path("/Users/claudiobarone/Projects/CeminiDFS/artifacts/cache/pbp_2026.parquet"),
)
_DEFAULT_NGS_REC = (
    Path("/Users/claudiobarone/Projects/CeminiDFS/artifacts/cache/ngs_receiving_2025.parquet"),
    Path("/Users/claudiobarone/Projects/CeminiDFS/artifacts/cache/ngs_receiving_2026.parquet"),
)
_DEFAULT_NGS_PASS = (
    Path("/Users/claudiobarone/Projects/CeminiDFS/artifacts/cache/ngs_passing_2025.parquet"),
    Path("/Users/claudiobarone/Projects/CeminiDFS/artifacts/cache/ngs_passing_2026.parquet"),
)


def shrink_share(n: int, raw: float, league: float, k: float = SHRINK_K) -> float:
    """Pull a mean toward the league mean. ``k`` is the prior strength."""

    return (n * raw + k * league) / (n + k)


def sample_sd(values: list[float]) -> float | None:
    """Sample standard deviation. ``None`` when fewer than two values."""

    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    var = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(var)


def is_real_split(n: int, shrunk: float, league: float, se: float | None) -> bool:
    """True when the shrunk share is not noise around the league share."""

    if n < MIN_GAMES or se is None:
        return False
    return abs(shrunk - league) > se


def normal_over_prob(line: float, mean: float, sigma: float) -> float:
    """``P(stat > line)`` for a normal draw. No continuity correction."""

    if sigma <= 0:
        raise ValueError("sigma must be positive")
    z = (line - mean) / sigma
    return 1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def pick_side(mean: float, line: float) -> str | None:
    """Side from the model mean. A tie returns ``None``. Prices are not read."""

    if abs(mean - line) <= TIE_EPS:
        return None
    if mean > line:
        return "over"
    return "under"


def typed_question(row: dict[str, object]) -> str:
    """A question this module does not send.

    Jev does not price the leg. The rate model stays in this file.
    """

    return (
        f"Is the {row.get('stat_type')} split for {row.get('player_name')} "
        "real after the posted vig? Answer only pass or fail."
    )


def _finite(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(number):
        return 0.0
    return number


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}"


def _parse_float(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number):
        return None
    return number


def _parse_int(value: object) -> int | None:
    number = _parse_float(value)
    if number is None:
        return None
    return int(round(number))


def _price(value: object) -> int | None:
    price = _parse_int(value)
    if price is None or price == 0 or -100 < price < 100:
        return None
    return price


def _initial_last(display: str) -> tuple[str, str]:
    text = str(display or "").replace(".", " ").replace("'", "").replace("’", "")
    parts = [part for part in text.split() if part.lower() not in _SUFFIXES]
    if not parts:
        return "", ""
    initial = parts[0][0].lower()
    return initial, fold_name(parts[-1])


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear percentile. ``pct`` is in 0 to 100. ``sorted_values`` is sorted."""

    if not sorted_values:
        raise ValueError("percentile of an empty sample")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * (pct / 100.0)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    weight = rank - low
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * weight


def _bootstrap_mean(values: list[float], rng: random.Random) -> tuple[float, float]:
    draws: list[float] = []
    width = len(values)
    for _ in range(N_BOOT):
        total = 0.0
        for _index in range(width):
            total += values[rng.randrange(width)]
        draws.append(total / width)
    draws.sort()
    return _percentile(draws, 2.5), _percentile(draws, 97.5)


def _cluster_mean(groups: list[list[float]], rng: random.Random) -> tuple[float, float]:
    draws: list[float] = []
    width = len(groups)
    for _ in range(N_BOOT):
        chosen: list[float] = []
        for _index in range(width):
            chosen.extend(groups[rng.randrange(width)])
        draws.append(sum(chosen) / len(chosen))
    draws.sort()
    return _percentile(draws, 2.5), _percentile(draws, 97.5)


@dataclass(frozen=True)
class Leg:
    market: str
    game_key: str
    side: str
    ev: float
    price: int
    model_mean: float
    line: float
    p_side: float


@dataclass(frozen=True)
class MarketScore:
    market: str
    n_legs: int
    mean_ev: float | None
    ci_low: float | None
    ci_high: float | None
    cluster_ci_low: float | None
    cluster_ci_high: float | None
    verdict: str
    reason: str

    def as_row(self) -> dict[str, str]:
        return {
            "market": self.market,
            "n_legs": str(self.n_legs),
            "mean_ev": _fmt(self.mean_ev),
            "ci_low": _fmt(self.ci_low),
            "ci_high": _fmt(self.ci_high),
            "cluster_ci_low": _fmt(self.cluster_ci_low),
            "cluster_ci_high": _fmt(self.cluster_ci_high),
            "verdict": self.verdict,
            "reason": self.reason,
        }


def _sigma(stat: str, full_line: float, posted_line: float, player_sd: float | None) -> float:
    if stat in YARD_STATS:
        floor = max(YARD_SIGMA_FLOOR, 0.25 * full_line)
    elif stat == "receptions":
        floor = max(RECEPTION_SIGMA_FLOOR, 0.25 * posted_line)
    else:
        floor = max(POINT_SIGMA_FLOOR, 0.25 * full_line)
    if player_sd is None:
        return floor
    return max(floor, player_sd)


def _period_fields(row: dict[str, str], period: str) -> tuple[int, float, float, float | None, float | None]:
    if period == "q1":
        n = _parse_int(row.get("q1_n_games")) or 0
        shrunk = _parse_float(row.get("q1_shrunk_share"))
        league = _parse_float(row.get("q1_league_share"))
        se = _parse_float(row.get("q1_share_se"))
        sigma = _parse_float(row.get("sigma_q1"))
    else:
        n = _parse_int(row.get("n_games")) or 0
        shrunk = _parse_float(row.get("shrunk_share"))
        league = _parse_float(row.get("league_share"))
        se = _parse_float(row.get("share_se"))
        sigma = _parse_float(row.get("sigma_h1"))
    if shrunk is None or league is None:
        return n, 0.0, 0.0, se, sigma
    return n, shrunk, league, se, sigma


class _ShareIndex:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.by_key: dict[tuple[str, str], dict[str, str] | None] = {}
        self.by_init: dict[tuple[str, str, str], dict[str, str] | None] = {}
        self.by_team: dict[tuple[str, str], dict[str, str] | None] = {}
        self.ngs_player_rows = 0
        self.ngs_attached = 0
        for row in rows:
            stat = row.get("stat") or ""
            if stat == "team_points":
                team = normalize_team(row.get("team") or "")
                self._put(self.by_team, (stat, team), row)
                continue
            self.ngs_player_rows += 1
            if any(str(row.get(field) or "").strip() for field in (
                "ngs_avg_separation",
                "ngs_catch_percentage",
                "ngs_avg_yac_above_expectation",
                "ngs_cpoe",
            )):
                self.ngs_attached += 1
            player_key = row.get("player_key") or ""
            if player_key:
                self._put(self.by_key, (stat, player_key), row)
            initial = (row.get("match_initial") or "").lower()
            last = row.get("match_last") or ""
            if initial and last:
                self._put(self.by_init, (stat, initial, last), row)

    @staticmethod
    def _put(index: dict[Any, dict[str, str] | None], key: Any, row: dict[str, str]) -> None:
        if key in index:
            index[key] = None
        else:
            index[key] = row

    def player(self, stat: str, display: str, player_key: str) -> dict[str, str] | None:
        keyed = self.by_key.get((stat, player_key))
        if keyed is not None and (stat, player_key) in self.by_key:
            return keyed
        if (stat, player_key) in self.by_key:
            return None
        initial, last = _initial_last(display)
        if not initial or not last:
            return None
        return self.by_init.get((stat, initial, last))

    def team(self, team: str) -> dict[str, str] | None:
        return self.by_team.get(("team_points", normalize_team(team)))


def _game_key(row: dict[str, str]) -> str:
    teams = sorted([normalize_team(str(row.get("team") or "")), normalize_team(str(row.get("opp") or ""))])
    return f"{row.get('commence_time') or ''}|{'|'.join(teams)}"


def _index_lines(rows: list[dict[str, str]]) -> dict[tuple[str, str, str, str], list[dict[str, str]]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[
            (
                str(row.get("commence_time") or ""),
                str(row.get("stat_type") or ""),
                str(row.get("player_key") or ""),
                str(row.get("line_type") or ""),
            )
        ].append(row)
    return grouped


def _one_standard(
    grouped: dict[tuple[str, str, str, str], list[dict[str, str]]],
    commence: str,
    stat: str,
    player_key: str,
) -> dict[str, str] | None:
    hits = grouped.get((commence, stat, player_key, "standard")) or []
    if len(hits) != 1:
        return None
    return hits[0]


def _make_leg(
    market: str,
    row: dict[str, str],
    *,
    mean: float,
    sigma: float,
    full_line: float,
) -> Leg | None:
    posted = _parse_float(row.get("line"))
    if posted is None or sigma <= 0:
        return None
    side = pick_side(mean, posted)
    if side is None:
        return None
    p_over = normal_over_prob(posted, mean, sigma)
    if side == "over":
        price = _price(row.get("book_over"))
        p_side = p_over
    else:
        price = _price(row.get("book_under"))
        p_side = 1.0 - p_over
    if price is None:
        return None
    return Leg(
        market=market,
        game_key=_game_key(row),
        side=side,
        ev=p_side * american_to_decimal(price) - 1.0,
        price=price,
        model_mean=mean,
        line=posted,
        p_side=p_side,
    )


def select_legs(
    lines: list[dict[str, str]], shares: list[dict[str, str]]
) -> tuple[dict[str, list[Leg]], dict[str, int], _ShareIndex]:
    """Build one leg per posted main line. Drop noise, ties, and missing joins."""

    index = _ShareIndex(shares)
    grouped = _index_lines(lines)
    dropped = {
        "unmatched": 0,
        "no_split": 0,
        "no_full_line": 0,
        "tie": 0,
        "no_price": 0,
    }
    chosen: dict[str, list[Leg]] = {market: [] for market in GATE_MARKETS}
    for row in lines:
        market = str(row.get("stat_type") or "")
        if market not in _PERIOD:
            continue
        base, period = _PERIOD[market]
        want = "half" if period == "h1" else "quarter"
        if str(row.get("line_type") or "") != want:
            continue
        if market == "total_h1":
            leg = _game_total_leg(row, index, grouped, dropped)
        elif market == "team_total_h1":
            leg = _team_total_leg(row, index, grouped, dropped)
        else:
            leg = _player_leg(row, market, base, period, index, grouped, dropped)
        if leg is not None:
            chosen[market].append(leg)
    return chosen, dropped, index


def _player_leg(
    row: dict[str, str],
    market: str,
    base: str,
    period: str,
    index: _ShareIndex,
    grouped: dict[tuple[str, str, str, str], list[dict[str, str]]],
    dropped: dict[str, int],
) -> Leg | None:
    share = index.player(base, str(row.get("player_name") or ""), str(row.get("player_key") or ""))
    if share is None:
        dropped["unmatched"] += 1
        return None
    n, shrunk, league, se, player_sd = _period_fields(share, period)
    if not is_real_split(n, shrunk, league, se):
        dropped["no_split"] += 1
        return None
    full = _one_standard(grouped, str(row.get("commence_time") or ""), base, str(row.get("player_key") or ""))
    if full is None:
        dropped["no_full_line"] += 1
        return None
    full_line = _parse_float(full.get("line"))
    posted = _parse_float(row.get("line"))
    if full_line is None or posted is None:
        dropped["no_full_line"] += 1
        return None
    mean = full_line * shrunk
    if pick_side(mean, posted) is None:
        dropped["tie"] += 1
        return None
    leg = _make_leg(market, row, mean=mean, sigma=_sigma(base, full_line, posted, player_sd), full_line=full_line)
    if leg is None:
        dropped["no_price"] += 1
    return leg


def _team_total_leg(
    row: dict[str, str],
    index: _ShareIndex,
    grouped: dict[tuple[str, str, str, str], list[dict[str, str]]],
    dropped: dict[str, int],
) -> Leg | None:
    share = index.team(str(row.get("team") or ""))
    if share is None:
        dropped["unmatched"] += 1
        return None
    n, shrunk, league, se, player_sd = _period_fields(share, "h1")
    if not is_real_split(n, shrunk, league, se):
        dropped["no_split"] += 1
        return None
    full = _team_full_line(grouped, row, "team_total")
    if full is None:
        dropped["no_full_line"] += 1
        return None
    full_line = _parse_float(full.get("line"))
    posted = _parse_float(row.get("line"))
    if full_line is None or posted is None:
        dropped["no_full_line"] += 1
        return None
    mean = full_line * shrunk
    if pick_side(mean, posted) is None:
        dropped["tie"] += 1
        return None
    leg = _make_leg(
        "team_total_h1",
        row,
        mean=mean,
        sigma=_sigma("team_points", full_line, posted, player_sd),
        full_line=full_line,
    )
    if leg is None:
        dropped["no_price"] += 1
    return leg


def _game_total_leg(
    row: dict[str, str],
    index: _ShareIndex,
    grouped: dict[tuple[str, str, str, str], list[dict[str, str]]],
    dropped: dict[str, int],
) -> Leg | None:
    home = index.team(str(row.get("team") or ""))
    away = index.team(str(row.get("opp") or ""))
    if home is None or away is None:
        dropped["unmatched"] += 1
        return None
    left = _period_fields(home, "h1")
    right = _period_fields(away, "h1")
    if not is_real_split(left[0], left[1], left[2], left[3]) or not is_real_split(
        right[0], right[1], right[2], right[3]
    ):
        dropped["no_split"] += 1
        return None
    full = _one_standard(
        grouped,
        str(row.get("commence_time") or ""),
        "total",
        str(row.get("player_key") or ""),
    )
    if full is None:
        dropped["no_full_line"] += 1
        return None
    full_line = _parse_float(full.get("line"))
    posted = _parse_float(row.get("line"))
    if full_line is None or posted is None:
        dropped["no_full_line"] += 1
        return None
    mean = full_line * ((left[1] + right[1]) / 2.0)
    if pick_side(mean, posted) is None:
        dropped["tie"] += 1
        return None
    sigma = _sigma("team_points", full_line, posted, _combine_sd(left[4], right[4]))
    leg = _make_leg("total_h1", row, mean=mean, sigma=sigma, full_line=full_line)
    if leg is None:
        dropped["no_price"] += 1
    return leg


def _combine_sd(left: float | None, right: float | None) -> float | None:
    if left is None and right is None:
        return None
    return max(left or 0.0, right or 0.0)


def _team_full_line(
    grouped: dict[tuple[str, str, str, str], list[dict[str, str]]],
    row: dict[str, str],
    stat: str,
) -> dict[str, str] | None:
    commence = str(row.get("commence_time") or "")
    team = normalize_team(str(row.get("team") or ""))
    hits: list[dict[str, str]] = []
    for (kick, kind, _key, line_type), rows in grouped.items():
        if kick != commence or kind != stat or line_type != "standard":
            continue
        for candidate in rows:
            if normalize_team(str(candidate.get("team") or "")) == team:
                hits.append(candidate)
    if len(hits) != 1:
        return None
    return hits[0]


def score_markets(
    lines: list[dict[str, str]], shares: list[dict[str, str]]
) -> tuple[list[MarketScore], dict[str, int], _ShareIndex]:
    """Score each gate market. The same inputs return the same verdicts."""

    chosen, dropped, index = select_legs(lines, shares)
    scored: list[MarketScore] = []
    for market in GATE_MARKETS:
        legs = chosen[market]
        scored.append(_summarize(market, legs))
    return scored, dropped, index


def _summarize(market: str, legs: list[Leg]) -> MarketScore:
    n_legs = len(legs)
    if n_legs < MIN_LEGS:
        return MarketScore(market, n_legs, _mean(legs), None, None, None, None, "fail", "too_few_legs")
    values = [leg.ev for leg in legs]
    mean_ev = sum(values) / n_legs
    ci_low, ci_high = _bootstrap_mean(values, random.Random(LEG_SEED))
    groups: dict[str, list[float]] = defaultdict(list)
    for leg in legs:
        groups[leg.game_key].append(leg.ev)
    cluster_low, cluster_high = _cluster_mean(list(groups.values()), random.Random(CLUSTER_SEED))
    if mean_ev <= 0:
        reason = "mean_ev_not_positive"
        verdict = "fail"
    elif ci_low <= 0:
        reason = "ci_includes_zero"
        verdict = "fail"
    elif cluster_low <= 0:
        reason = "cluster_ci_includes_zero"
        verdict = "fail"
    else:
        reason = ""
        verdict = "pass"
    return MarketScore(
        market,
        n_legs,
        mean_ev,
        ci_low,
        ci_high,
        cluster_low,
        cluster_high,
        verdict,
        reason,
    )


def _mean(legs: list[Leg]) -> float | None:
    if not legs:
        return None
    return sum(leg.ev for leg in legs) / len(legs)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_scores(path: Path, scores: list[MarketScore]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=EV_FIELDS)
        writer.writeheader()
        for score in scores:
            writer.writerow(score.as_row())


def format_report(scores: list[MarketScore], dropped: dict[str, int], index: _ShareIndex) -> str:
    lines = [
        f"ngs_player_rows={index.ngs_player_rows}",
        f"ngs_attached={index.ngs_attached}",
        f"dropped_unmatched={dropped['unmatched']}",
        f"dropped_no_split={dropped['no_split']}",
        f"dropped_no_full_line={dropped['no_full_line']}",
        f"dropped_tie={dropped['tie']}",
        f"dropped_no_price={dropped['no_price']}",
        ",".join(EV_FIELDS),
    ]
    for score in scores:
        row = score.as_row()
        lines.append(",".join(row[field] for field in EV_FIELDS))
    return "\n".join(lines) + "\n"


def _finish_player(
    stat: str,
    gsis: str,
    games: list[dict[str, float]],
    names: dict[str, str],
    league_h1: float,
    league_q1: float,
) -> dict[str, str]:
    h1_shares = [game["h1"] / game["full"] for game in games]
    q1_shares = [game["q1"] / game["full"] for game in games]
    n = len(games)
    raw = sum(h1_shares) / n
    q1_raw = sum(q1_shares) / n
    h1_sd = sample_sd(h1_shares)
    q1_sd = sample_sd(q1_shares)
    return {
        "stat": stat,
        "gsis_id": gsis,
        "player_key": names.get("player_key", ""),
        "match_initial": names.get("match_initial", ""),
        "match_last": names.get("match_last", ""),
        "pbp_name": names.get("pbp_name", ""),
        "full_name": names.get("full_name", ""),
        "team": names.get("team", ""),
        "n_games": str(n),
        "raw_share": _fmt(raw),
        "share_sd": _fmt(h1_sd),
        "share_se": _fmt(None if h1_sd is None else h1_sd / math.sqrt(n)),
        "shrunk_share": _fmt(shrink_share(n, raw, league_h1)),
        "league_share": _fmt(league_h1),
        "sigma_h1": _fmt(sample_sd([game["h1"] for game in games])),
        "q1_n_games": str(n),
        "q1_raw_share": _fmt(q1_raw),
        "q1_share_sd": _fmt(q1_sd),
        "q1_share_se": _fmt(None if q1_sd is None else q1_sd / math.sqrt(n)),
        "q1_shrunk_share": _fmt(shrink_share(n, q1_raw, league_q1)),
        "q1_league_share": _fmt(league_q1),
        "sigma_q1": _fmt(sample_sd([game["q1"] for game in games])),
        "ngs_avg_separation": names.get("ngs_avg_separation", ""),
        "ngs_catch_percentage": names.get("ngs_catch_percentage", ""),
        "ngs_avg_yac_above_expectation": names.get("ngs_avg_yac_above_expectation", ""),
        "ngs_cpoe": names.get("ngs_cpoe", ""),
    }


def _rows_for_stat(
    games_by_id: dict[str, list[dict[str, float]]],
    names: dict[str, dict[str, str]],
    stat: str,
) -> list[dict[str, str]]:
    included = {gsis: games for gsis, games in games_by_id.items() if games}
    if not included:
        raise ValueError(f"no games cleared the floor for {stat}")
    h1_pool = [game["h1"] / game["full"] for games in included.values() for game in games]
    q1_pool = [game["q1"] / game["full"] for games in included.values() for game in games]
    league_h1 = sum(h1_pool) / len(h1_pool)
    league_q1 = sum(q1_pool) / len(q1_pool)
    rows = [
        _finish_player(stat, gsis, games, names.get(gsis, {}), league_h1, league_q1)
        for gsis, games in included.items()
    ]
    rows.sort(key=lambda row: (row["team"], row["gsis_id"], row["player_key"]))
    return rows


def build_shares(
    pbp_paths: list[Path],
    ngs_rec_paths: list[Path],
    ngs_pass_paths: list[Path],
    out: Path,
) -> dict[str, int]:
    """Write the historical share table. The score command reads this file."""

    import pandas as pd

    frames = [_read_pbp(pd, path) for path in pbp_paths]
    plays = pd.concat(frames, ignore_index=True)
    plays["game_date"] = plays["game_date"].astype(str).str.slice(0, 10)
    plays = plays[(plays["season_type"].astype(str) == "REG") & (plays["game_date"] < CUTOFF)]
    plays = plays[plays["qtr"].notna()].copy()
    ngs = _load_ngs(pd, ngs_rec_paths, ngs_pass_paths)
    rows: list[dict[str, str]] = []
    specs = (
        ("pass_yds", "passer_player_id", "passer_player_name", "passing_yards", None),
        ("rush_yds", "rusher_player_id", "rusher_player_name", "rushing_yards", None),
        ("rec_yds", "receiver_player_id", "receiver_player_name", "receiving_yards", None),
        ("receptions", "receiver_player_id", "receiver_player_name", "complete_pass", "complete_pass"),
    )
    for stat, id_col, name_col, value_col, mask_col in specs:
        games, names = _player_stat_games(plays, stat, id_col, name_col, value_col, mask_col, ngs)
        rows.extend(_rows_for_stat(games, names, stat))
    rows.extend(_team_rows(plays))
    rows.sort(key=lambda row: (row["stat"], row["team"], row["gsis_id"], row["player_key"]))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHARE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    attached = sum(
        1
        for row in rows
        if row["stat"] != "team_points"
        and any(row[field] for field in (
            "ngs_avg_separation",
            "ngs_catch_percentage",
            "ngs_avg_yac_above_expectation",
            "ngs_cpoe",
        ))
    )
    players = sum(1 for row in rows if row["stat"] != "team_points")
    teams = sum(1 for row in rows if row["stat"] == "team_points")
    return {"player_rows": players, "team_rows": teams, "ngs_attached": attached, "rows": len(rows)}


def _read_pbp(pd: Any, path: Path) -> Any:
    if not path.is_file():
        raise ValueError(f"pbp file is missing: {path}")
    frame = pd.read_parquet(path, columns=_PBP_COLUMNS)
    missing = [column for column in _PBP_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"{path} missing columns: {', '.join(missing)}")
    return frame


def _player_stat_games(
    plays: Any,
    stat: str,
    id_col: str,
    name_col: str,
    value_col: str,
    mask_col: str | None,
    ngs: dict[str, dict[str, str]],
) -> tuple[dict[str, list[dict[str, float]]], dict[str, dict[str, str]]]:
    part = plays
    if mask_col == "complete_pass":
        part = part[part["complete_pass"].fillna(0) >= 1]
    keep = ["game_id", "game_date", "qtr", "posteam", id_col, name_col, value_col]
    part = part.loc[:, keep].copy()
    part = part[part[id_col].notna()]
    part[id_col] = part[id_col].astype(str)
    part = part[part[id_col].str.len() > 0]
    part = part[part[id_col] != "None"]
    part["value"] = part[value_col].fillna(0).astype(float)
    if mask_col == "complete_pass":
        part["value"] = 1.0
    part["h1_value"] = part["value"].where(part["qtr"] <= 2, 0.0)
    part["q1_value"] = part["value"].where(part["qtr"] == 1, 0.0)
    part = part.sort_values(["game_id", "game_date", name_col])
    grouped = part.groupby(["game_id", id_col], as_index=False).agg(
        full=("value", "sum"),
        h1=("h1_value", "sum"),
        q1=("q1_value", "sum"),
        pbp_name=(name_col, "last"),
        team=("posteam", "last"),
        game_date=("game_date", "max"),
    )
    floor = FLOORS[stat]
    games: dict[str, list[dict[str, float]]] = defaultdict(list)
    name_rows: dict[str, dict[str, str]] = {}
    for record in grouped.to_dict("records"):
        full = float(record["full"])
        if full < floor:
            continue
        h1 = min(float(record["h1"]), full)
        q1 = min(float(record["q1"]), full)
        gsis = str(record[id_col])
        games[gsis].append({"full": full, "h1": h1, "q1": q1})
        current = name_rows.get(gsis)
        stamp = str(record["game_date"])
        if current is not None and stamp < current.get("game_date", ""):
            continue
        info = _name_fields(str(record["pbp_name"] or ""), gsis, ngs)
        info["team"] = normalize_team(str(record["team"] or ""))
        info["game_date"] = stamp
        name_rows[gsis] = info
    return games, name_rows


def _name_fields(pbp_name: str, gsis: str, ngs: dict[str, dict[str, str]]) -> dict[str, str]:
    extra = ngs.get(gsis, {})
    full_name = extra.get("full_name", "")
    if full_name:
        initial, last = _initial_last(full_name)
        player_key = fold_name(full_name)
    else:
        initial, last = _initial_last(pbp_name)
        player_key = ""
    return {
        "player_key": player_key,
        "match_initial": initial,
        "match_last": last,
        "pbp_name": pbp_name,
        "full_name": full_name,
        "ngs_avg_separation": extra.get("ngs_avg_separation", ""),
        "ngs_catch_percentage": extra.get("ngs_catch_percentage", ""),
        "ngs_avg_yac_above_expectation": extra.get("ngs_avg_yac_above_expectation", ""),
        "ngs_cpoe": extra.get("ngs_cpoe", ""),
    }


def _team_rows(plays: Any) -> list[dict[str, str]]:
    meta = plays.groupby("game_id", as_index=False).agg(
        home=("home_team", "first"),
        away=("away_team", "first"),
        final_home=("total_home_score", "max"),
        final_away=("total_away_score", "max"),
    )
    h1 = (
        plays[plays["qtr"] <= 2]
        .groupby("game_id", as_index=False)
        .agg(h1_home=("total_home_score", "max"), h1_away=("total_away_score", "max"))
    )
    q1 = (
        plays[plays["qtr"] == 1]
        .groupby("game_id", as_index=False)
        .agg(q1_home=("total_home_score", "max"), q1_away=("total_away_score", "max"))
    )
    merged = meta.merge(h1, on="game_id", how="left").merge(q1, on="game_id", how="left")
    by_team: dict[str, list[dict[str, float]]] = defaultdict(list)
    for record in merged.to_dict("records"):
        for side in ("home", "away"):
            final = float(record[f"final_{side}"] or 0)
            if final < FLOORS["team_points"]:
                continue
            h1_value = _finite(record.get(f"h1_{side}"))
            q1_value = _finite(record.get(f"q1_{side}"))
            team = normalize_team(str(record[side] or ""))
            if not team:
                continue
            by_team[team].append(
                {"full": final, "h1": min(h1_value, final), "q1": min(q1_value, final)}
            )
    names = {
        team: {
            "player_key": team,
            "match_initial": "",
            "match_last": "",
            "pbp_name": team,
            "full_name": team,
            "team": team,
        }
        for team in by_team
    }
    return _rows_for_stat(by_team, names, "team_points")


def _load_ngs(pd: Any, rec_paths: list[Path], pass_paths: list[Path]) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    rec_fields = {
        "avg_separation": "ngs_avg_separation",
        "catch_percentage": "ngs_catch_percentage",
        "avg_yac_above_expectation": "ngs_avg_yac_above_expectation",
    }
    _merge_ngs(pd, rec_paths, rec_fields, found)
    _merge_ngs(
        pd,
        pass_paths,
        {"completion_percentage_above_expectation": "ngs_cpoe"},
        found,
    )
    return found


def _merge_ngs(
    pd: Any,
    paths: list[Path],
    fields: dict[str, str],
    found: dict[str, dict[str, str]],
) -> None:
    frames = []
    for path in paths:
        if not path.is_file():
            continue
        columns = ["season", "season_type", "week", "player_name", "player_id", *fields]
        frame = pd.read_parquet(path, columns=columns)
        frames.append(frame)
    if not frames:
        return
    data = pd.concat(frames, ignore_index=True)
    data = data[(data["season_type"].astype(str) == "REG") & (data["week"] >= 1)]
    data["season"] = data["season"].astype(int)
    data["week"] = data["week"].astype(int)
    data = data[~((data["season"] == 2026) & (data["week"] >= 6))]
    data = data[data["player_id"].notna()]
    data = data.sort_values(["player_id", "season", "week"])
    means = data.groupby("player_id", as_index=False).agg(
        player_name=("player_name", "last"),
        **{src: (src, "mean") for src in fields},
    )
    for record in means.to_dict("records"):
        gsis = str(record["player_id"])
        slot = found.setdefault(gsis, {})
        slot["full_name"] = str(record.get("player_name") or slot.get("full_name") or "")
        for src, dest in fields.items():
            value = record.get(src)
            if value is None or (isinstance(value, float) and math.isnan(value)):
                continue
            slot[dest] = _fmt(float(value))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ceminiparlays.half_edge")
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser("score", help="Score the captured lines from the share file")
    score.add_argument("--lines", type=Path, required=True)
    score.add_argument("--shares", type=Path, required=True)
    score.add_argument("--out", type=Path, required=True)
    shares = sub.add_parser("shares", help="Build the historical share table")
    shares.add_argument("--pbp", type=Path, action="append")
    shares.add_argument("--ngs-rec", type=Path, action="append")
    shares.add_argument("--ngs-pass", type=Path, action="append")
    shares.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "shares":
        summary = build_shares(
            args.pbp or list(_DEFAULT_PBP),
            args.ngs_rec or list(_DEFAULT_NGS_REC),
            args.ngs_pass or list(_DEFAULT_NGS_PASS),
            args.out,
        )
        print(
            f"rows={summary['rows']} player_rows={summary['player_rows']} "
            f"team_rows={summary['team_rows']} ngs_attached={summary['ngs_attached']}"
        )
        return 0
    scores, dropped, index = score_markets(read_csv(args.lines), read_csv(args.shares))
    write_scores(args.out, scores)
    print(format_report(scores, dropped, index), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
