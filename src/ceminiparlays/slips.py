from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import combinations
from math import comb, isnan
from pathlib import Path

import numpy as np

from ceminiparlays.copula import exact_joint, nearest_correlation, simulate_slip
from ceminiparlays.correlation import (
    LegRef,
    UnmodeledCorrelationError,
    correlation_matrix,
    load_priors,
)
from ceminiparlays.delta_rho import perturb_matrix
from ceminiparlays.environment import Environment, env_for
from ceminiparlays.fair import FairResult, p_over_line, side_probability
from ceminiparlays.io import DistRow, LineRow, is_flagged, is_scratched
from ceminiparlays.kelly import slip_kelly
from ceminiparlays.markets import is_first_td, is_td_market, is_two_plus_td
from ceminiparlays.odds import (
    DevigMethod,
    american_to_decimal,
    american_to_implied,
    decimal_to_american,
    devig_two_way,
)
from ceminiparlays.payouts import (
    PICKEM_PLATFORMS,
    PREDICTION_PLATFORMS,
    SPORTSBOOK_PLATFORMS,
    display_name,
    flex_ev,
    normalize_platform,
    pickem_breakeven,
    power_ev,
    resolve_payout,
)
from ceminiparlays.roster import Roster, roster_mismatch
from ceminiparlays.weather import apply_weather_discount

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
    "no-line",
    "book-line-mismatch",
    "bad-odds",
    "wrong-team",
    "rec-line-bar",
    "no-model-marginal",
    "bad-distribution",
    "already-kicked",
    "stale-line",
}
#: Scratch is expected (a listed player is out); every other exclusion is a
#: data problem and aborts the default strict rank.
NON_FATAL_EXCLUDES = {"scratch"}
COMBO_BUDGET = 20_000
#: TD props and prediction contracts have no yard line. A blank line is legal
#: for those and shown as this dummy.
NO_LINE_DUMMY = 0.5


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
    #: Model P for the edge gate. Typed ``fair_p`` first, else the projection.
    #: ``None`` when the leg carries no model and cannot show an edge.
    model_p: float | None = None
    #: Market implied P. The de-vigged two-way book first, else the TD leg odds
    #: or a prediction contract mid. ``None`` when the leg has no market price.
    market_implied_p: float | None = None
    #: ``model_p - market_implied_p`` when both exist, else ``None``.
    prop_edge: float | None = None
    edge_source: str = ""
    #: CeminiDFS split-normal P(over), the non-circular reference fair, the two
    #: blended, and the gap between the handoff and the market in basis points.
    #: All ``None`` unless ``--dfs-pricing`` ran with a handoff.
    p_dfs_over: float | None = None
    p_market_fair: float | None = None
    p_fair_posterior: float | None = None
    disagreement_edge_bps: float | None = None


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
    #: One per leg pair, in the order the matrix was built. Empty unless a Jev
    #: regime perturbation ran. Carries rho_base / delta_rho / rho_adj.
    rho_records: list = field(default_factory=list)
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


class ModelRequiredError(Exception):
    """Raised when ``--require-model`` forbids a market-only marginal."""


def _side_probability_of(p_over: float, p_under: float, side: str) -> float:
    if side in MORE_SIDES:
        return p_over
    if side in LESS_SIDES:
        return p_under
    raise ValueError(f"unknown side: {side}")


def _distribution_prob(line: LineRow, dist: DistRow) -> FairResult:
    family = dist.family or None
    # ``two_plus_td`` is a count market: a typed count projection prices it with
    # Poisson. A normal family (typed or defaulted) is never invented for it.
    if is_two_plus_td(line.stat_type):
        family = "poisson"
    elif family not in {"lognormal", "normal", "poisson"}:
        family = None
    return p_over_line(
        line=line.line,
        median=dist.median,
        sigma=dist.sigma,
        family=family,
        stat_type=line.stat_type,
    )


def _checked_probability(value: float, label: str) -> float:
    if not 0.0 < value < 1.0:
        raise ValueError(f"{label} must be between 0 and 1, got {value}")
    return value


def _refuse_market_only(line: LineRow, require_model: bool, reason: str) -> None:
    if require_model:
        raise ModelRequiredError(f"{reason} for {line.player_key}/{line.stat_type}")


def _from_ref_book(
    line: LineRow, method: DevigMethod, require_model: bool
) -> tuple[float, str] | None:
    """An independent sharp book. Not market-only, so never refused."""

    if line.ref_book_over is None or line.ref_book_under is None:
        return None
    result = devig_two_way(line.ref_book_over, line.ref_book_under, method=method)
    return _side_probability_of(result.p_over, result.p_under, line.side), "ref_devig"


def _from_own_book(
    line: LineRow, method: DevigMethod, require_model: bool
) -> tuple[float, str] | None:
    if line.book_over is None or line.book_under is None:
        return None
    _refuse_market_only(line, require_model, "same-book marginal refused")
    result = devig_two_way(line.book_over, line.book_under, method=method)
    return _side_probability_of(result.p_over, result.p_under, line.side), "book_devig"


def _from_leg_odds(
    line: LineRow, method: DevigMethod, require_model: bool
) -> tuple[float, str] | None:
    if not is_td_market(line.stat_type) or line.leg_odds is None:
        return None
    _refuse_market_only(line, require_model, "market-only marginal refused")
    implied = american_to_implied(int(line.leg_odds))
    if line.side in LESS_SIDES:
        implied = 1.0 - implied
    elif line.side not in MORE_SIDES:
        raise ValueError(f"unknown side: {line.side}")
    return implied, "leg_odds_implied"


def _from_contract_price(
    line: LineRow, method: DevigMethod, require_model: bool
) -> tuple[float, str] | None:
    if line.contract_price is None:
        return None
    _refuse_market_only(line, require_model, "market-only marginal refused")
    implied = _checked_probability(line.contract_price, "contract_price")
    if line.side in LESS_SIDES:
        implied = 1.0 - implied
    return implied, "contract_price"


