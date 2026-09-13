from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from math import comb, isnan
from pathlib import Path

import numpy as np

from ceminiparlays.copula import exact_joint, nearest_correlation, simulate_slip
from ceminiparlays.correlation import LegRef, correlation_matrix, load_priors
from ceminiparlays.fair import FairResult, p_over_line, side_probability
from ceminiparlays.io import DistRow, LineRow, is_flagged, is_scratched
from ceminiparlays.kelly import slip_kelly
from ceminiparlays.markets import is_first_td, is_td_market
from ceminiparlays.odds import (
    DevigMethod,
    american_to_decimal,
    american_to_implied,
    decimal_to_american,
    devig_two_way,
)
from ceminiparlays.payouts import (
    PREDICTION_PLATFORMS,
    SPORTSBOOK_PLATFORMS,
    display_name,
    flex_ev,
    normalize_platform,
    power_ev,
    resolve_payout,
)
from ceminiparlays.roster import Roster, roster_mismatch

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


def fair_for_line(
    line: LineRow,
    dist: DistRow | None,
    method: DevigMethod = "power",
) -> tuple[float, str, FairResult | None]:
    """Prefer operator-typed probabilities; fall back to a projected distribution.

    Precedence: typed ``fair_p`` → de-vigged two-way book → TD ``leg_odds``
    implied → projected distribution → prediction ``contract_price`` mid. A TD
    market never falls through to a fake Gaussian: with no distribution it is
    dropped, not invented.
    """

    if line.fair_p is not None:
        if not 0.0 < line.fair_p < 1.0:
            raise ValueError(f"fair_p must be between 0 and 1, got {line.fair_p}")
        return line.fair_p, "fair_p", None
    if line.book_over is not None and line.book_under is not None:
        result = devig_two_way(line.book_over, line.book_under, method=method)
        if line.side in MORE_SIDES:
            p = result.p_over
        elif line.side in LESS_SIDES:
            p = result.p_under
        else:
            raise ValueError(f"unknown side: {line.side}")
        return p, "book_devig", None
    if is_td_market(line.stat_type) and line.leg_odds is not None:
        implied = american_to_implied(int(line.leg_odds))
        if line.side in LESS_SIDES:
            implied = 1.0 - implied
        elif line.side not in MORE_SIDES:
            raise ValueError(f"unknown side: {line.side}")
        return implied, "leg_odds_implied", None
    if dist is not None:
        family = dist.family or None
        fair = p_over_line(
            line=line.line,
            median=dist.median,
            sigma=dist.sigma,
            family=family if family in {"lognormal", "normal", "poisson"} else None,
            stat_type=line.stat_type,
        )
        return side_probability(fair, line.side), "distribution", fair
    if line.contract_price is not None:
        if not 0.0 < line.contract_price < 1.0:
            raise ValueError(
                f"contract_price must be between 0 and 1, got {line.contract_price}"
            )
        implied = line.contract_price
        if line.side in LESS_SIDES:
            implied = 1.0 - implied
        return implied, "contract_price", None
    raise KeyError(
        f"no distribution for {line.player_key}/{line.stat_type} and no book odds"
    )


def _american_ok(odds: int | None) -> bool:
    if odds is None:
        return True
    try:
        american_to_decimal(odds)
        return True
    except ValueError:
        return False


