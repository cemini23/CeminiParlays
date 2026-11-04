"""Week-7 gates, the $25 card writer, and the blocked board."""

import csv

import pytest

from ceminiparlays.grade_card import LEDGER_COLUMNS
from ceminiparlays.jev_sizing import DollarPlay
from ceminiparlays.sunday_card import norm_name
from ceminiparlays.week7_card import (
    PlayView,
    WeekCard,
    WeekTicket,
    _BY_TEAMS,
    build_from_lines,
    candidate_plays,
    card_from_plays,
    confirmed_starters,
    exposure_cents,
    funnel_lines,
    game_for,
    gate_reason,
    is_sunday_kick,
    load_never,
    main,
    market_stem,
    pair_ok,
    price_scheme_line,
    render_blocked,
    render_card,
    same_game_slips,
    t90_flags,
    validate_week7,
    write_ledger,
)


def _leg(**kwargs: object) -> dict:
    base: dict = {
        "player_name": "Jordan Love",
        "player_key": "jordan_love",
        "team": "GB",
        "opp": "DET",
        "market": "pass_yds_q4",
        "side": "over",
        "line": 60.5,
        "position": "QB",
        "commence_time": "2026-10-25T20:25:00Z",
        "price": -110,
        "model_p": 0.62,
        "ev": 0.20,
        "game_id": "2026_07_GB_DET",
        "kick_et": "4:25 PM ET",
        "gsis_id": "",
    }
    base.update(kwargs)
    return base


_STARTERS = {
    "GB": "jordan_love",
    "BAL": "tyler_huntley",
    "CLE": "",
    "SF": "brock_purdy",
    "PIT": "aaron_rodgers",
    "DET": "jared_goff",
}


def test_sunday_window_and_required_scratches(tmp_path) -> None:
    assert is_sunday_kick("2026-10-25T13:30:00Z")
    assert is_sunday_kick("2026-10-25T20:25:00Z")
    assert not is_sunday_kick("2026-10-25T12:30:00Z")
    assert not is_sunday_kick("2026-10-25T21:05:00Z")
    assert not is_sunday_kick("2026-10-26T00:20:00Z")
    path = tmp_path / "scratches.csv"
    path.write_text("team,player,pos,token\nTEN,Calvin Ridley,WR,q\nTB,Emeka Egbuka,WR,out\n", encoding="utf-8")
    never = load_never(path)
    assert norm_name("Lamar Jackson") in never
    assert norm_name("De'Von Achane") in never
    assert norm_name("Emeka Egbuka") in never
    assert norm_name("Calvin Ridley") not in never
    with pytest.raises(ValueError):
        load_never(tmp_path / "missing.csv")


def test_gates_block_scratches_backups_cleveland_and_atlanta_wind() -> None:
    never = {norm_name("Lamar Jackson")}
    assert gate_reason(_leg(player_name="Lamar Jackson", player_key="lamar_jackson", team="BAL", opp="CIN"), never, _STARTERS)
    assert gate_reason(_leg(player_name="Malik Willis", player_key="malik_willis"), never, _STARTERS) == "backup_qb"
    assert gate_reason(_leg(player_name="Tyler Huntley", player_key="tyler_huntley", team="BAL", opp="CIN"), never, _STARTERS) is None
    assert gate_reason(_leg(player_name="Deshaun Watson", player_key="deshaun_watson", team="CLE", opp="TEN"), never, _STARTERS)
    sf = _leg(
        player_name="Brock Purdy",
        player_key="brock_purdy",
        team="SF",
        opp="ATL",
        market="pass_yds",
        commence_time="2026-10-25T17:00:00Z",
    )
    assert gate_reason(sf, never, _STARTERS) == "wind_pass_fade"
    check = _leg(
        player_name="Christian McCaffrey",
        player_key="christian_mccaffrey",
        team="SF",
        opp="ATL",
        market="receptions_q4",
        position="RB",
        commence_time="2026-10-25T17:00:00Z",
    )
    assert gate_reason(check, never, _STARTERS) is None
    late = _leg(commence_time="2026-10-26T00:20:00Z")
    assert gate_reason(late, never, _STARTERS) == "off_window"


