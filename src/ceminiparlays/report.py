from __future__ import annotations

from ceminiparlays import STANDARD_DISCLAIMER
from ceminiparlays.fair import FairResult
from ceminiparlays.odds import decimal_to_american
from ceminiparlays.payouts import (
    PREDICTION_PLATFORMS,
    SPORTSBOOK_PLATFORMS,
    normalize_platform,
)
from ceminiparlays.slips import EvaluatedLeg, EvaluatedSlip

PREDICTION_BANNER = (
    "PREDICTION COMBOS — product of independently settled binaries. "
    "Correlated NFL legs overstate EV; paper only."
)


def fair_card(
    player: str,
    stat: str,
    line: float,
    result: FairResult,
    side: str,
    fair_p: float,
    shade_pp: float = 0.0,
) -> str:
    lines = [
        f"player: {player}",
        f"stat: {stat}",
        f"line: {line}",
        f"side: {side}",
        f"fair_p: {fair_p:.4f}",
        f"fair_p_over: {result.fair_p_over:.4f}",
        f"fair_p_under: {result.fair_p_under:.4f}",
    ]
    if result.fair_p_push > 0.0:
        lines.append(f"fair_p_push: {result.fair_p_push:.4f} (void on an exact hit)")
    lines.extend(
        [
            f"p_over_at_median: {result.fair_p_at_median:.4f} (diagnostic)",
            f"median: {result.median}",
            f"sigma: {result.sigma}",
            f"family: {result.family}",
        ]
    )
    if result.note:
        lines.append(f"warning: {result.note}")
    if shade_pp:
        lines.append(f"shade_pp: {shade_pp:g}")
    lines.append(STANDARD_DISCLAIMER)
    return "\n".join(lines)


def _ticket_suffix(slip: EvaluatedSlip) -> str:
    ticket_ids = {leg.line.ticket_id for leg in slip.legs if leg.line.ticket_id}
    return f" ticket={next(iter(ticket_ids))}" if len(ticket_ids) == 1 else ""


def _leg_line(leg: EvaluatedLeg) -> str:
    detail = f"fair_p={leg.fair_p:.3f}"
    if leg.implied_p > 0.0:
        detail += f" implied_p={leg.implied_p:.3f} edge={leg.edge:+.3f}"
    if leg.prop_edge is not None:
        detail += f" prop_edge={leg.prop_edge:+.4f}"
    else:
        detail += " prop_edge=na"
    leg_ticket = f" ticket={leg.line.ticket_id}" if leg.line.ticket_id else ""
    warn = f" [{leg.warn}]" if leg.warn else ""
    return (
        f"  {leg.line.player_name} {leg.line.side} {leg.line.line} "
        f"[{leg.line.stat_type}]{leg_ticket} {detail} via {leg.source}{warn}"
    )


def _joint_line(slip: EvaluatedSlip) -> str:
    independence = "copula" if abs(slip.p_joint - slip.p_naive) > 1e-4 else "independent"
    joint = f"  p_joint={slip.p_joint:.4f}"
    if slip.p_all_se > 0.0:
        joint += f" p_joint_se={slip.p_all_se:.4f}"
    return joint + f" p_naive={slip.p_naive:.4f} ({independence})"


def _price_text(slip: EvaluatedSlip, platform: str) -> str:
    """The multiplier, with an American price when the book settles in American odds."""

    source = slip.multiplier_source
    if slip.multiplier_unconfirmed:
        source += " unconfirmed"
    if platform in PREDICTION_PLATFORMS:
        return f"M={slip.multiplier:.4g} ({source} COMBOS)"
    if platform in SPORTSBOOK_PLATFORMS:
        try:
            american = decimal_to_american(slip.multiplier)
        except ValueError:
            return f"M={slip.multiplier:.4g} ({source})"
        sign = "+" if american > 0 else ""
        return f"M={slip.multiplier:.4g} ({sign}{american} {source})"
    return f"M={slip.multiplier:.4g} ({source})"


def _corr_lines(slip: EvaluatedSlip) -> list[str]:
    if not (slip.corr_repaired and slip.corr_clean is not None):
        return []
    lines = []
    for row_index, row in enumerate(slip.corr_clean):
        formatted = ", ".join(f"{value:+.3f}" for value in row)
        lines.append(f"  corr row {row_index}: [{formatted}]")
    return lines


def _slip_lines(index: int, slip: EvaluatedSlip) -> list[str]:
    platform = normalize_platform(slip.platform)
    kelly = "na (flex proxy suppressed)" if slip.mode.lower() == "flex" else f"{slip.kelly:.4f}"
    lines = [f"#{index} {slip.platform} {slip.mode} {len(slip.legs)}-leg{_ticket_suffix(slip)}"]
    lines.extend(_leg_line(leg) for leg in slip.legs)
    lines.append(_joint_line(slip))
    price = _price_text(slip, platform)
    lines.append(
        f"  {price} EV={slip.ev:+.3f} "
        f"EV_lo={slip.ev_lo:+.3f} quarter_kelly={kelly}"
    )
    lines.extend(f"  {note}" for note in slip.notes)
    lines.extend(_corr_lines(slip))
    if platform in PREDICTION_PLATFORMS and slip.multiplier_unconfirmed:
        lines.append(f"  {PREDICTION_BANNER}")
    lines.append("  do not submit — type the ticket in-app")
    lines.append("")
    return lines


def slip_card(slips: list[EvaluatedSlip], bankroll_note: str | None = None) -> str:
    if not slips:
        card = "No slips cleared the filters.\n" + STANDARD_DISCLAIMER
        return f"{bankroll_note}\n{card}" if bankroll_note else card
    lines = ["CeminiParlays slip card", ""]
    for index, slip in enumerate(slips, start=1):
        lines.extend(_slip_lines(index, slip))
    if bankroll_note:
        lines.append(bankroll_note)
    lines.append(STANDARD_DISCLAIMER)
    return "\n".join(lines)