#: The market-only chain, in precedence order. Each step returns None when the
#: line carries none of its prices.
_MARKET_STEPS = (_from_ref_book, _from_own_book, _from_leg_odds, _from_contract_price)


def fair_for_line(
    line: LineRow,
    dist: DistRow | None,
    method: DevigMethod = "power",
    *,
    require_model: bool = False,
) -> tuple[float, str, FairResult | None]:
    """Resolve the leg marginal that drives the copula, EV, and Kelly.

    The marginal must be an INDEPENDENT probability, never the target book's own
    de-vig. Precedence: typed ``fair_p`` (model) → projected ``dist`` (model) →
    typed ``ref_p`` → de-vigged ``ref_book_*`` (an independent sharp book) →
    the target book's own ``book_over`` / ``book_under`` de-vig → TD ``leg_odds``
    implied → prediction ``contract_price`` mid.

    The last three are market-only: they carry no independent model, so the edge
    gate sees no model P and marks the leg ``no-edge``. With ``require_model``
    set, a leg that would fall through to a market-only marginal is refused.

    A TD market never falls through to a fake Gaussian: with no distribution it
    is priced from a typed ``fair_p`` or a de-vigged pool / leg price, not
    invented. ``two_plus_td`` needs a typed ``fair_p`` or a count distribution.
    """

    if line.fair_p is not None:
        return _checked_probability(line.fair_p, "fair_p"), "fair_p", None
    if is_two_plus_td(line.stat_type) and dist is None:
        raise KeyError(
            f"two_plus_td needs a typed fair_p or a count distribution "
            f"for {line.player_key}/{line.stat_type}"
        )
    if dist is not None:
        fair = _distribution_prob(line, dist)
        return side_probability(fair, line.side), "distribution", fair
    if line.ref_p is not None:
        return _checked_probability(line.ref_p, "ref_p"), "ref_p", None
    for step in _MARKET_STEPS:
        found = step(line, method, require_model)
        if found is not None:
            probability, source = found
            return probability, source, None
    raise KeyError(
        f"no distribution for {line.player_key}/{line.stat_type} and no book odds"
    )


def model_prob_for_line(
    line: LineRow,
    dist: DistRow | None,
) -> tuple[float | None, str]:
    """Model P for the edge gate. Typed ``fair_p`` first, else the projection.

    This is the model side of the edge, kept apart from ``fair_for_line``, which
    prefers the de-vigged book. When book odds exist, ``fair_for_line`` returns
    the market implied as ``fair_p``, so ``fair_p - implied`` is zero by
    construction. The edge needs the model, and the model comes from the typed
    ``fair_p`` or the projected distribution. A leg with neither has no model P
    and cannot show an edge.
    """

    if line.fair_p is not None:
        if not 0.0 < line.fair_p < 1.0:
            raise ValueError(f"fair_p must be between 0 and 1, got {line.fair_p}")
        return line.fair_p, "fair_p"
    if dist is not None:
        family = dist.family or None
        if is_two_plus_td(line.stat_type):
            family = "poisson"
        elif family not in {"lognormal", "normal", "poisson"}:
            family = None
        fair = p_over_line(
            line=line.line,
            median=dist.median,
            sigma=dist.sigma,
            family=family,
            stat_type=line.stat_type,
        )
        return side_probability(fair, line.side), "distribution"
    return None, ""


def market_implied_for_line(
    line: LineRow,
    method: DevigMethod = "power",
) -> tuple[float | None, str]:
    """Market implied P for the edge gate.

    The de-vigged two-way book first, else the TD ``leg_odds`` implied, else a
    prediction contract mid. A leg with no market price has no market implied P
    and cannot show an edge.
    """

    if line.book_over is not None and line.book_under is not None:
        result = devig_two_way(line.book_over, line.book_under, method=method)
        if line.side in MORE_SIDES:
            return result.p_over, "book_devig"
        if line.side in LESS_SIDES:
            return result.p_under, "book_devig"
        return None, ""
    if is_td_market(line.stat_type) and line.leg_odds is not None:
        implied = american_to_implied(int(line.leg_odds))
        if line.side in LESS_SIDES:
            implied = 1.0 - implied
        elif line.side not in MORE_SIDES:
            return None, ""
        return implied, "leg_odds_implied"
    if line.contract_price is not None:
        if not 0.0 < line.contract_price < 1.0:
            raise ValueError(
                f"contract_price must be between 0 and 1, got {line.contract_price}"
            )
        implied = line.contract_price
        if line.side in LESS_SIDES:
            implied = 1.0 - implied
        elif line.side not in MORE_SIDES:
            return None, ""
        return implied, "contract_price"
    return None, ""


