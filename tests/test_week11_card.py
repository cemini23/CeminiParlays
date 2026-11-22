"""Week 11 Saturday card: $23 bankroll, holds, and model fair prices."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import pytest

from ceminiparlays.card_sync import default_sync_roots, sync_dated_card
from ceminiparlays.resources import REPO_ROOT
from ceminiparlays.sunday_card import norm_name
from ceminiparlays.week11_card import (
    BANKROLL_CENTS,
    CARD_CSV,
    CARD_MD,
    ENV_PATH,
    HOLD_PATH,
    LEG_EXPOSURE_CAP_CENTS,
    MAX_LEG_REUSE,
    PricedLeg,
    SCRATCH_PATH,
    STARTERS_PATH,
    _starters,
    build_tickets,
    qb_check_failures,
    render_csv,
    render_markdown,
    screen_pool,
)

HARD_EXCLUDE = {
    "carson beck",
    "tyjae spears",
    "jonathon brooks",
    "michael pittman",
    "kenneth walker",
    "jake ferguson",
    "jonathan mingo",
    "dalton kincaid",
    "dontayvion wicks",
    "omar cooper",
    "isaiah williams",
}
QUESTIONABLE = {
    "baker mayfield",
    "brock bowers",
    "ladd mcconkey",
    "luke schoonmaker",
    "darren waller",
    "tommy tremble",
    "carnell tate",
    "charlie kolar",
    "will shipley",
}


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def built():
    pool = screen_pool()
    tickets = build_tickets(pool)
    return pool, tickets


def test_environment_odds_fill_every_sunday_row() -> None:
    env = _rows(ENV_PATH)
    odds = {row["team"]: row for row in _rows(ENV_PATH.parent / "environment_odds_2026-11-22.csv")}
    assert len(env) == 20
    assert len(odds) == 20
    for row in env:
        assert row["spread"] != ""
        assert row["implied_total"] != ""
        assert row["spread"] == odds[row["team"]]["spread"]
        assert row["implied_total"] == odds[row["team"]]["implied_total"]
    by_team = {row["team"]: row for row in env}
    assert by_team["CHI"]["wind_mph"] == "15"
    assert by_team["CHI"]["precip_pop"] == "84"
    assert by_team["CHI"]["spread"] == "-11.5"
    assert by_team["DET"]["roof"] == "dome"
    assert by_team["DET"]["weather_exposed"] == "false"
    assert by_team["DET"]["wind_mph"] == ""
    assert by_team["BUF"]["spread"] == "-16.5"
    assert by_team["BUF"]["implied_total"] == "30.5"


def test_scratches_and_watchlist_cover_the_saturday_names() -> None:
    scratches = {norm_name(row["player"]): row["token"] for row in _rows(SCRATCH_PATH)}
    held = {norm_name(row["player"]) for row in _rows(HOLD_PATH)}
    assert set(scratches) >= HARD_EXCLUDE
    assert scratches["carson beck"] == "out"
    assert scratches["tyjae spears"] == "ir"
    assert scratches["jonathon brooks"] == "ir"
    assert scratches["michael pittman"] == "ir"
    assert scratches["kenneth walker"] == "out"
    assert scratches["dalton kincaid"] == "doubtful"
    assert held == QUESTIONABLE


def test_bankroll_caps_and_script_gates(built) -> None:
    _pool, tickets = built
    assert BANKROLL_CENTS == 2300
    assert LEG_EXPOSURE_CAP_CENTS == 805
    assert MAX_LEG_REUSE == 1
    assert 4 <= len(tickets) <= 6
    assert sum(int(ticket["stake_cents"]) for ticket in tickets) == 2300
    exposure: dict[str, int] = defaultdict(int)
    reuse: dict[tuple[str, str, str], int] = defaultdict(int)
    for ticket in tickets:
        legs = ticket["legs"]
        stake = int(ticket["stake_cents"])
        assert stake % 100 == 0
        assert 2 <= len(legs) <= 3
        if ticket["same_game"]:
            assert stake in {200, 300}
        else:
            assert stake in {400, 500, 600}
        assert ticket["unmodeled"] is False
        assert ticket["fair_american"] not in range(-99, 100)
        players = set()
        for leg in legs:
            assert leg.ok
            assert leg.fair_american is not None
            assert leg.fair_american not in range(-99, 100)
            name = norm_name(leg.player)
            assert name not in HARD_EXCLUDE
            assert name not in QUESTIONABLE
            assert leg.market != "first_td"
            reuse[(name, leg.market, leg.side)] += 1
            players.add(name)
            if leg.market == "rush_yds_q4" and leg.side == "over":
                assert leg.spread is not None
                assert -7.5 <= leg.spread <= -3.0
            if leg.market == "receptions_q4":
                assert leg.spread is not None and leg.spread >= 7.0
        for player in players:
            exposure[player] += stake
    assert max(reuse.values()) <= MAX_LEG_REUSE
    assert max(exposure.values()) <= LEG_EXPOSURE_CAP_CENTS
    failures = qb_check_failures(
        [leg for ticket in tickets for leg in ticket["legs"]],
        _starters(STARTERS_PATH),
    )
    assert failures == []


def test_published_fair_prices(built) -> None:
    pool, tickets = built
    by_id = {ticket["ticket_id"]: ticket for ticket in tickets}
    assert [ticket["fair_american"] for ticket in tickets] == [282, 248, 130, 335, 130]
    assert int(by_id["HR11-5"]["stake_cents"]) == 300
    assert by_id["HR11-5"]["same_game"] is True
    assert pool["johnson_under"].fair_american == -150
    assert pool["lawrence_under"].fair_american == -194
    assert pool["coleman_rush"].fair_american == -137
    assert pool["pollard_rush"].fair_american == -170
    assert pool["kamara_rec"].fair_american == -172
    assert pool["milton_under"].reason == "OK"
    assert pool["milton_under"].fair_american == -134
    assert pool["allgeier_rec"].reason == "NO_EDGE"
    assert pool["dak_over"].reason == "ROOF_CHECK"
    assert pool["lamb_over"].reason == "NO_PLAYER_RATE"
    assert pool["pickens_over"].reason == "NO_PLAYER_RATE"
    assert pool["mayfield_under"].reason == "SATURDAY_HOLD"
    assert pool["mayfield_under"].fair_american == -194
    staked = {leg.leg_id for ticket in tickets for leg in ticket["legs"]}
    assert "mayfield_under" not in staked
    assert "dak_over" not in staked
    assert "pollard_rec" not in staked


def test_beck_pass_leg_fails_and_mayfield_does_not(built) -> None:
    pool, _tickets = built
    starters = _starters(STARTERS_PATH)
    beck = PricedLeg(
        "beck_under",
        "Carson Beck",
        "ARI",
        "KC",
        "pass_yds",
        "under",
        217.5,
        0.6,
        0.6,
        0.1,
        -150,
        15.5,
        "1:00 PM ET",
        "ARI@KC",
        "OK",
        "",
    )
    failures = qb_check_failures([beck], starters)
    assert len(failures) == 1
    assert failures[0].startswith("FAIL_BACKUP_QB")
    assert qb_check_failures([pool["mayfield_under"]], starters) == []
    assert qb_check_failures([pool["johnson_under"]], starters) == []


def test_written_card_has_no_book_price_column(built) -> None:
    pool, tickets = built
    csv_text = render_csv(tickets)
    markdown = render_markdown(tickets, pool)
    header = csv_text.splitlines()[0]
    assert "book_american_odds" not in header
    assert "fair_american" in header
    assert CARD_CSV.read_text(encoding="utf-8") == csv_text
    assert CARD_MD.read_text(encoding="utf-8") == markdown
    for name in (
        "Baker Mayfield",
        "Brock Bowers",
        "Ladd McConkey",
        "Luke Schoonmaker",
        "Darren Waller",
        "Tommy Tremble",
        "Carnell Tate",
        "Charlie Kolar",
        "Will Shipley",
    ):
        assert name in markdown
    slate = REPO_ROOT / "parlays-slate" / "2026-11-22"
    recap = REPO_ROOT / "parlays-recap" / "2026-11-22"
    assert (slate / "hardrock_card_2026-11-22.csv").read_text(encoding="utf-8") == csv_text
    assert (recap / "card_2026-11-22.md").read_text(encoding="utf-8") == markdown


def test_sync_copies_both_names_and_skips_a_missing_workspace(tmp_path: Path) -> None:
    csv_path = tmp_path / "hardrock_card_2026-11-22.csv"
    md_path = tmp_path / "card_2026-11-22.md"
    csv_path.write_text("ticket\n", encoding="utf-8")
    md_path.write_text("# card\n", encoding="utf-8")
    written = sync_dated_card(
        csv_path,
        md_path,
        "2026-11-22",
        [tmp_path / "parlays-slate", tmp_path / "parlays-recap"],
    )
    assert len(written) == 4
    assert (tmp_path / "parlays-slate" / "2026-11-22" / csv_path.name).read_text() == "ticket\n"
    assert (tmp_path / "parlays-recap" / "2026-11-22" / md_path.name).read_text() == "# card\n"
    assert all(not str(path).startswith("/workspace") for path in default_sync_roots())
