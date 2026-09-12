from ceminiparlays.correlation import LegRef, _pair_rho, load_priors


def test_opposite_sides_of_same_prop_are_perfectly_negative() -> None:
    priors = load_priors()
    more = LegRef("patrick_mahomes", "KC", "BUF", "pass_yds", "more")
    less = LegRef("patrick_mahomes", "KC", "BUF", "pass_yds", "less")
    assert _pair_rho(more, less, priors) == -1.0


def test_opposite_sides_flip_same_team_prior() -> None:
    priors = load_priors()
    qb_over = LegRef("patrick_mahomes", "KC", "BUF", "pass_yds", "more")
    wr_over = LegRef("travis_kelce", "KC", "BUF", "rec_yds", "more")
    wr_under = LegRef("travis_kelce", "KC", "BUF", "rec_yds", "less")
    assert _pair_rho(qb_over, wr_over, priors) > 0
    assert _pair_rho(qb_over, wr_under, priors) < 0
