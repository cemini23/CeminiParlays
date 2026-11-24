"""Local-first market discovery: normalization, diffing, state, and CLI.

Every fixture lives in ``tmp_path`` and every assertion is offline. The module
never opens a socket, so this file never mocks one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ceminiparlays.cli import main
from ceminiparlays.discovery import (
    MarketOffer,
    diff_feed,
    format_alerts,
    load_state,
    normalize_offer,
    normalize_team_token,
    offer_key,
    parse_teams,
    read_snapshot,
    summary_payload,
    write_state,
)

SNAPSHOT = (
    "venue,series,market_id,title,kind,teams,players\n"
    "KALSHI,KXNFLGAME,KN-1,Jaguars at Commanders,listed,JAC @ WSH,\n"
    "KALSHI,KXNFLGAME,KN-2,Bills at Dolphins,listed,BUF @ MIA,\n"
    "KALSHI,KXNFLGAME,KN-3,Will the concert be postponed,rfq,,\n"
)

EMPTY_STATE = {"version": 1, "series": {}, "markets": {}}
STAMP = "2026-11-24T00:00:00+00:00"


@pytest.fixture()
def snapshot(tmp_path: Path) -> Path:
    path = tmp_path / "snapshot.csv"
    path.write_text(SNAPSHOT, encoding="utf-8")
    return path


def _first_diff(path: Path):
    return diff_feed(read_snapshot(path), EMPTY_STATE, seen_at=STAMP)


def test_first_run_alerts_new_series_and_rfq(snapshot: Path) -> None:
    diff = _first_diff(snapshot)
    kinds = [alert.kind for alert in diff.alerts]
    assert kinds.count("new_series") == 1
    assert kinds.count("new_market") == 2
    assert kinds.count("rfq_market") == 1
    # Two listed props and one RFQ listing are markets; the series row is not.
    assert len(diff.state["markets"]) == 3
    assert len(diff.state["series"]) == 1
    assert diff.new_market_count == 3
    assert diff.rfq_count == 1

    series_alert = diff.alerts[0]
    assert series_alert.kind == "new_series"
    assert (series_alert.venue, series_alert.series) == ("kalshi", "KXNFLGAME")
    rfq = next(alert for alert in diff.alerts if alert.kind == "rfq_market")
    assert rfq.market_id == "KN-3"
    assert rfq.message.startswith("NEW RFQ kalshi KXNFLGAME KN-3")

    # Series first, then markets ordered by key.
    assert [alert.kind for alert in diff.alerts] == [
        "new_series",
        "new_market",
        "new_market",
        "rfq_market",
    ]
    assert [alert.key for alert in diff.alerts[1:]] == [
        "kalshi|KXNFLGAME|KN-1",
        "kalshi|KXNFLGAME|KN-2",
        "kalshi|KXNFLGAME|KN-3",
    ]


def test_second_run_is_quiet(snapshot: Path) -> None:
    first = _first_diff(snapshot)
    second = diff_feed(
        read_snapshot(snapshot), first.state, seen_at="2026-11-25T00:00:00+00:00"
    )
    assert second.alerts == ()
    for key, record in first.state["markets"].items():
        assert second.state["markets"][key]["first_seen"] == record["first_seen"]
        assert second.state["markets"][key]["first_seen"] == STAMP
    for key, record in first.state["series"].items():
        assert second.state["series"][key]["first_seen"] == record["first_seen"]


def test_one_new_market_produces_one_alert(snapshot: Path) -> None:
    first = _first_diff(snapshot)
    with snapshot.open("a", encoding="utf-8") as handle:
        handle.write("KALSHI,KXNFLGAME,KN-4,Chiefs at Broncos,listed,KC @ DEN,\n")
    second = diff_feed(read_snapshot(snapshot), first.state, seen_at=STAMP)
    assert [alert.kind for alert in second.alerts] == ["new_market"]
    alert = second.alerts[0]
    assert alert.key == "kalshi|KXNFLGAME|KN-4"
    assert alert.teams == ("DEN", "KC")
    assert len(second.state["markets"]) == 4


def test_duplicate_rows_in_one_snapshot_alert_once() -> None:
    offers = [
        MarketOffer("kalshi", "KXNFLGAME", "KN-9", "first spelling", teams=("JAC", "WSH")),
        MarketOffer("kalshi", "KXNFLGAME", "KN-9", "second spelling", teams=("JAX", "WAS")),
    ]
    diff = diff_feed(offers, EMPTY_STATE, seen_at=STAMP)
    assert [alert.kind for alert in diff.alerts] == ["new_series", "new_market"]
    market_alert = diff.alerts[1]
    assert market_alert.title == "first spelling"
    assert len(diff.state["markets"]) == 1


def test_alias_tokens_are_canonical() -> None:
    assert normalize_team_token("JAC") == "JAX"
    assert normalize_team_token("JAX") == "JAX"
    assert normalize_team_token("WSH") == "WAS"
    assert normalize_team_token("WAS") == "WAS"
    assert normalize_team_token("not a team") == ""
    assert normalize_team_token("") == ""

    left = MarketOffer("kalshi", "S", "M", "t", teams=("JAC", "WSH"))
    right = MarketOffer("kalshi", "S", "M", "t", teams=("JAX", "WAS"))
    assert normalize_offer(left).teams == ("JAX", "WAS")
    assert offer_key(left) == offer_key(right)

    assert parse_teams("JAC @ WSH") == ("JAX", "WAS")
    assert parse_teams("KC vs DEN") == ("DEN", "KC")
    assert parse_teams("JAC/WAS") == ("JAX", "WAS")

    # Player aliases fold through ``names.fold_name``.
    players = normalize_offer(
        MarketOffer("kalshi", "S", "M", "t", players=("Patrick Mahomes",))
    ).players
    assert players == ("patrick_mahomes",)


def test_missing_snapshot_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_snapshot(tmp_path / "absent.csv")


def test_cli_writes_state_and_dry_run_skips_it(
    snapshot: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_path = tmp_path / "state.json"

    dry = main(
        [
            "discover-markets",
            "--source",
            str(snapshot),
            "--state",
            str(state_path),
            "--dry-run",
        ]
    )
    assert dry == 0
    dry_out = capsys.readouterr().out
    assert "DISCOVERY new_series kalshi KXNFLGAME" in dry_out
    assert "DISCOVERY rfq_market kalshi KXNFLGAME KN-3" in dry_out
    assert not state_path.exists()

    wet = main(
        ["discover-markets", "--source", str(snapshot), "--state", str(state_path)]
    )
    assert wet == 0
    assert "DISCOVERY" in capsys.readouterr().out
    assert state_path.is_file()

    repeat = main(
        ["discover-markets", "--source", str(snapshot), "--state", str(state_path)]
    )
    assert repeat == 0
    assert capsys.readouterr().out.strip() == "DISCOVERY none"


def test_state_write_is_sorted(snapshot: Path, tmp_path: Path) -> None:
    diff = _first_diff(snapshot)
    state_path = tmp_path / "nested" / "state.json"
    write_state(state_path, diff.state)

    text = state_path.read_text(encoding="utf-8")
    assert json.loads(text) == diff.state
    assert text == json.dumps(diff.state, indent=2, sort_keys=True) + "\n"
    assert text.index('"markets"') < text.index('"series"') < text.index('"version"')
    assert text.index("KN-1") < text.index("KN-2") < text.index("KN-3")


def test_snapshot_accepts_ticker_and_name_aliases(tmp_path: Path) -> None:
    path = tmp_path / "alias.csv"
    path.write_text(
        "venue,series,ticker,name\n"
        "Draft Kings,kxgame,DK-1,First market\n",
        encoding="utf-8",
    )
    offers = read_snapshot(path)
    assert len(offers) == 1
    offer = offers[0]
    assert offer.market_id == "DK-1"
    assert offer.title == "First market"
    assert normalize_offer(offer).venue == "draft_kings"
    assert normalize_offer(offer).kind == "listed"


def test_snapshot_missing_column_raises(tmp_path: Path) -> None:
    path = tmp_path / "broken.csv"
    path.write_text("venue,series,title\nkalshi,KXNFLGAME,t\n", encoding="utf-8")
    with pytest.raises(ValueError, match="market_id"):
        read_snapshot(path)


def test_state_loader_rejects_malformed_payload(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_state(broken)

    listed = tmp_path / "listed.json"
    listed.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_state(listed)

    assert load_state(tmp_path / "absent.json") == {
        "version": 1,
        "series": {},
        "markets": {},
    }


def test_sources_config_resolves_relative_paths(
    snapshot: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "sources.json"
    config.write_text(
        json.dumps({"sources": ["snapshot.csv"]}), encoding="utf-8"
    )
    code = main(
        [
            "discover-markets",
            "--sources",
            str(config),
            "--state",
            str(tmp_path / "state.json"),
            "--dry-run",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["new_series"] == 1
    assert payload["new_markets"] == 3
    assert payload["rfq"] == 1


def test_cli_requires_a_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["discover-markets", "--state", str(tmp_path / "state.json")])
    assert code == 2
    assert "discover-markets needs --source or --sources" in capsys.readouterr().err


def test_format_and_summary_shapes(snapshot: Path) -> None:
    diff = _first_diff(snapshot)
    lines = format_alerts(diff).splitlines()
    assert len(lines) == len(diff.alerts)
    assert all(line.startswith("DISCOVERY ") for line in lines)
    assert lines[0] == "DISCOVERY new_series kalshi KXNFLGAME"
    assert lines[1] == (
        "DISCOVERY new_market kalshi KXNFLGAME KN-1 Jaguars at Commanders"
    )

    payload = summary_payload(diff)
    assert payload["new_series"] == 1
    assert payload["new_markets"] == 3
    assert payload["rfq"] == 1
    assert len(payload["alerts"]) == 4
    assert payload["alerts"][0]["kind"] == "new_series"
    assert payload["alerts"][1]["teams"] == ["JAX", "WAS"]

    quiet = diff_feed([], diff.state)
    assert format_alerts(quiet) == "DISCOVERY none"
    assert summary_payload(quiet) == {
        "new_series": 0,
        "new_markets": 0,
        "rfq": 0,
        "alerts": [],
    }
