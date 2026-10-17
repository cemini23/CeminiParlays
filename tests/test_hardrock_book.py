from __future__ import annotations

import json
from pathlib import Path

import pytest

from ceminiparlays.hardrock_book import (
    inventory_from_capture,
    load_capture,
    parse_capture,
    write_inventory,
    write_rows,
)
from ceminiparlays.markets import parse_markets

FIXTURE = Path(__file__).parent / "fixtures" / "hardrock_min.json"


def test_parse_is_deterministic(tmp_path: Path) -> None:
    payload = load_capture(FIXTURE)
    first = tmp_path / "a.csv"
    second = tmp_path / "b.csv"
    write_rows(first, parse_capture(payload))
    write_rows(second, parse_capture(json.loads(FIXTURE.read_text(encoding="utf-8"))))
    assert first.read_bytes() == second.read_bytes()


def test_parser_keeps_the_balanced_line_and_skips_a_missing_price() -> None:
    rows = parse_capture(load_capture(FIXTURE))
    by_key = {(row["stat_type"], row["line"], row["line_type"]) for row in rows}
    assert ("pass_yds_h1", "119.5", "half") in by_key
    assert ("pass_yds", "250.5", "standard") in by_key
    assert ("pass_yds", "300.5", "alternate") in by_key
    assert ("rec_yds_h1", "10.5", "half") not in by_key
    assert all(row["player_name"] != "Nobody" for row in rows)
    stroud = next(row for row in rows if row["stat_type"] == "pass_yds_h1")
    assert stroud["team"] == "HOU"
    assert stroud["opp"] == "JAX"
    assert stroud["book_over"] == -115
    assert stroud["book_under"] == -115
    assert stroud["commence_time"].startswith("2026-10-18T")
    jaguars = next(row for row in rows if row["stat_type"] == "team_total")
    assert jaguars["team"] == "JAX"
    assert jaguars["line_type"] == "standard"


def test_inventory_marks_period_markets_absent() -> None:
    payload = {
        "events": [{}, {}],
        "market_types": [
            {
                "type": "AMERICAN_FOOTBALL:FTOT:ML",
                "period": "game",
                "sample_name": "To Win",
                "count": 2,
            },
            {
                "type": "AMERICAN_FOOTBALL:FTOT:OU",
                "period": "game",
                "sample_name": "Total Points",
                "count": 10,
            },
            {
                "type": "AMERICAN_FOOTBALL:P:PROPPSYDSH1",
                "period": "h1",
                "sample_name": "C.J. Stroud - 1st Half Pass Yards",
                "count": 2,
            },
            {
                "type": "AMERICAN_FOOTBALL:FT:OUPUNTSGAME",
                "period": "game",
                "sample_name": "Total Punts",
                "count": 2,
            },
        ],
    }
    rows = {row["book_type"]: row for row in inventory_from_capture(payload)}
    assert rows["AMERICAN_FOOTBALL:FTOT:ML"]["repo_gate"] == "covered"
    assert rows["AMERICAN_FOOTBALL:FTOT:ML"]["odds_api"] == "not_fetched"
    assert rows["AMERICAN_FOOTBALL:FTOT:OU"]["repo_gate"] == "partial"
    assert rows["AMERICAN_FOOTBALL:P:PROPPSYDSH1"]["repo_gate"] == "absent"
    assert rows["AMERICAN_FOOTBALL:P:PROPPSYDSH1"]["odds_api"] == "absent"
    assert rows["AMERICAN_FOOTBALL:FT:OUPUNTSGAME"]["repo_gate"] == "absent"
    assert rows["AMERICAN_FOOTBALL:FT:OUPUNTSGAME"]["feed"] == "hardrock_getevents"
    assert rows["AMERICAN_FOOTBALL:FT:OUPUNTSGAME"]["feed_status"] == "live"


def test_period_tokens_stay_out_of_the_accept_list() -> None:
    """The first-study period tokens stay illegal.

    ``receptions_q1`` cleared the numeric EV rule on the 2026-10-18 slate.
    It stays out. 21 of 25 legs were a 0.5 line, the scorer used a normal,
    and one leg moves the CI lower bound to or below zero. ``fair.py`` prices
    a low count as Poisson. Do not add the token until that path exists.
    Canon C24 names a later, separate promotion. This list is not that set.
    """

    for token in (
        "pass_yds_h1",
        "rush_yds_h1",
        "rec_yds_h1",
        "receptions_h1",
        "pass_yds_q1",
        "rush_yds_q1",
        "rec_yds_q1",
        "receptions_q1",
        "team_total_h1",
        "total_h1",
    ):
        with pytest.raises(ValueError):
            parse_markets(token)


def test_inventory_write_round_trip(tmp_path: Path) -> None:
    rows = inventory_from_capture(load_capture(FIXTURE), parse_capture(load_capture(FIXTURE)))
    path = tmp_path / "inventory.csv"
    write_inventory(path, rows)
    again = tmp_path / "inventory2.csv"
    write_inventory(again, rows)
    assert path.read_bytes() == again.read_bytes()
