"""Week 8 card rules. Live Hard Rock prices stay out of this file."""

import pytest

from ceminiparlays.week8_card import (
    BANKROLL_CENTS,
    GAME_CAP_CENTS,
    PARLAY_CAP_CENTS,
    SINGLES_FLOOR_CENTS,
    TICKET_CAP_CENTS,
    CardTicket,
    _checkdown_inputs,
    add_exposure,
    american_int,
    american_text,
    build_from_files,
    build_pools,
    clip_printed_side,
    exposure_ok,
    favored_catch_under,
    frame_rows,
    game_exposure,
    game_key,
    has_quarter_pair,
    kick_label,
    load_pbp_plays,
    mean_of,
    price_period_yards,
    product_ev,
    read_lines,
    render_markdown,
    select_card,
    stake_cents,
    verify_card,
)


def _leg(**overrides):
    base = {
        "player_key": "player_a",
        "player_name": "Player A",
        "team": "BUF",
        "opp": "BAL",
        "market": "receptions_q4",
        "side": "over",
        "line": 0.5,
        "price": 150,
        "model_p": 0.55,
        "ev": 0.20,
        "game_id": "2026_08_BAL_BUF",
        "kick_et": "1:00 PM ET",
        "game_label": "BAL @ BUF",
        "gsis_id": "00-1",
        "position": "RB",
        "spread": 3.0,
        "note": "none",
    }
    base.update(overrides)
    return base


def _games():
    """Eight games so the $2.50 cap cannot force a short card."""

    pairs = [
        ("BUF", "BAL", "BAL @ BUF"),
        ("DAL", "ARI", "ARI @ DAL"),
        ("DET", "MIN", "MIN @ DET"),
        ("CIN", "TEN", "TEN @ CIN"),
        ("PIT", "CLE", "CLE @ PIT"),
        ("TB", "ATL", "ATL @ TB"),
        ("NYJ", "LV", "LV @ NYJ"),
        ("LAR", "LAC", "LAC @ LAR"),
    ]
    return pairs


def test_quarter_targets_stay_on_the_prior_when_the_cache_has_no_count():
    player = {
        "games": 16,
        "receptions_per_game": 2.5,
        "rec_yds_per_game": 20,
        "targets_per_game": 3,
        "trail4_opps": 80,
        "q4_trail_target_share": 0.2,
        "vacated_target_boost": 0,
        "avg_cushion": 0,
    }
    inputs = _checkdown_inputs(
        player,
        None,
        0.15,
        None,
        None,
        None,
        "receptions_q4",
        3.0,
        45.0,
    )
    assert inputs.opps_q == 0.0
    assert inputs.opps_total == 0.0


def test_quarter_target_counts_replace_the_flat_prior():
    player = {
        "games": 16,
        "receptions_per_game": 2.5,
        "rec_yds_per_game": 20,
        "targets_per_game": 3,
        "q4_targets": 5,
        "total_targets": 17,
        "q4_trail_target_share": 0.2,
        "vacated_target_boost": 0,
        "avg_cushion": 0,
    }
    inputs = _checkdown_inputs(
        player,
        None,
        0.15,
        None,
        None,
        None,
        "receptions_q4",
        3.0,
        45.0,
    )
    assert inputs.opps_q == 5.0
    assert inputs.opps_total == 17.0


def test_favored_grinder_under_needs_a_positive_ev():
    paid = favored_catch_under(
        market="receptions_q4",
        line=0.5,
        over_p=0.20,
        book_under=-110,
        spread=-2.5,
    )
    assert paid is not None
    assert paid[1] > 0.0
    assert (
        favored_catch_under(
            market="receptions_q4",
            line=0.5,
            over_p=0.20,
            book_under=-110,
            spread=-1.5,
        )
        is None
    )
    assert (
        favored_catch_under(
            market="rec_yds_q4",
            line=0.5,
            over_p=0.20,
            book_under=-110,
            spread=-6.0,
        )
        is None
    )


def test_period_yards_clip_stays_inside_the_main_line_band():
    priced = price_period_yards(games=10, rate=80, line=10.5, book_over=-110, book_under=-110)
    assert priced is not None
    assert priced["side"] == "over"
    assert 0.18 <= priced["model_p"] <= 0.78
    assert priced["ev"] > 0.0


