from pathlib import Path

from ceminiparlays.environment import env_for, read_environment

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


def test_read_environment_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_environment(tmp_path / "nope.csv") == {}
    assert read_environment(None) == {}
    assert env_for({}, "CIN", "TB") is None


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
