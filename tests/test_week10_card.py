"""Week 10 card caps, script gates, and ticket-level Brier."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from ceminiparlays.compose import MAX_TICKETS_PER_PROP, joint_ticket
from ceminiparlays.copula import exact_joint
from ceminiparlays.environment import (
    EnvRow,
    fill_environment_from_odds_csv,
    write_compose_itt,
)
from ceminiparlays.grade_card import EXTRA_LEDGER_COLUMNS, grade_rows
from ceminiparlays.io import OUT_STATUSES
from ceminiparlays.q4_checkdown import (
    CheckdownInputs,
    _route_share_ok,
    q4_rush_over_blocked,
    q4_rush_script_multiplier,
    q4_trail_market_rank,
    starter_rb,
    trail_receptions_over_allowed,
)
from ceminiparlays.sunday_card import norm_name
from ceminiparlays.week10_card import (
    BANKROLL_CENTS,
    CARD_PATH,
    DOC_PATH,
    GAME_CAP_CENTS,
    ODDS_PATH,
    PARLAY_CAP_CENTS,
    PLAYER_CAP_CENTS,
    SCRATCH_PATH,
    SINGLES_FLOOR_CENTS,
    TICKET_CAP_CENTS,
    build_card,
    build_pools,
    game_exposure,
    player_exposure,
    prop_counts,
)

ROOT = Path(__file__).resolve().parents[1]


def _inputs(**kwargs: object) -> CheckdownInputs:
    base = {
        "games": 6.0,
        "receptions_per_game": 4.0,
        "rec_yds_per_game": 32.0,
        "targets_per_game": 5.0,
        "opps_q": 12.0,
        "opps_total": 40.0,
        "q4_trail_target_share": 0.25,
        "vacated_target_boost": 0.0,
        "avg_cushion": None,
        "def_q4_comp_rate": None,
        "def_q4_yac": None,
        "league_trail_share": 0.25,
        "league_cushion": None,
        "league_comp": None,
        "league_yac": None,
        "quarter": 4,
    }
    base.update(kwargs)
    return CheckdownInputs(**base)  # type: ignore[arg-type]


def _grade_row(
    ticket: str,
    leg_num: int,
    status: str,
    joint: float,
    marginal: float,
    stake: str = "1.00",
) -> dict[str, str]:
    return {
        "ticket_id": ticket,
        "leg_num": str(leg_num),
        "line": "14.5",
        "side": "over",
        "model_prob": f"{joint:.4f}",
        "leg_model_prob": f"{marginal:.4f}",
        "leg_status": status,
        "ticket_stake_usd": stake,
        "book_american_odds": "-110",
        "market": "rush_yds_q4",
    }


@pytest.fixture(scope="module")
def card():
    tickets, problems, pools = build_card()
    assert problems == []
    return tickets, pools


def test_constants_and_stake_split(card) -> None:
    tickets, _pools = card
    assert BANKROLL_CENTS == 1800
    assert SINGLES_FLOOR_CENTS >= 1170
    assert PARLAY_CAP_CENTS <= 630
    assert GAME_CAP_CENTS <= 450
    assert PLAYER_CAP_CENTS <= 450
    assert TICKET_CAP_CENTS <= 250
    assert MAX_TICKETS_PER_PROP == 2
    assert sum(ticket.stake_cents for ticket in tickets) == 1800
    singles = sum(ticket.stake_cents for ticket in tickets if len(ticket.legs) == 1)
    parlays = sum(ticket.stake_cents for ticket in tickets if len(ticket.legs) > 1)
    assert singles >= SINGLES_FLOOR_CENTS
    assert parlays <= PARLAY_CAP_CENTS
    assert singles + parlays == 1800
    assert all(ticket.stake_cents <= TICKET_CAP_CENTS for ticket in tickets)
    assert all(cents <= GAME_CAP_CENTS for cents in game_exposure(tickets).values())
    assert all(cents <= PLAYER_CAP_CENTS for cents in player_exposure(tickets).values())
    assert all(count <= MAX_TICKETS_PER_PROP for count in prop_counts(tickets).values())
    assert len(tickets) == 13


def test_bench_rb1_q4_rush_over_stays_off_the_card(card) -> None:
    tickets, _pools = card
    assert starter_rb("James Cook III", 2) is True
    assert q4_rush_script_multiplier(-8.5, is_starter_rb=True) == 0.68
    assert q4_rush_over_blocked(-8.5, is_starter_rb=True) is True
    assert q4_rush_over_blocked(-9.5, starter_rb("Kyren Williams", 1)) is True
    assert q4_rush_over_blocked(-10.5, starter_rb("Bhayshul Tuten", 1)) is True
    assert q4_rush_script_multiplier(-4.5) == 1.08
    assert q4_rush_script_multiplier(-3.0) == 1.08
    assert q4_rush_script_multiplier(-2.5) == 1.00
    assert q4_rush_script_multiplier(6.5) == 1.00
    assert q4_rush_over_blocked(6.5) is False
    assert q4_rush_script_multiplier(7.0) is None
    assert q4_rush_over_blocked(7.0) is True
    blocked = {"james cook", "kyren williams", "bhayshul tuten"}
    for ticket in tickets:
        for leg in ticket.legs:
            name = norm_name(str(leg["player_name"]))
            if name in blocked:
                assert not (leg["market"] == "rush_yds_q4" and leg["side"] == "over")
    legs = [leg for ticket in tickets for leg in ticket.legs]
    assert any(
        norm_name(leg["player_name"]) == "james cook" and leg["market"] == "rush_yds" for leg in legs
    )
    assert any(norm_name(leg["player_name"]) == "braelon allen" for leg in legs)
    assert all(norm_name(leg["player_name"]) != "kenneth walker" for leg in legs)
    assert all(
        not (
            norm_name(leg["player_name"]) == "drew lock"
            and (str(leg["market"]).startswith("pass") or leg["market"] == "interceptions")
        )
        for leg in legs
    )
    assert all(leg["team"] not in {"NE", "DET"} and leg["opp"] not in {"NE", "DET"} for leg in legs)


def test_walker_stays_out_until_the_dnp_flag() -> None:
    held = build_pools(include_munich=False, allow_questionable_dnp=False)
    allowed = build_pools(include_munich=False, allow_questionable_dnp=True)
    held_names = {norm_name(leg["player_name"]) for leg in held["tier1"]}
    open_names = {norm_name(leg["player_name"]) for leg in allowed["tier1"]}
    assert "kenneth walker" not in held_names
    assert "kenneth walker" in open_names


def test_rank1_trail_catch_beats_a_named_rb2() -> None:
    allen = _inputs(
        spread=8.5,
        targets_per_game=2.5,
        games=8,
        third_down_route_share=None,
        target_share_rank=1,
        player_name="Braelon Allen",
    )
    davis = _inputs(
        spread=8.5,
        targets_per_game=4.0,
        games=8,
        third_down_route_share=0.80,
        target_share_rank=3,
        player_name="Isaiah Davis",
    )
    assert _route_share_ok(allen) is True
    assert _route_share_ok(davis) is False
    assert trail_receptions_over_allowed(8.5, 8, 2.5, 1, "Braelon Allen") is True
    assert trail_receptions_over_allowed(8.5, 8, 4.0, 3, "Isaiah Davis") is False
    assert trail_receptions_over_allowed(8.5, 6, 2.17, 1, "Tony Pollard") is True
    assert q4_trail_market_rank("receptions_q4", "over", 8.5) < q4_trail_market_rank(
        "rec_yds_q4", "over", 8.5
    )


def test_negative_rho_uses_the_lower_student_t_joint() -> None:
    corr = np.array([[1.0, -0.3], [-0.3, 1.0]])
    marginals = [0.55, 0.60]
    gaussian = exact_joint(marginals, corr, "gaussian")
    student = exact_joint(marginals, corr, "t", df=5)
    alias = exact_joint(marginals, corr, "student_t", df=5)
    ticket = joint_ticket(marginals, [-110, -110], corr)
    assert alias == pytest.approx(student)
    assert ticket["gaussian_joint_p"] == pytest.approx(gaussian)
    assert ticket["t_copula_joint_p"] == pytest.approx(student)
    assert ticket["joint_p"] == pytest.approx(min(float(gaussian), float(student)))
    eye = joint_ticket([0.5, 0.5], [100, 100], np.eye(2))
    assert eye["joint_p"] == pytest.approx(0.25, abs=1e-6)
    assert eye["t_copula_joint_p"] is not None


def test_ticket_brier_is_one_term_per_settled_ticket() -> None:
    assert "leg_model_prob" in EXTRA_LEDGER_COLUMNS
    rows = [
        _grade_row("multi", 1, "win", 0.30, 0.80),
        _grade_row("multi", 2, "win", 0.30, 0.70),
        _grade_row("single", 1, "win", 0.55, 0.55),
    ]
    grade = grade_rows(rows, [])
    multi = (0.30 - 1.0) ** 2
    single = (0.55 - 1.0) ** 2
    assert grade.settled_tickets == 2
    assert grade.brier == pytest.approx((multi + single) / 2.0)
    paper = grade_rows([_grade_row("paper", 1, "win", 0.40, 0.40, stake="TBD")], [])
    assert paper.stake == 0.0
    zero = grade_rows([_grade_row("paper", 1, "loss", 0.40, 0.40, stake="0.00")], [])
    assert zero.stake == 0.0


def test_scratch_file_blocks_never_enter_and_conflicts() -> None:
    rows = list(csv.DictReader(SCRATCH_PATH.open(encoding="utf-8")))
    never = [row for row in rows if str(row["token"]).strip().lower() in OUT_STATUSES]
    conflict = [
        row
        for row in rows
        if "CONFLICT" in str(row["label"]).upper() or "RESERVE_VS_HUB" in str(row["label"]).upper()
    ]
    assert len(rows) == 103
    assert len(never) == 89
    assert len(conflict) == 14
    names = {norm_name(row["player"]) for row in conflict}
    for name in (
        "puka nacua",
        "travis etienne",
        "chris brooks",
        "skyy moore",
        "xavier legette",
        "tyrell shavers",
        "hunter long",
    ):
        assert name in names
    assert norm_name("Travis Etienne Jr.") in names


def test_environment_odds_match_the_packet() -> None:
    rows = {
        (row["team"], row["opp"]): row
        for row in csv.DictReader(ODDS_PATH.open(encoding="utf-8"))
    }
    expected = {
        ("DET", "NE"): (-2.5, 26.0, 49.5),
        ("NE", "DET"): (2.5, 23.5, 49.5),
        ("KC", "ATL"): (-3.0, 25.25, 47.5),
        ("ATL", "KC"): (3.0, 22.25, 47.5),
        ("HOU", "CLE"): (-4.5, 22.5, 40.5),
        ("CLE", "HOU"): (4.5, 18.0, 40.5),
        ("GB", "MIN"): (-2.5, 22.5, 42.5),
        ("MIN", "GB"): (2.5, 20.0, 42.5),
        ("JAX", "TEN"): (-10.5, 28.5, 46.5),
        ("TEN", "JAX"): (10.5, 18.0, 46.5),
        ("IND", "MIA"): (-3.5, 21.0, 38.5),
        ("MIA", "IND"): (3.5, 17.5, 38.5),
        ("NO", "CAR"): (-2.5, 25.5, 48.5),
        ("CAR", "NO"): (2.5, 23.0, 48.5),
        ("BUF", "NYJ"): (-8.5, 29.5, 50.5),
        ("NYJ", "BUF"): (8.5, 21.0, 50.5),
        ("SEA", "LV"): (-6.5, 23.5, 40.5),
        ("LV", "SEA"): (6.5, 17.0, 40.5),
        ("LAR", "ARI"): (-9.5, 24.5, 39.5),
        ("ARI", "LAR"): (9.5, 15.0, 39.5),
        ("SF", "DAL"): (-4.5, 30.0, 55.5),
        ("DAL", "SF"): (4.5, 25.5, 55.5),
    }
    for key, (spread, implied, total) in expected.items():
        row = rows[key]
        assert float(row["spread"]) == spread
        assert float(row["implied_total"]) == implied
        assert float(row["over_under"]) == total


def test_odds_fill_does_not_touch_the_csv(tmp_path: Path) -> None:
    before = ODDS_PATH.read_bytes()
    env = {("HOU", "CLE"): EnvRow(game_id="hou-cle", team="HOU", opponent="CLE")}
    filled = fill_environment_from_odds_csv(env, ODDS_PATH)
    assert filled[("HOU", "CLE")].spread == -4.5
    assert filled[("HOU", "CLE")].implied_total == 22.5
    assert ODDS_PATH.read_bytes() == before
    out = tmp_path / "compose_itt.json"
    write_compose_itt(out, captured_at="2026-11-15T16:00:00Z", source=ODDS_PATH.name, rows=[filled[("HOU", "CLE")]])
    payload = out.read_text(encoding="utf-8")
    assert "22.5" in payload
    assert "-4.5" in payload


def test_saved_card_and_note(card) -> None:
    tickets, _pools = card
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "Do not submit" in text
    assert "REF_LADDER_NOT_BOOK" in text
    assert "Kenneth Walker" in text
    assert "Drew Lock" in text
    assert "Munich" in text
    assert "Student-t" in text
    assert "Brier" in text
    saved = list(csv.DictReader(CARD_PATH.open(encoding="utf-8")))
    stakes = {row["ticket_id"]: row["ticket_stake_usd"] for row in saved}
    assert {ticket.ticket_id: f"{ticket.stake_cents / 100:.2f}" for ticket in tickets} == stakes
    assert sum(round(float(stake) * 100) for stake in stakes.values()) == 1800
    assert any("t_copula_joint_p=" in ticket.note for ticket in tickets)
    assert any("[WIND_REVIEW_NOTE]" in ticket.note for ticket in tickets)
    assert ROOT.joinpath("src/ceminiparlays/week10_card.py").is_file()
