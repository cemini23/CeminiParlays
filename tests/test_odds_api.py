import io
import json
import urllib.error
from urllib.parse import parse_qs, urlparse

from datetime import date

from ceminiparlays.odds_api import (
    BOOKMAKER_TO_PLATFORM,
    MARKET_TO_STAT,
    TEAM_NAMES,
    bookmakers_for_platforms,
    et_slate_window,
    event_odds_url,
    events_url,
    get_json,
    redact_url,
    resolve_api_key,
    select_bookmakers,
    team_code,
    utc_day_window,
)


def test_market_and_book_maps() -> None:
    assert MARKET_TO_STAT["player_pass_yds"] == "pass_yds"
    assert MARKET_TO_STAT["player_rush_yds"] == "rush_yds"
    assert MARKET_TO_STAT["player_reception_yds"] == "rec_yds"
    assert MARKET_TO_STAT["player_receptions"] == "receptions"
    assert MARKET_TO_STAT["player_rush_attempts"] == "rush_att"
    assert MARKET_TO_STAT["player_pass_tds"] == "pass_tds"
    assert MARKET_TO_STAT["player_1st_td"] == "first_td"
    assert MARKET_TO_STAT["player_anytime_td"] == "anytime_td"
    assert MARKET_TO_STAT["h2h"] == "moneyline"
    assert MARKET_TO_STAT["spreads"] == "spread"
    assert MARKET_TO_STAT["totals"] == "total"
    assert BOOKMAKER_TO_PLATFORM["fanduel"] == "fanduel"
    assert BOOKMAKER_TO_PLATFORM["draftkings"] == "draftkings"
    assert BOOKMAKER_TO_PLATFORM["betmgm"] == "betmgm"
    assert BOOKMAKER_TO_PLATFORM["hardrockbet"] == "hardrock"
    assert BOOKMAKER_TO_PLATFORM["hardrockbet_fl"] == "hardrock"


def test_team_names_cover_odds_api_full_names() -> None:
    assert TEAM_NAMES["Buffalo Bills"] == "BUF"
    assert TEAM_NAMES["Kansas City Chiefs"] == "KC"
    assert TEAM_NAMES["Los Angeles Rams"] == "LAR"
    assert TEAM_NAMES["Washington Commanders"] == "WAS"
    assert team_code("Chicago Bears") == "CHI"
    assert team_code("carolina panthers") == "CAR"


def test_redact_url_strips_apikey(monkeypatch) -> None:
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    url = events_url(
        "americanfootball_nfl",
        "2026-09-13T00:00:00Z",
        "2026-09-14T00:00:00Z",
        "dummy-key-value",
    )
    assert "dummy-key-value" in url
    redacted = redact_url(url)
    assert "apiKey" not in redacted
    assert "apikey" not in redacted.lower()
    assert "dummy-key-value" not in redacted
    odds = event_odds_url(
        "americanfootball_nfl",
        "evt-1",
        regions="us,us2",
        markets="player_pass_yds",
        bookmakers="fanduel,hardrockbet_fl",
        api_key="dummy-key-value",
    )
    assert "/events/evt-1/odds" in odds
    parsed = urlparse(odds)
    assert parse_qs(parsed.query)["oddsFormat"] == ["american"]
    assert "apiKey" not in redact_url(odds)


def test_prefer_hardrock_fl() -> None:
    books = [
        {"key": "hardrockbet", "markets": []},
        {"key": "hardrockbet_fl", "markets": []},
        {"key": "fanduel", "markets": []},
    ]
    selected = select_bookmakers(books)
    assert [book["key"] for book in selected] == ["hardrockbet_fl", "fanduel"]
    assert bookmakers_for_platforms(["hardrock"]) == ["hardrockbet", "hardrockbet_fl"]


class _FakeResponse:
    def __init__(self, payload: object, headers: dict[str, str] | None = None) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.headers = headers or {
            "x-requests-remaining": "10",
            "x-requests-used": "2",
        }

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def test_get_json_uses_injectable_opener() -> None:
    class Opener:
        def open(self, request, timeout=None):
            assert timeout == 30
            assert "apiKey" not in request.full_url
            return _FakeResponse({"ok": True})

    payload, headers = get_json("https://example.test/v4/ok", opener=Opener())
    assert payload == {"ok": True}
    assert headers["x-requests-remaining"] == "10"
    assert headers["x-requests-used"] == "2"


def test_get_json_retries_once_on_http_429() -> None:
    slept: list[float] = []

    class Opener:
        def __init__(self) -> None:
            self.calls = 0

        def open(self, request, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise urllib.error.HTTPError(
                    request.full_url,
                    429,
                    "Too Many Requests",
                    {},
                    io.BytesIO(b""),
                )
            return _FakeResponse({"id": "evt"})

    opener = Opener()
    payload, headers = get_json(
        "https://example.test/v4/odds",
        opener=opener,
        sleeper=slept.append,
    )
    assert opener.calls == 2
    assert slept == [2]
    assert payload == {"id": "evt"}
    assert headers["x-requests-remaining"] == "10"


def test_et_slate_window_includes_snf_kickoff() -> None:
    kick = "2026-09-14T00:20:00Z"
    start, end = et_slate_window(date(2026, 9, 13))
    assert start <= kick < end
    utc_start, utc_end = utc_day_window(date(2026, 9, 13))
    assert not (utc_start <= kick < utc_end)


def test_resolve_api_key_unset(monkeypatch) -> None:
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    try:
        resolve_api_key()
    except ValueError as exc:
        assert str(exc) == "THE_ODDS_API_KEY is unset"
    else:
        raise AssertionError("expected unset key to fail")
