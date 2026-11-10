"""Q4 running-back checkdown funnel.

A book often prices a quarter catch as a flat slice of the full-game catch
total. This module prices the quarter with the locked v3 compound
Poisson-gamma hurdle. Lambda is full-game receptions, plus vacated targets,
times the shrunk quarter share, the Q4 trailing-target factor, the cushion
factor, and the defense completion and YAC factor.

The module does not read a board and does not place a bet.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ceminiparlays.matchup_math import (
    YPC_SD_FLOOR,
    baseline_volume,
    defense_multiplier,
    fair_over_prob,
    gamma_shape_rate,
    hurdle_over_prob,
    leg_ev,
    poisson_over_prob,
    quarter_share,
)

CHECKDOWN_MARKETS = frozenset({"receptions_q4", "rec_yds_q4", "rec_yds_q3"})
YARDS_MARKETS = frozenset({"rec_yds_q4", "rec_yds_q3"})
#: Q4 rush script. Negative spread means the back's team is favored.
_COMPETITIVE_LEAD = 1.08
_NEUTRAL_SCRIPT = 1.00
_BENCH_HAIRCUT = 0.68


def q4_rush_script_multiplier(
    spread: float | None,
    is_starter_rb: bool = True,
) -> float | None:
    """Scale a starter's Q4 rush mean for the game script.

    ``COMPETITIVE_LEAD`` (``-7.5 <= spread <= -2.5``) returns ``1.08``.
    The back stays on the field to kill the clock in a one- or two-score lead.
    ``NEUTRAL_OR_SLIGHT_DOG`` (``-2.5 < spread <= 4.5``) returns ``1.00``.
    ``BENCH_BLOWOUT_RISK`` (``spread <= -8.0``) returns ``0.68`` for a starter
    RB1. That haircut is the benching prior. The over is still blocked from
    Tier 1 and from anchor selection. Use the full-game ``rush_yds`` over.
    ``TRAIL_BLOWOUT`` (``spread > 4.5``) returns ``None``. The trailing team
    leaves the run, so the Q4 rush over is not priced.
    A missing spread returns ``None`` and the caller leaves the mean alone.
    """

    if spread is None:
        return None
    try:
        number = float(spread)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if number <= -8.0:
        return _BENCH_HAIRCUT if is_starter_rb else _NEUTRAL_SCRIPT
    if number > 4.5:
        return None
    if -7.5 <= number <= -2.5:
        return _COMPETITIVE_LEAD
    if -2.5 < number <= 4.5:
        return _NEUTRAL_SCRIPT
    return _NEUTRAL_SCRIPT


def q4_rush_over_blocked(spread: float | None, is_starter_rb: bool = True) -> bool:
    """True when an RB ``rush_yds_q4`` over is off the anchor card.

    A starter RB1 at ``spread <= -8`` is a bench-blowout. Any RB at
    ``spread > 4.5`` is a trail-blowout. Both miss the Q4 rush over.
    """

    if spread is None:
        return False
    try:
        number = float(spread)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(number):
        return False
    if number <= -8.0 and is_starter_rb:
        return True
    return number > 4.5


@dataclass(frozen=True)
class CheckdownInputs:
    """One back, one quarter, and the defense he faces.

    ``avg_cushion`` is the back's own NGS cushion when that cell exists.
    Running backs in the week-7 cache have no cushion, so the caller passes
    the opposing defense's allowed cushion instead. A missing cushion leaves
    the factor at 1. ``opps_q`` and ``opps_total`` are target counts. Both
    zero uses the 0.25 quarter prior inside ``quarter_share``.
    """

    games: float
    receptions_per_game: float
    rec_yds_per_game: float
    targets_per_game: float
    opps_q: float
    opps_total: float
    q4_trail_target_share: float | None
    vacated_target_boost: float
    avg_cushion: float | None
    def_q4_comp_rate: float | None
    def_q4_yac: float | None
    league_trail_share: float
    league_cushion: float | None
    league_comp: float | None
    league_yac: float | None
    quarter: int
    ypc_sd: float = YPC_SD_FLOOR
    p_gain: float = 1.0
    #: Team spread. Negative means the back's team is favored.
    spread: float | None = None
    #: Game total. Used with a near-pick'em spread for the high-total window.
    game_total: float | None = None
    #: Share of the team's RB third-down and two-minute routes. ``None`` leaves
    #: the route gate on ``q4_trail_target_share > 0``.
    third_down_route_share: float | None = None
    #: When true, a missing spread drops a script-dependent Q4 price.
    require_script: bool = False


@dataclass(frozen=True)
class CheckdownLambda:
    lam: float
    volume: float
    vacated_receptions: float
    w_q_eb: float
    trail_factor: float
    cushion_factor: float
    defense_factor: float


@dataclass(frozen=True)
class CheckdownPrice:
    market: str
    side: str
    line: float
    price: int
    lam: float
    model_p: float
    fair_p: float
    ev: float
    detail: CheckdownLambda


def vacated_receptions(boost: float, targets_per_game: float, receptions_per_game: float) -> float:
    """Turn extra targets per game into receptions with the back's catch rate."""

    try:
        extra = float(boost)
        targets = float(targets_per_game)
        catches = float(receptions_per_game)
    except (TypeError, ValueError):
        return 0.0
    if extra <= 0.0 or targets <= 0.0 or catches <= 0.0:
        return 0.0
    if not math.isfinite(extra) or not math.isfinite(targets) or not math.isfinite(catches):
        return 0.0
    return extra * min(1.0, catches / targets)