def test_period_yards_drop_when_the_clip_removes_the_edge():
    # A short price cannot keep a clipped probability that no longer clears the juice.
    priced = price_period_yards(games=10, rate=40, line=10.5, book_over=-400, book_under=300)
    if priced is not None:
        assert priced["ev"] > 0.0
        assert priced["model_p"] <= 0.78


def test_select_keeps_one_under_then_fills_with_overs():
    pairs = _games()
    unders = [
        _leg(
            player_key="under_back",
            player_name="Under Back",
            team=pairs[0][0],
            opp=pairs[0][1],
            game_label=pairs[0][2],
            side="under",
            price=-105,
            ev=0.05,
        )
    ]
    overs = []
    for index, (team, opp, label) in enumerate(pairs[1:], start=1):
        overs.append(
            _leg(
                player_key=f"over_{index}",
                player_name=f"Over {index}",
                team=team,
                opp=opp,
                game_label=label,
                game_id=label,
                ev=0.30 - index * 0.01,
            )
        )
    tier2 = [
        _leg(
            player_key="core_a",
            player_name="Core A",
            team=pairs[0][0],
            opp=pairs[0][1],
            game_label=pairs[0][2],
            market="rush_yds_q4",
            line=9.5,
            ev=0.15,
            model_p=0.62,
        ),
        _leg(
            player_key="core_b",
            player_name="Core B",
            team=pairs[2][0],
            opp=pairs[2][1],
            game_label=pairs[2][2],
            market="rec_yds_q3",
            line=12.5,
            ev=0.12,
            model_p=0.60,
        ),
    ]
    sgps = []
    for index, (team, opp, label) in enumerate(pairs[3:5], start=1):
        left = _leg(
            player_key=f"sgp_{index}_a",
            player_name=f"Sgp {index} A",
            team=team,
            opp=opp,
            game_label=label,
            market="receptions_q4",
            ev=0.08,
        )
        right = _leg(
            player_key=f"sgp_{index}_b",
            player_name=f"Sgp {index} B",
            team=team,
            opp=opp,
            game_label=label,
            market="rush_yds_q4",
            line=8.5,
            ev=0.08,
        )
        sgps.append(
            {
                "legs": [left, right],
                "n_legs": 2,
                "tax_adjusted_sgp_ev": 0.04,
                "sgp_tax_applied": True,
            }
        )
    boost = []
    for index, (team, opp, label) in enumerate(pairs[5:], start=1):
        boost.append(
            _leg(
                player_key=f"boost_{index}",
                player_name=f"Boost {index}",
                team=team,
                opp=opp,
                game_label=label,
                price=180,
                ev=0.11,
                model_p=0.48,
            )
        )
    tickets, short = select_card(unders + overs, tier2, sgps, boost)
    assert short == []
    assert stake_cents(tickets) == BANKROLL_CENTS
    assert verify_card(tickets, set()) == []
    tier1 = [ticket for ticket in tickets if ticket.tier == "1"]
    assert len(tier1) == 4
    assert tier1[0].legs[0]["side"] == "under"
    assert all(ticket.stake_cents == 100 for ticket in tier1)
    assert [ticket.stake_cents for ticket in tickets if ticket.tier == "2"] == [125, 125]
    assert sum(1 for ticket in tickets if ticket.tier == "3") == 3
    assert all(ticket.joint_p > 0.0 for ticket in tickets)
    assert all(ticket.book_implied_p > 0.0 for ticket in tickets)
    single_cents = sum(ticket.stake_cents for ticket in tickets if len(ticket.legs) == 1)
    parlay_cents = sum(ticket.stake_cents for ticket in tickets if len(ticket.legs) > 1)
    assert single_cents >= SINGLES_FLOOR_CENTS
    assert parlay_cents <= PARLAY_CAP_CENTS
    multi = [ticket for ticket in tickets if len(ticket.legs) > 1]
    seen: set[tuple] = set()
    for ticket in multi:
        for leg in ticket.legs:
            ident = (leg["player_key"], leg["market"], leg["side"], leg["line"])
            assert ident not in seen
            seen.add(ident)
    text = render_markdown(tickets, [], {"quarter_players": 4})
    assert "joint" not in text.split("Model prob")[1]
    assert "w_rec_q4_eb" in text
    for ticket in tickets:
        assert f"{ticket.joint_p:.4f}" in text


