"""Week 12 card guards: kickoff map, missing rates, stakes, and live prices."""

from __future__ import annotations

import csv
from datetime import date
from io import StringIO

import pytest

from ceminiparlays.names import fold_name, fold_name_suffix_aware, strip_trailing_suffix
from ceminiparlays.sunday_card import norm_name
from ceminiparlays.week12_card import (
    BANKROLL_CENTS,
    LIVE_PATH,
    SLIP_FIELDS,
    STAKE_POOL,
    UNQUOTED_SGP_ESTIMATE,
    FixedCardError,
    FixedLeg,
    RATE_DROPS,
    assign_stakes,
    build_fixed_card,
    card_legs,
    format_ticket_table,
    hard_exclude_names,
    kickoff_commence,
    load_team_rates,
    player_mean_from_team_rates,
    raw_game_label,
    read_csv,
    render_csv,
    render_slip_csv,
    resolve_leg_row,
    snapshot_leg_index,
    validate_fixed_card,
    widen_snapshot,
)


class _Leg:
    def __init__(self, player: str, market: str, side: str) -> None:
        self.player = player
        self.market = market
        self.side = side


def test_kickoff_commence_maps_thanksgiving_et() -> None:
    day = date(2026, 11, 26)
    assert kickoff_commence(day, "1:00 PM ET") == "2026-11-26T18:00:00Z"
    assert kickoff_commence(day, "4:30 PM ET") == "2026-11-26T21:30:00Z"
    assert kickoff_commence(day, "8:20 PM ET") == "2026-11-27T01:20:00Z"


def test_missing_team_rates_file_is_none(tmp_path) -> None:
    assert load_team_rates(tmp_path / "team_rates_2026-11-26.csv") is None


def test_missing_rates_record_a_drop_and_return_none() -> None:
    RATE_DROPS.clear()
    mean = player_mean_from_team_rates("Amon-Ra St. Brown", "DET", "rec_off", None)
    assert mean is None
    assert any(item.endswith("NO_TEAM_RATES_FILE") for item in RATE_DROPS)


def test_hard_exclude_covers_hurts_and_walker() -> None:
    names = hard_exclude_names()
    assert norm_name("Jalen Hurts") in names
    assert norm_name("Kenneth Walker III") in names


def test_four_stakes_sum_to_twenty_dollars() -> None:
    tickets: list[dict[str, object]] = []
    for index, ev in enumerate((0.0, -0.01, -0.02, -0.03)):
        tickets.append(
            {
                "ev": ev,
                "stake_cents": 0,
                "legs": [
                    _Leg(f"Player {index}a", "pass_yds", "over"),
                    _Leg(f"Player {index}b", "rec_yds", "over"),
                ],
            }
        )
    assign_stakes(tickets)
    stakes = [int(ticket["stake_cents"]) for ticket in tickets]
    assert stakes == list(STAKE_POOL)
    assert sum(stakes) == BANKROLL_CENTS
    assert all(400 <= stake <= 600 for stake in stakes)


def test_widen_keeps_a_long_snapshot() -> None:
    rows = [
        {
            "bookmaker": "hardrockbet",
            "player": "Jared Goff",
            "market": "player_pass_yds",
            "side": "over",
            "line": "279.5",
            "american_odds": "-115",
            "timestamp": "2026-11-26T01:00:00Z",
            "game": "CHI@DET",
            "team": "DET",
            "opp": "CHI",
        }
    ]
    assert widen_snapshot(rows) is rows


def test_widen_copies_two_way_prices(monkeypatch) -> None:
    monkeypatch.setattr(
        "ceminiparlays.week12_card._game_labels",
        lambda: {"2026-11-26T18:00:00Z": "CHI@DET"},
    )
    monkeypatch.setattr("ceminiparlays.week12_card._packet_teams", lambda: {})
    rows = [
        {
            "platform": "hardrock",
            "stat_type": "pass_yds",
            "commence_time": "2026-11-26T18:00:00Z",
            "player_name": "Jared Goff",
            "team": "DET",
            "opp": "CHI",
            "captured_at": "2026-11-26T01:00:00Z",
            "book_over": "-115",
            "book_under": "-105",
            "line": "279.5",
            "leg_odds": "",
        }
    ]
    widened = widen_snapshot(rows)
    assert len(widened) == 2
    assert {row["bookmaker"] for row in widened} == {"hardrockbet"}
    assert {row["side"] for row in widened} == {"over", "under"}
    assert {row["line"] for row in widened} == {"279.5"}
    by_side = {row["side"]: row["american_odds"] for row in widened}
    assert by_side == {"over": "-115", "under": "-105"}


def test_widen_skips_a_row_with_no_price(monkeypatch) -> None:
    monkeypatch.setattr(
        "ceminiparlays.week12_card._game_labels",
        lambda: {"2026-11-26T18:00:00Z": "CHI@DET"},
    )
    monkeypatch.setattr("ceminiparlays.week12_card._packet_teams", lambda: {})
    rows = [
        {
            "platform": "hardrock",
            "stat_type": "rush_yds",
            "commence_time": "2026-11-26T18:00:00Z",
            "player_name": "Jahmyr Gibbs",
            "team": "DET",
            "opp": "CHI",
            "captured_at": "2026-11-26T01:00:00Z",
            "book_over": "",
            "book_under": "",
            "line": "80.5",
            "leg_odds": "",
        }
    ]
    assert widen_snapshot(rows) == []