def test_pair_rule_and_review_notes() -> None:
    same = _leg(player_key="kyren_williams", player_name="Kyren Williams", market="receptions_q4", position="RB")
    yards = _leg(player_key="kyren_williams", player_name="Kyren Williams", market="rec_yds_q4", position="RB")
    rush = _leg(player_key="kyren_williams", player_name="Kyren Williams", market="rush_yds_q4", position="RB")
    other = _leg(player_key="puka_nacua", player_name="Puka Nacua", market="rec_yds_q4", position="WR")
    assert not pair_ok(same, yards)
    assert pair_ok(same, rush)
    assert pair_ok(same, other)
    wind = t90_flags(_leg(team="PIT", opp="NO", market="pass_yds_q4", game_id="2026_07_PIT_NO"))
    assert "[WIND_REVIEW_NOTE]" in wind
    roof = t90_flags(_leg(team="DEN", opp="ARI", market="rush_yds_q4", position="RB", game_id="2026_07_DEN_ARI"))
    assert "roof TBD" in roof
    assert "Q confirm at inactives" in t90_flags(other)
    assert "Huntley confirmed starter" in t90_flags(
        _leg(player_name="Tyler Huntley", player_key="tyler_huntley", team="BAL", opp="CIN")
    )


def test_funnel_keeps_only_a_two_way_half_catch() -> None:
    rows = [
        {"player_key": "kyren_williams", "stat_type": "receptions_q4", "line": "3.5", "book_over": "-110", "book_under": "-110"},
        {"player_key": "kyren_williams", "stat_type": "receptions_q4", "line": "0.5", "book_over": "-110", "book_under": "-110"},
        {"player_key": "bijan_robinson", "stat_type": "receptions_q4", "line": "0.5", "book_over": "-110", "book_under": ""},
    ]
    kept = funnel_lines(rows)
    assert len(kept) == 1
    assert kept[0]["player_key"] == "kyren_williams"
    assert float(kept[0]["line"]) == 0.5


def test_scheme_over_needs_a_real_mean() -> None:
    hot = price_scheme_line(
        games=10,
        yards_per_game=100,
        def_rate=1.2,
        league_rate=1.0,
        line=70.5,
        book_over=-110,
        book_under=-110,
    )
    cold = price_scheme_line(
        games=10,
        yards_per_game=20,
        def_rate=1.0,
        league_rate=1.0,
        line=70.5,
        book_over=-110,
        book_under=-110,
    )
    assert hot is not None and hot["side"] == "over" and hot["ev"] >= 0.08
    assert cold is None
    assert price_scheme_line(
        games=0,
        yards_per_game=100,
        def_rate=1.2,
        league_rate=1.0,
        line=70.5,
        book_over=-110,
        book_under=-110,
    ) is None


def test_confirmed_starters_force_huntley_and_block_cleveland() -> None:
    rows = [
        {"player_name": "Lamar Jackson", "team": "BAL", "position": "QB", "pass_yds_per_game": 280},
        {"player_name": "Tyler Huntley", "team": "BAL", "position": "QB", "pass_yds_per_game": 90},
        {"player_name": "Cooper Rush", "team": "BAL", "position": "QB", "pass_yds_per_game": 140},
        {"player_name": "Dillon Gabriel", "team": "CLE", "position": "QB", "pass_yds_per_game": 200},
        {"player_name": "Jordan Love", "team": "GB", "position": "QB", "pass_yds_per_game": 260},
        {"player_name": "Malik Willis", "team": "GB", "position": "QB", "pass_yds_per_game": 40},
    ]
    never = {norm_name("Lamar Jackson"), norm_name("Dillon Gabriel")}
    starters = confirmed_starters(rows, never)
    assert starters["BAL"] == "tyler_huntley"
    assert starters["CLE"] == ""
    assert starters["GB"] == "jordan_love"


def _dollar(index: int, pool: str, keys: tuple[str, ...]) -> tuple[DollarPlay, PlayView]:
    game = f"g{index}"
    play = DollarPlay(
        play_id=f"{pool}{index}",
        pool=pool,
        game_ids=(game,),
        player_keys=keys,
        ev=0.20,
        model_p=0.33 if pool == "sgp" else 0.62,
        decimal_odds=1.91,
    )
    if pool == "sgp":
        legs = (
            _leg(player_name=keys[0], player_key=keys[0], market="pass_yds_q4", model_p=0.51, game_id=game),
            _leg(player_name=keys[1], player_key=keys[1], market="receptions_q4", position="RB", model_p=0.52, game_id=game),
        )
        book = "SGP not captured; haircut decimal 3.200"
        display = 0.33
    else:
        market = "receptions_q4" if pool == "checkdown" else "rush_yds_q4"
        legs = (_leg(player_name=keys[0], player_key=keys[0], market=market, position="RB", model_p=0.62, game_id=game),)
        book = "-110"
        display = 0.62
    view = PlayView(
        play_id=play.play_id,
        pool=pool,
        game_label="GB @ DET",
        kick_et="4:25 PM ET",
        game_id=game,
        legs=legs,
        display_p=display,
        ticket_ev=0.20,
        book_price=book,
        note="none",
    )
    return play, view


