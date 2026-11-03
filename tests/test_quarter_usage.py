"""Q4 pass-to-run ratio and the clock-grinder role."""

from ceminiparlays.quarter_usage import (
    QuarterCounts,
    clock_grinder_role,
    counts_from_plays,
    is_q4_clock_grinder,
    match_usage,
    q4_pass_ratio,
)


def test_pass_ratio_uses_the_locked_smooth() -> None:
    assert q4_pass_ratio(0, 5) == (1.5 / 11.0)
    assert q4_pass_ratio(5, 8) == (6.5 / 19.0)


def test_week7_shape_is_a_grinder_and_the_season_sum_is_not() -> None:
    week7 = QuarterCounts(q4_targets=0, total_targets=0, q4_rush_att=5, total_rush_att=14)
    season = QuarterCounts(q4_targets=5, total_targets=17, q4_rush_att=8, total_rush_att=33)
    box = QuarterCounts(q4_targets=0, total_targets=0, q4_rush_att=17, total_rush_att=17)
    assert is_q4_clock_grinder("RB", week7) is True
    assert is_q4_clock_grinder("RB", season) is False
    assert is_q4_clock_grinder("RB", box) is True
    assert is_q4_clock_grinder("WR", box) is False
    assert clock_grinder_role("RB", season, week7) is True


def test_play_counts_join_k_gainwell_to_kenneth() -> None:
    plays = []
    for _index in range(14):
        plays.append(
            {
                "week": 7,
                "qtr": 4 if _index < 5 else 1,
                "posteam": "TB",
                "score_differential": 3,
                "pass_attempt": 0,
                "rush_attempt": 1,
                "rusher_player_name": "K.Gainwell",
                "receiver_player_name": "",
            }
        )
    bundles = counts_from_plays(plays, before_week=8)
    found = match_usage({"player_name": "Kenneth Gainwell", "team": "TB"}, bundles)
    assert found is not None
    assert found.season.q4_rush_att == 5
    assert found.season.total_rush_att == 14
    assert found.recent is not None
    assert found.recent.total_rush_att == 14
