"""Week 9 recap: ticket Brier, Q4 script, concentration, and odds fill."""

import json
from pathlib import Path

import pytest

from ceminiparlays.cli import build_parser, short_card_exit
from ceminiparlays.compose import MAX_TICKETS_PER_PROP, _note_card_caps, _within_card_caps
from ceminiparlays.environment import (
    discover_environment_odds,
    env_for,
    fill_environment_from_odds_csv,
    read_environment,
    write_compose_itt,
)
from ceminiparlays.feature_cache import active_teams_from_frames, overlay_pit
from ceminiparlays.grade_card import grade_rows
from ceminiparlays.io import LineRow
from ceminiparlays.q4_checkdown import (
    CheckdownInputs,
    _route_share_ok,
    price_checkdown,
    q4_rush_over_blocked,
    q4_rush_script_multiplier,
)
from ceminiparlays.roster import (
    active_teams_from_csv,
    apply_active_teams,
    load_roster,
    lookup_player,
    roster_mismatch,
)
from ceminiparlays.week8_card import (
    BANKROLL_CENTS,
    QUARTER_STAKE_SHARE,
    CardTicket,
    _duplicate_problems,
    _place,
    ledger_rows,
    main as week8_main,
    price_period_yards,
)


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


def _grade_row(
    ticket: str,
    leg_num: int,
    status: str,
    joint: float,
    marginal: float,
    stake: str = "TBD",
) -> dict[str, str]:
    return {
        "ticket_id": ticket,
        "leg_num": str(leg_num),
        "line": "14.5",
        "side": "over",
        "model_prob": f"{joint:.4f}",
        "leg_model_prob": f"{marginal:.4f}",
        "leg_status": status,
        "ticket_stake_usd": stake,
        "book_american_odds": "",
        "market": "rush_yds_q4",
    }


def test_week9_ticket_brier_is_one_term_per_ticket() -> None:
    # Published Week 9 joints. 2A and 3A won. The other four lost.
    joints = (
        ("W9-2B", 0.7876, "loss"),
        ("W9-3B", 0.6563, "loss"),
        ("W9-2A", 0.5841, "win"),
        ("W9-3A", 0.5371, "win"),
        ("W9-SGP-NYJKC", 0.5414, "loss"),
        ("W9-SGP-LVSF", 0.3036, "loss"),
    )
    rows: list[dict[str, str]] = []
    terms: list[float] = []
    for ticket, joint, result in joints:
        outcome = 1.0 if result == "win" else 0.0
        terms.append((joint - outcome) ** 2)
        first = "win" if result == "win" else "loss"
        second = "win"
        rows.append(_grade_row(ticket, 1, first, joint, 0.80))
        rows.append(_grade_row(ticket, 2, second, joint, 0.70))
    grade = grade_rows(rows, [])
    assert grade.settled_tickets == 6
    assert grade.stake == 0.0
    assert grade.profit == 0.0
    assert grade.brier == pytest.approx(sum(terms) / len(terms))
    assert round(grade.brier or 0.0, 4) == 0.3039


def test_paper_zero_stake_grades_without_odds() -> None:
    rows = [
        _grade_row("paper", 1, "win", 0.60, 0.60, stake="0"),
        _grade_row("paper", 2, "win", 0.60, 0.55, stake="0.00"),
        _grade_row("loss", 1, "loss", 0.40, 0.40, stake="TBD"),
        _grade_row("loss", 2, "win", 0.40, 0.70, stake="tbd"),
    ]
    grade = grade_rows(rows, [])
    assert grade.stake == 0.0
    assert grade.profit == 0.0
    assert grade.settled_tickets == 2
    assert {leg.result for leg in grade.legs} == {"win", "loss"}


