"""Locked math for the matchup gate.

V1 (2026-10-17) priced quarter yards with a normal. That price had no mass
at 0. V2 replaces it. The v2 rules below were fixed before the v2 score.
Do not refit k, the clips, the floors, or the Brier rule after the table.

V2 quarter receiving yards, quarter rushing yards, and quarter passing
yards use a compound Poisson-gamma hurdle. A reception count uses Poisson.
A 0.5 line is ``(1 - exp(-lambda)) * p_gain``. It is not a normal tail.

V3 (locked before the v3 table) builds that lambda from three factors.
Full-game volume is not shrunk toward a starter mean. The quarter share
is the only Empirical Bayes term. A defense multiplier is clipped.

A feature row is legal for target week W only when its ``(season, week)``
is strictly earlier than ``(target_season, W)``. Week W never prices week W.

The scored cells, the clip, and the side rule:

* Hurdle cells price ``P(Y > L)`` and take the over only when that
  probability beats the vig-stripped over. They never take the higher EV.
* A 0.5 line uses ``(1 - exp(-lambda)) * p_gain``. A higher line sums the
  Poisson-gamma series through k = 12.
* V3 lambda is ``full_game_volume * quarter_share * defense_multiplier``.
  The share uses k = 15 plays and a 0.25 prior. Volume with 3 or more
  games stays unshrunk. Fewer than 3 games can move down toward 1.2
  catches per game and cannot move up. The defense factor stays inside
  0.80 to 1.25. The old k = 12 level shrink is not the quarter volume.
* Gaussian cells that remain (kicking points, Q3 total) use
  ``sign(mean - line)``. Sigma floors match the half-gate:
  yards ``max(8, 0.25 * line)``, counts ``max(0.6, 0.25 * line)``,
  points ``max(3.5, 0.25 * line)``.
* Tail and Poisson cells take the over only when ``p_model`` is above the
  vig-stripped over probability. They never take the side with the higher EV.
* ``adj = clip(player_z * def_z / 4, -clip, clip)``. Yards, tails, kicking,
  and the Q3 total use 0.15. Attempts, completions, and interceptions use 0.10.
* ``mean = shrunk_base * (1 + adj)``. Shrink uses k = 8. A player or team
  with fewer than 4 prior games is dropped. A missing counterpart feature
  drops the leg. There is no univariate fallback.
* Poisson lines must be half-points. ``P(X > line) = 1 - cdf(floor(line))``.
* A longest-play probability is ``1 - F(line) ** n`` on a Weibull with
  location 0. ``n`` is the shrunk mean touches. Fewer than 30 positive
  prior plays skips the fit.
* Live floors: multi-player markets need 35 legs, single-starter markets
  need 16, and game markets need 10. A short cell fails ``cardinality``.
* The live Benjamini-Hochberg family is only the cells that meet the floor.
* One-sided bootstrap p is ``(1 + #{boot mean <= 0}) / (n_boot + 1)``.
* A live pass also needs mean EV ``> 0``, CI low ``> 0``, and ``q <= 0.10``.
* A historical pass needs at least 250 settled player-games, a Brier skill
  above 0, a bootstrap CI low above 0, and ``q <= 0.10``.
* Promotion needs both passes. A missing history fails ``no_hist``.
* ``spread_q3`` is captured and not scored (``spread_sign_not_locked``).

This module does not import ``jev_client``. Jev does not price a leg.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from ceminiparlays.half_edge import shrink_share
from ceminiparlays.odds import american_to_decimal, devig_two_way

SHRINK_K = 8.0
EB_K = 12.0
# V3 quarter-share shrinkage. These are not refit after the v3 table.
SHARE_K = 15.0
SHARE_W0 = 0.25
BACKUP_GAMES = 3.0
BACKUP_MU = 1.2
DEF_MULT_LO = 0.80
DEF_MULT_HI = 1.25
# Referee crew z is applied on the live slate only. The weight is locked.
REF_Z_WEIGHT = 0.02
REF_MULT_LO = 0.95
REF_MULT_HI = 1.05
MIN_GAMES = 4
MIN_PLAYS = 30
MIN_LEGS = 40
MIN_HIST = 250
N_BOOT = 2000
Z_CLIP = 2.0
YARD_SIGMA_FLOOR = 8.0
COUNT_SIGMA_FLOOR = 0.6
POINT_SIGMA_FLOOR = 3.5
YPC_SD_FLOOR = 4.0
HURDLE_K_MAX = 12
FDR_Q = 0.10
PRINT_EV = 0.02
WARN_EV = 0.45
TARGET_SEASON = 2026
TARGET_WEEK = 6
HIST_VIG = (-114, -114)
# Derivative line versus the full-game anchor. The shares are locked.
ANCHOR = {
    "rec_yds_q3": ("rec_yds", 0.25),
    "rec_yds_q4": ("rec_yds", 0.25),
    "rec_longest": ("rec_yds", 0.20),
    "rush_longest": ("rush_yds", 0.20),
    "pass_completions": ("pass_yds", 1.0 / 12.0),
    "total_q3": ("total", 0.25),
}
LAG_YARDS = 2.0
LAG_IMPLIED = 0.04
LAG_ELASTIC_SHARE = 0.35

MULTI_MARKETS = frozenset({"rec_yds_q3", "rec_yds_q4", "receptions_q4", "rec_longest"})
STARTER_MARKETS = frozenset(
    {
        "pass_attempts",
        "pass_completions",
        "pass_longest",
        "pass_yds_q4",
        "interceptions",
        "rush_longest",
        "rush_yds_q4",
    }
)
GAME_LEVEL_MARKETS = frozenset({"total_q3", "spreads_q3", "spreads_q4"})
HURDLE_MARKETS = frozenset({"rec_yds_q3", "rec_yds_q4", "rush_yds_q4", "pass_yds_q4"})
# 0.5 hurdle lines are for zero-inflated player props. Game totals and
# longest-play markets use the point-in-time median only.
HURDLE_LINE_MARKETS = frozenset(
    {
        "rec_yds_q3",
        "rec_yds_q4",
        "rush_yds_q4",
        "pass_yds_q4",
        "receptions_q4",
        "interceptions",
        "field_goals",
    }
)

# Index order is the bootstrap seed order. Do not sort or insert a cell later.
CELLS: tuple[tuple[str, str, str, float], ...] = (
    ("rec_yds_q3", "q3_script", "hurdle", 0.15),
    ("rec_yds_q4", "q4_separation", "hurdle", 0.15),
    ("receptions_q4", "q4_separation", "poisson", 0.15),
    ("rush_yds_q4", "q4_rush", "hurdle", 0.15),
    ("pass_yds_q4", "q4_qb", "hurdle", 0.15),
    ("rec_longest", "tail_rec", "tail", 0.15),
    ("rush_longest", "tail_rush", "tail", 0.15),
    ("pass_longest", "tail_pass", "tail", 0.15),
    ("pass_attempts", "funnel_volume", "poisson", 0.10),
    ("pass_completions", "funnel_volume", "poisson", 0.10),
    ("interceptions", "funnel_int", "poisson", 0.10),
    ("field_goals", "rz_stall", "poisson", 0.15),
    ("kicking_points", "rz_stall", "gaussian", 0.15),
    ("total_q3", "q3_script_game", "gaussian", 0.15),
)
COUNT_MARKETS = frozenset(
    {
        "receptions_q4",
        "pass_attempts",
        "pass_completions",
        "interceptions",
        "field_goals",
    }
)
CELL_SEED = {market: 20261017 + index for index, (market, *_rest) in enumerate(CELLS)}


def prior_to(season: int, week: int, target_season: int, target_week: int) -> bool:
    """True when this week is strictly before the target week."""

    return (int(season), int(week)) < (int(target_season), int(target_week))


def interaction(player_z: float, def_z: float, clip: float) -> float:
    """Locked product. The clip is 0.15 or 0.10. It is not fit."""

    raw = float(player_z) * float(def_z) / 4.0
    if raw > clip:
        return float(clip)
    if raw < -clip:
        return float(-clip)
    return raw


def z_score(value: float, league: float, scale: float, clip: float = Z_CLIP) -> float:
    """Clip a shrunk gap. ``scale`` must be positive."""

    if scale <= 0:
        raise ValueError("scale must be positive")
    raw = (float(value) - float(league)) / float(scale)
    if raw > clip:
        return float(clip)
    if raw < -clip:
        return float(-clip)
    return raw


def maxima_over_prob(single_cdf: float, n_touches: float) -> float:
    """``P(max of n i.i.d. plays > line) = 1 - F(line) ** n``."""

    cdf = float(single_cdf)
    touches = float(n_touches)
    if cdf < 0.0 or cdf > 1.0:
        raise ValueError("cdf must be in 0 to 1")
    if touches < 0.0:
        raise ValueError("touches must be >= 0")
    if touches == 0.0:
        return 0.0
    return 1.0 - cdf**touches


def weibull_fit(yards: list[float]) -> tuple[float, float] | None:
    """Fit shape and scale at location 0. ``None`` below 30 positive plays."""

    sample = [float(yard) for yard in yards if math.isfinite(float(yard)) and float(yard) > 0.0]
    if len(sample) < MIN_PLAYS:
        return None
    from scipy.stats import weibull_min

    try:
        shape, _loc, scale = weibull_min.fit(sample, floc=0)
    except (ValueError, FloatingPointError):
        return None
    if not math.isfinite(shape) or not math.isfinite(scale):
        return None
    if shape <= 0.0 or scale <= 0.0:
        return None
    return float(shape), float(scale)


def weibull_max_over_prob(yards: list[float], line: float, n_touches: float) -> float | None:
    """Fit a Weibull at location 0. ``None`` when the sample is too small."""

    fitted = weibull_fit(yards)
    if fitted is None or n_touches <= 0:
        return None
    shape, scale = fitted
    return tail_over_prob(shape, scale, line, n_touches, 0.0)


def tail_over_prob(
    shape: float, scale: float, line: float, n_touches: float, adj: float
) -> float | None:
    """``P(max > line)`` after the locked scale adjustment ``scale * (1 + adj)``."""

    adj_scale = float(scale) * (1.0 + float(adj))
    if shape <= 0.0 or adj_scale <= 0.0 or n_touches <= 0.0:
        return None
    from scipy.stats import weibull_min

    cdf = float(weibull_min.cdf(line, shape, loc=0.0, scale=adj_scale))
    if not math.isfinite(cdf):
        return None
    cdf = min(1.0, max(0.0, cdf))
    return maxima_over_prob(cdf, n_touches)


def poisson_over_prob(mean: float, line: float) -> float:
    """``P(X > line)`` for a half-point line. An integer line is a void."""

    if mean <= 0:
        raise ValueError("mean must be positive")
    if abs(line - round(line)) < 1e-9:
        raise ValueError("poisson line must be a half point")
    from scipy.stats import poisson

    return float(1.0 - poisson.cdf(math.floor(line), mean))


def fair_over_prob(odds_over: int, odds_under: int) -> float:
    """Vig-stripped over probability. The house method is power de-vig."""

    return float(devig_two_way(int(odds_over), int(odds_under)).p_over)


def leg_ev(p_side: float, american: int) -> float:
    """``p * decimal - 1``. De-vig is not the payout."""

    return float(p_side) * american_to_decimal(int(american)) - 1.0


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        raise ValueError("percentile of an empty sample")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * (pct / 100.0)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    weight = rank - low
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * weight


def bootstrap_means(values: list[float], rng: random.Random, n_boot: int = N_BOOT) -> list[float]:
    """Return ``n_boot`` resampled means. The caller owns ``rng``.

    The index order is ``randrange`` once per draw. A wide sample uses the
    same calls and the same means, summed in NumPy.
    """

    width = len(values)
    if width == 0:
        raise ValueError("bootstrap of an empty sample")
    if n_boot < 1:
        raise ValueError("n_boot must be positive")
    if width == 1:
        return [float(values[0])] * n_boot
    import numpy as np

    arr = np.asarray(values, dtype=np.float64)
    idx = np.empty(n_boot * width, dtype=np.int32)
    for i in range(idx.size):
        idx[i] = rng.randrange(width)
    means = arr[idx].reshape(n_boot, width).mean(axis=1)
    return [float(value) for value in means]


def bootstrap_ci(values: list[float], rng: random.Random, n_boot: int = N_BOOT) -> tuple[float, float]:
    """Equal-tailed 95 percent CI of the mean. Percentile is linear."""

    draws = bootstrap_means(values, rng, n_boot)
    draws.sort()
    return _percentile(draws, 2.5), _percentile(draws, 97.5)


def one_sided_p(values: list[float], rng: random.Random, n_boot: int = N_BOOT) -> float:
    """``(1 + #{boot mean <= 0}) / (n_boot + 1)``."""

    draws = bootstrap_means(values, rng, n_boot)
    hits = sum(1 for draw in draws if draw <= 0.0)
    return (1.0 + hits) / (n_boot + 1.0)


def bh_qvalues(p_values: list[float]) -> list[float]:
    """Benjamini-Hochberg q-values. Order matches ``p_values``."""

    count = len(p_values)
    if count == 0:
        return []
    order = sorted(range(count), key=lambda index: (p_values[index], index))
    raw = [0.0] * count
    for rank, index in enumerate(order, start=1):
        raw[index] = p_values[index] * count / rank
    # Monotone from the largest rank back toward the smallest.
    running = 1.0
    adjusted = [0.0] * count
    for index in reversed(order):
        running = min(running, raw[index])
        adjusted[index] = min(1.0, running)
    return adjusted


def sigma_floor(kind: str, line: float) -> float:
    """The locked floor. ``kind`` is ``yards``, ``count``, or ``points``."""

    scale = 0.25 * abs(float(line))
    if kind == "yards":
        return max(YARD_SIGMA_FLOOR, scale)
    if kind == "count":
        return max(COUNT_SIGMA_FLOOR, scale)
    if kind == "points":
        return max(POINT_SIGMA_FLOOR, scale)
    raise ValueError(f"unknown sigma kind: {kind}")


def shrunk(n: int, raw: float, league: float) -> float:
    return shrink_share(n, raw, league, SHRINK_K)


def slate_floor(market: str) -> int:
    """Live-slate minimum. A quarterback market cannot reach 40 legs."""

    if market in MULTI_MARKETS:
        return 35
    if market in STARTER_MARKETS:
        return 16
    if market in GAME_LEVEL_MARKETS:
        return 10
    return MIN_LEGS


def eb_mean(n_opp: float, raw: float, league: float, k: float = EB_K) -> float:
    """Empirical Bayes mean. ``k`` is an opportunity weight, not a fitted one."""

    n_value = max(0.0, float(n_opp))
    weight = float(k)
    if weight < 0:
        raise ValueError("k must be >= 0")
    return (n_value * float(raw) + weight * float(league)) / (n_value + weight)


def baseline_volume(n_games: float, trailing: float) -> float | None:
    """Unshrunk full-game rate. A short sample can move down, never up.

    Three or more games return the trailing mean. One or two games blend
    toward 1.2 and then keep the lower of that blend and the trailing mean.
    A non-positive game count has no volume.
    """

    try:
        games = float(n_games)
        raw = float(trailing)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(games) or not math.isfinite(raw) or games <= 0.0:
        return None
    raw = max(0.0, raw)
    if games >= BACKUP_GAMES:
        return raw
    blended = (games * raw + (BACKUP_GAMES - games) * BACKUP_MU) / BACKUP_GAMES
    return min(raw, max(0.0, blended))


def quarter_share(opps_q: float, opps_total: float) -> float:
    """Share of a player's own plays that fall in one quarter.

    The prior is 0.25 with weight 15. Quarter plays cannot exceed the
    player's total, so a bad extract cannot push the share above the prior
    formula's natural cap.
    """

    quarter = max(0.0, float(opps_q))
    total = max(quarter, float(opps_total))
    return (quarter + SHARE_K * SHARE_W0) / (total + SHARE_K)


def defense_multiplier(def_rate: float | None, league_rate: float | None, *, epa: bool = False) -> float:
    """Map a defense rate to ``[0.80, 1.25]``. Missing inputs stay at 1.

    A higher allowed rate raises the multiplier. EPA uses a difference
    because an EPA rate can be negative. Other rates use a ratio.
    """

    if def_rate is None or league_rate is None:
        return 1.0
    try:
        defense = float(def_rate)
        league = float(league_rate)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(defense) or not math.isfinite(league):
        return 1.0
    if epa:
        raw = 1.0 + (defense - league)
    elif league <= 0.0 or defense <= 0.0:
        return 1.0
    else:
        raw = defense / league
    return min(DEF_MULT_HI, max(DEF_MULT_LO, raw))


def referee_multiplier(dpi_z: float | None, holding_z: float | None) -> float:
    """Small live crew factor. A missing z leaves the multiplier at 1."""

    if dpi_z is None or holding_z is None:
        return 1.0
    try:
        total = float(dpi_z) + float(holding_z)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(total):
        return 1.0
    raw = 1.0 + REF_Z_WEIGHT * total
    return min(REF_MULT_HI, max(REF_MULT_LO, raw))


def split_lambda(volume: float, opps_q: float, opps_total: float, defense: float, crew: float = 1.0) -> float:
    """``volume * quarter share * defense * crew``. Volume is not shrunk up."""

    return max(0.0, float(volume)) * quarter_share(opps_q, opps_total) * float(defense) * float(crew)


def implied_count_mean(line: float, p_over: float) -> float | None:
    """Poisson mean whose over probability matches a vig-stripped price."""

    try:
        posted = float(line)
        target = float(p_over)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(posted) or not math.isfinite(target):
        return None
    if abs(posted - round(posted)) < 1e-9:
        return None
    target = min(1.0 - 1e-6, max(1e-6, target))
    lo = 1e-4
    hi = max(80.0, abs(posted) * 4.0)
    if poisson_over_prob(hi, posted) < target:
        return hi
    for _step in range(60):
        mid = 0.5 * (lo + hi)
        if poisson_over_prob(mid, posted) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def implied_yards_mean(line: float, p_over: float, sd: float) -> float | None:
    """Normal mean for one vig-stripped over probability and a known sd."""

    try:
        posted = float(line)
        target = float(p_over)
        sigma = float(sd)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(posted) or not math.isfinite(target) or not math.isfinite(sigma):
        return None
    if sigma <= 0.0:
        return None
    target = min(1.0 - 1e-4, max(1e-4, target))
    from scipy.stats import norm

    return posted + sigma * float(norm.ppf(target))


def gamma_shape_rate(mean: float, sd: float) -> tuple[float, float]:
    """Shape and rate. The sd floor is 4 yards. It is not fit."""

    mu = max(float(mean), 0.5)
    sigma = max(float(sd), YPC_SD_FLOOR)
    var = sigma * sigma
    return (mu * mu) / var, mu / var


def hurdle_over_prob(
    lam: float,
    alpha: float,
    rate: float,
    line: float,
    p_gain: float = 1.0,
    k_max: int = HURDLE_K_MAX,
) -> float:
    """``P(Y > line)`` for a compound Poisson-gamma hurdle.

    ``K ~ Poisson(lam)``. ``Y | K=k ~ Gamma(shape=k*alpha, rate=rate)``.
    A line of 0.5 uses ``(1 - exp(-lam)) * p_gain``. ``p_gain`` is the
    share of events with at least 1 yard. The series stops at ``k_max``.
    """

    if lam < 0.0 or alpha <= 0.0 or rate <= 0.0:
        raise ValueError("hurdle inputs must be positive")
    gain = min(1.0, max(0.0, float(p_gain)))
    if lam == 0.0:
        return 0.0
    if float(line) <= 0.5:
        return (1.0 - math.exp(-float(lam))) * gain
    from scipy.stats import gamma, poisson

    total = 0.0
    for k in range(1, int(k_max) + 1):
        pk = float(poisson.pmf(k, lam))
        if pk <= 0.0:
            continue
        cdf = float(gamma.cdf(line, a=k * alpha, scale=1.0 / rate))
        if not math.isfinite(cdf):
            continue
        total += pk * (1.0 - min(1.0, max(0.0, cdf)))
    if not math.isfinite(total):
        return 0.0
    return min(1.0, max(0.0, total))


@dataclass(frozen=True)
class CellSpec:
    market: str
    signal: str
    family: str
    clip: float

    @property
    def seed(self) -> int:
        return CELL_SEED[self.market]


def cell_specs() -> tuple[CellSpec, ...]:
    return tuple(CellSpec(market, signal, family, clip) for market, signal, family, clip in CELLS)


def half_line_share(lines: list[float]) -> float:
    if not lines:
        return 0.0
    return sum(1 for line in lines if line <= 0.5) / len(lines)


def verdict_for(
    *,
    n_legs: int,
    mean_ev: float,
    ci_low: float,
    q_value: float | None,
    market: str,
    one_leg_ci_low: float | None = None,
    half_share: float = 0.0,
) -> tuple[str, str]:
    """Live slate rule. History is a second key. See ``combine_verdict``."""

    del one_leg_ci_low, half_share
    if n_legs < slate_floor(market):
        return "fail", "cardinality"
    if mean_ev <= 0.0:
        return "fail", "nonpositive_mean"
    if ci_low <= 0.0:
        return "fail", "ci_covers_zero"
    if q_value is None or q_value > FDR_Q:
        return "fail", "fdr"
    return "pass", "live_pass"


def hist_verdict(
    *,
    n_hist: int,
    delta_brier: float,
    ci_low: float,
    q_value: float | None,
) -> tuple[str, str]:
    """Settled-outcome rule. Skill must beat a 50/50 de-vigged benchmark."""

    if n_hist < MIN_HIST:
        return "fail", "too_few_hist"
    if delta_brier <= 0.0:
        return "fail", "no_brier_skill"
    if ci_low <= 0.0:
        return "fail", "hist_ci"
    if q_value is None or q_value > FDR_Q:
        return "fail", "hist_fdr"
    return "pass", "hist_pass"


def combine_verdict(
    live: tuple[str, str],
    hist: tuple[str, str] | None,
) -> tuple[str, str]:
    """Both keys must pass. A missing history fails closed."""

    if hist is None:
        return "fail", "no_hist"
    if hist[0] != "pass":
        return "fail", hist[1]
    if live[0] != "pass":
        return "fail", live[1]
    return "pass", "pass"