def _parse_utc(value: str) -> datetime | None:
    """Parse an ISO-8601 UTC timestamp (``2026-09-13T17:00:00Z``), else ``None``."""

    text = (value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _american_ok(odds: int | None) -> bool:
    if odds is None:
        return True
    try:
        american_to_decimal(odds)
        return True
    except ValueError:
        return False


def _time_reason(
    line: LineRow, reference_now: datetime, max_age: float | None
) -> str | None:
    kick = _parse_utc(line.commence_time)
    if kick is not None and reference_now >= kick:
        return "already-kicked"
    if max_age is None:
        return None
    captured = _parse_utc(line.captured_at)
    if captured is None:
        return None
    age_minutes = (reference_now - captured).total_seconds() / 60.0
    return "stale-line" if age_minutes > max_age else None


def _shape_reason(line: LineRow, td_priced: bool) -> str | None:
    """A blank team, or a blank line on a leg that needs a real one."""

    if not line.team or not line.opponent:
        return "no-team"
    if not isnan(line.line):
        return None
    if not (td_priced or line.contract_price is not None):
        return "no-line"
    # TD props and prediction contracts have no yard line; 0.5 is a display
    # dummy, never priced.
    line.line = NO_LINE_DUMMY
    return None


def _line_rules(line: LineRow, allow_high_receiving: bool) -> str | None:
    if (
        not allow_high_receiving
        and (line.stat_type or "").strip().lower() == "rec_yds"
        and line.line >= 50
    ):
        return "rec-line-bar"
    if line.book_line is not None and abs(line.book_line - line.line) > 1e-9:
        return "book-line-mismatch"
    if (line.book_over is None) != (line.book_under is None):
        return "one-sided-book"
    return None


def _no_source_reason(
    line: LineRow, dist: DistRow | None, td_priced: bool
) -> str | None:
    """A leg with no model, no book, and no typed price carries nothing."""

    if (
        line.book_over is None
        and line.ref_p is None
        and line.ref_book_over is None
        and dist is None
        and line.fair_p is None
        and not td_priced
        and line.contract_price is None
    ):
        return "dropped"
    return None


def _odds_rules(line: LineRow, allow_integers: bool) -> str | None:
    if not allow_integers and float(line.line).is_integer():
        return "integer-line"
    if not (
        _american_ok(line.book_over)
        and _american_ok(line.book_under)
        and _american_ok(line.leg_odds)
        and _american_ok(line.slip_odds)
    ):
        return "bad-odds"
    return None


def _rejection_reason(
    line: LineRow,
    dist: DistRow | None,
    reference_now: datetime,
    max_age: float | None,
    roster: Roster | None,
    allow_high_receiving: bool,
    allow_integers: bool,
) -> str | None:
    """The first rule that keeps a line off the card, in reporting order."""

    if is_scratched(line.injury_status):
        return "scratch"
    reason = _time_reason(line, reference_now, max_age)
    if reason is not None:
        return reason
    td_priced = is_td_market(line.stat_type) and (
        line.fair_p is not None or line.leg_odds is not None
    )
    reason = _shape_reason(line, td_priced)
    if reason is not None:
        return reason
    if roster is not None and roster_mismatch(line, roster):
        return "wrong-team"
    reason = _line_rules(line, allow_high_receiving)
    if reason is not None:
        return reason
    reason = _no_source_reason(line, dist, td_priced)
    if reason is not None:
        return reason
    return _odds_rules(line, allow_integers)


def _apply_weather(
    line: LineRow,
    fair_p: float,
    model_p: float | None,
    family: str,
    environment: "Environment | None",
    source: str,
) -> tuple[float, float | None, str]:
    """Move a model marginal. A market marginal already carries the book price."""

    if environment is None or source not in {"fair_p", "distribution"}:
        return fair_p, model_p, family
    env_row = env_for(environment, line.team, line.opponent)
    if env_row is None:
        return fair_p, model_p, family
    weather = apply_weather_discount(
        fair_p,
        env_row,
        side=line.side,
        stat_type=line.stat_type,
    )
    if abs(weather.adjusted - fair_p) <= 1e-12:
        return fair_p, model_p, family
    if model_p is not None:
        model_p = weather.adjusted
    return weather.adjusted, model_p, f"{family} [{weather.note}]"


def _model_inputs(
    line: LineRow, dist: DistRow | None, method: DevigMethod
) -> tuple[float | None, str, float | None, str | None]:
    try:
        model_p, edge_source = model_prob_for_line(line, dist)
    except KeyError:
        model_p, edge_source = None, ""
    except ValueError:
        return None, "", None, "bad-distribution"
    try:
        market_implied, _market_source = market_implied_for_line(line, method)
    except (KeyError, ValueError):
        market_implied = None
    return model_p, edge_source, market_implied, None


def _build_leg(
    line: LineRow,
    *,
    fair_p: float,
    source: str,
    fair: FairResult | None,
    family: str,
    model_p: float | None,
    market_implied: float | None,
    edge_source: str,
    implied_p: float,
    stored_implied: float,
) -> EvaluatedLeg:
    prop_edge = (
        model_p - market_implied
        if model_p is not None and market_implied is not None
        else None
    )
    return EvaluatedLeg(
        line=line,
        fair_p=fair_p,
        implied_p=stored_implied,
        edge=(fair_p - implied_p) if implied_p > 0.0 else 0.0,
        source=source,
        family=family,
        median=fair.median if fair else 0.0,
        warn="questionable" if is_flagged(line.injury_status) else "",
        p_over_at_median=fair.fair_p_at_median if fair else 0.0,
        model_p=model_p,
        market_implied_p=market_implied,
        prop_edge=prop_edge,
        edge_source=edge_source,
    )


def _price_leg(
    line: LineRow,
    dist: DistRow | None,
    implied_p: float,
    stored_implied: float,
    method: DevigMethod,
    require_model: bool,
    environment: "Environment | None",
) -> tuple[EvaluatedLeg | None, str | None]:
    """The priced leg, or the warn token that kept it out."""

    try:
        fair_p, source, fair = fair_for_line(
            line, dist, method=method, require_model=require_model
        )
    except ModelRequiredError:
        return None, "no-model-marginal"
    except (KeyError, ValueError):
        return None, "dropped"

    family = fair.family if fair else "book"
    if fair is not None and fair.note:
        family = f"{family} ({fair.note})"
    model_p, edge_source, market_implied, reason = _model_inputs(line, dist, method)
    if reason is not None:
        return None, reason
    fair_p, model_p, family = _apply_weather(
        line, fair_p, model_p, family, environment, source
    )
    return (
        _build_leg(
            line,
            fair_p=fair_p,
            source=source,
            fair=fair,
            family=family,
            model_p=model_p,
            market_implied=market_implied,
            edge_source=edge_source,
            implied_p=implied_p,
            stored_implied=stored_implied,
        ),
        None,
    )


def evaluate_legs(
    lines: list[LineRow],
    distributions: dict[tuple[str, str], DistRow],
    implied_p: float,
    method: DevigMethod = "power",
    allow_integer_lines: bool = False,
    platform: str = "",
    roster: Roster | None = None,
    allow_high_receiving: bool = False,
    require_model: bool = False,
    environment: "Environment | None" = None,
    now: datetime | None = None,
    max_line_age_minutes: float | None = None,
) -> tuple[list[EvaluatedLeg], list[EvaluatedLeg]]:
    """Split lines into rankable legs and named exclusions.

    Every path that skips a line appends to ``excluded`` with a warn token, so
    the operator can reconcile CSV in vs card out (I-03 / I-26). Sportsbook
    integer lines stay excluded even when ``allow_integer_lines`` is set
    (push / reduced-ticket payout is not modeled). A receiving-yards line at 50
    or higher is barred with ``rec-line-bar`` unless ``allow_high_receiving`` is
    set (the 49.5 line stays legal; rush yards are never barred).
    """

    sportsbook = (
        normalize_platform(platform) in SPORTSBOOK_PLATFORMS if platform else False
    )
    allow_integers = bool(allow_integer_lines) and not sportsbook
    stored_implied = implied_p if implied_p > 0.0 else 0.0
    reference_now = now if now is not None else datetime.now(timezone.utc)
    live: list[EvaluatedLeg] = []
    excluded: list[EvaluatedLeg] = []
    for line in lines:
        dist = distributions.get((line.player_key, line.stat_type))
        reason = _rejection_reason(
            line,
            dist,
            reference_now,
            max_line_age_minutes,
            roster,
            allow_high_receiving,
            allow_integers,
        )
        if reason is None:
            leg, reason = _price_leg(
                line,
                dist,
                implied_p,
                stored_implied,
                method,
                require_model,
                environment,
            )
        else:
            leg = None
        if leg is None:
            excluded.append(_excluded_leg(line, stored_implied, reason or "dropped"))
            continue
        live.append(leg)
    return live, excluded


#: Default modeled-edge floor for a leg to enter a card: one probability point.
#: It absorbs the devig error band and the book price you actually get.
DEFAULT_MIN_EDGE = 0.01


def edge_status(leg: EvaluatedLeg, min_edge: float) -> str:
    """Return "" when a leg clears the edge floor, else the failing token.

    ``no-edge`` means the leg carries no model P (or no market price), so no
    edge can be computed. ``weak-edge`` means the edge is below the floor.
    """

    if leg.prop_edge is None:
        return "no-edge"
    if leg.prop_edge < min_edge:
        return "weak-edge"
    return ""


def edge_failures(
    legs: list[EvaluatedLeg], min_edge: float
) -> list[tuple[EvaluatedLeg, str]]:
    """Return ``(leg, token)`` for each leg that fails the edge floor, in order."""

    return [(leg, token) for leg in legs if (token := edge_status(leg, min_edge))]


def _slip_label(legs: list[EvaluatedLeg]) -> str:
    return " + ".join(
        f"{leg.line.player_name} {leg.line.side} {leg.line.line} {leg.line.stat_type}"
        for leg in legs
    )


def _combo_names(legs: list[EvaluatedLeg] | tuple[EvaluatedLeg, ...]) -> str:
    return " + ".join(leg.line.player_name for leg in legs)


def _same_game(refs: list[LegRef]) -> bool:
    teams = {ref.team for ref in refs if ref.team}
    if len(teams) <= 1:
        return True
    for index, left in enumerate(refs):
        for right in refs[index + 1 :]:
            if left.opponent == right.team or right.opponent == left.team:
                return True
    return False


def _agreeing_quotes(values: list[int | None]) -> tuple[str, int | None]:
    """Classify a combo's American quotes: agree / conflict / partial / none."""

    if all(value is not None for value in values):
        distinct = sorted(set(values))
        if len(distinct) == 1:
            return "agree", distinct[0]
        return "conflict", None
    if any(value is not None for value in values):
        return "partial", None
    return "none", None


def _sportsbook_combo_multiplier(
    combo: tuple[EvaluatedLeg, ...] | list[EvaluatedLeg],
) -> tuple[float, str] | None:
    """Resolve a sportsbook decimal M from typed American prices.

    ``slip_odds`` prices the combo only when every leg carries the same quote.
    Partial or conflicting quotes return None (caller skips).
    """

    state, value = _agreeing_quotes([leg.line.slip_odds for leg in combo])
    if state == "agree" and value is not None:
        return american_to_decimal(int(value)), "slip_odds"
    if state in {"conflict", "partial"}:
        return None
    if all(leg.line.leg_odds is not None for leg in combo):
        product = 1.0
        for leg in combo:
            product *= american_to_decimal(int(leg.line.leg_odds))
        return product, "leg_odds"
    return None


def _prediction_combo_multiplier(
    combo: tuple[EvaluatedLeg, ...] | list[EvaluatedLeg],
) -> tuple[float, str] | None:
    """Prediction COMBOS: M = 1 / product of typed 0-1 contract prices.

    Every leg must carry a ``contract_price`` strictly inside (0, 1); a missing
    or out-of-range price returns None so the combo is skipped, not guessed.
    """

    product = 1.0
    for leg in combo:
        price = leg.line.contract_price
        if price is None or not 0.0 < price < 1.0:
            return None
        product *= price
    if product <= 0.0:
        return None
    return 1.0 / product, "contract_product"


def combo_over_market_cap(combo: tuple, max_legs_per_market: int | None) -> bool:
    """True when one ``stat_type`` appears more than ``max_legs_per_market`` times.

    ``None`` or any int below 1 is no cap. This is the same rule as compose.
    """

    if max_legs_per_market is None or max_legs_per_market < 1:
        return False
    counts: dict[str, int] = {}
    for leg in combo:
        stat = leg.line.stat_type
        counts[stat] = counts.get(stat, 0) + 1
        if counts[stat] > max_legs_per_market:
            return True
    return False


@dataclass
class _RankContext:
    """Everything one rank call needs, carried across combos."""

    platform: str
    mode: str
    slip_size: int
    n_sims: int
    seed: int
    displayed_multiplier: float | None
    profile_dir: Path | None
    priors: dict
    shade_pp: float
    allow_unmodeled_correlation: bool
    scores_by_game: dict | None
    max_legs_per_market: int | None
    sportsbook: bool
    prediction: bool
    priced_venue: bool
    is_flex: bool
    notes: list[str]
    pickem_hurdle: float | None = None


def _refs_for(combo) -> list[LegRef]:
    return [
        LegRef(
            player_key=leg.line.player_key,
            team=leg.line.team,
            opponent=leg.line.opponent,
            stat_type=leg.line.stat_type,
            side=leg.line.side,
        )
        for leg in combo
    ]


def _ticket_id_skip(combo) -> str | None:
    ticket_ids = {leg.line.ticket_id for leg in combo if leg.line.ticket_id}
    if ticket_ids and any(not leg.line.ticket_id for leg in combo):
        return "mixed-ticket-id"
    if len(ticket_ids) > 1:
        return "mixed-ticket-id"
    return None


def _same_game_first_td(refs: list[LegRef]) -> bool:
    first_td_refs = [ref for ref in refs if is_first_td(ref.stat_type)]
    return len(first_td_refs) > 1 and _same_game(first_td_refs)


def _roster_skip(refs: list[LegRef], ctx: _RankContext) -> str | None:
    """The two-team rule and the distinct-prop rule, for an unpriced venue."""

    if not ctx.priced_venue and len({ref.team for ref in refs}) < 2:
        return "same-team (two-team rule)"
    props = [(ref.player_key, ref.stat_type) for ref in refs]
    if len(set(props)) < ctx.slip_size:
        return "duplicate player+stat"
    if not ctx.priced_venue and len({ref.player_key for ref in refs}) < ctx.slip_size:
        return "same-player multi-stat not supported"
    return None


def _combo_skip(combo, refs: list[LegRef], ctx: _RankContext) -> str | None:
    """The structural rule that rejects a combo. The caller adds the names."""

    if combo_over_market_cap(combo, ctx.max_legs_per_market):
        return "market-cap"
    if any(not ref.team for ref in refs):
        return "no-team"
    ticket_skip = _ticket_id_skip(combo)
    if ticket_skip is not None:
        return ticket_skip
    if _same_game_first_td(refs):
        return "same-game-first-td"
    return _roster_skip(refs, ctx)


def _agreed_multiplier(
    combo, slip_value, ctx: _RankContext
) -> tuple[float | None, str, str | None]:
    try:
        multiplier = american_to_decimal(int(slip_value))
    except ValueError:
        return None, "", "bad-odds"
    if (
        ctx.displayed_multiplier is not None
        and abs(multiplier - ctx.displayed_multiplier) > 1e-9
    ):
        ctx.notes.append(
            f"row slip_odds M {multiplier} overrides CLI M "
            f"{ctx.displayed_multiplier}: {_combo_names(combo)}"
        )
    return multiplier, "slip_odds", None


def _venue_multiplier(
    combo, ctx: _RankContext
) -> tuple[float | None, str, str | None]:
    """A priced venue: row slip_odds, then the CLI, then the leg product."""

    slip_state, slip_value = _agreeing_quotes([leg.line.slip_odds for leg in combo])
    if slip_state == "conflict":
        return None, "", "conflicting row slip_odds"
    if slip_state == "partial":
        return None, "", f"{ctx.platform}-needs-price"
    if slip_state == "agree" and slip_value is not None:
        return _agreed_multiplier(combo, slip_value, ctx)
    if ctx.displayed_multiplier is not None:
        return ctx.displayed_multiplier, "cli", None
    try:
        priced = (
            _prediction_combo_multiplier(combo)
            if ctx.prediction
            else _sportsbook_combo_multiplier(combo)
        )
    except ValueError:
        return None, "", "bad-odds"
    if priced is None:
        return None, "", f"{ctx.platform}-needs-price"
    multiplier, source = priced
    return multiplier, source, None


def _resolve_multiplier(
    combo, ctx: _RankContext
) -> tuple[float | None, str, str | None]:
    """Row multiplier, then the venue chain, then the CLI, then the table."""

    row_ms = sorted(
        {
            leg.line.displayed_multiplier
            for leg in combo
            if leg.line.displayed_multiplier is not None
        }
    )
    if len(row_ms) > 1:
        return None, "", f"conflicting row slip_multiplier {row_ms}"
    if row_ms:
        multiplier = row_ms[0]
        if (
            ctx.displayed_multiplier is not None
            and abs(multiplier - ctx.displayed_multiplier) > 1e-9
        ):
            ctx.notes.append(
                f"row M {multiplier} overrides CLI M {ctx.displayed_multiplier}: "
                f"{_combo_names(combo)}"
            )
        return multiplier, "row", None
    if ctx.priced_venue:
        return _venue_multiplier(combo, ctx)
    if ctx.displayed_multiplier is not None:
        return ctx.displayed_multiplier, "cli", None
    return None, "table", None


def _combo_correlation(combo, refs: list[LegRef], ctx: _RankContext):
    """(requested, clean, records, max delta), or None when the pair is refused."""

    try:
        requested = correlation_matrix(
            refs,
            ctx.priors,
            repair=False,
            allow_unmodeled=ctx.allow_unmodeled_correlation,
        )
    except UnmodeledCorrelationError as exc:
        ctx.notes.append(f"skip unmodeled-corr ({exc}): {_combo_names(combo)}")
        return None
    rho_records: list = []
    if ctx.scores_by_game:
        requested, rho_records = perturb_matrix(requested, refs, ctx.scores_by_game)
    clean = nearest_correlation(requested)
    max_corr_delta = float(np.max(np.abs(clean - requested)))
    return requested, clean, rho_records, max_corr_delta


def _joint_probabilities(combo, clean, ctx: _RankContext) -> tuple:
    marginals = [
        min(max(leg.fair_p - ctx.shade_pp, 1e-9), 1.0 - 1e-9) for leg in combo
    ]
    if ctx.is_flex or ctx.slip_size > 3:
        sim = simulate_slip(marginals, clean, n_sims=ctx.n_sims, seed=ctx.seed)
        return (
            float(sim["p_all"]),
            float(sim["p_all_se"]),
            float(sim["p_naive"]),
            float(sim["p_minus_1"]),
            float(sim["p_minus_2"]),
        )
    # Power 2-3 legs: deterministic exact Gaussian joint, no MC noise.
    return exact_joint(marginals, clean), 0.0, float(np.prod(marginals)), 0.0, 0.0


def _combo_ev(
    p_all: float,
    p_all_se: float,
    p_minus_1: float,
    p_minus_2: float,
    price: float,
    table,
    ctx: _RankContext,
) -> tuple[float, float, float, float, list[str]]:
    p_lo = max(p_all - p_all_se, 0.0)
    if ctx.is_flex:
        ev = flex_ev(p_all, p_minus_1, p_minus_2, table)
        return ev, 0.0, ev, p_lo, ["quarter_kelly=na (flex proxy suppressed)"]
    kelly = slip_kelly(p_all, price)
    return power_ev(p_all, price), kelly, p_lo * price - 1.0, p_lo, []


def _pickem_notes(combo, ctx: _RankContext) -> tuple[float, list[str]]:
    # Payout-structure hurdle, not a de-vigged market line. The typed displayed
    # multiplier still drives price; this only annotates it.
    if ctx.pickem_hurdle is None:
        ctx.pickem_hurdle = pickem_breakeven(
            ctx.platform, ctx.mode, ctx.slip_size, profile_dir=ctx.profile_dir
        )
    hurdle = ctx.pickem_hurdle
    notes = [f"pickem_breakeven={hurdle:.4f} (uniform per-leg)"]
    geomean = math.prod(leg.fair_p for leg in combo) ** (1.0 / len(combo))
    notes.append(
        f"pickem_geomean_fair_p={geomean:.4f} vs pickem_breakeven={hurdle:.4f}"
    )
    for leg in combo:
        notes.append(
            f"pickem_leg {leg.line.player_name} fair_p={leg.fair_p:.4f} "
            f"vs pickem_breakeven={hurdle:.4f}"
        )
    return hurdle, notes


def _naive_price(
    combo,
    refs: list[LegRef],
    ctx: _RankContext,
    source: str,
    unconfirmed: bool,
    kelly: float,
) -> tuple[str, bool, float, str | None]:
    """Mark a product-of-leg prices source unconfirmed and suppress Kelly."""

    note = None
    if ctx.sportsbook and source == "leg_odds":
        unconfirmed = True
        source = "leg_odds_naive"
        kelly = 0.0
        if _same_game(refs):
            note = (
                f"naive product of leg_odds — {display_name(ctx.platform)} SGP "
                "usually pays less; rebuild in-app and pass --displayed-odds"
            )
        else:
            note = "naive product of leg_odds — confirm in-app; Kelly suppressed"
    if ctx.prediction and source == "contract_product":
        unconfirmed = True
        kelly = 0.0
        note = (
            "contract_product — independent-binary COMBOS; correlated NFL "
            "legs overstate EV; Kelly 0"
        )
    return source, unconfirmed, kelly, note


def _combo_notes(
    combo,
    refs: list[LegRef],
    ctx: _RankContext,
    table,
    source: str,
    unconfirmed: bool,
    kelly: float,
    repaired: bool,
    max_corr_delta: float,
    base: list[str],
) -> tuple[str, bool, float, list[str]]:
    notes = base
    if table.note:
        notes.append(table.note)
    if ctx.platform in PICKEM_PLATFORMS:
        _hurdle, pickem = _pickem_notes(combo, ctx)
        notes.extend(pickem)
    if repaired:
        notes.append(f"corr_repaired=yes max_delta={max_corr_delta:.4f}")
    if unconfirmed:
        notes.append("multiplier_unconfirmed=yes (table)")
    source, unconfirmed, kelly, naive = _naive_price(
        combo, refs, ctx, source, unconfirmed, kelly
    )
    if naive:
        notes.append(naive)
    if ctx.shade_pp:
        notes.append(f"shade_pp={ctx.shade_pp:g}")
    return source, unconfirmed, kelly, notes


def _rank_combo(combo, ctx: _RankContext) -> EvaluatedSlip | None:
    """One ranked slip, or None after the reject note is recorded."""

    refs = _refs_for(combo)
    skip = _combo_skip(combo, refs, ctx)
    if skip is not None:
        ctx.notes.append(f"skip {skip}: {_combo_names(combo)}")
        return None
    multiplier, source, skip = _resolve_multiplier(combo, ctx)
    if skip is not None:
        ctx.notes.append(f"skip {skip}: {_combo_names(combo)}")
        return None
    if source == "table" and any(
        leg.line.line_type not in STANDARD_LINE_TYPES for leg in combo
    ):
        ctx.notes.append(f"skip alt-needs-m: {_combo_names(combo)}")
        return None
    if ctx.priced_venue and multiplier is not None and multiplier <= 1:
        ctx.notes.append(f"skip bad-odds: {_combo_names(combo)}")
        return None

    table = resolve_payout(
        ctx.platform,
        ctx.mode,
        ctx.slip_size,
        displayed_multiplier=multiplier,
        profile_dir=ctx.profile_dir,
    )
    price = table.all_hit
    correlated = _combo_correlation(combo, refs, ctx)
    if correlated is None:
        return None
    requested, clean, rho_records, max_corr_delta = correlated
    p_all, p_all_se, p_naive, p_minus_1, p_minus_2 = _joint_probabilities(
        combo, clean, ctx
    )
    ev, kelly, ev_lo, p_lo, base_notes = _combo_ev(
        p_all, p_all_se, p_minus_1, p_minus_2, price, table, ctx
    )
    source, unconfirmed, kelly, slip_notes = _combo_notes(
        combo,
        refs,
        ctx,
        table,
        source,
        source == "table",
        kelly,
        max_corr_delta > 0.02,
        max_corr_delta,
        base_notes,
    )
    return EvaluatedSlip(
        legs=list(combo),
        p_joint=p_all,
        p_naive=p_naive,
        ev=float(ev),
        kelly=kelly,
        mode=ctx.mode,
        multiplier=price,
        platform=ctx.platform,
        p_all_se=p_all_se,
        p_lo=p_lo,
        ev_lo=float(ev_lo),
        multiplier_source=source,
        multiplier_unconfirmed=unconfirmed,
        shade_pp=ctx.shade_pp,
        corr_repaired=max_corr_delta > 0.02,
        corr_requested=requested,
        corr_clean=clean,
        rho_records=rho_records,
        notes=slip_notes,
    )


def _rank_scope_ok(
    live: list[EvaluatedLeg],
    slip_size: int,
    priced_venue: bool,
    displayed_multiplier: float | None,
    allow_large_enum: bool,
) -> bool:
    """Raise on an impossible request. False means there is nothing to rank."""

    if priced_venue and displayed_multiplier is not None and len(live) != slip_size:
        raise ValueError(
            "displayed odds / multiplier prices one ticket. "
            f"This slate has {len(live)} live legs; slip-size is {slip_size}. "
            "Filter the CSV to those legs (see examples/hardrock_ticket.csv), "
            "pass --legs matching the ticket, or type the same slip_odds on "
            "every combo leg. A shared ticket_id does not relax this."
        )
    if len(live) < slip_size or slip_size < 1:
        return False
    total_combos = comb(len(live), slip_size)
    if total_combos > COMBO_BUDGET and not allow_large_enum:
        raise ValueError(
            f"{total_combos} combinations exceed the {COMBO_BUDGET} budget; "
            "raise --max-slips or pass --allow-large-enum"
        )
    return True


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
    allow_unmodeled_correlation: bool = False,
    scores_by_game: dict | None = None,
    max_legs_per_market: int | None = None,
) -> list[EvaluatedSlip]:
    """Enumerate slip_size combinations and rank by a lower-bound EV.

    Multiplier precedence per combo: agreeing row ``slip_multiplier`` → agreeing
    all-leg ``slip_odds`` → CLI displayed (sportsbook / prediction: legal only
    for one ticket, i.e. ``live == slip_size``; a shared ``ticket_id`` does not
    relax the size match) →
    product of ``leg_odds`` (sportsbook) or ``contract_price`` (prediction
    COMBOS), both unconfirmed with Kelly 0. A table-only pick'em price is marked
    unconfirmed (I-01 / I-07 / I-14 / I-19).
    """

    if notes is None:
        notes = []
    platform = normalize_platform(platform)
    sportsbook = platform in SPORTSBOOK_PLATFORMS
    prediction = platform in PREDICTION_PLATFORMS
    priced_venue = sportsbook or prediction
    live = [leg for leg in legs if leg.warn not in EXCLUDED_WARNS]
    if not _rank_scope_ok(
        live, slip_size, priced_venue, displayed_multiplier, allow_large_enum
    ):
        return []
    ctx = _RankContext(
        platform=platform,
        mode=mode,
        slip_size=slip_size,
        n_sims=n_sims,
        seed=seed,
        displayed_multiplier=displayed_multiplier,
        profile_dir=profile_dir,
        priors=load_priors(priors_path),
        shade_pp=shade_pp,
        allow_unmodeled_correlation=allow_unmodeled_correlation,
        scores_by_game=scores_by_game,
        max_legs_per_market=max_legs_per_market,
        sportsbook=sportsbook,
        prediction=prediction,
        priced_venue=priced_venue,
        is_flex=mode.lower() in {"flex"},
        notes=notes,
    )
    ranked: list[EvaluatedSlip] = []
    for combo in combinations(live, slip_size):
        slip = _rank_combo(combo, ctx)
        if slip is not None:
            ranked.append(slip)
    ranked.sort(key=lambda item: (item.multiplier_unconfirmed, -item.ev_lo, -item.ev))
    return ranked[:max_slips]


