"""Week 11 card: live Hard Rock lines, fail-closed guards, $18 remainder."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from ceminiparlays.card_sync import default_sync_roots, sync_dated_card
from ceminiparlays.resources import REPO_ROOT
from ceminiparlays.sunday_card import norm_name
from ceminiparlays.week11_card import (
    BANKROLL_CENTS,
    BOOKED_LEGS,
    CARD_CSV,
    CARD_MD,
    ENTERED_PATH,
    ENV_PATH,
    HOLD_PATH,
    LIVE_PATH,
    MAX_LEG_REUSE,
    RATES_PATH,
    SCRATCH_PATH,
    STARTERS_PATH,
    TEMPLATE_PATH,
    TEMPLATE_ROWS,
    LiveLinesMissingError,
    PricedLeg,
    TeamTotalAsPlayerError,
    _rates,
    _starters,
    allocated_cents,
    assert_mean_not_team_total,
    build_tickets,
    decision_legs,
    format_leg_table,
    load_live_lines,
    pricing_source,
    qb_check_failures,
    render_csv,
    render_entered,
    render_markdown,
    screen_pool,
    shift_fair_over,
    team_level_totals,
    unallocated_cents,
    write_hardrock_template,
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


def _quote(book: str, player: str, market: str, side: str, line: float, odds: int, game: str) -> dict[str, str]:
    return {
        "bookmaker": book,
        "player": player,
        "market": market,
        "side": side,
        "line": f"{line:.1f}",
        "american_odds": str(odds),
        "timestamp": "2026-11-22T00:00:00Z",
        "game": game,
    }


def _two_way(book: str, player: str, market: str, line: float, over: int, under: int, game: str) -> list[dict[str, str]]:
    return [
        _quote(book, player, market, "over", line, over, game),
        _quote(book, player, market, "under", line, under, game),
    ]


def _skewed_prop(player: str, game: str) -> list[dict[str, str]]:
    """Hard Rock -115. Two other books are short the over, so the over is +EV."""

    rows: list[dict[str, str]] = []
    rows.extend(_two_way("hardrockbet", player, "player_rush_yds", 70.5, -115, -115, game))
    rows.extend(_two_way("draftkings", player, "player_rush_yds", 70.5, -150, 130, game))
    rows.extend(_two_way("fanduel", player, "player_rush_yds", 70.5, -150, 130, game))
    return rows


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


def test_missing_live_lines_fail_closed(tmp_path: Path) -> None:
    missing = tmp_path / "live_lines.csv"
    with pytest.raises(LiveLinesMissingError):
        load_live_lines(missing)
    empty = tmp_path / "empty.csv"
    empty.write_text(
        "bookmaker,player,market,side,line,american_odds,timestamp,game\n",
        encoding="utf-8",
    )
    with pytest.raises(LiveLinesMissingError):
        load_live_lines(empty)
    blank = tmp_path / "blank.csv"
    blank.write_text(
        "bookmaker,player,market,side,line,american_odds,timestamp,game\n"
        "hardrockbet,Jonah Coleman,player_rush_yds,over,,,-,\n",
        encoding="utf-8",
    )
    with pytest.raises(LiveLinesMissingError):
        load_live_lines(blank)


def test_mean_equal_to_a_team_total_fails_closed() -> None:
    totals = team_level_totals(_rates(RATES_PATH))
    blend = (91.4 + 151.1) / 2.0
    assert abs(blend - 121.25) < 1e-9
    assert any(abs(item - 121.25) <= 0.01 for item in totals)
    with pytest.raises(TeamTotalAsPlayerError):
        assert_mean_not_team_total("Jonah Coleman", blend, totals)
    with pytest.raises(TeamTotalAsPlayerError):
        shift_fair_over(
            "Jonah Coleman",
            "rush_yds",
            122.5,
            [
                ("draftkings", 121.25, -110, -110),
                ("fanduel", 121.25, -110, -110),
            ],
            totals,
        )


def test_single_book_does_not_invent_a_price() -> None:
    rows = _two_way("hardrockbet", "Jonah Coleman", "player_rush_yds", 71.5, -115, -115, "LV@DEN")
    pool = screen_pool(rows=rows)
    leg = pool["jonah coleman|rush_yds|over"]
    assert leg.line == 71.5
    assert leg.reason == "NO_CONSENSUS"
    assert not leg.ok
    assert build_tickets(pool) == []


def test_same_line_plus_ev_can_fill_three_six_dollar_tickets() -> None:
    games = ["MIA@BUF", "NO@CHI", "TEN@DAL", "TB@DET", "ARI@KC", "PIT@PHI"]
    rows: list[dict[str, str]] = []
    for index, game in enumerate(games):
        rows.extend(_skewed_prop(f"Test Back {index}", game))
    pool = screen_pool(rows=rows)
    overs = [leg for leg in pool.values() if leg.side == "over" and leg.player.startswith("Test Back")]
    assert overs
    assert all(leg.ok for leg in overs)
    assert all((leg.edge or 0.0) >= 0.02 for leg in overs)
    tickets = build_tickets(pool)
    assert len(tickets) == 3
    assert allocated_cents(tickets) == 1800
    assert unallocated_cents(tickets) == 0
    assert BANKROLL_CENTS == 1800
    seen: set[tuple[str, str, str]] = set()
    for ticket in tickets:
        assert int(ticket["stake_cents"]) == 600
        legs = ticket["legs"]
        assert isinstance(legs, list)
        assert 2 <= len(legs) <= 3
        for leg in legs:
            key = (norm_name(leg.player), leg.market, leg.side)
            assert key not in seen
            seen.add(key)
            assert (norm_name(leg.player), leg.market) not in BOOKED_LEGS
    assert max(1, len(seen)) >= 1
    assert len(seen) == sum(len(ticket["legs"]) for ticket in tickets)


def test_live_card_uses_book_lines_and_skips_booked_legs(built) -> None:
    pool, tickets = built
    coleman = pool["jonah coleman|rush_yds|over"]
    lawrence = pool["trevor lawrence|pass_yds|under"]
    assert coleman.line == 71.5
    assert coleman.book_american == -115
    assert "121.25" not in coleman.note
    assert "LEAGUE_SLATE_MEDIAN" not in coleman.note
    assert coleman.mean is None or abs(coleman.mean - 121.25) > 0.01
    assert coleman.reason != "OK"
    assert lawrence.line == 232.5
    assert lawrence.line != 217.5
    assert lawrence.reason != "OK"
    gibbs = pool["jahmyr gibbs|rush_yds_q4|over"]
    assert gibbs.reason == "NO_QUARTER_BOOK"
    assert gibbs.line is None
    booked = {leg.leg_id for ticket in tickets for leg in ticket["legs"]}
    for player, market in BOOKED_LEGS:
        assert f"{player}|{market}|over" not in booked
        assert f"{player}|{market}|under" not in booked
    assert 3 <= len(tickets) <= 4
    assert allocated_cents(tickets) == 1800
    assert unallocated_cents(tickets) == 0
    for ticket in tickets:
        assert int(ticket["stake_cents"]) in {300, 400, 500, 600}
        assert float(ticket["ev"]) > 0.0
        assert not ticket.get("best_available")
        legs = ticket["legs"]
        assert 2 <= len(legs) <= 3
        for leg in legs:
            assert leg.ok
            assert leg.market != "rush_yds_q4"
            assert leg.market != "total_q3"
            if leg.market == "receptions_q4":
                assert "Q4_POISSON_MODEL" in leg.note
                assert leg.line is not None
            assert norm_name(leg.player) not in HARD_EXCLUDE
            assert norm_name(leg.player) not in QUESTIONABLE
            assert "LEAGUE_SLATE_MEDIAN" not in leg.note
            assert leg.line not in {112.85, 11.10, 14.5}
    assert allocated_cents(tickets) + unallocated_cents(tickets) == 1800
    assert MAX_LEG_REUSE == 1
    breece = pool["breece hall|rec_yds|under"]
    assert breece.line == 21.5
    assert breece.book_american == -115
    assert breece.reason == "OK"
    assert pricing_source(breece) == "LINE_SHIFT_DEVIG"
    assert (breece.edge or 0.0) > 0.0
    header = format_leg_table(decision_legs(pool)).splitlines()[0]
    assert header == (
        "Player | Team | Market | Side | HR Line | HR Odds | Fair Odds | Edge % | Pricing Source"
    )
    failures = qb_check_failures(
        [leg for ticket in tickets for leg in ticket["legs"]],
        _starters(STARTERS_PATH),
    )
    assert failures == []
    mayfield = pool["baker mayfield|pass_yds|under"]
    assert mayfield.reason == "SATURDAY_HOLD"
    assert "mayfield" not in " ".join(leg.leg_id for ticket in tickets for leg in ticket["legs"])


def test_beck_pass_leg_fails_and_mayfield_does_not(built) -> None:
    pool, _tickets = built
    starters = _starters(STARTERS_PATH)
    beck = PricedLeg(
        "beck",
        "Carson Beck",
        "ARI",
        "KC",
        "pass_yds",
        "under",
        163.5,
        0.6,
        0.6,
        0.1,
        -150,
        15.5,
        "1:00 PM ET",
        "2026-11-22-ARI@KC",
        "OK",
        "",
    )
    failures = qb_check_failures([beck], starters)
    assert len(failures) == 1
    assert failures[0].startswith("FAIL_BACKUP_QB")
    assert qb_check_failures([pool["baker mayfield|pass_yds|under"]], starters) == []
    johnson = pool["josh johnson|pass_yds|under"]
    assert johnson.reason == "BOOKED"
    assert qb_check_failures([johnson], starters) == []


def test_builder_source_has_no_slate_median_path() -> None:
    source = (REPO_ROOT / "src" / "ceminiparlays" / "week11_card.py").read_text(encoding="utf-8")
    assert "_full_game_mean" not in source
    assert "clip_main_line_prob" not in source
    assert "LEAGUE_SLATE_MEDIAN" not in source
    assert "Q4_RUSH_LINE" not in source
    assert "REF_PRICE" not in source


def test_template_is_twelve_blank_rows(tmp_path: Path) -> None:
    path = write_hardrock_template(tmp_path / "hardrock_lines_template_2026-11-22.csv")
    rows = _rows(path)
    assert len(rows) == 12
    assert len(TEMPLATE_ROWS) == 12
    assert rows[0]["line"] == ""
    assert rows[0]["american_odds"] == ""
    assert rows[0]["bookmaker"] == "hardrockbet"
    assert not TEMPLATE_PATH.exists()


def test_entered_ticket_shell_marks_the_slip_blank() -> None:
    text = render_entered()
    rows = list(csv.DictReader(text.splitlines()))
    assert len(rows) == 3
    assert {row["ticket_id"] for row in rows} == {"HR11-1"}
    assert rows[0]["stake_usd"] == "5.00"
    assert {row["line"] for row in rows} == {"FILL_FROM_SLIP"}
    assert {row["american_odds"] for row in rows} == {"FILL_FROM_SLIP"}
    markets = {(row["player_name"], row["market"], row["side"]) for row in rows}
    assert markets == {
        ("Josh Johnson", "pass_yds", "under"),
        ("James Cook III", "rush_yds", "over"),
        ("Jahmyr Gibbs", "rush_yds_q4", "over"),
    }


def test_written_card_matches_the_live_render(built) -> None:
    pool, tickets = built
    csv_text = render_csv(tickets)
    markdown = render_markdown(tickets, pool)
    assert "book_american_odds" in csv_text.splitlines()[0]
    assert "LEAGUE_SLATE_MEDIAN" not in markdown
    assert "112.85" not in markdown
    assert "Unallocated:" in markdown
    assert CARD_CSV.read_text(encoding="utf-8") == csv_text
    assert CARD_MD.read_text(encoding="utf-8") == markdown
    assert ENTERED_PATH.read_text(encoding="utf-8") == render_entered()
    slate = REPO_ROOT / "parlays-slate" / "2026-11-22"
    recap = REPO_ROOT / "parlays-recap" / "2026-11-22"
    assert (slate / "hardrock_card_2026-11-22.csv").read_text(encoding="utf-8") == csv_text
    assert (recap / "card_2026-11-22.md").read_text(encoding="utf-8") == markdown
    assert LIVE_PATH.is_file()


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