def test_select_blocks_a_same_player_quarter_pair_and_a_third_dollar():
    crowded = [
        _leg(player_key=f"same_{index}", player_name=f"Same {index}", ev=0.4 - index * 0.01)
        for index in range(3)
    ]
    yards = _leg(
        player_key="same_0",
        player_name="Same 0",
        market="rec_yds_q4",
        line=6.5,
        ev=0.10,
        team="DAL",
        opp="ARI",
        game_label="ARI @ DAL",
    )
    other = [
        _leg(
            player_key=f"other_{index}",
            player_name=f"Other {index}",
            team="DAL" if index == 0 else "DET",
            opp="ARI" if index == 0 else "MIN",
            game_label="ARI @ DAL" if index == 0 else "MIN @ DET",
            ev=0.2,
        )
        for index in range(4)
    ]
    tickets, short = select_card(crowded + [yards] + other, [], [], [])
    keys = [(leg["player_key"], leg["market"]) for ticket in tickets for leg in ticket.legs]
    assert ("same_0", "receptions_q4") in keys
    assert ("same_0", "rec_yds_q4") not in keys
    buf_stake = sum(
        ticket.stake_cents
        for ticket in tickets
        if any(leg["team"] == "BUF" for leg in ticket.legs)
    )
    assert buf_stake <= 250
    assert any("tier 1 short" in item or "tier 2 short" in item for item in short)


def test_select_rejects_a_negative_ev_leg():
    bad = _leg(ev=-0.01, player_key="bad", player_name="Bad")
    tickets, short = select_card([bad], [], [], [])
    assert tickets == []
    assert any(item.startswith("tier 1 short") for item in short)


def test_one_prop_cannot_sit_on_two_sgp_tickets():
    pairs = _games()
    shared = _leg(
        player_key="hooper",
        player_name="Austin Hooper",
        team=pairs[3][0],
        opp=pairs[3][1],
        game_label=pairs[3][2],
    )
    partner_a = _leg(
        player_key="otton",
        player_name="Cade Otton",
        team=pairs[3][0],
        opp=pairs[3][1],
        game_label=pairs[3][2],
        market="rec_yds_q4",
        line=4.5,
    )
    partner_b = _leg(
        player_key="godwin",
        player_name="Chris Godwin",
        team=pairs[3][0],
        opp=pairs[3][1],
        game_label=pairs[3][2],
        market="rush_yds_q4",
        line=6.5,
    )
    other_game = pairs[4]
    clean_a = _leg(
        player_key="clean_a",
        player_name="Clean A",
        team=other_game[0],
        opp=other_game[1],
        game_label=other_game[2],
    )
    clean_b = _leg(
        player_key="clean_b",
        player_name="Clean B",
        team=other_game[0],
        opp=other_game[1],
        game_label=other_game[2],
        market="rush_yds_q4",
        line=8.5,
    )
    sgps = [
        {"legs": [shared, partner_a], "n_legs": 2, "tax_adjusted_sgp_ev": 0.20},
        {"legs": [shared, partner_b], "n_legs": 2, "tax_adjusted_sgp_ev": 0.19},
        {"legs": [clean_a, clean_b], "n_legs": 2, "tax_adjusted_sgp_ev": 0.05},
    ]
    tickets, _short = select_card([], [], sgps, [])
    placed = [ticket for ticket in tickets if ticket.ticket_id.startswith("HR8-SGP")]
    assert len(placed) == 2
    hooper_tickets = [
        ticket for ticket in placed if any(leg["player_key"] == "hooper" for leg in ticket.legs)
    ]
    assert len(hooper_tickets) == 1


