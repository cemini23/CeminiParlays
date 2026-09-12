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