def resolve_slip_sizes(slip_size: int, legs: str | None = None) -> list[int]:
    """Return the slip sizes to rank. ``--legs 2,3,4`` or ``2-4`` overrides slip-size."""

    if legs is None or not str(legs).strip():
        parts = [str(slip_size)]
    else:
        parts = [part.strip() for part in str(legs).split(",") if part.strip()]
    sizes: list[int] = []
    for part in parts:
        if "-" in part:
            low_text, high_text = part.split("-", 1)
            start, end = int(low_text), int(high_text)
            if start > end:
                raise ValueError(f"legs range {part} is empty")
            sizes.extend(range(start, end + 1))
        else:
            sizes.append(int(part))
    cleaned: list[int] = []
    for size in sizes:
        if size < 1:
            raise ValueError("leg count must be >= 1")
        if size not in cleaned:
            cleaned.append(size)
    return cleaned


def slip_clears_odds(
    slip: EvaluatedSlip,
    min_odds: int | None = None,
    max_odds: int | None = None,
) -> bool:
    """Keep slips whose decimal M sits between the American min and max."""

    if min_odds is None and max_odds is None:
        return True
    if min_odds is not None and slip.multiplier + 1e-12 < american_to_decimal(min_odds):
        return False
    if max_odds is not None and slip.multiplier > american_to_decimal(max_odds) + 1e-12:
        return False
    return True


