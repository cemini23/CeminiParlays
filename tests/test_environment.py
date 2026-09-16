from pathlib import Path

from ceminiparlays.environment import env_for, env_rows_for_games, read_environment, write_compose_itt

ROOT = Path(__file__).resolve().parents[1]


def test_read_environment_is_keyed_by_team_and_game_id() -> None:
    env = read_environment(ROOT / "examples" / "environment.csv")
    assert env_for(env, "CIN", "TB").implied_total == 27.0
    assert env_for(env, "TB", "CIN").roof == "open"
    by_game = env_for(env, "", "", "TB@CIN")
    assert by_game is not None
    assert by_game.implied_total == 23.5
    assert env["TB@CIN"].game_id == "TB@CIN"
    assert env[("TB@CIN", "")].game_id == "TB@CIN"
    assert env_for(env, "KC", "BUF") is None


def test_sofi_stadium_is_semi_open_not_a_dome() -> None:
    env = read_environment(ROOT / "examples" / "environment.csv")
    lac = env_for(env, "LAC", "ARI")
    assert lac is not None
    assert lac.roof == "semi_open"
    assert lac.weather_exposed is False
    assert lac.wind_mph is None
    assert lac.precip_pop is None
    ari = env_for(env, "ARI", "LAC")
    assert ari is not None
    assert ari.roof == "semi_open"
    assert ari.weather_exposed is False
    assert ari.wind_mph is None
    assert ari.precip_pop is None


def test_read_environment_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_environment(tmp_path / "nope.csv") == {}
    assert read_environment(None) == {}
    assert env_for({}, "CIN", "TB") is None


def test_env_rows_for_games_keeps_only_composed_games() -> None:
    env = read_environment(ROOT / "examples" / "environment.csv")
    rows = env_rows_for_games(env, {tuple(sorted({"LAC", "ARI"}))})
    pairs = {(row.team, row.opponent) for row in rows}
    assert ("LAC", "ARI") in pairs
    assert ("ARI", "LAC") in pairs
    assert all(tuple(sorted({row.team, row.opponent})) == ("ARI", "LAC") for row in rows)


def test_write_compose_itt_keeps_null_implied_total(tmp_path: Path) -> None:
    import json

    from ceminiparlays.environment import EnvRow

    path = tmp_path / "compose_itt.json"
    write_compose_itt(
        path,
        captured_at="2026-09-15T12:00:00Z",
        source="environment.csv",
        rows=[
            EnvRow(
                game_id="CHI@CAR",
                team="CHI",
                opponent="CAR",
                implied_total=None,
                spread=-3.0,
                roof="open",
                weather_exposed=True,
            )
        ],
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["captured_at"] == "2026-09-15T12:00:00Z"
    assert payload["rows"][0]["implied_total"] is None
    assert payload["rows"][0]["spread"] == -3.0


def test_environment_flags_roof_exposure(tmp_path: Path) -> None:
    path = tmp_path / "env.csv"
    path.write_text(
        "game_id,team,opp,implied_total,roof,weather_exposed,wind_mph,precip_pop\n"
        "DET@NO,DET,NO,28.25,dome,false,0,0\n",
        encoding="utf-8",
    )
    row = read_environment(path)[("DET", "NO")]
    assert row.roof == "dome"
    assert row.weather_exposed is False
    assert row.wind_mph == 0.0
    assert row.precip_pop == 0.0
