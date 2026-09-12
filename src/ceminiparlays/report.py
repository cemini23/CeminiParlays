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
) -> str:
    return "\n".join(
        [
            f"player: {player}",
            f"stat: {stat}",
            f"line: {line}",
            f"side: {side}",
            f"fair_p: {fair_p:.4f}",
            f"fair_p_over: {result.fair_p_over:.4f}",
            f"fair_p_under: {result.fair_p_under:.4f}",
            f"median: {result.median}",
            f"sigma: {result.sigma}",
            f"family: {result.family}",
            STANDARD_DISCLAIMER,
        ]
    )


def slip_card(slips: list[EvaluatedSlip]) -> str:
    if not slips:
        return "No slips cleared the filters.\n" + STANDARD_DISCLAIMER
    lines = ["CeminiParlays slip card", ""]
    for index, slip in enumerate(slips, start=1):
        independence = "copula" if abs(slip.p_joint - slip.p_naive) > 1e-4 else "independent"
        lines.append(f"#{index} {slip.platform} {slip.mode} {len(slip.legs)}-leg")
        for leg in slip.legs:
            warn = f" [{leg.warn}]" if leg.warn else ""
            lines.append(
                f"  {leg.line.player_name} {leg.line.side} {leg.line.line} "
                f"{leg.line.stat_type} fair_p={leg.fair_p:.3f} via {leg.source}{warn}"
            )
        lines.append(
            f"  p_joint={slip.p_joint:.4f} p_naive={slip.p_naive:.4f} ({independence})"
        )
        lines.append(
            f"  M={slip.multiplier} EV={slip.ev:+.3f} quarter_kelly={slip.kelly:.4f}"
        )
        lines.append("  do not submit — type the ticket in-app")
        lines.append("")
    lines.append(STANDARD_DISCLAIMER)
    return "\n".join(lines)
