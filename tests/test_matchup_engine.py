"""Point-in-time lag, tail math, de-vig, and the FDR gate."""

from __future__ import annotations

import math
import random
from pathlib import Path

import pytest

from ceminiparlays.hardrock_book import _base_stat
from ceminiparlays.markets import parse_markets
from ceminiparlays.matchup_features import _prior_frame
from ceminiparlays.compose import joint_ticket
from ceminiparlays.matchup_math import (
    baseline_volume,
    bh_qvalues,
    bootstrap_ci,
    bootstrap_means,
    defense_multiplier,
    eb_mean,
    hurdle_over_prob,
    implied_count_mean,
    interaction,
    maxima_over_prob,
    one_sided_p,
    poisson_over_prob,
    prior_to,
    quarter_share,
    referee_multiplier,
    slate_floor,
    tail_over_prob,
    verdict_for,
)
from ceminiparlays.matchup_scanner import format_flags
from ceminiparlays.matchup_score import score_board
from ceminiparlays.odds import devig_two_way


def test_gate_promotes_the_two_key_tokens_and_keeps_receptions_q1_out() -> None:
    assert parse_markets(
        "rec_yds_q3,rec_yds_q4,receptions_q4,rush_yds_q4,pass_yds_q4,interceptions,total_q3"
    ) == [
        "rec_yds_q3",
        "rec_yds_q4",
        "receptions_q4",
        "rush_yds_q4",
        "pass_yds_q4",
        "interceptions",
        "total_q3",
    ]
    for token in ("receptions_q1", "rec_longest", "rush_longest"):
        with pytest.raises(ValueError):
            parse_markets(token)


def test_prior_week_is_excluded_from_the_feature_window() -> None:
    assert prior_to(2026, 6, 2026, 6) is False
    assert prior_to(2026, 5, 2026, 6) is True
    assert prior_to(2025, 18, 2026, 6) is True
    pandas = pytest.importorskip("pandas")
    frame = pandas.DataFrame(
        {"season": [2026, 2026, 2025], "week": [6, 5, 18], "stat": [999, 1, 2]}
    )
    kept = _prior_frame(frame, 2026, 6)
    assert kept["stat"].tolist() == [1, 2]
    assert 999 not in kept["stat"].tolist()


def test_longest_play_tail_uses_the_product_of_cdfs() -> None:
    assert maxima_over_prob(0.5, 2) == pytest.approx(0.75)
    assert maxima_over_prob(1.0, 4) == 0.0
    assert maxima_over_prob(0.0, 3) == 1.0
    # Exponential Weibull: shape 1, scale 10, P(X > 20) = exp(-2).
    assert tail_over_prob(1.0, 10.0, 20.0, 1.0, 0.0) == pytest.approx(math.exp(-2.0))
    # A positive matchup adjustment stretches the scale and raises the tail.
    base = tail_over_prob(1.0, 10.0, 20.0, 2.0, 0.0)
    bumped = tail_over_prob(1.0, 10.0, 20.0, 2.0, 0.15)
    assert base is not None and bumped is not None
    assert bumped > base


def test_poisson_half_line_and_integer_void() -> None:
    from scipy.stats import poisson

    assert poisson_over_prob(1.0, 0.5) == pytest.approx(1.0 - float(poisson.cdf(0, 1.0)))
    with pytest.raises(ValueError):
        poisson_over_prob(1.0, 2.0)


def test_power_devig_of_a_balanced_price_is_one_half() -> None:
    result = devig_two_way(-115, -115)
    assert result.p_over == pytest.approx(0.5)
    assert result.p_under == pytest.approx(0.5)


def test_bh_qvalues_are_monotone_from_the_largest_rank() -> None:
    adjusted = bh_qvalues([0.001, 0.04, 0.03, 0.2])
    assert adjusted[0] == pytest.approx(0.004)
    assert adjusted[1] == pytest.approx(0.0533333333)
    assert adjusted[2] == pytest.approx(0.0533333333)
    assert adjusted[3] == pytest.approx(0.2)


