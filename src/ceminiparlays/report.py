from __future__ import annotations

from ceminiparlays import STANDARD_DISCLAIMER
from ceminiparlays.fair import FairResult
from ceminiparlays.odds import decimal_to_american
from ceminiparlays.payouts import (
    PREDICTION_PLATFORMS,
    SPORTSBOOK_PLATFORMS,
    normalize_platform,
)
from ceminiparlays.slips import EvaluatedSlip

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


def slip_card(slips: list[EvaluatedSlip], bankroll_note: str | None = None) -> str:
    if not slips:
        card = "No slips cleared the filters.\n" + STANDARD_DISCLAIMER
        if bankroll_note:
            card = f"{bankroll_note}\n{card}"
        return card
    lines = ["CeminiParlays slip card", ""]
    for index, slip in enumerate(slips, start=1):
        independence = "copula" if abs(slip.p_joint - slip.p_naive) > 1e-4 else "independent"
        is_flex = slip.mode.lower() in {"flex"}
        ticket_ids = {leg.line.ticket_id for leg in slip.legs if leg.line.ticket_id}
        ticket = f" ticket={next(iter(ticket_ids))}" if len(ticket_ids) == 1 else ""
        lines.append(f"#{index} {slip.platform} {slip.mode} {len(slip.legs)}-leg{ticket}")
        for leg in slip.legs:
            warn = f" [{leg.warn}]" if leg.warn else ""
            detail = f"fair_p={leg.fair_p:.3f}"
            if leg.implied_p > 0.0:
                detail += f" implied_p={leg.implied_p:.3f} edge={leg.edge:+.3f}"
            leg_ticket = f" ticket={leg.line.ticket_id}" if leg.line.ticket_id else ""
            lines.append(
                f"  {leg.line.player_name} {leg.line.side} {leg.line.line} "
                f"[{leg.line.stat_type}]{leg_ticket} {detail} via {leg.source}{warn}"
            )
        joint = f"  p_joint={slip.p_joint:.4f}"
        if slip.p_all_se > 0.0:
            joint += f" p_joint_se={slip.p_all_se:.4f}"
        joint += f" p_naive={slip.p_naive:.4f} ({independence})"
        lines.append(joint)
        source = slip.multiplier_source
        if slip.multiplier_unconfirmed:
            source += " unconfirmed"
        kelly = "na (flex proxy suppressed)" if is_flex else f"{slip.kelly:.4f}"
        price = f"M={slip.multiplier:.4g} ({source})"
        if normalize_platform(slip.platform) in SPORTSBOOK_PLATFORMS:
            try:
                american = decimal_to_american(slip.multiplier)
                sign = "+" if american > 0 else ""
                price = f"M={slip.multiplier:.4g} ({sign}{american} {source})"
            except ValueError:
                pass
        elif normalize_platform(slip.platform) in PREDICTION_PLATFORMS:
            price = f"M={slip.multiplier:.4g} ({source} COMBOS)"
        lines.append(
            f"  {price} EV={slip.ev:+.3f} "
            f"EV_lo={slip.ev_lo:+.3f} quarter_kelly={kelly}"
        )
        for note in slip.notes:
            lines.append(f"  {note}")
        if slip.corr_repaired and slip.corr_clean is not None:
            for row_index, row in enumerate(slip.corr_clean):
                formatted = ", ".join(f"{value:+.3f}" for value in row)
                lines.append(f"  corr row {row_index}: [{formatted}]")
        if (
            normalize_platform(slip.platform) in PREDICTION_PLATFORMS
            and slip.multiplier_unconfirmed
        ):
            lines.append(f"  {PREDICTION_BANNER}")
        lines.append("  do not submit — type the ticket in-app")
        lines.append("")
    if bankroll_note:
        lines.append(bankroll_note)
    lines.append(STANDARD_DISCLAIMER)
    return "\n".join(lines)