def test_suffix_aware_fold_covers_all_generational_cases() -> None:
    assert fold_name("James Cook III") == fold_name("James Cook")
    assert fold_name_suffix_aware("James Cook III") == fold_name_suffix_aware("James Cook")
    assert fold_name_suffix_aware("Marvin Harrison Jr.") == fold_name_suffix_aware("Marvin Harrison")
    assert fold_name_suffix_aware("Patrick Mahomes II") == fold_name_suffix_aware("Patrick Mahomes")
    # St. is not a suffix. The name survives, and only the last token is considered.
    assert strip_trailing_suffix("Amon-Ra St. Brown") == "Amon-Ra St. Brown"
    assert fold_name_suffix_aware("Amon-Ra St. Brown") == fold_name("Amon-Ra St. Brown")
    assert strip_trailing_suffix("Robert V Jones") == "Robert V Jones"
    assert strip_trailing_suffix("James Cook III Jr.") == "James Cook III"


def test_snapshot_lookup_folds_james_cook_iii_to_the_posted_row() -> None:
    index = snapshot_leg_index(read_csv(LIVE_PATH))
    row = resolve_leg_row(
        FixedLeg("James Cook III", "KC@BUF", "rush_yds", "over", 82.5, -115),
        index,
    )
    assert row["player"] == "James Cook"
    assert row["american_odds"] == "-115"


def test_fixed_card_is_the_operator_card_and_not_an_optimizer_card() -> None:
    tickets = build_fixed_card(read_csv(LIVE_PATH), {})
    assert [ticket["ticket_id"] for ticket in tickets] == ["HR12-1", "HR12-2", "HR12-3", "HR12-4"]
    assert [int(ticket["stake_cents"]) for ticket in tickets] == [600, 500, 500, 400]
    assert sum(int(ticket["stake_cents"]) for ticket in tickets) == BANKROLL_CENTS
    assert all(len(ticket["legs"]) == 2 for ticket in tickets)
    legs = card_legs(tickets)
    assert len(legs) == 8
    expected = [
        ("James Cook", "KC@BUF", "rush_yds", "over", 82.5, -115),
        ("CeeDee Lamb", "PHI@DAL", "rec_yds", "over", 89.5, -115),
        ("Patrick Mahomes", "KC@BUF", "pass_yds", "under", 236.5, -115),
        ("Amon-Ra St. Brown", "CHI@DET", "rec_yds", "over", 82.5, -115),
        ("BUF", "KC@BUF", "total_q3", "under", 7.5, 100),
        ("George Pickens", "PHI@DAL", "rec_yds", "over", 68.5, -115),
        ("Caleb Williams", "CHI@DET", "pass_yds", "over", 261.5, -115),
        ("Javonte Williams", "PHI@DAL", "rush_yds", "over", 75.5, -115),
    ]
    actual = [
        (leg.player, raw_game_label(leg.game_id), leg.market, leg.side, leg.line, leg.book_american)
        for leg in legs
    ]
    assert actual == expected
    assert not [leg for leg in legs if leg.market == "receptions_q4"]
    assert not [
        leg
        for leg in legs
        if raw_game_label(leg.game_id) == "CHI@DET" and leg.side == "under"
    ]
    assert not [leg for leg in legs if "allen" in fold_name_suffix_aware(leg.player)]
    assert all(ticket["pricing_source"] == UNQUOTED_SGP_ESTIMATE for ticket in tickets)
    assert all(ticket["ev"] is None for ticket in tickets)


def test_unquoted_product_never_prints_a_market_ev() -> None:
    tickets = build_fixed_card(read_csv(LIVE_PATH), {})
    for ticket in tickets:
        ticket["ev"] = 0.42
    with pytest.raises(FixedCardError):
        validate_fixed_card(tickets)
    rows = list(csv.DictReader(StringIO(render_csv(tickets))))
    assert len(rows) == 8
    assert {row["pricing_source"] for row in rows} == {UNQUOTED_SGP_ESTIMATE}
    assert all(not row["ticket_ev"].strip() for row in rows)
    assert all(float(row["ticket_ev"]) <= 0.0 for row in rows if row["ticket_ev"].strip())
    table = format_ticket_table(tickets)
    assert "UNQUOTED_SGP_ESTIMATE" in table
    assert "42.00%" not in table


def test_slip_csv_columns_and_ticket_stakes_are_exact() -> None:
    tickets = build_fixed_card(read_csv(LIVE_PATH), {})
    rows = list(csv.DictReader(StringIO(render_slip_csv(tickets))))
    assert list(rows[0]) == list(SLIP_FIELDS)
    assert len(rows) == 8
    assert [row["stake"] for row in rows] == [
        "6.00",
        "6.00",
        "5.00",
        "5.00",
        "5.00",
        "5.00",
        "4.00",
        "4.00",
    ]
    assert rows[4]["ticket_id"] == "HR12-3"
    assert rows[4]["player"] == "BUF"
    assert rows[4]["market"] == "total_q3"
    assert rows[4]["side"] == "under"
    assert rows[4]["book_american_odds"] == "100"
    assert {row["market"] for row in rows} == {"rush_yds", "rec_yds", "pass_yds", "total_q3"}
