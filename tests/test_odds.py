import pytest

from ceminiparlays.odds import (
    american_to_decimal,
    american_to_implied,
    decimal_to_american,
    devig_multiway,
    devig_spread,
    devig_two_way,
    market_width_cents,
)


def test_american_to_decimal() -> None:
    assert american_to_decimal(-110) == 1.0 + 100 / 110
    assert american_to_decimal(120) == 2.2
    assert american_to_decimal(-100) == 2.0
    assert american_to_decimal(100) == 2.0
    assert decimal_to_american(2.6) == 160
    assert decimal_to_american(american_to_decimal(-110)) == -110


@pytest.mark.parametrize("odds", [-10, 50, 99, -99])
def test_american_to_decimal_rejects_inside_juice_band(odds: int) -> None:
    with pytest.raises(ValueError, match=r"<= -100 or >= \+100"):
        american_to_decimal(odds)


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


def test_power_devig_retries_wider_bracket() -> None:
    result = devig_two_way(-2000, -2000, method="power")
    assert abs(result.p_over - 0.5) < 1e-9


def test_power_devig_unbracketed_raises_clear_message() -> None:
    with pytest.raises(ValueError, match="power de-vig could not bracket k"):
        devig_two_way(-100000, -100000, method="power")


def test_devig_spread_reports_all_methods() -> None:
    spread = devig_spread(-155, 120)
    assert spread["spread_pp"] > 0
    assert spread["unstable"] is False
    assert spread["multiplicative_p_over"] != spread["additive_p_over"]


def test_devig_spread_flags_unstable_market() -> None:
    spread = devig_spread(-300, 200)
    assert spread["spread_pp"] > 1.5
    assert spread["unstable"] is True


def test_devig_multiway_power_strips_pool_overround() -> None:
    # A first_td pool: raw implied probabilities sum well above 1 (the pool vig).
    # Power de-vig scales each one down so the pool sums to 1.
    result = devig_multiway([200, 150, 120, 100], method="power")
    assert abs(sum(result.probs) - 1.0) < 1e-9
    raw = [american_to_implied(o) for o in (200, 150, 120, 100)]
    assert all(p < r for p, r in zip(result.probs, raw))
    assert result.k_exponent > 1.0


def test_devig_multiway_incomplete_pool_is_not_inflated() -> None:
    # Sum < 1 means outcomes are missing. Normalizing would inflate every leg, so
    # the raw implied probability is kept.
    result = devig_multiway([320, 145], method="power")
    assert abs(result.probs[0] - american_to_implied(320)) < 1e-12
    assert "incomplete" in result.note


def test_devig_multiway_hold_haircuts_a_one_way_pool() -> None:
    plain = devig_multiway([145, 320], method="power")
    held = devig_multiway([145, 320], method="power", hold_pct=0.15)
    assert held.probs[0] < plain.probs[0]
    assert abs(held.probs[0] - plain.probs[0] * 0.85) < 1e-12
    assert "hold" in held.note


def test_devig_multiway_rejects_empty_pool() -> None:
    with pytest.raises(ValueError, match="at least one price"):
        devig_multiway([])
