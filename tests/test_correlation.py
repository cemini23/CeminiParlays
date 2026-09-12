import json
from pathlib import Path

import numpy as np
import pytest

from ceminiparlays.correlation import LegRef, _pair_rho, correlation_matrix, load_priors


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


def test_same_team_rb_rb_rush_yds_uses_fallback() -> None:
    priors = load_priors()
    a = LegRef("rb_a", "MIA", "NE", "rush_yds", "more")
    b = LegRef("rb_b", "MIA", "NE", "rush_yds", "more")
    assert _pair_rho(a, b, priors) == pytest.approx(0.08, abs=1e-12)


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
        json.dumps(
            {
                "default_cross_game": -0.9,
                "pairs": [
                    {"stat_a": "pass_yds", "stat_b": "rec_yds", "same_team": True, "rho": 0.9},
                    {"stat_a": "pass_yds", "stat_b": "pass_yds", "opponents": True, "rho": 0.9},
                ],
            }
        ),
        encoding="utf-8",
    )
    priors = json.loads(priors_path.read_text(encoding="utf-8"))
    refs = [
        LegRef("a", "KC", "BUF", "pass_yds", "more"),
        LegRef("b", "KC", "BUF", "rec_yds", "more"),
        LegRef("c", "BUF", "KC", "pass_yds", "more"),
    ]
    raw = correlation_matrix(refs, priors, repair=False)
    clean = correlation_matrix(refs, priors, repair=True)
    assert np.max(np.abs(clean - raw)) > 0.02
    assert np.all(np.linalg.eigvalsh(clean) > -1e-8)
