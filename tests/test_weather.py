import numpy as np
from ceminiparlays.environment import EnvRow
from ceminiparlays.weather import apply_weather_discount, sgp_from_score_marginals
from ceminiparlays.copula import exact_joint


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


def test_sgp_from_score_marginals_with_weather() -> None:
    # Two legs, one with weather discount
    marginals = [0.5, 0.5]
    corr = np.array([[1.0, 0.2], [0.2, 1.0]])
    rows = [
        EnvRow(
            game_id="test1",
            team="AAA",
            opponent="BBB",
            roof="open",
            weather_exposed=True,
            wind_mph=20.0,
            precip_pop=None,
        ),
        EnvRow(
            game_id="test2",
            team="CCC",
            opponent="DDD",
            roof="dome",
            weather_exposed=False,
            wind_mph=None,
            precip_pop=None,
        ),
    ]
    joint, notes = sgp_from_score_marginals(marginals, corr, rows)
    # Leg 1: 0.5 -> 0.48 (wind haircut 0.02)
    # Leg 2: 0.5 (indoor, no discount)
    # Joint should be < exact_joint([0.5, 0.5], corr) = naive * copula_factor
    raw_joint = exact_joint([0.5, 0.5], corr)
    assert joint < raw_joint
    # Check notes
    assert any("WEATHER_DISCOUNT" in n for n in notes)
    assert any("WEATHER_NO_DISCOUNT: indoor" in n for n in notes)


def test_sgp_from_score_marginals_no_rows() -> None:
    # No env rows provided -> no discounts
    marginals = [0.5, 0.5]
    corr = np.array([[1.0, 0.2], [0.2, 1.0]])
    joint, notes = sgp_from_score_marginals(marginals, corr, [])
    raw_joint = exact_joint([0.5, 0.5], corr)
    assert abs(joint - raw_joint) < 1e-9
    assert all("no env row provided" in n for n in notes)


def test_sgp_from_score_marginals_fewer_rows_than_marginals() -> None:
    # Fewer rows than marginals -> remaining legs get no discount
    marginals = [0.5, 0.5, 0.5]
    corr = np.eye(3)
    corr[0, 1] = corr[1, 0] = 0.2
    rows = [
        EnvRow(
            game_id="test1",
            team="AAA",
            opponent="BBB",
            roof="open",
            weather_exposed=True,
            wind_mph=20.0,
            precip_pop=None,
        ),
    ]
    joint, notes = sgp_from_score_marginals(marginals, corr, rows)
    # Leg 1 discounted, legs 2 and 3 not
    assert len(notes) == 3
    assert "WEATHER_DISCOUNT" in notes[0]
    assert "no env row provided" in notes[1]
    assert "no env row provided" in notes[2]