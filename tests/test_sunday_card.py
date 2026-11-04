"""Stake and exclude checks for the $15 research card."""

import pytest

from ceminiparlays.sunday_card import (
    BANKROLL_CENTS,
    GAME_CAP_CENTS,
    REPORT_OUT,
    build_sunday_card,
    game_key,
    kick_et,
    leg_text,
    norm_name,
    pass_over_blocked,
    qualifying_legs,
    render_table,
    select_anchors,
    select_lottos,
    select_sgps,
    validate_card,
    SundayCard,
    CardTicket,
)


def _leg(**kwargs):
    base = {
        "player_name": "Justin Herbert",
        "player_key": "justin_herbert",
        "team": "LAC",
        "opp": "KC",
        "market": "rush_yds_q4",
        "side": "over",
        "line": "2.5",
        "price": "-110",
        "model_p": "0.80",
        "ev": "0.20",
        "commence_time": "2026-10-18T20:25:00Z",
    }
    base.update(kwargs)
    return base


def test_norm_name_drops_a_suffix_and_an_apostrophe() -> None:
    assert norm_name("Michael Pittman Jr.") == "michael pittman"
    assert norm_name("Tre' Harris") == "tre harris"


def test_kick_et_is_daylight_time() -> None:
    assert kick_et("2026-10-18T17:00:00Z") == "1:00 PM ET"
    assert kick_et("2026-10-18T13:30:00Z") == "9:30 AM ET"


def test_qualifying_legs_drop_a_scratch_a_pass_over_and_a_night_kick() -> None:
    legs = [
        _leg(),
        _leg(player_name="Baker Mayfield", player_key="baker", team="TB", opp="PIT"),
        _leg(
            player_name="Matthew Stafford",
            player_key="stafford",
            team="TB",
            opp="PIT",
            market="pass_yds_q4",
            side="over",
        ),
        _leg(commence_time="2026-10-19T00:20:00Z", player_key="night"),
        _leg(ev="0.01", player_key="small"),
    ]
    kept = qualifying_legs(
        legs,
        never_enter={"Baker Mayfield"},
        blocked_pass_games={frozenset({"PIT", "TB"})},
    )
    assert [leg["player_key"] for leg in kept] == ["justin_herbert"]
    assert pass_over_blocked(legs[2], {frozenset({"PIT", "TB"})}) is True


def test_a_report_out_name_is_dropped() -> None:
    legs = [
        _leg(),
        _leg(player_name="Zach Charbonnet", player_key="charbonnet", team="SEA", opp="DEN"),
    ]
    kept = qualifying_legs(legs, never_enter=set(REPORT_OUT), blocked_pass_games=set())
    assert [leg["player_key"] for leg in kept] == ["justin_herbert"]
    assert "Pat Surtain II" in REPORT_OUT


def test_anchors_take_one_leg_per_game() -> None:
    legs = [
        _leg(ev="0.50"),
        _leg(player_name="Other", player_key="other", market="receptions_q4", ev="0.40"),
        _leg(
            player_name="James Cook III",
            player_key="cook",
            team="BUF",
            opp="LV",
            ev="0.30",
            commence_time="2026-10-18T20:25:00Z",
        ),
    ]
    picked = select_anchors(legs, wait=set(), count=2)
    assert [leg["player_key"] for leg in picked] == ["justin_herbert", "cook"]


def test_validate_card_accepts_fifteen_dollars_and_rejects_a_scratch() -> None:
    specs = (
        ("alpha", "LAC", "KC"),
        ("bravo", "BUF", "LV"),
        ("charlie", "LAR", "ARI"),
        ("delta", "IND", "TEN"),
        ("echo", "BAL", "CLE"),
    )
    tickets = []
    for index, (key, team, opp) in enumerate(specs, start=1):
        tickets.append(
            CardTicket(
                index,
                "1",
                team,
                "1:00 PM ET",
                [_leg(player_name=key, player_key=key, team=team, opp=opp)],
                "-110",
                0.8,
                0.2,
                300,
                "none",
            )
        )
    card = SundayCard(mode="A", tickets=tickets)
    validate_card(card, never_enter=set())
    assert card.stake_cents == BANKROLL_CENTS
    assert GAME_CAP_CENTS == 450
    card.tickets[0].legs[0] = _leg(player_name="Jalen Hurts", player_key="hurts")
    try:
        validate_card(card, never_enter={"Jalen Hurts"})
    except ValueError as exc:
        assert "never_enter" in str(exc)
    else:
        raise AssertionError("a scratch must fail the card")


