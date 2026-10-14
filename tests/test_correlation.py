import json
from pathlib import Path

import numpy as np
import pytest

from ceminiparlays.correlation import (
    LegRef,
    UnmodeledCorrelationError,
    _pair_rho,
    correlation_matrix,
    load_priors,
)


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


def test_same_team_wr_wr_rec_yds_is_point_one() -> None:
    priors = load_priors()
    a = LegRef("wr_a", "MIA", "NE", "rec_yds", "more")
    b = LegRef("wr_b", "MIA", "NE", "rec_yds", "more")
    assert _pair_rho(a, b, priors) == pytest.approx(0.10, abs=1e-12)


def test_same_team_rb_rb_rush_yds_uses_the_prior() -> None:
    # Two backs on one team compete for carries: the prior is negative, not the
    # old +0.08 guessed fallback (A-03).
    priors = load_priors()
    a = LegRef("rb_a", "MIA", "NE", "rush_yds", "more")
    b = LegRef("rb_b", "MIA", "NE", "rush_yds", "more")
    assert _pair_rho(a, b, priors) == pytest.approx(-0.18, abs=1e-12)


def test_unmodeled_same_game_pair_is_refused() -> None:
    priors = load_priors()
    a = LegRef("qb", "KC", "BUF", "pass_yds", "more")
    b = LegRef("wr", "KC", "BUF", "two_plus_td", "more")
    with pytest.raises(UnmodeledCorrelationError):
        _pair_rho(a, b, priors)


def test_unmodeled_pair_falls_back_when_allowed() -> None:
    priors = load_priors()
    a = LegRef("qb", "KC", "BUF", "pass_yds", "more")
    b = LegRef("wr", "KC", "BUF", "two_plus_td", "more")
    assert _pair_rho(a, b, priors, allow_unmodeled=True) == pytest.approx(0.08)


def test_same_player_multi_stat_uses_the_same_player_prior() -> None:
    priors = load_priors()
    a = LegRef("wr", "KC", "BUF", "receptions", "more")
    b = LegRef("wr", "KC", "BUF", "rec_yds", "more")
    assert _pair_rho(a, b, priors) == pytest.approx(0.80, abs=1e-12)
    qb_yards = LegRef("qb", "KC", "BUF", "pass_yds", "more")
    qb_tds = LegRef("qb", "KC", "BUF", "pass_tds", "more")
    assert _pair_rho(qb_yards, qb_tds, priors) == pytest.approx(0.52, abs=1e-12)


def test_same_team_qb_wr_is_point_forty_five() -> None:
    priors = load_priors()
    qb = LegRef("qb", "KC", "BUF", "pass_yds", "more")
    wr = LegRef("wr", "KC", "BUF", "rec_yds", "more")
    assert _pair_rho(qb, wr, priors) == pytest.approx(0.45, abs=1e-12)


def test_under_under_matches_over_over_sign() -> None:
    priors = load_priors()
    qb_over = LegRef("qb", "KC", "BUF", "pass_yds", "more")
    wr_over = LegRef("wr", "KC", "BUF", "rec_yds", "more")
    qb_under = LegRef("qb", "KC", "BUF", "pass_yds", "less")
    wr_under = LegRef("wr", "KC", "BUF", "rec_yds", "less")
    assert _pair_rho(qb_under, wr_under, priors) == pytest.approx(
        _pair_rho(qb_over, wr_over, priors), abs=1e-12
    )


def test_same_player_different_stat_is_not_a_perfect_pair() -> None:
    priors = load_priors()
    yds = LegRef("qb", "KC", "BUF", "pass_yds", "more")
    tds = LegRef("qb", "KC", "BUF", "pass_tds", "more")
    assert abs(_pair_rho(yds, tds, priors)) < 1.0


def test_correlation_matrix_repair_flag_exposes_raw_priors(tmp_path: Path) -> None:
    priors_path = tmp_path / "priors.json"
    priors_path.write_text(
        # Three cross-game legs, all pairwise -0.9: indefinite (eigenvalue -0.8),
        # so the repair must change the raw prior matrix.
        json.dumps({"default_cross_game": -0.9, "pairs": []}),
        encoding="utf-8",
    )
    priors = json.loads(priors_path.read_text(encoding="utf-8"))
    refs = [
        LegRef("a", "KC", "BUF", "pass_yds", "more"),
        LegRef("b", "MIA", "NE", "pass_yds", "more"),
        LegRef("c", "DAL", "PHI", "pass_yds", "more"),
    ]
    raw = correlation_matrix(refs, priors, repair=False)
    clean = correlation_matrix(refs, priors, repair=True)
    assert np.max(np.abs(clean - raw)) > 0.02
    assert np.all(np.linalg.eigvalsh(clean) > -1e-8)