def test_interaction_clip_is_the_locked_cap() -> None:
    assert interaction(2, 2, 0.15) == 0.15
    assert interaction(2, 2, 0.10) == 0.10
    assert interaction(0, 2, 0.15) == 0.0
    assert interaction(-2, 2, 0.15) == -0.15


def test_baseline_volume_never_moves_a_low_mean_up() -> None:
    assert baseline_volume(10, 0.4) == pytest.approx(0.4)
    assert baseline_volume(1, 0.2) == pytest.approx(0.2)
    assert baseline_volume(1, 4.0) == pytest.approx((4.0 + 2.4) / 3.0)
    assert baseline_volume(0, 1.0) is None
    assert quarter_share(10, 40) == pytest.approx(0.25)
    assert quarter_share(0, 0) == pytest.approx(0.25)
    assert defense_multiplier(2.0, 1.0) == pytest.approx(1.25)
    assert defense_multiplier(0.5, 1.0) == pytest.approx(0.80)
    assert referee_multiplier(2.0, 2.0) == pytest.approx(1.05)
    assert referee_multiplier(None, 0.1) == pytest.approx(1.0)
    posted = poisson_over_prob(2.5, 1.5)
    assert implied_count_mean(1.5, posted) == pytest.approx(2.5, abs=1e-3)


def test_backup_quarter_volume_is_not_pulled_up_to_the_starter_mean() -> None:
    players = [
        {
            "player_key": "backup",
            "initial": "b",
            "last": "backup",
            "team": "HOU",
            "n_rec": "10",
            "receptions_mean": "1.0",
            "q4_receptions_mean": "0.2",
            "q4_target_n": "3",
            "target_n": "40",
            "q4_target_share_mean": "0.02",
            "q4_ypc_mean": "8",
            "q4_ypc_sd": "4",
        }
    ]
    teams = [
        {
            "team": "HOU",
            "n_games": "10",
            "q4_completion_allowed": "0.60",
            "p0_rec": "0.2",
            "roof": "outdoors",
        },
        {
            "team": "JAX",
            "n_games": "10",
            "q4_completion_allowed": "0.60",
            "p0_rec": "0.2",
            "roof": "outdoors",
        },
    ]
    lines = [
        {
            "stat_type": "receptions_q4",
            "line_type": "half",
            "player_name": "B Backup",
            "player_key": "backup",
            "team": "Los Angeles Rams",
            "opp": "JAX",
            "line": "0.5",
            "book_over": "300",
            "book_under": "-400",
            "commence_time": "2026-10-18T17:00:00Z",
        }
    ]
    # The book team is a full name with no HOU row, so this leg must drop.
    _summaries, dropped = score_board(lines, players, teams)
    assert dropped == []
    lines[0]["team"] = "HOU"
    _summaries, legs = score_board(lines, players, teams)
    assert len(legs) == 1
    assert legs[0]["team"] == "HOU"
    assert legs[0]["offense_team"] == "HOU"
    assert legs[0]["side"] == "under"
    over_p = 1.0 - float(legs[0]["model_p"])
    assert over_p < 0.25


def test_joint_ticket_of_two_even_money_legs_is_the_product() -> None:
    import numpy as np

    ticket = joint_ticket([0.5, 0.5], [100, 100], np.eye(2))
    assert ticket["joint_p"] == pytest.approx(0.25, abs=1e-6)
    assert ticket["indep_p"] == pytest.approx(0.25)
    assert ticket["joint_ev"] == pytest.approx(0.0, abs=1e-6)
    assert ticket["naive_joint_ev"] == pytest.approx(0.0, abs=1e-6)
    assert ticket["tax_adjusted_sgp_ev"] == pytest.approx(0.0, abs=1e-6)
    assert ticket["sgp_tax_applied"] is False
    assert ticket["correlation_alpha"] == pytest.approx(0.0, abs=1e-6)
    assert ticket["price_source"] == "leg_odds_naive"
    assert ticket["unconfirmed"] is True


