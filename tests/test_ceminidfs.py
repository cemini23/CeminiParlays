from pathlib import Path

from ceminiparlays.ceminidfs import (
    exposure_notes,
    load_ceminidfs_handoff,
    merge_implied_totals,
)
from ceminiparlays.cli import main
from ceminiparlays.environment import env_for, read_environment
from ceminiparlays.io import DistRow, read_distributions

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "ceminidfs_handoff.csv"


def test_missing_handoff_is_named_skip(tmp_path: Path) -> None:
    path = tmp_path / "nope.csv"
    handoff = load_ceminidfs_handoff(path)
    assert handoff.missing is True
    assert handoff.note == f"CEMINIDFS_HANDOFF_MISSING: {path}"
    assert handoff.rows == []


def test_merge_fills_blank_itt_and_keeps_roof(tmp_path: Path) -> None:
    env_path = tmp_path / "env.csv"
    env_path.write_text(
        "game_id,team,opp,implied_total,roof,weather_exposed,wind_mph,precip_pop\n"
        "CIN@TB,CIN,TB,,open,true,12,0.4\n"
        "CIN@TB,TB,CIN,23.5,open,true,12,0.4\n",
        encoding="utf-8",
    )
    env = read_environment(env_path)
    handoff_path = tmp_path / "h.csv"
    handoff_path.write_text(
        "player,team,projection,lineup_exposure_pct,game,implied_total,roof,salary\n"
        "Demo Back,CIN,99.9,42,CIN@TB,24.5,dome,8000\n",
        encoding="utf-8",
    )
    merged = merge_implied_totals(env, load_ceminidfs_handoff(handoff_path).rows)
    cin = env_for(merged, "CIN", "TB")
    assert cin is not None
    assert cin.implied_total == 24.5
    assert cin.roof == "open"
    assert cin.weather_exposed is True
    assert cin.wind_mph == 12.0
    assert cin.precip_pop == 0.4
    tb = env_for(merged, "TB", "CIN")
    assert tb is not None
    assert tb.implied_total == 23.5
    assert tb.roof == "open"


def test_merge_does_not_overwrite_existing_itt() -> None:
    env = read_environment(ROOT / "examples" / "environment.csv")
    before = env_for(env, "CIN", "TB")
    assert before is not None
    assert before.implied_total == 27.0
    merged = merge_implied_totals(env, load_ceminidfs_handoff(FIXTURE).rows)
    cin = env_for(merged, "CIN", "TB")
    assert cin is not None
    assert cin.implied_total == 27.0
    assert cin.roof == before.roof


def test_merge_creates_minimal_row_when_game_missing(tmp_path: Path) -> None:
    path = tmp_path / "h.csv"
    path.write_text(
        "player,team,projection,lineup_exposure_pct,game,implied_total\n"
        "Demo Back,KC,5,10,KC@BUF,22.0\n",
        encoding="utf-8",
    )
    merged = merge_implied_totals({}, load_ceminidfs_handoff(path).rows)
    row = env_for(merged, "KC", "BUF")
    assert row is not None
    assert row.implied_total == 22.0
    assert row.roof == ""
    assert row.weather_exposed is False
    assert row.wind_mph is None
    assert row.precip_pop is None


def test_projection_not_passed_into_read_distributions(tmp_path: Path) -> None:
    import ceminiparlays.ceminidfs as mod

    text = Path(mod.__file__).read_text(encoding="utf-8")
    assert "from ceminiparlays.io" not in text
    assert "read_distributions(" not in text
    assert "DistRow(" not in text

    handoff = load_ceminidfs_handoff(FIXTURE)
    projections = [row.projection for row in handoff.rows if row.projection is not None]
    assert 12.4 in projections
    env = merge_implied_totals({}, handoff.rows)
    assert not any(isinstance(value, DistRow) for value in env.values())
    dist_path = tmp_path / "distributions.csv"
    dist_path.write_text(
        "player_name,player_key,stat_type,median,sd,family\n"
        "Demo Back,demo_back,rush_yds,60.0,15.0,normal\n",
        encoding="utf-8",
    )
    dists = read_distributions(dist_path)
    assert dists[("demo_back", "rush_yds")].median == 60.0
    assert dists[("demo_back", "rush_yds")].median not in projections


def test_exposure_notes_from_fixture() -> None:
    notes = exposure_notes(load_ceminidfs_handoff(FIXTURE).rows)
    assert notes == [
        "ceminidfs exposure: Demo Back lineup_exposure_pct=42",
        "ceminidfs exposure: Demo Receiver lineup_exposure_pct=18.5",
        "ceminidfs exposure: Demo Rusher lineup_exposure_pct=5",
    ]


def test_compose_missing_handoff_prints_token_and_exits_zero(
    tmp_path: Path, capsys
) -> None:
    missing = tmp_path / "missing.csv"
    code = main(
        [
            "compose",
            "--auto",
            "--n-tickets",
            "1",
            "--lines",
            str(ROOT / "examples" / "sunday_lines.csv"),
            "--from-ceminidfs",
            str(missing),
            "--out-dir",
            str(tmp_path / "compose"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert f"CEMINIDFS_HANDOFF_MISSING: {missing}" in out
