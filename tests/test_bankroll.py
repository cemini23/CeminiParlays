import pytest

from ceminiparlays.bankroll import flat_stake, kelly_cap_stake


def test_bankroll_25_over_5_tickets() -> None:
    assert flat_stake(25, 5) == 5.00
    assert kelly_cap_stake(25) == 1.25


def test_kelly_cap_is_the_existing_five_percent_cap() -> None:
    assert kelly_cap_stake(1000) == 50.0
    assert kelly_cap_stake(0) == 0.0


def test_flat_stake_rounds_to_cents() -> None:
    assert flat_stake(10, 3) == 3.33


def test_bankroll_validation() -> None:
    with pytest.raises(ValueError, match="n_tickets"):
        flat_stake(25, 0)
    with pytest.raises(ValueError, match="non-negative"):
        flat_stake(-1, 5)
    with pytest.raises(ValueError, match="non-negative"):
        kelly_cap_stake(-1)