def test_joint_ticket_haircut_uses_the_vigged_copula() -> None:
    import numpy as np

    from ceminiparlays.copula import exact_joint

    corr = np.array([[1.0, 0.60], [0.60, 1.0]])
    ticket = joint_ticket([0.40, 0.40], [100, 100], corr)
    p_joint = float(exact_joint([0.40, 0.40], corr, "gaussian"))
    p_copula_vig = float(exact_joint([0.50, 0.50], corr, "gaussian"))
    p_book = 0.25 + 0.55 * (p_copula_vig - 0.25)
    assert ticket["naive_joint_ev"] == pytest.approx(p_joint * 4.0 - 1.0)
    assert ticket["tax_adjusted_sgp_ev"] == pytest.approx(p_joint / p_book - 1.0)
    assert ticket["tax_adjusted_sgp_ev"] < ticket["naive_joint_ev"]
    assert ticket["sgp_tax_applied"] is True
    assert ticket["price_source"] == "leg_odds_naive"


def test_rank_same_game_drops_same_player_receptions_and_yards() -> None:
    from ceminiparlays.compose import rank_same_game, redundant_quarter_pair

    def leg(key: str, market: str, side: str, price: int, prob: float) -> dict:
        return {
            "player_key": key,
            "player_name": key,
            "team": "LAR",
            "opp": "ARI",
            "market": market,
            "side": side,
            "line": "0.5",
            "price": str(price),
            "model_p": str(prob),
        }

    same = leg("00-1", "receptions_q4", "over", 230, 0.47)
    yards = leg("00-1", "rec_yds_q4", "over", 240, 0.45)
    rush = leg("00-1", "rush_yds_q4", "under", -120, 0.75)
    other = leg("00-2", "receptions_q4", "over", 110, 0.60)
    earlier = leg("00-1", "rec_yds_q3", "over", 170, 0.53)
    assert redundant_quarter_pair(same, yards) is True
    assert redundant_quarter_pair(yards, same) is True
    assert redundant_quarter_pair(same, rush) is False
    assert redundant_quarter_pair(same, other) is False
    assert redundant_quarter_pair(earlier, yards) is False
    priced = rank_same_game([same, yards, rush, other, earlier])
    banned = {("00-1", "receptions_q4"), ("00-1", "rec_yds_q4")}
    for row in priced:
        markets = {(str(item["player_key"]), str(item["market"])) for item in row["legs"]}
        assert not banned <= markets
    cross = [
        row
        for row in priced
        if {str(item["market"]) for item in row["legs"]} == {"receptions_q4", "rec_yds_q4"}
        and {str(item["player_key"]) for item in row["legs"]} == {"00-1", "00-2"}
    ]
    assert len(cross) == 1
    assert cross[0]["sgp_tax_applied"] is True
    from ceminiparlays.matchup_scanner import format_same_game

    text = format_same_game([same, yards, rush, other, earlier])
    assert "sgp_rank=tax_adjusted" in text
    for line in text.splitlines():
        assert not (
            "00-1|receptions_q4" in line and "00-1|rec_yds_q4" in line
        )


def test_hurdle_half_line_is_the_zero_mass_formula() -> None:
    lam = 0.7
    gain = 0.9
    priced = hurdle_over_prob(lam, alpha=100.0, rate=1.0, line=0.5, p_gain=gain)
    assert priced == pytest.approx((1.0 - math.exp(-lam)) * gain)
    assert hurdle_over_prob(0.0, 1.0, 1.0, 0.5, 1.0) == 0.0
    assert eb_mean(1, 8.0, 0.7, k=12) == pytest.approx(16.4 / 13.0)


def test_bootstrap_means_match_a_pure_randrange_loop() -> None:
    values = [0.2, -0.1, 0.5, 0.0, 1.1]
    left = bootstrap_means(values, random.Random(7), n_boot=30)
    rng = random.Random(7)
    width = len(values)
    right = []
    for _draw in range(30):
        total = 0.0
        for _index in range(width):
            total += values[rng.randrange(width)]
        right.append(total / width)
    assert left == pytest.approx(right)