def test_q4_rush_blocks_a_mega_favorite_rb1_over() -> None:
    assert q4_rush_script_multiplier(-6.5) == 1.08
    assert q4_rush_over_blocked(-6.5) is False
    assert q4_rush_script_multiplier(-8.0) == 0.68
    assert q4_rush_over_blocked(-8.0) is True
    assert q4_rush_over_blocked(-9.5) is True
    assert q4_rush_script_multiplier(-9.5, is_starter_rb=False) == 1.00
    assert q4_rush_over_blocked(-9.5, is_starter_rb=False) is False
    assert q4_rush_script_multiplier(9.5) is None
    assert q4_rush_over_blocked(9.5) is True
    assert q4_rush_script_multiplier(None) is None
    assert q4_rush_over_blocked(None) is False
    blocked = price_period_yards(
        games=6,
        rate=120.0,
        line=14.5,
        book_over=-110,
        book_under=-110,
        market="rush_yds_q4",
        spread=-8.0,
        is_starter_rb=True,
    )
    kept = price_period_yards(
        games=6,
        rate=120.0,
        line=14.5,
        book_over=-110,
        book_under=-110,
        market="rush_yds_q4",
        spread=-6.5,
        is_starter_rb=True,
    )
    assert blocked is None
    assert kept is not None
    assert kept["side"] == "over"


def test_trail_blowout_blocks_a_low_target_rb2() -> None:
    rb2 = _inputs(spread=9.5, targets_per_game=2.0, games=6.0, third_down_route_share=None)
    assert _route_share_ok(rb2) is False
    volume = _inputs(spread=6.5, targets_per_game=3.0, games=4.0, third_down_route_share=None)
    assert _route_share_ok(volume) is True
    routes = _inputs(
        spread=9.5,
        targets_per_game=1.0,
        games=6.0,
        third_down_route_share=0.50,
    )
    assert _route_share_ok(routes) is True
    short = _inputs(spread=9.5, targets_per_game=5.0, games=3.0)
    assert _route_share_ok(short) is False
    close = _inputs(spread=3.0, targets_per_game=1.0, games=2.0, third_down_route_share=None)
    assert _route_share_ok(close) is True


def test_trail_blowout_yards_over_needs_league_yac() -> None:
    thin = _inputs(spread=9.5, def_q4_yac=2.0, league_yac=4.0)
    fat = _inputs(spread=9.5, def_q4_yac=5.0, league_yac=4.0)
    assert price_checkdown(thin, "rec_yds_q4", 0.5, -110, -110) is None
    priced = price_checkdown(fat, "rec_yds_q4", 0.5, -110, -110)
    assert priced is not None
    assert priced.side == "over"
    catches = price_checkdown(thin, "receptions_q4", 0.5, -110, -110)
    assert catches is not None


class _Line:
    def __init__(self, key: str, stat: str, side: str = "over") -> None:
        self.player_key = key
        self.player_name = key
        self.stat_type = stat
        self.side = side


class _Leg:
    def __init__(self, key: str, stat: str) -> None:
        self.line = _Line(key, stat)


def test_prop_cap_is_two_tickets_and_thirty_percent() -> None:
    assert MAX_TICKETS_PER_PROP == 2
    assert QUARTER_STAKE_SHARE == 0.30
    counts: dict[tuple[str, str, str], int] = {}
    units: dict[tuple[str, str, str], float] = {}
    quarter = [_Leg("kenneth_walker", "rush_yds_q4")]
    assert _within_card_caps(counts, units, quarter, 6) is True
    _note_card_caps(counts, units, quarter)
    assert _within_card_caps(counts, units, quarter, 6) is False
    full: dict[tuple[str, str, str], int] = {}
    plain = [_Leg("tua_tagovailoa", "pass_yds")]
    assert _within_card_caps(full, {}, plain, 6) is True
    _note_card_caps(full, {}, plain)
    assert _within_card_caps(full, {}, plain, 6) is True
    _note_card_caps(full, {}, plain)
    assert _within_card_caps(full, {}, plain, 6) is False


def _leg(team: str = "KC", opp: str = "NYJ") -> dict:
    return {
        "player_key": "kenneth_walker",
        "player_name": "Kenneth Walker III",
        "market": "rush_yds_q4",
        "side": "over",
        "line": 14.5,
        "price": -110,
        "model_p": 0.60,
        "ev": 0.10,
        "team": team,
        "opp": opp,
        "game_label": f"{opp} @ {team}",
    }


def _ticket(ticket_id: str, stake: int, team: str = "KC", opp: str = "NYJ") -> CardTicket:
    return CardTicket(
        ticket_id=ticket_id,
        tier="2",
        legs=(_leg(team, opp),),
        stake_cents=stake,
        tax_ev=0.10,
        note="none",
        joint_p=0.60,
    )