def evaluate_legs(
    lines: list[LineRow],
    distributions: dict[tuple[str, str], DistRow],
    implied_p: float,
    method: DevigMethod = "power",
    allow_integer_lines: bool = False,
    platform: str = "",
    roster: Roster | None = None,
) -> tuple[list[EvaluatedLeg], list[EvaluatedLeg]]:
    """Split lines into rankable legs and named exclusions.

    Every path that skips a line appends to ``excluded`` with a warn token, so
    the operator can reconcile CSV in vs card out (I-03 / I-26). Sportsbook
    integer lines stay excluded even when ``allow_integer_lines`` is set
    (push / reduced-ticket payout is not modeled).
    """

    sportsbook = (
        normalize_platform(platform) in SPORTSBOOK_PLATFORMS if platform else False
    )
    allow_integers = bool(allow_integer_lines) and not sportsbook
    stored_implied = implied_p if implied_p > 0.0 else 0.0
    live: list[EvaluatedLeg] = []
    excluded: list[EvaluatedLeg] = []
    for line in lines:
        dist = distributions.get((line.player_key, line.stat_type))
        if is_scratched(line.injury_status):
            excluded.append(_excluded_leg(line, stored_implied, "scratch"))
            continue
        if not line.team or not line.opponent:
            excluded.append(_excluded_leg(line, stored_implied, "no-team"))
            continue
        td_market = is_td_market(line.stat_type)
        td_priced = td_market and (
            line.fair_p is not None or line.leg_odds is not None
        )
        line_optional = td_priced or line.contract_price is not None
        if isnan(line.line):
            if not line_optional:
                excluded.append(_excluded_leg(line, stored_implied, "no-line"))
                continue
            # TD props and prediction contracts have no yard line; 0.5 is a
            # display dummy, never priced.
            line.line = NO_LINE_DUMMY
        if roster is not None and roster_mismatch(line, roster):
            excluded.append(_excluded_leg(line, stored_implied, "wrong-team"))
            continue
        if line.book_line is not None and abs(line.book_line - line.line) > 1e-9:
            excluded.append(_excluded_leg(line, stored_implied, "book-line-mismatch"))
            continue
        if (line.book_over is None) != (line.book_under is None):
            excluded.append(_excluded_leg(line, stored_implied, "one-sided-book"))
            continue
        if (
            line.book_over is None
            and dist is None
            and line.fair_p is None
            and not td_priced
            and line.contract_price is None
        ):
            excluded.append(_excluded_leg(line, stored_implied, "dropped"))
            continue
        if not allow_integers and float(line.line).is_integer():
            excluded.append(_excluded_leg(line, stored_implied, "integer-line"))
            continue
        if not (
            _american_ok(line.book_over)
            and _american_ok(line.book_under)
            and _american_ok(line.leg_odds)
            and _american_ok(line.slip_odds)
        ):
            excluded.append(_excluded_leg(line, stored_implied, "bad-odds"))
            continue
        try:
            fair_p, source, fair = fair_for_line(line, dist, method=method)
        except (KeyError, ValueError):
            excluded.append(_excluded_leg(line, stored_implied, "dropped"))
            continue
        warn = "questionable" if is_flagged(line.injury_status) else ""
        family = fair.family if fair else "book"
        if fair is not None and fair.note:
            family = f"{family} ({fair.note})"
        edge = (fair_p - implied_p) if implied_p > 0.0 else 0.0
        live.append(
            EvaluatedLeg(
                line=line,
                fair_p=fair_p,
                implied_p=stored_implied,
                edge=edge,
                source=source,
                family=family,
                median=fair.median if fair else 0.0,
                warn=warn,
                p_over_at_median=fair.fair_p_at_median if fair else 0.0,
            )
        )
    return live, excluded


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
    is_flex = mode.lower() in {"flex"}
    live = [leg for leg in legs if leg.warn not in EXCLUDED_WARNS]
    if (
        priced_venue
        and displayed_multiplier is not None
        and len(live) != slip_size
    ):
        raise ValueError(
            "displayed odds / multiplier prices one ticket. "
            f"This slate has {len(live)} live legs; slip-size is {slip_size}. "
            "Filter the CSV to those legs (see examples/hardrock_ticket.csv), "
            "pass --legs matching the ticket, or type the same slip_odds on "
            "every combo leg. A shared ticket_id does not relax this."
        )
    if len(live) < slip_size or slip_size < 1:
        return []
    total_combos = comb(len(live), slip_size)
    if total_combos > COMBO_BUDGET and not allow_large_enum:
        raise ValueError(
            f"{total_combos} combinations exceed the {COMBO_BUDGET} budget; "
            "raise --max-slips or pass --allow-large-enum"
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
        if any(not ref.team for ref in refs):
            notes.append(f"skip no-team: {_combo_names(combo)}")
            continue
        ticket_ids = {leg.line.ticket_id for leg in combo if leg.line.ticket_id}
        if ticket_ids and any(not leg.line.ticket_id for leg in combo):
            notes.append(f"skip mixed-ticket-id: {_combo_names(combo)}")
            continue
        if len(ticket_ids) > 1:
            notes.append(f"skip mixed-ticket-id: {_combo_names(combo)}")
            continue
        first_td_refs = [ref for ref in refs if is_first_td(ref.stat_type)]
        if len(first_td_refs) > 1 and _same_game(first_td_refs):
            notes.append(f"skip same-game-first-td: {_combo_names(combo)}")
            continue
        if not priced_venue and len({ref.team for ref in refs}) < 2:
            notes.append(f"skip same-team (two-team rule): {_combo_names(combo)}")
            continue
        props = [(ref.player_key, ref.stat_type) for ref in refs]
        if len(set(props)) < slip_size:
            notes.append(f"skip duplicate player+stat: {_combo_names(combo)}")
            continue
        if not priced_venue and len({ref.player_key for ref in refs}) < slip_size:
            notes.append(
                f"skip same-player multi-stat not supported: {_combo_names(combo)}"
            )
            continue

        row_ms = sorted(
            {
                leg.line.displayed_multiplier
                for leg in combo
                if leg.line.displayed_multiplier is not None
            }
        )
        if len(row_ms) > 1:
            notes.append(
                f"skip conflicting row slip_multiplier {row_ms}: {_combo_names(combo)}"
            )
            continue
        if row_ms:
            multiplier = row_ms[0]
            multiplier_source = "row"
            if (
                displayed_multiplier is not None
                and abs(multiplier - displayed_multiplier) > 1e-9
            ):
                notes.append(
                    f"row M {multiplier} overrides CLI M {displayed_multiplier}: "
                    f"{_combo_names(combo)}"
                )
        elif priced_venue:
            slip_state, slip_value = _agreeing_quotes(
                [leg.line.slip_odds for leg in combo]
            )
            if slip_state == "conflict":
                notes.append(
                    f"skip conflicting row slip_odds: {_combo_names(combo)}"
                )
                continue
            if slip_state == "partial":
                notes.append(f"skip {platform}-needs-price: {_combo_names(combo)}")
                continue
            if slip_state == "agree" and slip_value is not None:
                try:
                    multiplier = american_to_decimal(int(slip_value))
                except ValueError:
                    notes.append(f"skip bad-odds: {_combo_names(combo)}")
                    continue
                multiplier_source = "slip_odds"
                if (
                    displayed_multiplier is not None
                    and abs(multiplier - displayed_multiplier) > 1e-9
                ):
                    notes.append(
                        f"row slip_odds M {multiplier} overrides CLI M "
                        f"{displayed_multiplier}: {_combo_names(combo)}"
                    )
            elif displayed_multiplier is not None:
                multiplier = displayed_multiplier
                multiplier_source = "cli"
            else:
                try:
                    if prediction:
                        priced = _prediction_combo_multiplier(combo)
                    else:
                        priced = _sportsbook_combo_multiplier(combo)
                except ValueError:
                    notes.append(f"skip bad-odds: {_combo_names(combo)}")
                    continue
                if priced is None:
                    notes.append(
                        f"skip {platform}-needs-price: {_combo_names(combo)}"
                    )
                    continue
                multiplier, multiplier_source = priced
        elif displayed_multiplier is not None:
            multiplier = displayed_multiplier
            multiplier_source = "cli"
        else:
            multiplier = None
            multiplier_source = "table"
        if multiplier_source == "table" and any(
            leg.line.line_type not in STANDARD_LINE_TYPES for leg in combo
        ):
            notes.append(f"skip alt-needs-m: {_combo_names(combo)}")
            continue
        if priced_venue and multiplier is not None and multiplier <= 1:
            notes.append(f"skip bad-odds: {_combo_names(combo)}")
            continue

        table = resolve_payout(
            platform,
            mode,
            slip_size,
            displayed_multiplier=multiplier,
            profile_dir=profile_dir,
        )
        price = table.all_hit
        unconfirmed = multiplier_source == "table"

        requested = correlation_matrix(refs, priors, repair=False)
        clean = nearest_correlation(requested)
        max_corr_delta = float(np.max(np.abs(clean - requested)))
        repaired = max_corr_delta > 0.02

        marginals = [
            min(max(leg.fair_p - shade_pp, 1e-9), 1.0 - 1e-9) for leg in combo
        ]
        if is_flex or slip_size > 3:
            sim = simulate_slip(marginals, clean, n_sims=n_sims, seed=seed)
            p_all = float(sim["p_all"])
            p_all_se = float(sim["p_all_se"])
            p_naive = float(sim["p_naive"])
            p_minus_1 = float(sim["p_minus_1"])
            p_minus_2 = float(sim["p_minus_2"])
        else:
            # Power 2-3 legs: deterministic exact Gaussian joint, no MC noise.
            p_all = exact_joint(marginals, clean)
            p_all_se = 0.0
            p_naive = float(np.prod(marginals))
            p_minus_1 = 0.0
            p_minus_2 = 0.0
        p_lo = max(p_all - p_all_se, 0.0)

        slip_notes: list[str] = []
        if is_flex:
            ev = flex_ev(p_all, p_minus_1, p_minus_2, table)
            kelly = 0.0
            slip_notes.append("quarter_kelly=na (flex proxy suppressed)")
            ev_lo = ev
        else:
            ev = power_ev(p_all, price)
            kelly = slip_kelly(p_all, price)
            ev_lo = p_lo * price - 1.0
        if table.note:
            slip_notes.append(table.note)
        if repaired:
            slip_notes.append(f"corr_repaired=yes max_delta={max_corr_delta:.4f}")
        if unconfirmed:
            slip_notes.append("multiplier_unconfirmed=yes (table)")
        if sportsbook and multiplier_source == "leg_odds":
            unconfirmed = True
            multiplier_source = "leg_odds_naive"
            kelly = 0.0
            if _same_game(refs):
                slip_notes.append(
                    f"naive product of leg_odds — {display_name(platform)} SGP "
                    "usually pays less; rebuild in-app and pass --displayed-odds"
                )
            else:
                slip_notes.append(
                    "naive product of leg_odds — confirm in-app; Kelly suppressed"
                )
        if prediction and multiplier_source == "contract_product":
            unconfirmed = True
            kelly = 0.0
            slip_notes.append(
                "contract_product — independent-binary COMBOS; correlated NFL "
                "legs overstate EV; Kelly 0"
            )
        if shade_pp:
            slip_notes.append(f"shade_pp={shade_pp:g}")

        ranked.append(
            EvaluatedSlip(
                legs=list(combo),
                p_joint=p_all,
                p_naive=p_naive,
                ev=float(ev),
                kelly=kelly,
                mode=mode,
                multiplier=price,
                platform=platform,
                p_all_se=p_all_se,
                p_lo=p_lo,
                ev_lo=float(ev_lo),
                multiplier_source=multiplier_source,
                multiplier_unconfirmed=unconfirmed,
                shade_pp=shade_pp,
                corr_repaired=repaired,
                corr_requested=requested,
                corr_clean=clean,
                notes=slip_notes,
            )
        )
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


def slip_as_row(slip: EvaluatedSlip, index: int) -> dict[str, object]:
    first = slip.legs[0].line
    is_flex = slip.mode.lower() in {"flex"}
    ticket_ids = {leg.line.ticket_id for leg in slip.legs if leg.line.ticket_id}
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
    "shade_pp",
    "notes",
    "do_not_submit",
    "captured_at",
]