def _other(**kwargs):
    base = {
        "player_name": "A Player",
        "player_key": "a_player",
        "team": "SF",
        "opp": "SEA",
    }
    base.update(kwargs)
    return _leg(**base)


def _priced(**kwargs):
    base = {
        "legs": [_leg(), _other()],
        "tax_adjusted_sgp_ev": "0.20",
        "n_legs": 2,
        "sgp_tax_applied": True,
    }
    base.update(kwargs)
    return base


def test_game_key_is_the_unordered_team_pair() -> None:
    assert game_key(_leg()) == frozenset({"LAC", "KC"})
    assert game_key(_leg(team="KC", opp="LAC")) == frozenset({"LAC", "KC"})


def test_leg_text_states_the_side_line_and_price() -> None:
    assert leg_text(_leg()) == "Justin Herbert rush_yds_q4 over 2.5 (-110)"


def test_select_sgps_keeps_one_taxed_ticket() -> None:
    row = _priced()
    assert select_sgps([row], used_players=set(), exposure={}, wait=set(), count=3) == [row]


def test_select_sgps_skips_an_untaxed_row() -> None:
    row = _priced(sgp_tax_applied=False)
    assert select_sgps([row], used_players=set(), exposure={}, wait=set()) == []


def test_select_sgps_skips_a_row_below_the_minimum_ev() -> None:
    row = _priced(tax_adjusted_sgp_ev="0.01")
    assert select_sgps([row], used_players=set(), exposure={}, wait=set()) == []


def test_select_sgps_skips_a_player_already_on_the_card() -> None:
    row = _priced()
    used = {norm_name("Justin Herbert")}
    assert select_sgps([row], used_players=used, exposure={}, wait=set()) == []


def test_select_lottos_builds_a_cross_game_three_leg() -> None:
    legs = [
        _leg(),
        _other(player_name="B Player", player_key="b_player"),
        _other(player_name="C Player", player_key="c_player", team="DAL", opp="PHI"),
    ]
    chosen = select_lottos(legs, used_players=set(), exposure={}, wait=set(), count=3)
    assert len(chosen) == 1
    assert len(chosen[0]) == 3


def test_select_lottos_refuses_three_legs_from_two_games() -> None:
    legs = [
        _leg(),
        _other(player_name="B Player", player_key="b_player", team="LAC", opp="KC"),
        _other(player_name="C Player", player_key="c_player"),
    ]
    assert select_lottos(legs, used_players=set(), exposure={}, wait=set()) == []


def test_build_sunday_card_refuses_a_thin_slate() -> None:
    with pytest.raises(ValueError, match="six daytime anchors"):
        build_sunday_card(
            [],
            [],
            never_enter=set(),
            wait=set(),
            blocked_pass_games=set(),
            game_label=lambda leg: "",
            note_for=lambda legs, kind: "",
        )


def test_render_table_writes_one_row_per_ticket() -> None:
    ticket = CardTicket(
        1, "1", "LAC@KC", "4:25 PM ET", [_leg()], "-110", 0.8, 0.2, 100, "none", "single"
    )
    lines = render_table(SundayCard(mode="A", tickets=[ticket])).splitlines()
    assert lines[0].startswith("| Ticket | Tier |")
    assert lines[2].startswith("| 1 | 1 | LAC@KC, 4:25 PM ET |")
    assert "$1.00" in lines[2]
    assert "20.0%" in lines[2]