def test_mode_a_ledger_sums_to_twenty_five_dollars(tmp_path) -> None:
    plays = []
    views = {}
    index = 1
    for pool, count in (("checkdown", 6), ("core", 5), ("sgp", 6)):
        for _step in range(count):
            keys = (f"a{index}", f"b{index}") if pool == "sgp" else (f"p{index}",)
            play, view = _dollar(index, pool, keys)
            plays.append(play)
            views[play.play_id] = view
            index += 1
    card = card_from_plays(plays, views, set())
    assert card.mode == "A"
    assert card.stake_cents == 2500
    path = tmp_path / "card.csv"
    write_ledger(card, path)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(LEDGER_COLUMNS)
        rows = list(reader)
    stakes = {row["ticket_id"]: round(float(row["ticket_stake_usd"]) * 100) for row in rows}
    assert sum(stakes.values()) == 2500
    assert max(stakes.values()) <= 400
    sgp = [row for row in rows if row["ticket_id"] == "17"]
    assert len(sgp) == 2
    assert sgp[0]["ticket_stake_usd"] == sgp[1]["ticket_stake_usd"] == "1.00"
    assert sgp[0]["model_prob"] == "0.510000"
    assert sgp[0]["tax_adj_ev"] == sgp[1]["tax_adj_ev"]
    assert all(row["gsis_id"] == "" for row in rows)


def test_validate_rejects_a_degenerate_pair_and_a_scratch() -> None:
    singles = []
    for index in range(6):
        stake = 358 if index == 0 else 357
        singles.append(
            WeekTicket(
                ticket_id=str(index + 1),
                tier="B",
                pool="core",
                game_label="GB @ DET",
                kick_et="4:25 PM ET",
                game_id=f"g{index}",
                legs=(
                    _leg(
                        player_name=f"Back {index}",
                        player_key=f"back{index}",
                        market="rush_yds_q4",
                        game_id=f"g{index}",
                    ),
                ),
                book_price="-110",
                model_p=0.6,
                tax_ev=0.2,
                stake_cents=stake,
                note="none",
            )
        )
    seventh = WeekTicket(
        ticket_id="7",
        tier="B",
        pool="sgp",
        game_label="LAR @ LV",
        kick_et="4:25 PM ET",
        game_id="g6",
        legs=(
            _leg(player_name="Kyren Williams", player_key="kyren_williams", market="rush_yds_q4", position="RB"),
            _leg(player_name="Kyren Williams", player_key="kyren_williams", market="receptions_q4", position="RB"),
        ),
        book_price="SGP not captured; haircut decimal 3.000",
        model_p=0.4,
        tax_ev=0.2,
        stake_cents=357,
        note="none",
    )
    # Rebuild six singles at 357 and one at 358 so the sum is 2500.
    band = []
    for index, ticket in enumerate(singles[:6]):
        stake = 358 if index == 0 else 357
        band.append(
            WeekTicket(
                ticket_id=str(index + 1),
                tier=ticket.tier,
                pool=ticket.pool,
                game_label=ticket.game_label,
                kick_et=ticket.kick_et,
                game_id=ticket.game_id,
                legs=ticket.legs,
                book_price=ticket.book_price,
                model_p=ticket.model_p,
                tax_ev=ticket.tax_ev,
                stake_cents=stake,
                note=ticket.note,
            )
        )
    orthogonal = WeekTicket(
        ticket_id="7",
        tier="B",
        pool="sgp",
        game_label="LAR @ LV",
        kick_et="4:25 PM ET",
        game_id="g7",
        legs=seventh.legs,
        book_price=seventh.book_price,
        model_p=seventh.model_p,
        tax_ev=seventh.tax_ev,
        stake_cents=357,
        note="none",
    )
    validate_week7(WeekCard(mode="B", tickets=tuple([*band, orthogonal])), set())
    degenerate = WeekTicket(
        ticket_id="7",
        tier="B",
        pool="sgp",
        game_label="LAR @ LV",
        kick_et="4:25 PM ET",
        game_id="g7",
        legs=(
            _leg(player_name="Kyren Williams", player_key="kyren_williams", market="receptions_q4", position="RB"),
            _leg(player_name="Kyren Williams", player_key="kyren_williams", market="rec_yds_q4", position="RB"),
        ),
        book_price=seventh.book_price,
        model_p=0.4,
        tax_ev=0.2,
        stake_cents=357,
        note="none",
    )
    with pytest.raises(ValueError, match="degenerate"):
        validate_week7(WeekCard(mode="B", tickets=tuple([*band, degenerate])), set())
    scratched = WeekTicket(
        ticket_id="7",
        tier="B",
        pool="core",
        game_label="GB @ DET",
        kick_et="4:25 PM ET",
        game_id="g7",
        legs=(
            _leg(
                player_name="Lamar Jackson",
                player_key="lamar_jackson",
                market="rush_yds_q4",
                game_id="g7",
            ),
        ),
        book_price="-110",
        model_p=0.6,
        tax_ev=0.2,
        stake_cents=357,
        note="none",
    )
    with pytest.raises(ValueError, match="never_enter"):
        validate_week7(
            WeekCard(mode="B", tickets=tuple([*band, scratched])),
            {norm_name("Lamar Jackson")},
        )


