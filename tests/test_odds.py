from ceminiparlays.odds import american_to_decimal, devig_two_way, market_width_cents


def test_american_to_decimal() -> None:
    assert american_to_decimal(-110) == 1.0 + 100 / 110
    assert american_to_decimal(120) == 2.2


def test_power_devig_asymmetric_prop() -> None:
    result = devig_two_way(-155, 120, method="power")
    assert 0.575 < result.p_over < 0.585
    assert abs(result.p_over + result.p_under - 1.0) < 1e-9
    assert result.raw_overround > 0
    assert result.k_exponent > 1.0


def test_multiplicative_and_additive_diverge_on_juice() -> None:
    multi = devig_two_way(-155, 120, method="multiplicative")
    additive = devig_two_way(-155, 120, method="additive")
    assert additive.p_over > multi.p_over


def test_minus_110_pair_is_coin_flip() -> None:
    result = devig_two_way(-110, -110, method="power")
    assert abs(result.p_over - 0.5) < 1e-9
    assert market_width_cents(-110, -110) == 0
    assert market_width_cents(-115, -105) == 10
