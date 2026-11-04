from __future__ import annotations

import numpy as np

from ceminiparlays import STANDARD_DISCLAIMER
from ceminiparlays.fair import FairResult
from ceminiparlays.io import LineRow
from ceminiparlays.report import PREDICTION_BANNER, fair_card, slip_card
from ceminiparlays.slips import EvaluatedLeg, EvaluatedSlip


def _leg(
    name: str,
    side: str,
    line: float,
    stat: str,
    *,
    platform: str = "hardrock",
    warn: str = "",
    implied: float = 0.5,
    edge: float = 0.02,
    prop_edge: float | None = 0.01,
    ticket: str = "",
) -> EvaluatedLeg:
    row = LineRow(
        slate_id="s1",
        platform=platform,
        player_name=name,
        player_key=name.lower().replace(" ", "_"),
        team="KC",
        opponent="BUF",
        stat_type=stat,
        line=line,
        side=side,
        line_type="over_under",
        captured_at="2026-11-03T12:00:00Z",
        displayed_multiplier=None,
        injury_status="",
        book_over=-110,
        book_under=-110,
        ticket_id=ticket,
    )
    return EvaluatedLeg(
        line=row,
        fair_p=0.55,
        implied_p=implied,
        edge=edge,
        source="model",
        family="normal",
        median=line,
        warn=warn,
        prop_edge=prop_edge,
    )


def _sportsbook_slip() -> EvaluatedSlip:
    return EvaluatedSlip(
        legs=[
            _leg("Patrick Mahomes", "over", 275.5, "pass_yds", ticket="T1"),
            _leg("Travis Kelce", "over", 55.5, "rec_yds", warn="questionable", ticket="T1"),
        ],
        p_joint=0.32,
        p_naive=0.30,
        ev=0.11,
        kelly=0.021,
        mode="power",
        multiplier=6.2,
        platform="hardrock",
        p_all_se=0.01,
        ev_lo=0.05,
        multiplier_source="table",
        corr_repaired=True,
        corr_clean=np.array([[1.0, -0.25], [-0.25, 1.0]]),
        notes=["pickem hurdle 45.5"],
    )


def test_slip_card_lays_out_a_sportsbook_slip() -> None:
    expected = (
        "CeminiParlays slip card\n"
        "\n"
        "#1 hardrock power 2-leg ticket=T1\n"
        "  Patrick Mahomes over 275.5 [pass_yds] ticket=T1 "
        "fair_p=0.550 implied_p=0.500 edge=+0.020 prop_edge=+0.0100 via model\n"
        "  Travis Kelce over 55.5 [rec_yds] ticket=T1 "
        "fair_p=0.550 implied_p=0.500 edge=+0.020 prop_edge=+0.0100 "
        "via model [questionable]\n"
        "  p_joint=0.3200 p_joint_se=0.0100 p_naive=0.3000 (copula)\n"
        "  M=6.2 (+520 table) EV=+0.110 EV_lo=+0.050 quarter_kelly=0.0210\n"
        "  pickem hurdle 45.5\n"
        "  corr row 0: [+1.000, -0.250]\n"
        "  corr row 1: [-0.250, +1.000]\n"
        "  do not submit — type the ticket in-app\n"
        "\n"
        "bankroll $1000\n"
        f"{STANDARD_DISCLAIMER}"
    )
    assert slip_card([_sportsbook_slip()], bankroll_note="bankroll $1000") == expected


def test_slip_card_marks_a_prediction_combo_and_withholds_flex_kelly() -> None:
    slip = EvaluatedSlip(
        legs=[_leg("A B", "over", 10.5, "rec_yds", platform="kalshi", prop_edge=None)],
        p_joint=0.5,
        p_naive=0.5,
        ev=0.01,
        kelly=0.0,
        mode="flex",
        multiplier=2.5,
        platform="kalshi",
        multiplier_source="table",
        multiplier_unconfirmed=True,
    )
    expected = (
        "CeminiParlays slip card\n"
        "\n"
        "#1 kalshi flex 1-leg\n"
        "  A B over 10.5 [rec_yds] fair_p=0.550 implied_p=0.500 edge=+0.020 "
        "prop_edge=na via model\n"
        "  p_joint=0.5000 p_naive=0.5000 (independent)\n"
        "  M=2.5 (table unconfirmed COMBOS) EV=+0.010 EV_lo=+0.000 "
        "quarter_kelly=na (flex proxy suppressed)\n"
        f"  {PREDICTION_BANNER}\n"
        "  do not submit — type the ticket in-app\n"
        "\n"
        f"{STANDARD_DISCLAIMER}"
    )
    assert slip_card([slip]) == expected


def test_slip_card_omits_the_american_price_when_the_multiplier_is_too_low() -> None:
    slip = EvaluatedSlip(
        legs=[_leg("C D", "under", 4.5, "rec_yds", platform="fanduel", implied=0.0, prop_edge=None)],
        p_joint=0.5,
        p_naive=0.5,
        ev=-0.02,
        kelly=0.0,
        mode="power",
        multiplier=1.0,
        platform="fanduel",
        multiplier_source="legs",
    )
    card = slip_card([slip])
    assert "  M=1 (legs) EV=-0.020 EV_lo=+0.000 quarter_kelly=0.0000\n" in card


def test_slip_card_with_no_slips_keeps_the_boundary() -> None:
    card = slip_card([])
    assert card == "No slips cleared the filters.\n" + STANDARD_DISCLAIMER


def test_slip_card_with_no_slips_leads_with_the_bankroll_note() -> None:
    card = slip_card([], bankroll_note="note")
    assert card == "note\nNo slips cleared the filters.\n" + STANDARD_DISCLAIMER


def test_slip_card_always_ends_with_the_disclaimer() -> None:
    card = slip_card([_sportsbook_slip()])
    assert card.endswith(STANDARD_DISCLAIMER)
    assert "do not submit" in card


def test_fair_card_reports_the_family_and_an_exact_hit_push() -> None:
    result = FairResult(
        fair_p_over=0.55,
        fair_p_under=0.45,
        median=45.5,
        sigma=18.2,
        family="normal",
        line=50.5,
        fair_p_push=0.01,
        note="thin sample",
    )
    card = fair_card("A B", "rec_yds", 50.5, result, "over", 0.55, shade_pp=2.0)
    lines = card.splitlines()
    assert lines[0] == "player: A B"
    assert lines[4] == "fair_p: 0.5500"
    assert "fair_p_push: 0.0100 (void on an exact hit)" in lines
    assert "family: normal" in lines
    assert "warning: thin sample" in lines
    assert "shade_pp: 2" in lines
    assert card.endswith(STANDARD_DISCLAIMER)


def test_fair_card_omits_push_and_shade_when_absent() -> None:
    result = FairResult(
        fair_p_over=0.55,
        fair_p_under=0.45,
        median=45.5,
        sigma=18.2,
        family="normal",
        line=50.5,
    )
    card = fair_card("A B", "rec_yds", 50.5, result, "over", 0.55)
    assert "fair_p_push" not in card
    assert "shade_pp" not in card
    assert "warning:" not in card
