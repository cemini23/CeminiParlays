from __future__ import annotations

from ceminiparlays import STANDARD_DISCLAIMER
from ceminiparlays.fair import FairResult
from ceminiparlays.slips import EvaluatedSlip


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


def slip_card(slips: list[EvaluatedSlip]) -> str:
    if not slips:
        return "No slips cleared the filters.\n" + STANDARD_DISCLAIMER
    lines = ["CeminiParlays slip card", ""]
    for index, slip in enumerate(slips, start=1):
        independence = "copula" if abs(slip.p_joint - slip.p_naive) > 1e-4 else "independent"
        is_flex = slip.mode.lower() in {"flex"}
        lines.append(f"#{index} {slip.platform} {slip.mode} {len(slip.legs)}-leg")
        for leg in slip.legs:
            warn = f" [{leg.warn}]" if leg.warn else ""
            lines.append(
                f"  {leg.line.player_name} {leg.line.side} {leg.line.line} "
                f"{leg.line.stat_type} fair_p={leg.fair_p:.3f} via {leg.source}{warn}"
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
        lines.append(
            f"  M={slip.multiplier} ({source}) EV={slip.ev:+.3f} "
            f"EV_lo={slip.ev_lo:+.3f} quarter_kelly={kelly}"
        )
        for note in slip.notes:
            lines.append(f"  {note}")
        if slip.corr_repaired and slip.corr_clean is not None:
            for row_index, row in enumerate(slip.corr_clean):
                formatted = ", ".join(f"{value:+.3f}" for value in row)
                lines.append(f"  corr row {row_index}: [{formatted}]")
        lines.append("  do not submit — type the ticket in-app")
        lines.append("")
    lines.append(STANDARD_DISCLAIMER)
    return "\n".join(lines)