def test_missing_board_writes_the_block_and_skips_the_ledger(tmp_path) -> None:
    report = tmp_path / "card.md"
    ledger = tmp_path / "card.csv"
    code = main(
        [
            "--lines",
            str(tmp_path / "missing.csv"),
            "--report",
            str(report),
            "--ledger",
            str(ledger),
        ]
    )
    assert code == 2
    text = report.read_text(encoding="utf-8")
    assert "CF_WAF_A_CR_DFD7" in text
    assert "No ledger was written" in text
    assert not ledger.exists()


def _ticket(**kwargs: object) -> WeekTicket:
    base: dict = {
        "ticket_id": "1",
        "tier": "1",
        "pool": "single",
        "game_label": "GB @ DET",
        "kick_et": "4:25 PM ET",
        "game_id": "2026_07_GB_DET",
        "legs": (_leg(),),
        "book_price": "-110",
        "model_p": 0.62,
        "tax_ev": 0.2,
        "stake_cents": 300,
        "note": "none",
    }
    base.update(kwargs)
    return WeekTicket(**base)


def test_market_stem_drops_a_quarter_suffix() -> None:
    assert market_stem("receptions_q4") == "receptions"
    assert market_stem("Rec_Yds_Q3") == "rec_yds"
    assert market_stem("pass_yds") == "pass_yds"


def test_game_for_returns_none_outside_the_slate() -> None:
    assert game_for("ZZ", "YY") is None


def test_game_for_finds_a_slated_game() -> None:
    first, second = sorted(next(iter(_BY_TEAMS)))
    window = game_for(first, second)
    assert window is not None
    assert window.game_id


def test_exposure_cents_charges_the_full_stake_to_the_game() -> None:
    card = WeekCard(mode="A", tickets=(_ticket(),))
    assert exposure_cents(card) == {"2026_07_GB_DET": 300}


def test_exposure_cents_sums_two_tickets_on_one_game() -> None:
    card = WeekCard(mode="A", tickets=(_ticket(), _ticket(ticket_id="2")))
    assert exposure_cents(card) == {"2026_07_GB_DET": 600}


def test_render_blocked_states_the_reason() -> None:
    text = render_blocked("no card today")
    assert text.splitlines()[6] == "no card today"
    assert "Do not submit a bet." in text


def test_render_card_names_the_exposure_and_the_cap() -> None:
    text = render_card(WeekCard(mode="A", tickets=(_ticket(),)))
    assert text.splitlines()[0] == "# Week 7 Sunday Hard Rock card, 2026-10-25"
    assert "The highest game exposure is $3.00" in text
    assert "| GB @ DET | $3.00 |" in text


def test_candidate_plays_with_no_legs_is_empty() -> None:
    assert candidate_plays([], [], never=set(), starters={}) == ([], {})


def test_same_game_slips_with_no_legs_is_empty() -> None:
    assert same_game_slips([]) == []


def test_build_from_lines_names_a_missing_scratch_file(tmp_path) -> None:
    with pytest.raises(ValueError, match="scratch file is missing"):
        build_from_lines(
            tmp_path / "lines.csv",
            scratches_path=tmp_path / "absent.csv",
            cache_dir=tmp_path / "cache",
        )