def filter_slips_by_odds(
    slips: list[EvaluatedSlip],
    min_odds: int | None = None,
    max_odds: int | None = None,
) -> list[EvaluatedSlip]:
    if min_odds is not None and max_odds is not None:
        if american_to_decimal(min_odds) > american_to_decimal(max_odds) + 1e-12:
            raise ValueError("--min-odds is longer than --max-odds")
    return [slip for slip in slips if slip_clears_odds(slip, min_odds, max_odds)]


def rank_slip_sizes(
    legs: list[EvaluatedLeg],
    platform: str,
    mode: str,
    sizes: list[int],
    n_sims: int = 20_000,
    seed: int = 42,
    displayed_multiplier: float | None = None,
    profile_dir: Path | None = None,
    priors_path: Path | None = None,
    max_slips: int = 25,
    allow_large_enum: bool = False,
    shade_pp: float = 0.0,
    notes: list[str] | None = None,
    min_odds: int | None = None,
    max_odds: int | None = None,
    allow_unmodeled_correlation: bool = False,
    scores_by_game: dict | None = None,
    max_legs_per_market: int | None = None,
) -> list[EvaluatedSlip]:
    """Rank one or more slip sizes, then apply optional American odds filters."""

    if notes is None:
        notes = []
    ranked: list[EvaluatedSlip] = []
    per_call = max(max_slips, 1) * max(len(sizes), 1)
    for size in sizes:
        ranked.extend(
            rank_slips(
                legs,
                platform=platform,
                mode=mode,
                slip_size=size,
                n_sims=n_sims,
                seed=seed,
                displayed_multiplier=displayed_multiplier,
                profile_dir=profile_dir,
                priors_path=priors_path,
                max_slips=per_call,
                allow_large_enum=allow_large_enum,
                shade_pp=shade_pp,
                notes=notes,
                allow_unmodeled_correlation=allow_unmodeled_correlation,
                scores_by_game=scores_by_game,
                max_legs_per_market=max_legs_per_market,
            )
        )
    before = len(ranked)
    ranked = filter_slips_by_odds(ranked, min_odds, max_odds)
    dropped = before - len(ranked)
    if dropped:
        bounds = []
        if min_odds is not None:
            bounds.append(f"min={min_odds:+d}" if min_odds > 0 else f"min={min_odds}")
        if max_odds is not None:
            bounds.append(f"max={max_odds:+d}" if max_odds > 0 else f"max={max_odds}")
        notes.append(f"odds-filter dropped {dropped} ({' '.join(bounds)})")
    ranked.sort(key=lambda item: (item.multiplier_unconfirmed, -item.ev_lo, -item.ev))
    return ranked[:max_slips]


