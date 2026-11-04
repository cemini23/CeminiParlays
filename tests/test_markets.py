import pytest

from ceminiparlays.markets import (
    AUTO_MARKETS,
    COUNT_STATS,
    GAME_STATS,
    LEGAL_MARKETS,
    TD_STATS,
    YARDS_STATS,
    canonical_stat,
    is_first_td,
    is_td_market,
    is_two_plus_td,
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


def test_pass_td_is_an_alias_of_pass_tds_not_its_own_family() -> None:
    assert parse_markets("pass_td") == ["pass_tds"]
    assert parse_markets("pass_tds") == ["pass_tds"]
    assert parse_markets("pass_td,pass_tds") == ["pass_tds"]
    # pass_td is never a legal canonical token of its own.
    assert "pass_td" not in LEGAL_MARKETS
    assert "pass_tds" in LEGAL_MARKETS


def test_two_plus_td_is_a_legal_count_market() -> None:
    assert "two_plus_td" in LEGAL_MARKETS
    assert "two_plus_td" in COUNT_STATS
    assert parse_markets("two_plus_td") == ["two_plus_td"]
    assert is_two_plus_td("two_plus_td") is True
    assert is_two_plus_td("pass_tds") is False


def test_canonical_stat_folds_a_known_alias() -> None:
    assert canonical_stat("pass_td") == "pass_tds"
    assert canonical_stat("TOTALS") == "total"
    assert canonical_stat("h2h") == "moneyline"


def test_canonical_stat_strips_an_unknown_token_without_guessing() -> None:
    assert canonical_stat("  rec_yds  ") == "rec_yds"
    assert canonical_stat("") == ""


def test_canonical_stat_does_not_lower_case_an_unknown_token() -> None:
    """The docstring promises a lower-cased token. The code does not lower-case it.

    ``catalog._canonical_stat`` does lower-case. Pinned as this function behaves
    today, because ``io.read_manual_lines`` puts the result on the pricing path
    and a change there needs a baseline rerun.
    """

    assert canonical_stat(" Rec_Yds ") == "Rec_Yds"