def _trail_factor(quarter: int, share: float | None, league: float) -> float:
    """Q4 trailing-target share versus the RB league share. Q3 stays at 1."""

    if quarter != 4 or share is None:
        return 1.0
    try:
        league_share = float(league)
        player_share = float(share)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(player_share) or not math.isfinite(league_share) or league_share <= 0.0:
        return 1.0
    return defense_multiplier(player_share, league_share)


def _cushion_factor(cushion: float | None, league: float | None) -> float:
    """A tighter cushion raises the checkdown rate. Missing inputs stay at 1."""

    if cushion is None or league is None:
        return 1.0
    try:
        player = float(cushion)
        league_cushion = float(league)
    except (TypeError, ValueError):
        return 1.0
    if (
        not math.isfinite(player)
        or not math.isfinite(league_cushion)
        or player <= 0.0
        or league_cushion <= 0.0
    ):
        return 1.0
    return defense_multiplier(league_cushion, player)


def _defense_factor(
    comp: float | None,
    yac: float | None,
    league_comp: float | None,
    league_yac: float | None,
) -> float:
    """Geometric mean of the completion factor and the YAC factor."""

    parts: list[float] = []
    if comp is not None and league_comp is not None:
        parts.append(defense_multiplier(comp, league_comp))
    if yac is not None and league_yac is not None:
        parts.append(defense_multiplier(yac, league_yac))
    if not parts:
        return 1.0
    if len(parts) == 1:
        return parts[0]
    return math.sqrt(parts[0] * parts[1])


def checkdown_lambda(inputs: CheckdownInputs) -> CheckdownLambda | None:
    """V3 volume times the four checkdown factors. ``None`` when volume is absent."""

    if inputs.quarter not in {3, 4}:
        raise ValueError("quarter must be 3 or 4")
    base = baseline_volume(inputs.games, inputs.receptions_per_game)
    if base is None:
        return None
    extra = vacated_receptions(
        inputs.vacated_target_boost,
        inputs.targets_per_game,
        inputs.receptions_per_game,
    )
    volume = base + extra
    if volume <= 0.0:
        return None
    share = quarter_share(inputs.opps_q, inputs.opps_total)
    trail = _trail_factor(inputs.quarter, inputs.q4_trail_target_share, inputs.league_trail_share)
    cushion = _cushion_factor(inputs.avg_cushion, inputs.league_cushion)
    defense = _defense_factor(
        inputs.def_q4_comp_rate,
        inputs.def_q4_yac,
        inputs.league_comp,
        inputs.league_yac,
    )
    lam = volume * share * trail * cushion * defense
    if inputs.spread is not None and inputs.spread <= -6.5:
        # A heavy favorite benches the starter or salts the clock in Q4.
        lam *= 0.70
    if lam <= 0.0 or not math.isfinite(lam):
        return None
    return CheckdownLambda(
        lam=lam,
        volume=volume,
        vacated_receptions=extra,
        w_q_eb=share,
        trail_factor=trail,
        cushion_factor=cushion,
        defense_factor=defense,
    )


def _competitive_script(spread: float, game_total: float | None) -> bool:
    """True when Q4 is projected competitive or the team is trailing.

    ``spread >= -4.5`` is the competitive/trailing window. A spread from
    ``-6.0`` through ``+10.0`` also qualifies when the game total is at
    least 45.5.
    """

    if spread >= -4.5:
        return True
    if -6.0 <= spread <= 10.0 and game_total is not None and game_total >= 45.5:
        return True
    return False


def _trail_blowout_volume_ok(inputs: CheckdownInputs) -> bool:
    """A trailing RB2 with a thin target rate does not keep the two-minute drill.

    ``spread >= 6.5`` is the trail-blowout window. The over then needs
    ``games >= 4`` and either ``targets_per_game >= 3`` or a third-down
    route share of at least half. A closer spread does not use this gate.
    """

    if inputs.spread is None:
        return True
    try:
        spread = float(inputs.spread)
        games = float(inputs.games)
        targets = float(inputs.targets_per_game)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(spread) or spread < 6.5:
        return True
    if not math.isfinite(games) or games < 4.0:
        return False
    target_ok = math.isfinite(targets) and targets >= 3.0
    route_ok = False
    if inputs.third_down_route_share is not None:
        try:
            held = float(inputs.third_down_route_share)
        except (TypeError, ValueError):
            held = float("nan")
        route_ok = math.isfinite(held) and held >= 0.50
    return target_ok or route_ok