def _leg_cell(slip: EvaluatedSlip, name: str, *, signed: bool = False) -> str:
    """Pipe-joined per-leg value for an optional column.

    A leg with no value keeps an empty slot, so the cell stays aligned with
    ``player_keys`` and its siblings.
    """

    parts: list[str] = []
    for leg in slip.legs:
        value = getattr(leg, name, None)
        if value is None:
            parts.append("")
        elif signed:
            parts.append(f"{float(value):+.1f}")
        else:
            parts.append(f"{float(value):.4f}")
    return "|".join(parts)


def slip_as_row(slip: EvaluatedSlip, index: int) -> dict[str, object]:
    first = slip.legs[0].line
    is_flex = slip.mode.lower() in {"flex"}
    ticket_ids = {leg.line.ticket_id for leg in slip.legs if leg.line.ticket_id}
    records = slip.rho_records or []
    return {
        "slate_id": first.slate_id,
        "platform": slip.platform,
        "slip_id": f"slip-{index:03d}",
        "ticket_id": next(iter(ticket_ids)) if len(ticket_ids) == 1 else "",
        "mode": slip.mode,
        "n_legs": len(slip.legs),
        "american": (
            decimal_to_american(slip.multiplier)
            if slip.mode.lower() not in {"flex"} and slip.multiplier > 1.0
            else ""
        ),
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
        "rho_base": "|".join(f"{record.rho_base:.4f}" for record in records),
        "delta_rho": "|".join(f"{record.delta_rho:+.4f}" for record in records),
        "rho_adj": "|".join(f"{record.rho_adj:.4f}" for record in records),
        "p_dfs_over": _leg_cell(slip, "p_dfs_over"),
        "p_market_fair": _leg_cell(slip, "p_market_fair"),
        "p_fair_posterior": _leg_cell(slip, "p_fair_posterior"),
        "disagreement_edge_bps": _leg_cell(slip, "disagreement_edge_bps", signed=True),
        "shade_pp": slip.shade_pp,
        "notes": "; ".join(slip.notes),
        "do_not_submit": "yes",
        "captured_at": first.captured_at,
    }


EDGE_FIELDS = [
    "slate_id",
    "platform",
    "slip_id",
    "ticket_id",
    "mode",
    "n_legs",
    "american",
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
    "rho_base",
    "delta_rho",
    "rho_adj",
    "p_dfs_over",
    "p_market_fair",
    "p_fair_posterior",
    "disagreement_edge_bps",
    "shade_pp",
    "notes",
    "do_not_submit",
    "captured_at",
]