def test_place_stops_a_third_copy_and_a_quarter_overweight() -> None:
    chosen: list[CardTicket] = []
    card_legs: list[dict] = []
    exposure: dict[frozenset[str], int] = {}
    assert _place(chosen, card_legs, exposure, _ticket("a", 50)) is True
    assert _place(chosen, card_legs, exposure, _ticket("b", 50)) is True
    assert _place(chosen, card_legs, exposure, _ticket("c", 50)) is False
    heavy: list[CardTicket] = []
    heavy_legs: list[dict] = []
    heavy_exposure: dict[frozenset[str], int] = {}
    assert _place(heavy, heavy_legs, heavy_exposure, _ticket("d", 175, "KC", "NYJ")) is True
    second = _ticket("e", 175, "SF", "LV")
    assert _place(heavy, heavy_legs, heavy_exposure, second) is False
    problems = _duplicate_problems([_ticket("d", 175, "KC", "NYJ"), second])
    assert any("30%" in item for item in problems)
    assert any("cap is 2" in item for item in _duplicate_problems(
        [_ticket("a", 50), _ticket("b", 50), _ticket("c", 50)]
    ))
    assert BANKROLL_CENTS == 800


def test_tbd_stake_mode_writes_unit_weight(tmp_path: Path) -> None:
    assert week8_main(["--stake-mode", "tbd", "--lines", str(tmp_path / "missing.csv")]) == 2
    with pytest.raises(SystemExit):
        week8_main(["--stake-mode", "paper"])
    ticket = CardTicket(
        ticket_id="W9-2B",
        tier="2",
        legs=(
            {**_leg(), "model_p": 0.86},
            {
                **_leg("NYJ", "KC"),
                "player_key": "braelon_allen",
                "player_name": "Braelon Allen",
                "market": "receptions_q4",
                "line": 0.5,
                "model_p": 0.63,
            },
        ),
        stake_cents=100,
        tax_ev=0.10,
        note="none",
        joint_p=0.5414,
    )
    rows = ledger_rows([ticket], stake_mode="tbd")
    assert rows[0]["ticket_stake_usd"] == "TBD"
    assert rows[1]["ticket_stake_usd"] == "TBD"
    assert rows[0]["model_prob"] == "0.541400"
    assert rows[1]["model_prob"] == "0.541400"
    assert rows[0]["leg_model_prob"] == "0.860000"
    assert rows[1]["leg_model_prob"] == "0.630000"
    assert "unit_weight=1.00" in rows[0]["t90_flag"]


def test_fill_environment_odds_into_compose_itt(tmp_path: Path) -> None:
    env_path = tmp_path / "environment_2026-11-08.csv"
    env_path.write_text(
        "team,opp,spread,implied_total,game_id\n"
        "NYJ,KC,9.5,21.0,nyj-kc\n"
        "KC,NYJ,,,\n"
        "DET,GB,-6.5,,det-gb\n",
        encoding="utf-8",
    )
    odds_path = tmp_path / "environment_odds_2026-11-08.csv"
    odds_path.write_text(
        "team,opp,spread,implied_total,over_under\n"
        "NYJ,KC,9.5,99.0,48.0\n"
        "KC,NYJ,-9.5,27.0,48.0\n"
        "DET,GB,-6.5,,44.5\n",
        encoding="utf-8",
    )
    assert discover_environment_odds(env_path) == odds_path
    filled = fill_environment_from_odds_csv(read_environment(env_path), odds_path)
    assert env_for(filled, "NYJ", "KC").implied_total == 21.0
    assert env_for(filled, "NYJ", "KC").spread == 9.5
    assert env_for(filled, "KC", "NYJ").spread == -9.5
    assert env_for(filled, "KC", "NYJ").implied_total == 27.0
    assert env_for(filled, "DET", "GB").spread == -6.5
    assert env_for(filled, "DET", "GB").implied_total == pytest.approx(25.5)
    unchanged = fill_environment_from_odds_csv(read_environment(env_path), tmp_path / "missing.csv")
    assert env_for(unchanged, "KC", "NYJ").spread is None
    rows = [
        row
        for key, row in filled.items()
        if isinstance(key, tuple) and len(key) == 2 and key[1]
    ]
    out = tmp_path / "compose_itt.json"
    write_compose_itt(out, captured_at="2026-11-08T18:00:00Z", source=env_path.name, rows=rows)
    payload = json.loads(out.read_text(encoding="utf-8"))
    by_team = {item["team"]: item for item in payload["rows"]}
    assert by_team["NYJ"]["implied_total"] == 21.0
    assert by_team["KC"]["spread"] == -9.5
    assert by_team["KC"]["implied_total"] == 27.0
    assert by_team["DET"]["implied_total"] == pytest.approx(25.5)
    bare = tmp_path / "one"
    bare.mkdir()
    only = bare / "environment_odds_2026-11-09.csv"
    only.write_text("team,opp,spread\n", encoding="utf-8")
    assert discover_environment_odds(bare / "environment.csv") == only
    extra = bare / "environment_odds_2026-11-10.csv"
    extra.write_text("team,opp,spread\n", encoding="utf-8")
    assert discover_environment_odds(bare / "environment.csv") is None