def _route_share_ok(inputs: CheckdownInputs) -> bool:
    """The back keeps the two-minute routes.

    ``q4_trail_target_share > 0`` is required. A typed third-down route
    share must be at least half of the team's RB routes. A trail-blowout
    also requires a real target rate or that route share.
    """

    share = inputs.q4_trail_target_share
    try:
        trail = float(share) if share is not None else None
    except (TypeError, ValueError):
        return False
    if trail is None or not math.isfinite(trail) or trail <= 0.0:
        return False
    if not _trail_blowout_volume_ok(inputs):
        return False
    route = inputs.third_down_route_share
    if route is None:
        return True
    try:
        held = float(route)
    except (TypeError, ValueError):
        return False
    return math.isfinite(held) and held >= 0.50


def _block_trail_yards_over(inputs: CheckdownInputs, market: str, side: str) -> bool:
    """Drop a trail-blowout receiving-yards over when YAC is thin.

    Catches behind the line still cash ``receptions_q4`` over 0.5. They do
    not cash a yard line. The yards over needs ``def_q4_yac`` at or above
    the league YAC. A missing rate fails closed.
    """

    if market != "rec_yds_q4" or side != "over" or inputs.spread is None:
        return False
    try:
        spread = float(inputs.spread)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(spread) or spread < 6.5:
        return False
    if inputs.def_q4_yac is None or inputs.league_yac is None:
        return True
    try:
        return float(inputs.def_q4_yac) < float(inputs.league_yac)
    except (TypeError, ValueError):
        return True


def _under_script_ok(inputs: CheckdownInputs) -> bool:
    """Early-down grinder, or a heavy favorite who can run the clock out."""

    route = inputs.third_down_route_share
    if route is not None:
        try:
            if float(route) < 0.50:
                return True
        except (TypeError, ValueError):
            return False
    share = inputs.q4_trail_target_share
    if share is not None:
        try:
            if float(share) <= 0.0:
                return True
        except (TypeError, ValueError):
            return False
    if inputs.spread is not None and inputs.spread <= -5.5:
        return True
    return False


def _script_blocks(inputs: CheckdownInputs, market: str, side: str, line: float) -> bool:
    """True when a Q4 RB side fails the game-script gate."""

    if market not in {"receptions_q4", "rec_yds_q4"} or inputs.quarter != 4:
        return False
    if side == "over":
        if inputs.spread is None:
            return bool(inputs.require_script)
        if not _competitive_script(float(inputs.spread), inputs.game_total):
            return True
        return not _route_share_ok(inputs)
    if market == "receptions_q4" and abs(float(line) - 0.5) <= 1e-9 and side == "under":
        if inputs.spread is None and inputs.third_down_route_share is None and inputs.q4_trail_target_share is None:
            return bool(inputs.require_script)
        if inputs.require_script and inputs.spread is None and not _under_script_ok(inputs):
            return True
        if inputs.spread is None and inputs.third_down_route_share is None:
            return False
        return not _under_script_ok(inputs)
    return False


def price_checkdown(
    inputs: CheckdownInputs,
    market: str,
    line: float,
    book_over: int,
    book_under: int,
) -> CheckdownPrice | None:
    """Price one posted line. The side is the v3 rule, not the higher EV."""

    if market not in CHECKDOWN_MARKETS:
        raise ValueError(f"unsupported checkdown market: {market}")
    if market in YARDS_MARKETS and inputs.quarter != int(market[-1]):
        raise ValueError("yards market quarter does not match the inputs")
    if market == "receptions_q4" and inputs.quarter != 4:
        raise ValueError("receptions_q4 requires quarter 4")
    built = checkdown_lambda(inputs)
    if built is None:
        return None
    posted = float(line)
    fair = fair_over_prob(int(book_over), int(book_under))
    if market == "receptions_q4":
        try:
            p_over = poisson_over_prob(built.lam, posted)
        except ValueError:
            return None
    else:
        catches = float(inputs.receptions_per_game)
        yards = float(inputs.rec_yds_per_game)
        if catches <= 0.0 or yards <= 0.0:
            return None
        ypc = yards / catches
        if ypc <= 0.0:
            return None
        alpha, rate = gamma_shape_rate(ypc, inputs.ypc_sd)
        gain = min(1.0, max(0.0, float(inputs.p_gain)))
        try:
            p_over = hurdle_over_prob(built.lam, alpha, rate, posted, gain)
        except ValueError:
            return None
    if abs(p_over - fair) <= 1e-12:
        return None
    if p_over > fair:
        side, prob, price = "over", p_over, int(book_over)
    else:
        side, prob, price = "under", 1.0 - p_over, int(book_under)
    if _script_blocks(inputs, market, side, posted):
        return None
    if _block_trail_yards_over(inputs, market, side):
        return None
    return CheckdownPrice(
        market=market,
        side=side,
        line=posted,
        price=price,
        lam=built.lam,
        model_p=prob,
        fair_p=fair if side == "over" else 1.0 - fair,
        ev=leg_ev(prob, price),
        detail=built,
    )
