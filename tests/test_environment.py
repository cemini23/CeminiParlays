from pathlib import Path

from ceminiparlays.environment import (
    env_for,
    env_rows_for_games,
    missing_env_games,
    read_environment,
    write_compose_itt,
)
from ceminiparlays.io import read_games

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


def test_week2_sunday_files_include_snf_not_mnf_or_tnf() -> None:
    env = read_environment(ROOT / "examples" / "2026-w02-sun-environment.csv")
    game_ids = {row.game_id for row in env.values() if row.game_id}
    assert "IND@KC" in game_ids
    assert "NYG@LAR" not in game_ids
    assert "DET@BUF" not in game_ids
    assert len(game_ids) == 14
    ind = env_for(env, "IND", "KC")
    kc = env_for(env, "KC", "IND")
    assert ind is not None and kc is not None
    assert ind.implied_total == 20.0
    assert kc.implied_total == 26.5
    assert kc.spread == -6.5
    assert kc.roof == "open"
    assert kc.weather_exposed is True
    assert kc.wind_mph == 10
    assert kc.precip_pop == 18
    lac = env_for(env, "LAC", "LV")
    assert lac is not None
    assert lac.roof == "semi_open"
    assert lac.weather_exposed is False
    games = read_games(ROOT / "examples" / "games_2026_w02_sun.csv")
    ids = {game.game_id for game in games}
    assert len(games) == 14
    assert ids == game_ids
    assert ("IND", "KC", "20:20") in {(g.away, g.home, g.kick) for g in games}
    snf = next(game for game in games if game.game_id == "IND@KC")
    assert snf.away_itt == 20.0
    assert snf.home_itt == 26.5
    assert snf.spread_home == -6.5
    assert snf.total == 46.5
    assert snf.roof == "open"


def test_missing_env_games_empty_on_week2_files_and_warns_when_snf_stripped(
    tmp_path: Path,
) -> None:
    games = read_games(ROOT / "examples" / "games_2026_w02_sun.csv")
    full = read_environment(ROOT / "examples" / "2026-w02-sun-environment.csv")
    assert missing_env_games(games, full) == []
    assert missing_env_games(games, {}) == []
    src = (ROOT / "examples" / "2026-w02-sun-environment.csv").read_text(
        encoding="utf-8"
    )
    stripped = "\n".join(line for line in src.splitlines() if "IND@KC" not in line)
    path = tmp_path / "env.csv"
    path.write_text(stripped + "\n", encoding="utf-8")
    assert missing_env_games(games, read_environment(path)) == ["IND@KC"]


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
