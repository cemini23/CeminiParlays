import csv
import json
from pathlib import Path

from ceminiparlays.cli import SLATE_FIELDS, main
from ceminiparlays.fetch import load_fixture, rows_from_events, write_fetch_csv
from ceminiparlays.roster import load_roster

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "odds_api_nfl.json"


def test_fixture_has_no_apikey() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    assert "apiKey" not in text
    assert "THE_ODDS_API_KEY" not in text


def test_rows_from_fixture_maps_two_way_and_td() -> None:
    events, meta = load_fixture(FIXTURE)
    notes: list[str] = []
    rows = rows_from_events(
        events,
        platform_filter={"hardrock", "fanduel", "draftkings"},
        roster=load_roster(),
        slate_id="demo",
        captured_at="2026-09-13T12:00:00Z",
        notes=notes,
    )
    assert meta["x-requests-remaining"] == "472"
    assert any(note.startswith("no-odds-api-market") for note in notes)
    assert "player_sacks" in "".join(notes)

    caleb_hr = next(
        row
        for row in rows
        if row["player_name"] == "Caleb Williams"
        and row["stat_type"] == "pass_yds"
        and row["platform"] == "hardrock"
    )
    assert caleb_hr["line"] == 224.5
    assert caleb_hr["side"] == "more"
    assert caleb_hr["book_over"] == -110
    assert caleb_hr["book_under"] == -110
    assert caleb_hr["team"] == "CHI"
    assert caleb_hr["opp"] == "CAR"
    assert caleb_hr["slip_odds"] == ""

    caleb_fd = next(
        row
        for row in rows
        if row["player_name"] == "Caleb Williams"
        and row["stat_type"] == "pass_yds"
        and row["platform"] == "fanduel"
    )
    assert caleb_fd["line"] == 225.5
    assert caleb_fd["book_over"] == -108
    assert caleb_fd["book_under"] == -112

    # A rostered player on neither team in the event is dropped, not written with
    # a half-populated opp (A-04).
    assert "roster-event-mismatch:Jahmyr Gibbs" in notes
    assert "roster-event-mismatch:DJ Moore" in notes
    assert not any(row["player_name"] == "Jahmyr Gibbs" for row in rows)
    assert not any(row["player_name"] == "DJ Moore" for row in rows)

    td = next(
        row
        for row in rows
        if row["player_name"] == "Caleb Williams" and row["stat_type"] == "anytime_td"
        and row["platform"] == "hardrock"
    )
    assert td["line"] == ""
    assert td["leg_odds"] == 320
    # The pool-normalized de-vig, never the raw implied probability.
    assert 0.0 < float(td["ref_p"]) < 1.0
    assert float(td["ref_p"]) < 100 / 420
    assert td["fair_p"] == ""
    assert td["team"] == "CHI"
    assert td["opp"] == "CAR"

    ml = next(row for row in rows if row["stat_type"] == "moneyline")
    assert ml["player_name"] in {"Chicago Bears", "Carolina Panthers"}
    assert ml["line"] == ""
    assert ml["leg_odds"] in {-175, 145}
    assert ml["slip_odds"] == ""
    # Moneyline is paired two-way and never priced from a raw implied probability.
    assert ml["book_over"] in {-175, 145}
    assert ml["book_under"] in {-175, 145}
    assert ml["book_over"] != ml["book_under"]
    assert ml["fair_p"] == ""
    assert ml["commence_time"] == "2026-09-13T17:00:00Z"
    total = next(row for row in rows if row["stat_type"] == "total")
    assert "total" in str(total["player_name"]).lower()
    assert total["line"] == 46.5
    assert total["book_over"] == -110
    assert total["book_under"] == -110
    assert total["slip_odds"] == ""


def test_write_fetch_csv_refuses_existing(tmp_path: Path) -> None:
    path = tmp_path / "lines.csv"
    path.write_text("already\n", encoding="utf-8")
    try:
        write_fetch_csv(path, [], force=False)
    except ValueError as exc:
        assert "force" in str(exc)
        assert "--force" in str(exc) or "exists" in str(exc)
    else:
        raise AssertionError("expected overwrite refusal")
    write_fetch_csv(path, [], force=True)
    assert path.read_text(encoding="utf-8").splitlines()[0] == ",".join(SLATE_FIELDS)


def test_fetch_fixture_cli_writes_slate_csv(tmp_path: Path, capsys) -> None:
    out = tmp_path / "lines.csv"
    code = main(
        [
            "fetch",
            "--fixture",
            str(FIXTURE),
            "--out",
            str(out),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "472" in captured.out
    assert "x-requests-remaining" in captured.out
    assert "do not submit" in captured.out.lower()
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert list(csv.DictReader(out.open(encoding="utf-8")).fieldnames) == SLATE_FIELDS
    stats = {row["stat_type"] for row in rows}
    assert "pass_yds" in stats
    assert "anytime_td" in stats or "first_td" in stats
    two_way = next(row for row in rows if row["stat_type"] == "pass_yds")
    assert two_way["book_over"]
    assert two_way["book_under"]
    td = next(row for row in rows if row["stat_type"] in {"anytime_td", "first_td"})
    assert td["line"] == ""
    assert td["leg_odds"]


def test_fetch_missing_key_exits_two(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    out = tmp_path / "lines.csv"
    code = main(["fetch", "--out", str(out)])
    err = capsys.readouterr().err
    assert code == 2
    assert "THE_ODDS_API_KEY is unset" in err
    assert "error:" in err
    assert not out.exists()


def test_fetch_cli_refuses_overwrite(tmp_path: Path, capsys) -> None:
    out = tmp_path / "lines.csv"
    out.write_text("nope\n", encoding="utf-8")
    code = main(
        [
            "fetch",
            "--fixture",
            str(FIXTURE),
            "--out",
            str(out),
        ]
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "force" in err.lower() or "exists" in err.lower()
    assert out.read_text(encoding="utf-8") == "nope\n"


def test_fetch_cli_game_markets(tmp_path: Path, capsys) -> None:
    out = tmp_path / "lines.csv"
    code = main(
        [
            "fetch",
            "--fixture",
            str(FIXTURE),
            "--markets",
            "h2h,totals",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    assert "do not submit" in capsys.readouterr().out.lower()
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    stats = {row["stat_type"] for row in rows}
    assert "moneyline" in stats or "total" in stats
    assert "pass_yds" not in stats


def test_load_fixture_rejects_garbage(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"nope": True}), encoding="utf-8")
    try:
        load_fixture(path)
    except ValueError as exc:
        assert "fixture" in str(exc).lower() or "odds" in str(exc).lower()
    else:
        raise AssertionError("expected bad fixture to fail")
