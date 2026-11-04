"""Q4 pass-to-run ratio and the clock-grinder role."""

from ceminiparlays.quarter_usage import (
    QuarterCounts,
    attach_quarter_counts,
    clock_grinder_role,
    counts_from_plays,
    counts_from_row,
    is_q4_clock_grinder,
    match_usage,
    q4_pass_ratio,
    reception_over_blocked,
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


def test_quarter_counts_as_dict_round_trips_every_field() -> None:
    counts = QuarterCounts(q4_targets=3, total_targets=9, q4_rush_att=2, total_rush_att=8)
    payload = counts.as_dict()
    assert set(payload) == set(QuarterCounts.__dataclass_fields__)
    assert payload["q4_targets"] == 3.0
    assert payload["total_rush_att"] == 8.0


def test_counts_from_row_returns_none_when_every_field_is_absent() -> None:
    assert counts_from_row({}) is None
    assert counts_from_row({"q4_targets": ""}) is None


def test_counts_from_row_fills_a_missing_field_with_zero() -> None:
    counts = counts_from_row({"q4_targets": "4"})
    assert counts is not None
    assert counts.q4_targets == 4.0
    assert counts.q3_targets == 0.0


def test_attach_quarter_counts_writes_the_typed_fields_and_names_a_grinder() -> None:
    row = {
        "player_name": "A Back",
        "team": "KC",
        "position": "RB",
        "q3_targets": 0,
        "q4_targets": 0,
        "total_targets": 0,
        "q4_rush_att": 9,
        "total_rush_att": 20,
        "q4_trail_targets": 0,
        "q4_lead_rush_att": 9,
    }
    assert attach_quarter_counts([row], None) == ["A Back"]
    assert row["q4_rush_att"] == 9
    assert row["q4_clock_grinder"] is True


def test_attach_quarter_counts_clears_a_row_with_no_counts() -> None:
    row = {"player_name": "B Receiver", "team": "KC", "position": "WR"}
    assert attach_quarter_counts([row], None) == []
    assert row["q4_clock_grinder"] is False


def test_reception_over_blocked_only_for_a_q4_reception_over() -> None:
    grinder = {"q4_clock_grinder": True}
    assert reception_over_blocked(grinder, "receptions_q4", "over") is True
    assert reception_over_blocked(grinder, "rec_yds_q4", "over") is True
    assert reception_over_blocked(grinder, "receptions_q4", "under") is False
    assert reception_over_blocked(grinder, "pass_yds", "over") is False
    assert reception_over_blocked({}, "receptions_q4", "over") is False
