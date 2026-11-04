import pytest

from ceminiparlays.environment import EnvRow
from ceminiparlays.weather import apply_weather_discount


def test_weather_discount_exposed_wind() -> None:
    # Exposed, roof=open, wind 20 mph -> wind_haircut = min(0.04, max(0, 20-10)*0.002) = min(0.04, 0.02) = 0.02
    row = EnvRow(
        game_id="test",
        team="AAA",
        opponent="BBB",
        roof="open",
        weather_exposed=True,
        wind_mph=20.0,
        precip_pop=None,
    )
    result = apply_weather_discount(0.5, row)
    # 0.5 - 0.02 = 0.48
    assert abs(result.adjusted - 0.48) < 1e-9
    assert "WEATHER_DISCOUNT" in result.note
    assert "haircut_pp=0.020000" in result.note


def test_weather_discount_blank_fields() -> None:
    # Exposed, but both wind and precip are None -> no discount, blank note
    row = EnvRow(
        game_id="test",
        team="AAA",
        opponent="BBB",
        roof="open",
        weather_exposed=True,
        wind_mph=None,
        precip_pop=None,
    )
    result = apply_weather_discount(0.5, row)
    assert result.adjusted == 0.5
    assert "WEATHER_FIELDS_BLANK" in result.note


def test_weather_discount_indoor_dome() -> None:
    # Dome -> no discount
    row = EnvRow(
        game_id="test",
        team="AAA",
        opponent="BBB",
        roof="dome",
        weather_exposed=True,
        wind_mph=20.0,
        precip_pop=50.0,
    )
    result = apply_weather_discount(0.5, row)
    assert result.adjusted == 0.5
    assert "WEATHER_NO_DISCOUNT: indoor" in result.note


@pytest.mark.parametrize("roof", ["indoor", "closed"])
def test_weather_discount_indoor_and_closed_roofs(roof: str) -> None:
    # indoor and closed roofs skip discount even with wind and precip
    row = EnvRow(
        game_id="test",
        team="AAA",
        opponent="BBB",
        roof=roof,
        weather_exposed=True,
        wind_mph=20.0,
        precip_pop=50.0,
    )
    result = apply_weather_discount(0.5, row)
    assert result.adjusted == 0.5
    assert "WEATHER_NO_DISCOUNT: indoor" in result.note


def test_weather_discount_retractable_closed() -> None:
    # retractable_closed -> no discount
    row = EnvRow(
        game_id="test",
        team="AAA",
        opponent="BBB",
        roof="retractable_closed",
        weather_exposed=True,
        wind_mph=20.0,
        precip_pop=50.0,
    )
    result = apply_weather_discount(0.5, row)
    assert result.adjusted == 0.5
    assert "WEATHER_NO_DISCOUNT: retractable-closed" in result.note


def test_weather_discount_retractable_not_exposed() -> None:
    # retractable with weather_exposed=false -> no discount
    row = EnvRow(
        game_id="test",
        team="AAA",
        opponent="BBB",
        roof="retractable",
        weather_exposed=False,
        wind_mph=20.0,
        precip_pop=50.0,
    )
    result = apply_weather_discount(0.5, row)
    assert result.adjusted == 0.5
    assert "WEATHER_NO_DISCOUNT: retractable-closed" in result.note


def test_weather_discount_typed_zero_wind_precip() -> None:
    # wind=0, precip=0 are typed values (not None) -> haircut 0 with discount note, not blank note
    row = EnvRow(
        game_id="test",
        team="AAA",
        opponent="BBB",
        roof="open",
        weather_exposed=True,
        wind_mph=0.0,
        precip_pop=0.0,
    )
    result = apply_weather_discount(0.5, row)
    assert result.adjusted == 0.5
    assert "WEATHER_DISCOUNT" in result.note
    assert "haircut_pp=0.000000" in result.note
    assert "WEATHER_FIELDS_BLANK" not in result.note


def _windy_row() -> EnvRow:
    return EnvRow(
        game_id="g",
        team="AAA",
        opponent="BBB",
        roof="open",
        weather_exposed=True,
        wind_mph=25.0,
        precip_pop=80.0,
    )


def test_weather_haircuts_the_over_and_lifts_the_under() -> None:
    over = apply_weather_discount(0.5, _windy_row(), side="more", stat_type="pass_yds")
    under = apply_weather_discount(0.5, _windy_row(), side="less", stat_type="pass_yds")
    assert over.adjusted < 0.5
    assert under.adjusted > 0.5
    # The pair stays consistent: P(over) + P(under) = 1.
    assert abs(over.adjusted + under.adjusted - 1.0) < 1e-9


def test_weather_ignores_a_non_weather_stat() -> None:
    result = apply_weather_discount(0.5, _windy_row(), side="more", stat_type="sacks")
    assert result.adjusted == 0.5
    assert "not weather-sensitive" in result.note
