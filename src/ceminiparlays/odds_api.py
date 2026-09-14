"""Licensed The Odds API client (stdlib urllib only).

Book-site scrapers are out of scope. This module is the only place
``urllib.request`` is allowed.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

from ceminiparlays.payouts import normalize_platform
from ceminiparlays.resources import read_config_text
from ceminiparlays.roster import normalize_team

API_HOST = "https://api.the-odds-api.com"
DEFAULT_TIMEOUT = 30
DEFAULT_REGIONS = "us,us2"
SPORT_KEYS = {"nfl": "americanfootball_nfl"}
BOOKMAKER_TO_PLATFORM = {
    "fanduel": "fanduel",
    "draftkings": "draftkings",
    "betmgm": "betmgm",
    "hardrockbet": "hardrock",
    "hardrockbet_fl": "hardrock",
}
MARKET_TO_STAT = {
    "player_pass_yds": "pass_yds",
    "player_rush_yds": "rush_yds",
    "player_reception_yds": "rec_yds",
    "player_receptions": "receptions",
    "player_rush_attempts": "rush_att",
    "player_pass_tds": "pass_tds",
    "player_1st_td": "first_td",
    "player_anytime_td": "anytime_td",
    "h2h": "moneyline",
    "spreads": "spread",
    "totals": "total",
}
STAT_TO_MARKET = {stat: market for market, stat in MARKET_TO_STAT.items()}
FETCH_BOOKS = ("hardrock", "fanduel", "draftkings", "betmgm")
CREDIT_HEADERS = ("x-requests-remaining", "x-requests-used")


def _load_team_names() -> dict[str, str]:
    raw = json.loads(read_config_text("nfl_teams.json"))
    return {str(name): normalize_team(str(code)) for name, code in raw.items()}


TEAM_NAMES = _load_team_names()
_TEAM_NAMES_LOWER = {name.lower(): code for name, code in TEAM_NAMES.items()}


def resolve_api_key() -> str:
    key = os.environ.get("THE_ODDS_API_KEY", "").strip()
    if not key:
        raise ValueError("THE_ODDS_API_KEY is unset")
    return key


def redact_url(url: str) -> str:
    """Strip ``apiKey`` query parameters before any print."""

    parsed = urlparse(url)
    kept = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() != "apikey"]
    return urlunparse(parsed._replace(query=urlencode(kept)))


def team_code(full_name: str) -> str:
    text = (full_name or "").strip()
    if not text:
        return ""
    if text in TEAM_NAMES:
        return TEAM_NAMES[text]
    mapped = _TEAM_NAMES_LOWER.get(text.lower())
    if mapped:
        return mapped
    return normalize_team(text)


def select_bookmakers(bookmakers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop ``hardrockbet`` when ``hardrockbet_fl`` is present for the same event."""

    keys = {str(book.get("key") or "") for book in bookmakers}
    drop = {"hardrockbet"} if "hardrockbet_fl" in keys and "hardrockbet" in keys else set()
    return [book for book in bookmakers if str(book.get("key") or "") not in drop]


def bookmakers_for_platforms(platforms: Iterable[str]) -> list[str]:
    wanted = {normalize_platform(token) for token in platforms}
    out: list[str] = []
    for key, platform in BOOKMAKER_TO_PLATFORM.items():
        if platform in wanted and key not in out:
            out.append(key)
    return out


def parse_books(value: str | None) -> list[str]:
    if value is None:
        return ["hardrock", "fanduel", "draftkings"]
    tokens: list[str] = []
    for part in value.split(","):
        token = normalize_platform(part)
        if not token:
            continue
        if token not in FETCH_BOOKS:
            raise ValueError(
                f"unknown --books token(s): {token}; legal: {', '.join(FETCH_BOOKS)}"
            )
        if token not in tokens:
            tokens.append(token)
    if not tokens:
        raise ValueError("no --books tokens")
    return tokens


def parse_fetch_date(value: str | None, *, tzinfo: timezone | ZoneInfo | None = None) -> date:
    if not value:
        return datetime.now(tzinfo or timezone.utc).date()
    return date.fromisoformat(value)


def utc_day_window(day: date) -> tuple[str, str]:
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return (
        start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def et_slate_window(day: date) -> tuple[str, str]:
    """America/New_York midnight→midnight for ``day``, formatted as UTC ``...Z``.

    DST offset comes from ``zoneinfo``, not a hard-coded −4/−5.
    """

    eastern = ZoneInfo("America/New_York")
    start_et = datetime(day.year, day.month, day.day, tzinfo=eastern)
    end_et = start_et + timedelta(days=1)
    start = start_et.astimezone(timezone.utc)
    end = end_et.astimezone(timezone.utc)
    return (
        start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def sport_key_for(sport: str) -> str:
    key = SPORT_KEYS.get((sport or "").strip().lower())
    if not key:
        raise ValueError(f"unknown --sport {sport}")
    return key


def events_url(sport_key: str, commence_from: str, commence_to: str, api_key: str) -> str:
    query = urlencode(
        {
            "commenceTimeFrom": commence_from,
            "commenceTimeTo": commence_to,
            "apiKey": api_key,
        }
    )
    return f"{API_HOST}/v4/sports/{sport_key}/events?{query}"


def event_odds_url(
    sport_key: str,
    event_id: str,
    *,
    regions: str,
    markets: str,
    bookmakers: str,
    api_key: str,
) -> str:
    query = urlencode(
        {
            "regions": regions,
            "markets": markets,
            "bookmakers": bookmakers,
            "oddsFormat": "american",
            "apiKey": api_key,
        }
    )
    return f"{API_HOST}/v4/sports/{sport_key}/events/{event_id}/odds?{query}"


def _credit_headers(headers: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in CREDIT_HEADERS:
        value = headers.get(key) if headers is not None else None
        out[key] = "" if value is None else str(value)
    return out


def get_json(
    url: str,
    *,
    opener: Any | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    sleeper: Any | None = None,
    _retried: bool = False,
) -> tuple[object, dict[str, str]]:
    """GET JSON via stdlib urllib. Returns payload plus credit headers."""

    handle = opener or urllib.request.build_opener()
    request = urllib.request.Request(url)
    try:
        with handle.open(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload, _credit_headers(response.headers)
    except urllib.error.HTTPError as exc:
        if exc.code == 429 and not _retried:
            exc.close()
            (sleeper or time.sleep)(2)
            return get_json(
                url,
                opener=opener,
                timeout=timeout,
                sleeper=sleeper,
                _retried=True,
            )
        raise ValueError(f"Odds API HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValueError("Odds API request failed") from exc


def pull_event_odds(
    sport_key: str,
    *,
    commence_from: str,
    commence_to: str,
    regions: str,
    markets: str,
    bookmakers: str,
    api_key: str,
    opener: Any | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """GET the day's events, then per-event player-prop odds. No polling."""

    events_payload, headers = get_json(
        events_url(sport_key, commence_from, commence_to, api_key),
        opener=opener,
        timeout=timeout,
    )
    if not isinstance(events_payload, list):
        raise ValueError("Odds API events payload is not a list")
    out: list[dict[str, Any]] = []
    for event in events_payload:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or "")
        if not event_id:
            continue
        payload, headers = get_json(
            event_odds_url(
                sport_key,
                event_id,
                regions=regions,
                markets=markets,
                bookmakers=bookmakers,
                api_key=api_key,
            ),
            opener=opener,
            timeout=timeout,
        )
        if isinstance(payload, dict):
            out.append(payload)
    return out, headers