def _tua(team: str) -> LineRow:
    return LineRow(
        slate_id="s",
        platform="hardrock",
        player_name="Tua Tagovailoa",
        player_key="",
        team=team,
        opponent="HOU",
        stat_type="pass_yds",
        line=240.5,
        side="more",
        line_type="standard",
        captured_at="",
        displayed_multiplier=None,
        injury_status="",
        book_over=-110,
        book_under=-110,
    )


def test_current_week_team_overrides_the_static_roster(tmp_path: Path) -> None:
    roster = load_roster()
    assert lookup_player(_tua("ATL"), roster).team == "ATL"
    updated = apply_active_teams(roster, {"Tua Tagovailoa": "MIA"})
    assert updated is not roster
    assert lookup_player(_tua("ATL"), roster).team == "ATL"
    assert lookup_player(_tua("MIA"), updated).team == "MIA"
    assert roster_mismatch(_tua("MIA"), updated) is None
    assert roster_mismatch(_tua("ATL"), updated) == "wrong-team"
    assert apply_active_teams(updated, {"Tua Tagovailoa": "MIA"}) is updated
    salary = tmp_path / "salary.csv"
    salary.write_text("player,recent_team\nTua Tagovailoa,MIA\n", encoding="utf-8")
    from_csv = apply_active_teams(load_roster(), active_teams_from_csv(salary))
    assert lookup_player(_tua("MIA"), from_csv).team == "MIA"
    assert active_teams_from_csv(tmp_path / "missing.csv") == {}
    frames = {
        "player_telemetry_pit.parquet": [
            {"player_name": "Tua Tagovailoa", "player_id": "00-0036212", "recent_team": "MIA"}
        ]
    }
    teams = active_teams_from_frames(frames)
    assert teams["Tua Tagovailoa"] == "MIA"
    assert teams["00-0036212"] == "MIA"
    from_frame = apply_active_teams(load_roster(), teams)
    assert roster_mismatch(_tua("MIA"), from_frame) is None


class _Frame:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def to_dict(self, orient: str) -> list[dict]:
        assert orient == "records"
        return self._rows


def test_overlay_copies_a_telemetry_team_when_the_column_exists() -> None:
    players = [{"gsis_id": "00-1"}, {"gsis_id": "00-2", "team": "ATL"}]
    frames = {
        "player_telemetry_pit.parquet": _Frame(
            [
                {"player_id": "00-1", "games": 4, "team": "MIA"},
                {"player_id": "00-2", "games": 4},
            ]
        )
    }
    out_players, _teams = overlay_pit(players, [], frames)
    assert out_players[0]["team"] == "MIA"
    assert out_players[1]["team"] == "ATL"
    assert "team" not in players[0]


def test_allow_short_card_is_compose_only(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    args = parser.parse_args(["compose", "--lines", "lines.csv", "--allow-short-card"])
    assert args.allow_short_card is True
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["rank", "--lines", "a.csv", "--distributions", "b.csv", "--allow-short-card"]
        )
    assert short_card_exit(4, 6, False) == 2
    text = capsys.readouterr().out
    assert "SHORT_CARD: composed 4 of 6 requested tickets" in text
    assert "COMPOSED_SHORTFALL composed=4 requested=6" in text
    assert short_card_exit(4, 6, True) == 0
    allowed = capsys.readouterr().out
    assert "SHORT_CARD: composed 4 of 6 requested tickets" in allowed
    assert short_card_exit(6, 6, False) is None
    assert capsys.readouterr().out == ""
