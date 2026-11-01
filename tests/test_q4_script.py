"""Q4 RB overs need a competitive script. Heavy favorites are cut."""

import pytest

from ceminiparlays.q4_checkdown import CheckdownInputs, checkdown_lambda, price_checkdown


def _inputs(**kwargs: object) -> CheckdownInputs:
    base = {
        "games": 6,
        "receptions_per_game": 4.0,
        "rec_yds_per_game": 32.0,
        "targets_per_game": 5.0,
        "opps_q": 12.0,
        "opps_total": 40.0,
        "q4_trail_target_share": 0.25,
        "vacated_target_boost": 0.0,
        "avg_cushion": None,
        "def_q4_comp_rate": None,
        "def_q4_yac": None,
        "league_trail_share": 0.25,
        "league_cushion": None,
        "league_comp": None,
        "league_yac": None,
        "quarter": 4,
    }
    base.update(kwargs)
    return CheckdownInputs(**base)  # type: ignore[arg-type]


def test_blowout_favorite_cuts_lambda_by_thirty_percent() -> None:
    close = checkdown_lambda(_inputs(spread=-3.0))
    blowout = checkdown_lambda(_inputs(spread=-7.0))
    assert close is not None and blowout is not None
    assert blowout.lam == pytest.approx(close.lam * 0.70)


def test_over_requires_a_competitive_route_share() -> None:
    hot = dict(receptions_per_game=8.0, targets_per_game=10.0, third_down_route_share=0.80)
    blocked = price_checkdown(_inputs(spread=-10.0, **hot), "receptions_q4", 0.5, -110, -110)
    kept = price_checkdown(_inputs(spread=-3.0, **hot), "receptions_q4", 0.5, -110, -110)
    high_total = price_checkdown(
        _inputs(spread=-5.5, game_total=47.0, **hot),
        "receptions_q4",
        0.5,
        -110,
        -110,
    )
    low_routes = price_checkdown(
        _inputs(spread=-3.0, receptions_per_game=8.0, third_down_route_share=0.20),
        "receptions_q4",
        0.5,
        -110,
        -110,
    )
    assert blocked is None
    assert low_routes is None
    assert kept is not None and kept.side == "over"
    assert high_total is not None and high_total.side == "over"


def test_under_fits_a_heavy_favorite_and_blocks_a_route_back() -> None:
    cold = dict(receptions_per_game=0.15, targets_per_game=0.4, opps_q=1.0, opps_total=40.0)
    favorite = price_checkdown(
        _inputs(spread=-7.0, third_down_route_share=0.80, **cold),
        "receptions_q4",
        0.5,
        -110,
        -110,
    )
    route_back = price_checkdown(
        _inputs(spread=1.0, third_down_route_share=0.80, **cold),
        "receptions_q4",
        0.5,
        -110,
        -110,
    )
    assert favorite is not None and favorite.side == "under"
    assert route_back is None


def test_missing_spread_fails_closed_only_when_required() -> None:
    hot = dict(receptions_per_game=8.0, targets_per_game=10.0)
    assert price_checkdown(_inputs(require_script=True, **hot), "receptions_q4", 0.5, -110, -110) is None
    priced = price_checkdown(_inputs(**hot), "receptions_q4", 0.5, -110, -110)
    assert priced is not None
