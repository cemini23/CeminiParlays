import pytest

from ceminiparlays.markets import (
    AUTO_MARKETS,
    GAME_STATS,
    TD_STATS,
    YARDS_STATS,
    is_first_td,
    is_td_market,
    parse_markets,
)


def test_td_helpers() -> None:
    assert is_first_td("first_td") is True
    assert is_first_td("anytime_td") is False
    assert is_td_market("anytime_td") is True
    assert is_td_market("first_td") is True
    assert is_td_market("pass_yds") is False
    assert TD_STATS == {"first_td", "anytime_td"}
    assert YARDS_STATS == {"pass_yds", "rush_yds", "rec_yds"}


def test_parse_markets_auto_default() -> None:
    assert parse_markets(",".join(AUTO_MARKETS)) == ["pass_yds", "rush_yds", "rec_yds"]


def test_parse_markets_dedupes_and_strips() -> None:
    assert parse_markets(" first_td , first_td ,anytime_td") == [
        "first_td",
        "anytime_td",
    ]
    assert parse_markets(None) == []
    assert parse_markets("") == []


def test_parse_markets_refuses_unknown_token() -> None:
    with pytest.raises(ValueError, match="unknown --markets token"):
        parse_markets("pass_yds,nonsense")


def test_parse_markets_accepts_game_aliases() -> None:
    assert parse_markets("h2h,spreads,totals") == ["moneyline", "spread", "total"]
    assert parse_markets("moneyline,spread,total") == ["moneyline", "spread", "total"]
    assert GAME_STATS == {"moneyline", "spread", "total"}
    assert not (set(AUTO_MARKETS) & GAME_STATS)
