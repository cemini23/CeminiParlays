"""Week-11 recap: Q4 reception direction, market cap, and the four-leg ban."""

import pytest

from ceminiparlays.compose import (
    MAX_LEGS,
    QUARTER_MARKET_STAKE_SHARE,
    FilterDrops,
    _note_card_caps,
    _within_card_caps,
    compose_tickets,
    q4_reception_direction_blocked,
)
from ceminiparlays.environment import EnvRow
from ceminiparlays.io import LineRow
from ceminiparlays.q4_checkdown import (
    SCRIPT_BENCH_BLOWOUT_RISK,
    SCRIPT_COMPETITIVE_LEAD,
    SCRIPT_NEUTRAL,
    SCRIPT_TRAIL_BLOWOUT,
    CheckdownInputs,
    price_checkdown,
    q4_receptions_over_blocked,
    q4_receptions_under_blocked,
    q4_script_tag,
)
from ceminiparlays.slips import EvaluatedLeg


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


def _leg(player: str, side: str, team: str = "NYJ", opp: str = "BUF") -> EvaluatedLeg:
    line = LineRow(
        slate_id="s",
        platform="hardrock",
        player_name=player,
        player_key=player.lower().replace(" ", "_"),
        team=team,
        opponent=opp,
        stat_type="receptions_q4",
        line=0.5,
        side=side,
        line_type="standard",
        captured_at="",
        displayed_multiplier=None,
        injury_status="",
        book_over=-110,
        book_under=-110,
        leg_odds=None,
    )
    return EvaluatedLeg(
        line=line,
        fair_p=0.5,
        implied_p=0.5,
        edge=0.0,
        source="distribution",
        family="poisson",
        median=0.0,
        warn="",
        prop_edge=0.0,
    )


def _env(spread: float) -> dict:
    return {("NYJ", "BUF"): EnvRow(game_id="", team="NYJ", opponent="BUF", spread=spread)}


def test_script_tag_maps_the_three_bands() -> None:
    assert q4_script_tag(9.5) == SCRIPT_TRAIL_BLOWOUT
    assert q4_script_tag(7.0) == SCRIPT_TRAIL_BLOWOUT
    assert q4_script_tag(-8.0) == SCRIPT_BENCH_BLOWOUT_RISK
    assert q4_script_tag(-5.5) == SCRIPT_COMPETITIVE_LEAD
    assert q4_script_tag(-3.0) == SCRIPT_COMPETITIVE_LEAD
    assert q4_script_tag(-2.5) == SCRIPT_NEUTRAL
    assert q4_script_tag(3.0) == SCRIPT_NEUTRAL
    assert q4_script_tag(None) is None


def test_under_blocks_a_trail_blowout_and_a_rank_one_grinder() -> None:
    assert q4_receptions_under_blocked(9.5) is True
    assert q4_receptions_under_blocked(6.5) is False
    assert q4_receptions_under_blocked(-3.0, 1, 3.0) is True
    assert q4_receptions_under_blocked(0.0, 1, 4.5) is True
    assert q4_receptions_under_blocked(0.0, 1, 2.9) is False
    assert q4_receptions_under_blocked(0.0, 2, 6.0) is False
    assert q4_receptions_under_blocked(0.0, 1, None) is False
    assert q4_receptions_under_blocked(None, None, None) is False


def test_over_blocks_a_favored_team_at_minus_three() -> None:
    assert q4_receptions_over_blocked(-3.0) is True
    assert q4_receptions_over_blocked(-5.5) is True
    assert q4_receptions_over_blocked(-9.5) is True
    assert q4_receptions_over_blocked(-2.5) is False
    assert q4_receptions_over_blocked(0.0) is False
    assert q4_receptions_over_blocked(None) is False


def test_price_checkdown_hard_blocks_both_directions() -> None:
    trail_under = _inputs(
        spread=9.5,
        receptions_per_game=0.15,
        targets_per_game=0.4,
        opps_q=1.0,
    )
    assert price_checkdown(trail_under, "receptions_q4", 0.5, -110, -110) is None
    favored_over = _inputs(spread=-5.5, receptions_per_game=8.0, targets_per_game=10.0)
    assert price_checkdown(favored_over, "receptions_q4", 0.5, -110, -110) is None
    rank_one_under = _inputs(
        spread=1.0,
        receptions_per_game=0.15,
        targets_per_game=3.5,
        target_share_rank=1,
        opps_q=1.0,
    )
    assert price_checkdown(rank_one_under, "receptions_q4", 0.5, -110, -110) is None


def test_compose_blocks_the_leg_from_the_environment() -> None:
    trail = _env(9.5)
    favored = _env(-5.5)
    close = _env(1.0)
    assert q4_reception_direction_blocked(_leg("Under Guy", "under"), trail) is True
    assert q4_reception_direction_blocked(_leg("Over Guy", "over"), favored) is True
    assert q4_reception_direction_blocked(_leg("Over Guy", "over"), close) is False
    assert q4_reception_direction_blocked(_leg("Under Guy", "under"), close) is False
    assert q4_reception_direction_blocked(_leg("Over Guy", "over"), None) is False


def test_compose_pool_counts_a_direction_drop() -> None:
    drops = FilterDrops()
    tickets = compose_tickets(
        [_leg("Trail Under", "under")],
        n_tickets=1,
        sizes=[1],
        min_odds=None,
        max_odds=None,
        markets=None,
        environment=_env(9.5),
        drops=drops,
    )
    assert tickets == []
    assert drops.q4_direction == 1
    assert "q4_direction=1" in drops.format()


class _CapLine:
    def __init__(self, key: str, stat: str, side: str = "over") -> None:
        self.player_key = key
        self.player_name = key
        self.stat_type = stat
        self.side = side


class _CapLeg:
    def __init__(self, key: str, stat: str = "receptions_q4") -> None:
        self.line = _CapLine(key, stat)


def test_one_quarter_market_stays_at_or_under_forty_percent() -> None:
    assert QUARTER_MARKET_STAKE_SHARE == 0.40
    counts: dict[tuple[str, str, str], int] = {}
    units: dict[tuple[str, str, str], float] = {}
    markets: dict[str, float] = {}
    first = [_CapLeg("alpha")]
    second = [_CapLeg("beta")]
    third = [_CapLeg("gamma")]
    assert _within_card_caps(counts, units, first, 5, 2, markets) is True
    _note_card_caps(counts, units, first, markets)
    assert _within_card_caps(counts, units, second, 5, 2, markets) is True
    _note_card_caps(counts, units, second, markets)
    assert markets["receptions_q4"] == 2.0
    assert _within_card_caps(counts, units, third, 5, 2, markets) is False
    other = [_CapLeg("delta", "rush_yds_q4")]
    assert _within_card_caps(counts, units, other, 5, 2, markets) is True


def test_a_five_leg_ticket_is_banned() -> None:
    assert MAX_LEGS == 4
    pool = [_leg(f"Rush {index}", "over", team=team, opp=opp) for index, (team, opp) in enumerate(
        [("KC", "BUF"), ("DAL", "PHI"), ("SF", "SEA"), ("NYJ", "BUF"), ("CIN", "CLE")]
    )]
    with pytest.raises(ValueError, match="at most 4 legs"):
        compose_tickets(
            pool,
            n_tickets=1,
            sizes=[5],
            min_odds=None,
            max_odds=None,
            markets=None,
            environment=None,
        )
