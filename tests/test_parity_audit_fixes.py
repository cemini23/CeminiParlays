"""P0/P1 parity fixes and Week 9 card guardrails."""

import json
from pathlib import Path

import pytest

from ceminiparlays.cli import _env_odds_required, build_parser, main
from ceminiparlays.compose import (
    FilterDrops,
    bench_blowout_q4_blocked,
    compose_tickets,
    tally_scratch_inactive,
)
from ceminiparlays.environment import (
    EnvRow,
    env_for,
    merge_environment_odds,
    read_environment,
    require_complete_env_odds,
    write_environment,
)
from ceminiparlays.io import LineRow
from ceminiparlays.roster import refresh_roster_files
from ceminiparlays.slips import EvaluatedLeg

LINES = (
    "slate_id,platform,player_name,player_key,team,opp,stat_type,line,side,"
    "line_type,captured_at,injury_status,book_over,book_under,leg_odds\n"
    "s,hardrock,Josh Allen,josh_allen,BUF,MIA,pass_yds,249.5,more,"
    "standard,,,-110,-110,100\n"
    "s,hardrock,Tyreek Hill,tyreek_hill,MIA,BUF,rec_yds,74.5,more,"
    "standard,,,-110,-110,120\n"
    "s,hardrock,Saquon Barkley,saquon_barkley,PHI,ATL,rush_yds,89.5,more,"
    "standard,,,-110,-110,105\n"
)


def _leg(
    name: str,
    key: str,
    team: str,
    opp: str,
    stat: str,
    *,
    side: str = "more",
    edge: float = 0.2,
    line: float = 14.5,
) -> EvaluatedLeg:
    row = LineRow(
        slate_id="s",
        platform="hardrock",
        player_name=name,
        player_key=key,
        team=team,
        opponent=opp,
        stat_type=stat,
        line=line,
        side=side,
        line_type="standard",
        captured_at="",
        displayed_multiplier=None,
        injury_status="",
        book_over=-110,
        book_under=-110,
        leg_odds=-110,
    )
    return EvaluatedLeg(
        line=row,
        fair_p=0.6,
        implied_p=0.5,
        edge=0.1,
        source="book",
        family="normal",
        median=line,
        warn="",
        prop_edge=edge,
    )


def _env_row(
    team: str,
    opp: str,
    spread: float | None,
    implied: float | None = 24.0,
) -> dict[tuple[str, str], EnvRow]:
    row = EnvRow(
        game_id=f"{opp}@{team}",
        team=team,
        opponent=opp,
        implied_total=implied,
        spread=spread,
        roof="open",
        wind_mph=4.0,
    )
    return {(team, opp): row}


def test_merge_env_odds_maps_jac_and_keeps_roof(tmp_path: Path) -> None:
    env_path = tmp_path / "environment.csv"
    env_path.write_text(
        "game_id,team,opp,implied_total,spread,roof,weather_exposed,wind_mph,precip_pop\n"
        "KC@JAX,JAX,KC,,,dome,false,12,30\n"
        "KC@JAX,KC,JAX,27.0,-3.5,dome,false,12,30\n",
        encoding="utf-8",
    )
    odds_path = tmp_path / "environment_odds_2026-11-08.csv"
    odds_path.write_text(
        "team,opp,spread,implied_total,over_under\n"
        "JAC,KC,3.5,21.25,48.0\n"
        "KC,JAX,-3.5,99.0,48.0\n",
        encoding="utf-8",
    )
    filled = merge_environment_odds(env_path, odds_path, require=True)
    jax = env_for(filled, "JAX", "KC")
    kc = env_for(filled, "KC", "JAX")
    assert jax is not None and kc is not None
    assert jax.spread == 3.5
    assert jax.implied_total == 21.25
    assert jax.roof == "dome"
    assert jax.wind_mph == 12.0
    assert jax.weather_exposed is False
    assert kc.implied_total == 27.0
    assert kc.spread == -3.5
    assert kc.roof == "dome"
    out = tmp_path / "merged.csv"
    write_environment(out, filled)
    roundtrip = read_environment(out)
    again = env_for(roundtrip, "JAC", "KC")
    assert again is not None
    assert again.roof == "dome"
    assert again.spread == 3.5
    assert "dome" in out.read_text(encoding="utf-8")