class _Frame:
    """The one method ``frame_rows`` asks of a DataFrame."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def to_dict(self, orient: str) -> list[dict]:
        assert orient == "records"
        return list(self.rows)


def test_american_int_reads_a_valid_price() -> None:
    assert american_int(-110) == -110
    assert american_int("+150") == 150
    assert american_int(150.7) == 150


def test_american_int_refuses_a_bad_price() -> None:
    assert american_int(0) is None
    assert american_int(-50) is None
    assert american_int("x") is None
    assert american_int(None) is None


def test_american_text_signs_a_positive_price() -> None:
    assert american_text(150) == "+150"
    assert american_text(-110) == "-110"


def test_kick_label_names_a_sunday_window() -> None:
    assert kick_label("2026-11-01T18:00:00Z") == "1:00 PM ET"
    assert kick_label("2026-01-01T00:00:00Z") == ""


def test_game_key_is_the_unordered_team_pair() -> None:
    assert game_key(_leg()) == frozenset({"BUF", "BAL"})


def test_mean_of_averages_the_finite_values() -> None:
    assert mean_of([{"a": 1}, {"a": 3}, {"a": "x"}], "a") == 2.0
    assert mean_of([], "a") is None


def test_frame_rows_clears_a_nan_and_keeps_a_null() -> None:
    rows = frame_rows(_Frame([{"a": 1.0, "b": float("nan"), "c": None}]))
    assert rows == [{"a": 1.0, "b": None, "c": None}]


def test_clip_printed_side_drops_a_leg_with_no_edge() -> None:
    assert clip_printed_side(0.40, 0.40, -110) is None


def test_clip_printed_side_returns_the_clip_and_the_ev() -> None:
    clipped, ev = clip_printed_side(0.62, 0.55, -110)
    assert clipped == 0.62
    assert ev > 0.0


def test_product_ev_multiplies_the_independent_product() -> None:
    ev, decimal = product_ev(
        [{"model_p": 0.6, "price": -110}, {"model_p": 0.5, "price": 100}]
    )
    assert decimal == pytest.approx(3.8181818, rel=1e-6)
    assert ev == pytest.approx(0.1454545, rel=1e-6)


def test_has_quarter_pair_flags_a_redundant_pair() -> None:
    receptions = _leg(market="receptions_q4")
    rec_yards = _leg(market="rec_yds_q4")
    other_player = _leg(player_key="player_b", market="rec_yds")
    assert has_quarter_pair([receptions, rec_yards]) is True
    assert has_quarter_pair([receptions, other_player]) is False
    assert has_quarter_pair([]) is False


def test_exposure_ok_respects_the_ticket_cap() -> None:
    assert exposure_ok({}, [_leg()], 100) is True
    assert exposure_ok({}, [_leg()], TICKET_CAP_CENTS + 1) is False


def test_exposure_ok_respects_the_game_cap() -> None:
    key = frozenset({"BUF", "BAL"})
    assert exposure_ok({key: GAME_CAP_CENTS - 100}, [_leg()], 100) is True
    assert exposure_ok({key: GAME_CAP_CENTS}, [_leg()], 100) is False


def test_add_exposure_charges_each_game_once() -> None:
    exposure: dict[frozenset[str], int] = {}
    add_exposure(exposure, [_leg(), _leg(player_key="player_b")], 300)
    assert exposure == {frozenset({"BUF", "BAL"}): 300}


def test_game_exposure_counts_a_ticket_once_per_game() -> None:
    ticket = CardTicket(
        ticket_id="1",
        tier="1",
        legs=(_leg(), _leg(player_key="player_b")),
        stake_cents=300,
        tax_ev=0.2,
        note="none",
    )
    assert game_exposure([ticket]) == {"BAL @ BUF": 300}


def test_read_lines_reads_the_csv(tmp_path) -> None:
    path = tmp_path / "lines.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    assert read_lines(path) == [{"a": "1", "b": "2"}]


def test_load_pbp_plays_without_a_file_is_empty(tmp_path) -> None:
    assert load_pbp_plays(None) == []
    assert load_pbp_plays(tmp_path / "absent.parquet") == []


def test_build_pools_on_an_empty_cache_returns_empty_pools() -> None:
    cache = {
        "player_telemetry_pit.parquet": _Frame([]),
        "defense_counterpart_pit.parquet": _Frame([]),
        "game_context_pit.parquet": _Frame([]),
    }
    pools = build_pools([], cache, set())
    assert pools["tier1"] == []
    assert pools["tier2"] == []
    assert pools["sgps"] == []
    assert pools["boost"] == []


def test_build_from_files_names_a_missing_lines_file(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="lines file is missing"):
        build_from_files(lines_path=tmp_path / "absent.csv")
