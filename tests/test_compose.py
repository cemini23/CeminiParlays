from pathlib import Path

from ceminiparlays.compose import compose_tickets, concentration_warnings, estimate_multiplier
from ceminiparlays.environment import read_environment
from ceminiparlays.io import LineRow, read_manual_lines
from ceminiparlays.slips import EvaluatedLeg, evaluate_legs

ROOT = Path(__file__).resolve().parents[1]
AUTO_MARKETS = ["pass_yds", "rush_yds", "rec_yds"]


def _live():
    lines = read_manual_lines(ROOT / "examples" / "sunday_lines.csv")
    live, excluded = evaluate_legs(lines, {}, implied_p=0.5, platform="hardrock")
    assert excluded == []
    assert len(live) == 12
    return live


def test_auto_defaults_produce_five_diversified_tickets() -> None:
    tickets = compose_tickets(
        _live(),
        n_tickets=5,
        sizes=[2],
        min_odds=150,
        max_odds=400,
        markets=AUTO_MARKETS,
        environment=read_environment(ROOT / "examples" / "environment.csv"),
    )
    assert len(tickets) == 5
    used: set[tuple[str, str]] = set()
    for ticket in tickets:
        assert len(ticket) == 2
        games = {frozenset({leg.line.team, leg.line.opponent}) for leg in ticket}
        assert len(games) == 2
        for leg in ticket:
            key = (leg.line.player_key or leg.line.player_name, leg.line.stat_type)
            assert key not in used
            used.add(key)


def test_min_max_odds_window_filters_tickets() -> None:
    assert (
        compose_tickets(
            _live(),
            n_tickets=5,
            sizes=[2],
            min_odds=1000,
            max_odds=2000,
            markets=AUTO_MARKETS,
            environment=None,
        )
        == []
    )
    assert (
        compose_tickets(
            _live(),
            n_tickets=5,
            sizes=[2],
            min_odds=-500,
            max_odds=-200,
            markets=AUTO_MARKETS,
            environment=None,
        )
        == []
    )


def test_markets_filter_limits_the_pool() -> None:
    tickets = compose_tickets(
        _live(),
        n_tickets=2,
        sizes=[2],
        min_odds=None,
        max_odds=None,
        markets=["rush_yds"],
        environment=None,
    )
    assert len(tickets) == 2
    for ticket in tickets:
        assert all(leg.line.stat_type == "rush_yds" for leg in ticket)


def test_environment_itt_prefers_the_higher_total_game(tmp_path: Path) -> None:
    env_path = tmp_path / "env.csv"
    env_path.write_text(
        "game_id,team,opp,implied_total,roof,weather_exposed\n"
        "TB@CIN,CIN,TB,99.0,open,true\n"
        "TB@CIN,TB,CIN,1.0,open,true\n",
        encoding="utf-8",
    )
    tickets = compose_tickets(
        _live(),
        n_tickets=1,
        sizes=[2],
        min_odds=None,
        max_odds=None,
        markets=AUTO_MARKETS,
        environment=read_environment(env_path),
    )
    assert tickets
    assert any(leg.line.team == "CIN" for leg in tickets[0])


def test_n_tickets_must_be_positive() -> None:
    import pytest

    with pytest.raises(ValueError, match="n_tickets"):
        compose_tickets(
            _live(),
            n_tickets=0,
            sizes=[2],
            min_odds=None,
            max_odds=None,
            markets=None,
            environment=None,
        )


def _eval_leg(name: str, key: str, stat: str) -> EvaluatedLeg:
    line = LineRow(
        slate_id="s",
        platform="hardrock",
        player_name=name,
        player_key=key,
        team="CIN",
        opponent="CLE",
        stat_type=stat,
        line=57.5,
        side="more",
        line_type="standard",
        captured_at="",
        displayed_multiplier=None,
        injury_status="",
        book_over=-110,
        book_under=-110,
    )
    return EvaluatedLeg(
        line=line,
        fair_p=0.55,
        implied_p=0.5,
        edge=0.05,
        source="book",
        family="normal",
        median=60.0,
        warn="",
    )


def test_concentration_warns_same_player_same_stat() -> None:
    tickets = [
        [
            _eval_leg("Chase Brown", "chase_brown", "rush_yds"),
            _eval_leg("Gibbs", "jahmyr_gibbs", "rush_yds"),
        ],
        [
            _eval_leg("Chase Brown", "chase_brown", "rush_yds"),
            _eval_leg("Henry", "derrick_henry", "rush_yds"),
        ],
    ]
    warnings = concentration_warnings(tickets)
    assert len(warnings) == 1
    assert "chase_brown" in warnings[0]
    assert "rush_yds" in warnings[0]


def test_concentration_skips_yards_plus_atd() -> None:
    tickets = [
        [_eval_leg("Chase Brown", "chase_brown", "rush_yds")],
        [_eval_leg("Chase Brown", "chase_brown", "anytime_td")],
    ]
    assert concentration_warnings(tickets) == []


def test_estimate_multiplier_from_leg_odds_product() -> None:
    live = _live()
    legs = [leg for leg in live if leg.line.leg_odds is not None][:2]
    multiplier, source, unconfirmed = estimate_multiplier(legs)
    assert multiplier is not None and multiplier > 1.0
    assert source == "leg_odds_naive"
    assert unconfirmed is True
