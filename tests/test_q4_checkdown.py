"""Lambda direction and the v3 side rule for the Q4 checkdown funnel."""

import math

import pytest

from ceminiparlays.q4_checkdown import CheckdownInputs, checkdown_lambda, price_checkdown


def _inputs(**kwargs: object) -> CheckdownInputs:
    base = {
        "games": 6,
        "receptions_per_game": 4.0,
        "rec_yds_per_game": 32.0,
        "targets_per_game": 5.0,
        "opps_q": 10.0,
        "opps_total": 40.0,
        "q4_trail_target_share": 0.20,
        "vacated_target_boost": 0.0,
        "avg_cushion": 3.0,
        "def_q4_comp_rate": 0.55,
        "def_q4_yac": 4.8,
        "league_trail_share": 0.20,
        "league_cushion": 3.0,
        "league_comp": 0.55,
        "league_yac": 4.8,
        "quarter": 4,
    }
    base.update(kwargs)
    return CheckdownInputs(**base)  # type: ignore[arg-type]


def test_vacated_targets_raise_lambda() -> None:
    low = checkdown_lambda(_inputs())
    high = checkdown_lambda(_inputs(vacated_target_boost=2))
    assert low is not None and high is not None
    assert high.vacated_receptions == pytest.approx(1.6)
    assert high.lam > low.lam


def test_trail_share_raises_q4_and_not_q3() -> None:
    base = checkdown_lambda(_inputs())
    hot = checkdown_lambda(_inputs(q4_trail_target_share=0.40))
    q3 = checkdown_lambda(_inputs(quarter=3))
    q3_hot = checkdown_lambda(_inputs(quarter=3, q4_trail_target_share=0.40))
    assert base is not None and hot is not None and q3 is not None and q3_hot is not None
    assert hot.lam > base.lam
    assert q3_hot.lam == pytest.approx(q3.lam)


def test_soft_defense_and_tight_cushion_raise_lambda() -> None:
    base = checkdown_lambda(_inputs())
    soft = checkdown_lambda(_inputs(def_q4_comp_rate=0.70))
    tight = checkdown_lambda(_inputs(avg_cushion=1.5))
    assert base is not None and soft is not None and tight is not None
    assert soft.lam > base.lam
    assert tight.lam > base.lam


def test_missing_volume_returns_none() -> None:
    assert checkdown_lambda(_inputs(games=0)) is None
    assert price_checkdown(_inputs(games=0), "receptions_q4", 0.5, -110, -110) is None


def test_poisson_half_point_matches_one_minus_exp() -> None:
    priced = price_checkdown(
        _inputs(receptions_per_game=8, targets_per_game=10, opps_q=20, opps_total=40),
        "receptions_q4",
        0.5,
        -110,
        -110,
    )
    assert priced is not None
    p_over = 1.0 - math.exp(-priced.lam)
    if priced.side == "over":
        assert priced.model_p == pytest.approx(p_over)
    else:
        assert priced.model_p == pytest.approx(1.0 - p_over)


def test_side_follows_the_fair_price() -> None:
    over = price_checkdown(
        _inputs(receptions_per_game=8, targets_per_game=10, opps_q=20, opps_total=40),
        "receptions_q4",
        0.5,
        -110,
        -110,
    )
    under = price_checkdown(
        _inputs(receptions_per_game=0.2, targets_per_game=0.4, opps_q=0, opps_total=0),
        "receptions_q4",
        0.5,
        -110,
        -110,
    )
    assert over is not None and over.side == "over"
    assert under is not None and under.side == "under"


def test_yards_market_must_match_the_quarter() -> None:
    with pytest.raises(ValueError):
        price_checkdown(_inputs(quarter=4), "rec_yds_q3", 10.5, -110, -110)


def test_yards_hurdle_returns_one_side() -> None:
    priced = price_checkdown(_inputs(), "rec_yds_q4", 10.5, -110, -110)
    assert priced is not None
    assert priced.side in {"over", "under"}
    assert priced.market == "rec_yds_q4"
