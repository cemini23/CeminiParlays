"""Stake and exclude checks for the $15 research card."""

from ceminiparlays.sunday_card import (
    BANKROLL_CENTS,
    GAME_CAP_CENTS,
    REPORT_OUT,
    kick_et,
    norm_name,
    pass_over_blocked,
    qualifying_legs,
    select_anchors,
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