def test_verdict_uses_the_cardinality_floor() -> None:
    assert slate_floor("rec_yds_q3") == 35
    assert slate_floor("pass_attempts") == 16
    assert slate_floor("total_q3") == 10
    assert verdict_for(
        n_legs=34,
        mean_ev=0.1,
        ci_low=0.01,
        q_value=0.01,
        market="rec_yds_q3",
    ) == ("fail", "cardinality")
    assert verdict_for(
        n_legs=35,
        mean_ev=0.1,
        ci_low=0.01,
        q_value=0.10,
        one_leg_ci_low=-0.01,
        half_share=0.9,
        market="rec_yds_q3",
    ) == ("pass", "live_pass")
    assert verdict_for(
        n_legs=15,
        mean_ev=0.1,
        ci_low=0.01,
        q_value=0.01,
        market="pass_attempts",
    ) == ("fail", "cardinality")
    assert verdict_for(
        n_legs=16,
        mean_ev=0.1,
        ci_low=0.01,
        q_value=0.10,
        market="pass_attempts",
    ) == ("pass", "live_pass")
    assert verdict_for(
        n_legs=40,
        mean_ev=0.1,
        ci_low=0.01,
        q_value=0.2,
        market="rec_yds_q3",
    ) == ("fail", "fdr")


def test_one_sided_bootstrap_p_is_high_when_the_mean_is_negative() -> None:
    p_value = one_sided_p([-1.0, -1.0, -1.0, -1.0], random.Random(1), n_boot=50)
    assert p_value == 1.0
    low, high = bootstrap_ci([0.2, 0.2, 0.2], random.Random(2), n_boot=20)
    assert low == pytest.approx(0.2)
    assert high == pytest.approx(0.2)


def test_longest_reception_marker_is_not_a_receptions_token() -> None:
    assert _base_stat("AMERICAN_FOOTBALL:FT:PROPLNGREC", "A - Longest Reception") == "rec_longest"
    assert _base_stat("AMERICAN_FOOTBALL:FT:PROPREC", "A - Receptions") == "receptions"
    assert _base_stat("AMERICAN_FOOTBALL:FT:PROPPSATT", "A - Pass Attempts") == "pass_attempts"
    assert _base_stat("AMERICAN_FOOTBALL:FT:PROPINTMULTILINE", "A - Interceptions") == "interceptions"


def test_score_board_is_byte_identical(tmp_path: Path) -> None:
    players = [
        {
            "player_key": "a_player",
            "initial": "a",
            "last": "player",
            "n_rec": "1",
            "n_rush": "0",
            "n_pass": "0",
            "n_kick": "0",
            "q3_rec_yds_mean": "10",
            "q3_rec_yds_sd": "4",
            "q3_target_share_mean": "0.2",
        }
    ]
    teams = [{"team": "HOU", "n_games": "1", "q3_epa_allowed": "0.1", "roof": "outdoors"}]
    lines = [
        {
            "stat_type": "rec_yds_q3",
            "line_type": "quarter",
            "player_name": "A Player",
            "player_key": "a_player",
            "team": "HOU",
            "opp": "JAX",
            "line": "12.5",
            "book_over": "-110",
            "book_under": "-110",
            "commence_time": "2026-10-18T17:00:00Z",
        }
    ]
    first, _legs = score_board(lines, players, teams)
    second, _again = score_board(lines, players, teams)
    assert first == second
    from ceminiparlays.matchup_score import EV_FIELDS, _write

    left = tmp_path / "a.csv"
    right = tmp_path / "b.csv"
    _write(left, EV_FIELDS, first)
    _write(right, EV_FIELDS, second)
    assert left.read_bytes() == right.read_bytes()
    text = format_flags(first, [])
    assert text.startswith("qualified=0")
    assert "promoted=none" in text
    assert "jev=not_called" in text
