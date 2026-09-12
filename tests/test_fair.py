import pytest

from ceminiparlays.fair import choose_family, p_over_line, side_probability


def test_median_trap_can_disagree_with_sign() -> None:
    result = p_over_line(line=275.5, median=268.0, sigma=55.0, family="lognormal")
    assert result.median < result.line
    assert 0.40 < result.fair_p_over < 0.55


def test_half_point_over_is_one_minus_cdf() -> None:
    result = p_over_line(line=1.5, median=1.8, sigma=1.0, family="poisson")
    assert result.fair_p_over > 0.4
    assert side_probability(result, "less") == result.fair_p_under


def test_family_tree() -> None:
    assert choose_family("pass_yds", 270) == "lognormal"
    assert choose_family("pass_tds", 1.8) == "poisson"
    assert choose_family("receptions", 5.0) == "poisson"


def test_integer_poisson_keeps_push_mass() -> None:
    result = p_over_line(line=2.0, median=2.0, sigma=0.0, family="poisson")
    assert result.fair_p_push > 0.0
    assert result.fair_p_over + result.fair_p_under + result.fair_p_push == pytest.approx(
        1.0, abs=1e-12
    )
    assert result.fair_p_over == pytest.approx(1.0 - 0.6766764, abs=1e-4)


def test_half_point_push_is_zero() -> None:
    result = p_over_line(line=2.5, median=2.0, sigma=0.0, family="poisson")
    assert result.fair_p_push == 0.0
    assert result.fair_p_over + result.fair_p_under == pytest.approx(1.0, abs=1e-12)


def test_poisson_sigma_is_flagged_not_silent() -> None:
    result = p_over_line(line=2.5, median=2.0, sigma=1.0, family="poisson")
    assert result.note == "poisson_sigma_ignored"


def test_lognormal_at_median_is_half() -> None:
    result = p_over_line(line=50.0, median=50.0, sigma=10.0, family="lognormal")
    assert result.fair_p_at_median == pytest.approx(0.5, abs=1e-6)
