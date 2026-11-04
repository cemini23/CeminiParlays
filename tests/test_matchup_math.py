"""The locked math helpers: clipping, floors, shrinkage, and the verdict rules."""

import random

import pytest

from ceminiparlays.matchup_math import (
    CELLS,
    COUNT_SIGMA_FLOOR,
    FDR_Q,
    MIN_HIST,
    MIN_PLAYS,
    POINT_SIGMA_FLOOR,
    YARD_SIGMA_FLOOR,
    Z_CLIP,
    cell_specs,
    combine_verdict,
    fair_over_prob,
    gamma_shape_rate,
    half_line_share,
    hist_verdict,
    implied_yards_mean,
    leg_ev,
    shrunk,
    sigma_floor,
    split_lambda,
    weibull_fit,
    z_score,
)


def _plays(count: int = 40, seed: int = 0) -> list[float]:
    rng = random.Random(seed)
    return [rng.weibullvariate(2.0, 1.0) for _ in range(count)]


def test_z_score_clips_at_the_limit() -> None:
    assert z_score(120.0, 100.0, 10.0) == 2.0
    assert z_score(120.0, 100.0, 10.0) == Z_CLIP
    assert z_score(0.0, 100.0, 10.0) == -Z_CLIP


def test_z_score_is_the_raw_ratio_inside_the_clip() -> None:
    assert z_score(110.0, 100.0, 20.0) == 0.5


def test_z_score_refuses_a_non_positive_scale() -> None:
    with pytest.raises(ValueError, match="scale must be positive"):
        z_score(1.0, 1.0, 0.0)


def test_sigma_floor_holds_the_locked_floor_on_a_small_line() -> None:
    assert sigma_floor("yards", 10.0) == YARD_SIGMA_FLOOR
    assert sigma_floor("count", 1.0) == COUNT_SIGMA_FLOOR
    assert sigma_floor("points", 10.0) == POINT_SIGMA_FLOOR


def test_sigma_floor_follows_a_quarter_of_a_large_line() -> None:
    assert sigma_floor("yards", 100.0) == 25.0
    assert sigma_floor("count", 4.0) == 1.0
    assert sigma_floor("points", 50.0) == 12.5


def test_sigma_floor_refuses_an_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unknown sigma kind"):
        sigma_floor("bogus", 50.0)


def test_gamma_shape_rate_floors_the_sd_and_the_mean() -> None:
    shape, rate = gamma_shape_rate(4.0, 2.0)
    assert (shape, rate) == (1.0, 0.25)
    # A zero mean and a zero sd still return a usable pair.
    tiny_shape, tiny_rate = gamma_shape_rate(0.0, 0.0)
    assert tiny_shape > 0.0 and tiny_rate > 0.0


def test_shrunk_pulls_toward_the_league_value() -> None:
    assert shrunk(10, 5.0, 4.0) > 4.0
    assert shrunk(10, 5.0, 4.0) < 5.0


def test_shrunk_returns_the_league_value_for_no_sample() -> None:
    assert shrunk(0, 5.0, 4.0) == 4.0


def test_split_lambda_scales_with_volume_and_stays_non_negative() -> None:
    assert split_lambda(20.0, 2.0, 4.0, 1.1) > 0.0
    assert split_lambda(0.0, 2.0, 4.0, 1.1) == 0.0
    assert split_lambda(-5.0, 2.0, 4.0, 1.1) == 0.0


def test_fair_over_prob_strips_the_vig() -> None:
    assert fair_over_prob(-110, -110) == pytest.approx(0.5, abs=1e-9)
    assert 0.0 < fair_over_prob(-150, 130) < 1.0


def test_leg_ev_is_the_payout_less_the_stake() -> None:
    assert leg_ev(0.55, 100) == pytest.approx(0.10, abs=1e-9)
    assert leg_ev(0.5, 100) == pytest.approx(0.0, abs=1e-9)
    assert leg_ev(0.5, -110) < 0.0


def test_implied_yards_mean_returns_the_line_at_an_even_split() -> None:
    assert implied_yards_mean(50.5, 0.5, 10.0) == pytest.approx(50.5, abs=1e-6)


def test_implied_yards_mean_refuses_a_non_positive_sd() -> None:
    assert implied_yards_mean(50.5, 0.5, 0.0) is None


def test_half_line_share_counts_lines_at_or_below_a_half() -> None:
    assert half_line_share([0.5, 10.5, 0.5]) == pytest.approx(2 / 3)
    assert half_line_share([]) == 0.0


def test_cell_specs_covers_every_configured_cell() -> None:
    specs = cell_specs()
    assert len(specs) == len(CELLS)
    assert specs[0].market == CELLS[0][0]


def test_weibull_fit_needs_the_minimum_play_count() -> None:
    assert weibull_fit([1.0] * (MIN_PLAYS - 1)) is None


def test_weibull_fit_returns_a_positive_shape_and_scale() -> None:
    fitted = weibull_fit(_plays())
    assert fitted is not None
    shape, scale = fitted
    assert shape > 0.0 and scale > 0.0


def test_hist_verdict_reports_each_failing_gate() -> None:
    assert hist_verdict(n_hist=MIN_HIST - 1, delta_brier=0.0, ci_low=0.0, q_value=0.0) == (
        "fail",
        "too_few_hist",
    )
    assert hist_verdict(n_hist=MIN_HIST, delta_brier=0.0, ci_low=0.0, q_value=0.0) == (
        "fail",
        "no_brier_skill",
    )
    assert hist_verdict(n_hist=MIN_HIST, delta_brier=0.01, ci_low=0.0, q_value=0.0) == (
        "fail",
        "hist_ci",
    )
    assert hist_verdict(
        n_hist=MIN_HIST, delta_brier=0.01, ci_low=0.001, q_value=None
    ) == ("fail", "hist_fdr")


def test_hist_verdict_passes_when_every_gate_holds() -> None:
    assert hist_verdict(
        n_hist=MIN_HIST, delta_brier=0.01, ci_low=0.001, q_value=FDR_Q / 2
    ) == ("pass", "hist_pass")


def test_combine_verdict_fails_closed_without_history() -> None:
    assert combine_verdict(("pass", "live"), None) == ("fail", "no_hist")


def test_combine_verdict_needs_both_keys() -> None:
    assert combine_verdict(("pass", "live"), ("pass", "hist")) == ("pass", "pass")
    assert combine_verdict(("pass", "live"), ("fail", "hist_fdr")) == ("fail", "hist_fdr")
    assert combine_verdict(("fail", "live_reason"), ("pass", "hist")) == (
        "fail",
        "live_reason",
    )