def test_require_env_odds_blocks_a_null_implied_total(tmp_path: Path) -> None:
    env_path = tmp_path / "environment.csv"
    env_path.write_text(
        "game_id,team,opp,implied_total,spread,roof\n"
        "G1,BUF,MIA,,,open\n",
        encoding="utf-8",
    )
    odds_path = tmp_path / "environment_odds_2026-11-08.csv"
    odds_path.write_text(
        "team,opp,spread,implied_total\nPHI,ATL,-2.5,22.0\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="ENV_ODDS_INCOMPLETE"):
        merge_environment_odds(env_path, odds_path, require=True)
    kept = merge_environment_odds(env_path, odds_path, require=False)
    assert env_for(kept, "BUF", "MIA").spread is None
    with pytest.raises(ValueError, match="compose_itt.json was not written"):
        require_complete_env_odds(kept)


def test_env_csv_fail_closed_does_not_write_compose_itt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = tmp_path / "lines.csv"
    lines.write_text(LINES, encoding="utf-8")
    env_path = tmp_path / "environment.csv"
    env_path.write_text(
        "game_id,team,opp,implied_total,spread,roof,weather_exposed,wind_mph\n"
        "MIA@BUF,BUF,MIA,,,open,true,8\n"
        "MIA@BUF,MIA,BUF,,,open,true,8\n",
        encoding="utf-8",
    )
    odds_path = tmp_path / "environment_odds_2026-11-08.csv"
    odds_path.write_text("team,opp,spread,implied_total\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    code = main(
        [
            "compose",
            "--lines",
            str(lines),
            "--env-csv",
            str(env_path),
            "--env-odds-csv",
            str(odds_path),
            "--legs",
            "2",
            "--n-tickets",
            "1",
            "--no-roster",
            "--no-strict",
            "--out-dir",
            str(out_dir),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "ENV_ODDS_INCOMPLETE" in captured.err
    assert "null implied_total" in captured.err
    assert not (out_dir / "compose_itt.json").exists()
    assert not (out_dir / "card.txt").exists()
    bare = build_parser().parse_args(
        ["compose", "--lines", "lines.csv", "--env-csv", "environment.csv"]
    )
    assert _env_odds_required(bare) is True
    legacy = build_parser().parse_args(
        ["compose", "--lines", "lines.csv", "--environment", "environment.csv"]
    )
    assert _env_odds_required(legacy) is False


def test_merge_env_odds_command_writes_the_csv(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env_path = tmp_path / "environment_2026-11-08.csv"
    env_path.write_text(
        "game_id,team,opp,implied_total,spread,roof,weather_exposed,wind_mph\n"
        "KC@JAX,JAX,KC,,,dome,false,9\n",
        encoding="utf-8",
    )
    odds_path = tmp_path / "environment_odds_2026-11-08.csv"
    odds_path.write_text(
        "team,opp,spread,implied_total\nJAC,KC,3.5,21.0\n",
        encoding="utf-8",
    )
    out = tmp_path / "environment.csv"
    code = main(
        [
            "merge-env-odds",
            "--env-csv",
            str(env_path),
            "--env-odds-csv",
            str(odds_path),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    assert f"wrote {out}" in capsys.readouterr().out
    row = env_for(read_environment(out), "JAX", "KC")
    assert row is not None
    assert row.spread == 3.5
    assert row.implied_total == 21.0
    assert row.roof == "dome"
    assert row.wind_mph == 9.0


def test_max_leg_reuse_stops_a_second_copy() -> None:
    legs = [
        _leg("Allen", "josh_allen", "BUF", "MIA", "pass_yds", edge=0.30),
        _leg("Barkley", "saquon_barkley", "PHI", "ATL", "rush_yds", edge=0.20),
        _leg("Hill", "tyreek_hill", "KC", "LV", "rec_yds", edge=0.10),
    ]
    loose = FilterDrops()
    reused = compose_tickets(
        legs,
        n_tickets=2,
        sizes=[2, 1],
        min_odds=None,
        max_odds=None,
        markets=None,
        environment=None,
        max_leg_reuse=2,
        drops=loose,
    )
    assert len(reused) == 2
    assert {leg.line.player_key for leg in reused[1]} == {"josh_allen"}
    tight = FilterDrops()
    once = compose_tickets(
        legs,
        n_tickets=2,
        sizes=[2, 1],
        min_odds=None,
        max_odds=None,
        markets=None,
        environment=None,
        max_leg_reuse=1,
        drops=tight,
    )
    assert len(once) == 2
    assert {leg.line.player_key for leg in once[0]} == {"josh_allen", "saquon_barkley"}
    assert {leg.line.player_key for leg in once[1]} == {"tyreek_hill"}
    assert tight.exposure_cap >= 1
    assert loose.exposure_cap == 0


def test_bench_blowout_blocks_q4_rush_over_at_minus_eight() -> None:
    environment = _env_row("BUF", "NYJ", -8.0)
    favorite = _leg("Cook", "james_cook", "BUF", "NYJ", "rush_yds_q4", side="over", edge=0.4)
    under = _leg("Cook", "james_cook", "BUF", "NYJ", "rush_yds_q4", side="under", edge=0.3)
    other = _leg("Mahomes", "patrick_mahomes", "KC", "LV", "pass_yds", edge=0.05)
    dog_env = _env_row("NYJ", "BUF", -7.5)
    close = _leg("Allen", "breece_hall", "NYJ", "BUF", "rush_yds_q4", side="over", edge=0.2)
    assert bench_blowout_q4_blocked(favorite, environment) is True
    assert bench_blowout_q4_blocked(under, environment) is False
    assert bench_blowout_q4_blocked(favorite, environment, allow=True) is False
    assert bench_blowout_q4_blocked(close, dog_env) is False
    drops = FilterDrops()
    blocked = compose_tickets(
        [favorite, other],
        n_tickets=1,
        sizes=[1],
        min_odds=None,
        max_odds=None,
        markets=None,
        environment={**environment, **_env_row("KC", "LV", -3.0)},
        drops=drops,
    )
    assert drops.bench_blowout_q4 == 1
    assert [leg.line.player_key for leg in blocked[0]] == ["patrick_mahomes"]
    allowed = compose_tickets(
        [favorite],
        n_tickets=1,
        sizes=[1],
        min_odds=None,
        max_odds=None,
        markets=None,
        environment=environment,
        allow_bench_blowout=True,
    )
    assert [leg.line.stat_type for leg in allowed[0]] == ["rush_yds_q4"]


def test_filter_drop_counts_cover_ev_correlation_and_scratch() -> None:
    low = [
        _leg("Allen", "josh_allen", "BUF", "MIA", "pass_yds", edge=0.01),
        _leg("Barkley", "saquon_barkley", "PHI", "ATL", "rush_yds", edge=0.01),
    ]
    ev = FilterDrops()
    assert (
        compose_tickets(
            low,
            n_tickets=1,
            sizes=[2],
            min_odds=None,
            max_odds=None,
            markets=None,
            environment=None,
            min_edge=0.05,
            drops=ev,
        )
        == []
    )
    assert ev.ev_floor == 1
    same = [
        _leg("Cook", "james_cook", "BUF", "MIA", "receptions_q4", edge=0.2),
        _leg("Cook", "james_cook", "KC", "LV", "rec_yds_q4", edge=0.2),
    ]
    corr = FilterDrops()
    assert (
        compose_tickets(
            same,
            n_tickets=1,
            sizes=[2],
            min_odds=None,
            max_odds=None,
            markets=None,
            environment=None,
            drops=corr,
        )
        == []
    )
    assert corr.correlation_cap == 1
    scratch = FilterDrops()

    class _Excluded:
        def __init__(self, warn: str) -> None:
            self.warn = warn

    tally_scratch_inactive(
        scratch,
        [_Excluded("scratch"), _Excluded("inactive"), _Excluded("wrong-team")],
    )
    assert scratch.scratch_inactive == 2
    assert "ev_floor=1" in ev.format()
    assert "scratch_inactive=2" in scratch.format()


def test_strict_ticket_count_overrides_allow_fewer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = tmp_path / "lines.csv"
    lines.write_text(LINES, encoding="utf-8")
    out_dir = tmp_path / "out"
    soft = main(
        [
            "compose",
            "--lines",
            str(lines),
            "--legs",
            "2",
            "--n-tickets",
            "5",
            "--no-roster",
            "--no-strict",
            "--allow-fewer",
            "--out-dir",
            str(out_dir),
        ]
    )
    soft_out = capsys.readouterr().out
    assert soft == 0
    assert "FILTER_DROPS" in soft_out
    assert "ev_floor=" in soft_out
    assert "correlation_cap=" in soft_out
    assert "exposure_cap=" in soft_out
    assert "scratch_inactive=" in soft_out
    assert "bench_blowout_q4=" in soft_out
    assert "COMPOSED_SHORTFALL composed=1 requested=5" in soft_out
    hard = main(
        [
            "compose",
            "--lines",
            str(lines),
            "--legs",
            "2",
            "--n-tickets",
            "5",
            "--no-roster",
            "--no-strict",
            "--allow-fewer",
            "--strict-ticket-count",
            "--out-dir",
            str(tmp_path / "hard"),
        ]
    )
    hard_out = capsys.readouterr().out
    assert hard == 2
    assert "FILTER_DROPS" in hard_out
    assert "SHORT_CARD: composed 1 of 5 requested tickets" in hard_out


def test_sync_dirs_copies_the_dated_card(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = tmp_path / "lines.csv"
    lines.write_text(LINES, encoding="utf-8")
    slate = tmp_path / "parlays-slate" / "2026-11-08"
    recap = tmp_path / "parlays-recap" / "2026-11-08"
    code = main(
        [
            "compose",
            "--lines",
            str(lines),
            "--legs",
            "2",
            "--n-tickets",
            "1",
            "--no-roster",
            "--no-strict",
            "--slate-date",
            "2026-11-08",
            "--sync-dirs",
            str(slate),
            str(recap),
            "--out-dir",
            str(tmp_path / "out"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    for folder in (slate, recap):
        card = folder / "hardrock_card_2026-11-08.csv"
        markdown = folder / "card_2026-11-08.md"
        assert card.is_file()
        assert markdown.is_file()
        assert "Saquon Barkley" in card.read_text(encoding="utf-8")
        assert "do not submit" in markdown.read_text(encoding="utf-8").lower()
        assert f"synced {card}" in out
        assert f"synced {markdown}" in out


def test_refresh_roster_prints_the_team_diff(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    payload = {
        "league": "nfl",
        "season": 2026,
        "retrieved": "2026-10-01",
        "aliases": {},
        "players": {
            "james_cook": {"name": "James Cook", "team": "BUF"},
            "tua_tagovailoa": {"name": "Tua Tagovailoa", "team": "ATL"},
        },
    }
    config = tmp_path / "config" / "nfl.json"
    package = tmp_path / "package" / "nfl.json"
    config.parent.mkdir()
    package.parent.mkdir()
    text = json.dumps(payload, indent=2) + "\n"
    config.write_text(text, encoding="utf-8")
    package.write_text(text, encoding="utf-8")
    whitelist = tmp_path / "active_roster_whitelist_2026-11-08.csv"
    whitelist.write_text(
        "player,team\nJames Cook,KC\nRookie Back,JAC\n",
        encoding="utf-8",
    )
    code = main(
        [
            "refresh-roster",
            "--whitelist",
            str(whitelist),
            "--config",
            str(config),
            "--package",
            str(package),
        ]
    )
    captured = capsys.readouterr().out
    assert code == 0
    assert "TEAM_CHANGE james_cook James Cook BUF -> KC" in captured
    assert "TEAM_CHANGE rookie_back Rookie Back (new) -> JAX" in captured
    for path in (config, package):
        roster = json.loads(path.read_text(encoding="utf-8"))
        assert roster["players"]["james_cook"]["team"] == "KC"
        assert roster["players"]["tua_tagovailoa"]["team"] == "ATL"
        assert roster["players"]["rookie_back"]["team"] == "JAX"
        assert roster["retrieved"] == "2026-11-08"
    assert config.read_bytes() == package.read_bytes()
    same = refresh_roster_files(whitelist, [config, package])
    assert same == []
