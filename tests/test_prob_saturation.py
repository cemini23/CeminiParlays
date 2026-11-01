"""Full-game yardage probabilities stay inside a real main-line band."""

from ceminiparlays.matchup_math import clip_main_line_prob, full_game_yard_sigma
from ceminiparlays.week7_card import price_scheme_line


def test_sigma_floor_tracks_the_line_and_player_rmse() -> None:
    assert full_game_yard_sigma("rush_yds", 28.5) == max(0.38 * 28.5, 14.0)
    assert full_game_yard_sigma("rec_yds", 10.0) == 14.0
    assert full_game_yard_sigma("pass_yds", 220.5) == 58.0
    assert full_game_yard_sigma("rush_yds", 28.5, player_rmse=40) == 40.0


def test_main_line_clip_uses_the_book_band_and_hard_bounds() -> None:
    assert clip_main_line_prob(0.99, 0.52) == 0.68
    assert clip_main_line_prob(0.01, 0.52) == 0.36
    assert clip_main_line_prob(0.99, 0.90) == 0.78
    assert clip_main_line_prob(0.01, 0.20) == 0.18


def test_scheme_over_cannot_print_a_saturated_probability() -> None:
    priced = price_scheme_line(
        games=10,
        yards_per_game=80,
        def_rate=1.2,
        league_rate=1.0,
        line=28.5,
        book_over=-110,
        book_under=-110,
        market="rush_yds",
    )
    assert priced is not None
    assert priced["side"] == "over"
    assert 0.18 <= priced["model_p"] <= 0.78
