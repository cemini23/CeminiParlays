"""Map Odds API event-odds payloads onto the fill-in slate CSV."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ceminiparlays.io import LineRow, write_csv
from ceminiparlays.markets import is_td_market
from ceminiparlays.names import fold_name
from ceminiparlays.odds import devig_multiway
from ceminiparlays.odds_api import (
    BOOKMAKER_TO_PLATFORM,
    MARKET_TO_STAT,
    select_bookmakers,
    team_code,
)
from ceminiparlays.roster import Roster, lookup_player


def load_fixture(path: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    meta: dict[str, str] = {}
    if isinstance(raw, dict) and isinstance(raw.get("meta"), dict):
        meta = {str(key): str(value) for key, value in raw["meta"].items()}
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)], meta
    if isinstance(raw, dict):
        events = raw.get("events")
        if isinstance(events, list):
            return [item for item in events if isinstance(item, dict)], meta
        if "bookmakers" in raw:
            return [raw], meta
    raise ValueError(f"{path} is not an Odds API events fixture")


def _lookup(name: str, roster: Roster | None):
    if roster is None:
        return None
    stub = LineRow(
        slate_id="",
        platform="",
        player_name=name,
        player_key="",
        team="",
        opponent="",
        stat_type="",
        line=float("nan"),
        side="more",
        line_type="standard",
        captured_at="",
        displayed_multiplier=None,
        injury_status="",
        book_over=None,
        book_under=None,
    )
    return lookup_player(stub, roster)


def _team_opp(
    name: str, home: str, away: str, roster: Roster | None
) -> tuple[str, str, str] | None:
    """Resolve ``(player_key, team, opp)`` for a prop row.

    ``None`` means the roster knows the player but places them on neither team in
    this game (a stale or corrupt roster entry). The caller drops the row instead
    of writing a half-populated ``opp`` (A-04).
    """

    found = _lookup(name, roster)
    if found is not None:
        team = found.team
        if team == home:
            return found.player_key, team, away
        if team == away:
            return found.player_key, team, home
        return None
    return fold_name(name), "", ""


def _blank_row(
    *,
    slate_id: str,
    platform: str,
    player_name: str,
    player_key: str,
    team: str,
    opp: str,
    stat_type: str,
    captured_at: str,
    commence_time: str = "",
) -> dict[str, object]:
    return {
        "slate_id": slate_id,
        "platform": platform,
        "player_name": player_name,
        "player_key": player_key,
        "team": team,
        "opp": opp,
        "stat_type": stat_type,
        "line": "",
        "side": "more",
        "line_type": "standard",
        "captured_at": captured_at,
        "commence_time": commence_time,
        "injury_status": "",
        "book_over": "",
        "book_under": "",
        "leg_odds": "",
        "slip_odds": "",
        "slip_multiplier": "",
        "ticket_id": "",
        "fair_p": "",
        "contract_price": "",
        "ref_p": "",
        "ref_book_over": "",
        "ref_book_under": "",
    }


def _int_price(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pair_two_way(outcomes: list[dict[str, Any]]) -> list[tuple[str, float, int, int]]:
    buckets: dict[tuple[str, float], dict[str, int]] = {}
    for outcome in outcomes:
        player = str(outcome.get("description") or "").strip()
        point = outcome.get("point")
        price = _int_price(outcome.get("price"))
        if not player or point is None or price is None:
            continue
        name = str(outcome.get("name") or "").strip().lower()
        bucket = buckets.setdefault((player, float(point)), {})
        if name in {"over", "more"}:
            bucket["over"] = price
        elif name in {"under", "less"}:
            bucket["under"] = price
    paired: list[tuple[str, float, int, int]] = []
    for (player, point), sides in buckets.items():
        if "over" in sides and "under" in sides:
            paired.append((player, point, sides["over"], sides["under"]))
    return paired


def _team_side(name: str, home: str, away: str) -> tuple[str, str] | None:
    team = team_code(name)
    if team == home:
        return home, away
    if team == away:
        return away, home
    return None


def _two_team_quotes(
    outcomes: list[dict[str, Any]], home: str, away: str
) -> dict[str, tuple[str, float | None, int]]:
    """Map each team code to ``(display_name, point, price)``."""

    quotes: dict[str, tuple[str, float | None, int]] = {}
    for outcome in outcomes:
        name = str(outcome.get("name") or "").strip()
        price = _int_price(outcome.get("price"))
        if not name or price is None:
            continue
        sides = _team_side(name, home, away)
        if sides is None:
            continue
        point = outcome.get("point")
        quotes[sides[0]] = (
            name,
            float(point) if point is not None else None,
            price,
        )
    return quotes


def _h2h_rows(
    outcomes: list[dict[str, Any]],
    *,
    home: str,
    away: str,
    slate_id: str,
    platform: str,
    captured_at: str,
    commence_time: str = "",
) -> list[dict[str, object]]:
    """Pair the two moneyline outcomes into ``book_over`` / ``book_under``.

    Each team's row carries its own price as ``book_over`` and the opponent's as
    ``book_under``, so the two-way de-vig yields that team's win probability. The
    raw implied probability is never written as ``fair_p`` (A-02).
    """

    quotes = _two_team_quotes(outcomes, home, away)
    rows: list[dict[str, object]] = []
    for team, opp in ((home, away), (away, home)):
        mine = quotes.get(team)
        theirs = quotes.get(opp)
        if mine is None or theirs is None:
            continue
        row = _blank_row(
            slate_id=slate_id,
            platform=platform,
            player_name=mine[0],
            player_key=fold_name(mine[0]),
            team=team,
            opp=opp,
            stat_type="moneyline",
            captured_at=captured_at,
            commence_time=commence_time,
        )
        row["leg_odds"] = mine[2]
        row["book_over"] = mine[2]
        row["book_under"] = theirs[2]
        rows.append(row)
    return rows


def _spread_rows(
    outcomes: list[dict[str, Any]],
    *,
    home: str,
    away: str,
    slate_id: str,
    platform: str,
    captured_at: str,
    commence_time: str = "",
) -> list[dict[str, object]]:
    """Pair the two spread outcomes for the home team.

    The home row keeps the posted home line and both prices; the away row mirrors
    it. Without the pair the row had no ``book_over`` / ``book_under`` and was
    dropped by ``evaluate_legs`` (A-10.5).
    """

    quotes = _two_team_quotes(outcomes, home, away)
    home_q = quotes.get(home)
    away_q = quotes.get(away)
    if home_q is None or away_q is None:
        return []
    rows: list[dict[str, object]] = []
    for team, opp, mine, theirs in (
        (home, away, home_q, away_q),
        (away, home, away_q, home_q),
    ):
        row = _blank_row(
            slate_id=slate_id,
            platform=platform,
            player_name=mine[0],
            player_key=fold_name(mine[0]),
            team=team,
            opp=opp,
            stat_type="spread",
            captured_at=captured_at,
            commence_time=commence_time,
        )
        row["line"] = mine[1] if mine[1] is not None else ""
        row["leg_odds"] = mine[2]
        row["book_over"] = mine[2]
        row["book_under"] = theirs[2]
        rows.append(row)
    return rows


def _pair_totals(outcomes: list[dict[str, Any]]) -> list[tuple[float, int, int]]:
    buckets: dict[float, dict[str, int]] = {}
    for outcome in outcomes:
        point = outcome.get("point")
        price = _int_price(outcome.get("price"))
        name = str(outcome.get("name") or "").strip().lower()
        if point is None or price is None:
            continue
        bucket = buckets.setdefault(float(point), {})
        if name in {"over", "more"}:
            bucket["over"] = price
        elif name in {"under", "less"}:
            bucket["under"] = price
    paired: list[tuple[float, int, int]] = []
    for point, sides in buckets.items():
        if "over" in sides and "under" in sides:
            paired.append((point, sides["over"], sides["under"]))
    return paired


def _total_rows(
    outcomes: list[dict[str, Any]],
    *,
    home: str,
    away: str,
    slate_id: str,
    platform: str,
    captured_at: str,
    commence_time: str = "",
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    player_name = f"{away}@{home} total"
    for point, over_price, under_price in _pair_totals(outcomes):
        row = _blank_row(
            slate_id=slate_id,
            platform=platform,
            player_name=player_name,
            player_key=fold_name(player_name),
            team=home,
            opp=away,
            stat_type="total",
            captured_at=captured_at,
            commence_time=commence_time,
        )
        row["line"] = point
        row["book_over"] = over_price
        row["book_under"] = under_price
        rows.append(row)
    return rows


def _td_yes(outcomes: list[dict[str, Any]]) -> list[tuple[str, int]]:
    found: dict[str, int] = {}
    for outcome in outcomes:
        name = str(outcome.get("name") or "").strip().lower()
        if name != "yes":
            continue
        player = str(outcome.get("description") or "").strip()
        price = _int_price(outcome.get("price"))
        if player and price is not None:
            found[player] = price
    return list(found.items())


def _td_rows(
    outcomes: list[dict[str, Any]],
    *,
    stat: str,
    home: str,
    away: str,
    slate_id: str,
    platform: str,
    captured_at: str,
    commence_time: str,
    roster: Roster | None,
    notes: list[str],
) -> list[dict[str, object]]:
    """One row per player in the game's TD pool, with a pool-normalized ``ref_p``.

    A ``first_td`` / ``anytime_td`` "Yes" price is one-way; the raw implied
    probability already contains the whole pool overround, so it is never written
    as ``fair_p``. Every player's price is de-vigged against the pool instead. An
    ``anytime_td`` pool may be incomplete, so it takes a conservative haircut
    (A-02).
    """

    pool = _td_yes(outcomes)
    if not pool:
        return []
    hold = 0.15 if stat == "anytime_td" else 0.0
    result = devig_multiway([price for _player, price in pool], hold_pct=hold)
    rows: list[dict[str, object]] = []
    for (player_name, yes_price), fair_p in zip(pool, result.probs):
        resolved = _team_opp(player_name, home, away, roster)
        if resolved is None:
            notes.append(f"roster-event-mismatch:{player_name}")
            continue
        player_key, team, opp = resolved
        row = _blank_row(
            slate_id=slate_id,
            platform=platform,
            player_name=player_name,
            player_key=player_key,
            team=team,
            opp=opp,
            stat_type=stat,
            captured_at=captured_at,
            commence_time=commence_time,
        )
        row["leg_odds"] = yes_price
        row["ref_p"] = round(fair_p, 6)
        rows.append(row)
    return rows


def _pair_key(row: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(row.get("player_name") or "").strip().lower(),
        str(row.get("stat_type") or ""),
        str(row.get("line") or ""),
    )


def _stamp_reference(
    rows: list[dict[str, object]], reference_book: str | None
) -> None:
    """Copy the reference book's quotes onto every other book's matching row.

    ``rank`` / ``compose`` filter to one platform before pricing, so a reference
    book's rows would be discarded. Carrying its quote as ``ref_book_over`` /
    ``ref_book_under`` (and ``ref_p`` for TD) keeps an independent fair value on
    the bet row.
    """

    if not reference_book:
        return
    index: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in rows:
        if str(row.get("platform")) == reference_book:
            index[_pair_key(row)] = row
    for row in rows:
        if str(row.get("platform")) == reference_book:
            continue
        ref = index.get(_pair_key(row))
        if ref is None:
            continue
        if ref.get("book_over") not in ("", None):
            row["ref_book_over"] = ref.get("book_over")
        if ref.get("book_under") not in ("", None):
            row["ref_book_under"] = ref.get("book_under")
        if row.get("ref_p") in ("", None) and ref.get("ref_p") not in ("", None):
            row["ref_p"] = ref.get("ref_p")


def rows_from_events(
    events: list[dict[str, Any]],
    *,
    platform_filter: set[str] | None,
    roster: Roster | None,
    slate_id: str,
    captured_at: str,
    notes: list[str],
    reference_book: str | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    unknown_markets: set[str] = set()
    for event in events:
        home = team_code(str(event.get("home_team") or ""))
        away = team_code(str(event.get("away_team") or ""))
        commence_time = str(event.get("commence_time") or "").strip()
        bookmakers = select_bookmakers(list(event.get("bookmakers") or []))
        for book in bookmakers:
            book_key = str(book.get("key") or "")
            platform = BOOKMAKER_TO_PLATFORM.get(book_key)
            if platform is None:
                continue
            if platform_filter is not None and platform not in platform_filter:
                continue
            for market in book.get("markets") or []:
                market_key = str(market.get("key") or "")
                stat = MARKET_TO_STAT.get(market_key)
                if stat is None:
                    if market_key and market_key not in unknown_markets:
                        unknown_markets.add(market_key)
                        notes.append(f"no-odds-api-market:{market_key}")
                    continue
                outcomes = [item for item in (market.get("outcomes") or []) if isinstance(item, dict)]
                if stat == "moneyline":
                    rows.extend(
                        _h2h_rows(
                            outcomes,
                            home=home,
                            away=away,
                            slate_id=slate_id,
                            platform=platform,
                            captured_at=captured_at,
                            commence_time=commence_time,
                        )
                    )
                    continue
                if stat == "spread":
                    rows.extend(
                        _spread_rows(
                            outcomes,
                            home=home,
                            away=away,
                            slate_id=slate_id,
                            platform=platform,
                            captured_at=captured_at,
                            commence_time=commence_time,
                        )
                    )
                    continue
                if stat == "total":
                    rows.extend(
                        _total_rows(
                            outcomes,
                            home=home,
                            away=away,
                            slate_id=slate_id,
                            platform=platform,
                            captured_at=captured_at,
                            commence_time=commence_time,
                        )
                    )
                    continue
                if is_td_market(stat):
                    rows.extend(
                        _td_rows(
                            outcomes,
                            stat=stat,
                            home=home,
                            away=away,
                            slate_id=slate_id,
                            platform=platform,
                            captured_at=captured_at,
                            commence_time=commence_time,
                            roster=roster,
                            notes=notes,
                        )
                    )
                    continue
                for player_name, point, over_price, under_price in _pair_two_way(outcomes):
                    resolved = _team_opp(player_name, home, away, roster)
                    if resolved is None:
                        notes.append(f"roster-event-mismatch:{player_name}")
                        continue
                    player_key, team, opp = resolved
                    row = _blank_row(
                        slate_id=slate_id,
                        platform=platform,
                        player_name=player_name,
                        player_key=player_key,
                        team=team,
                        opp=opp,
                        stat_type=stat,
                        captured_at=captured_at,
                        commence_time=commence_time,
                    )
                    row["line"] = point
                    row["book_over"] = over_price
                    row["book_under"] = under_price
                    rows.append(row)
    _stamp_reference(rows, reference_book)
    return rows


def write_fetch_csv(path: Path, rows: list[dict[str, object]], *, force: bool) -> None:
    from ceminiparlays.cli import SLATE_FIELDS

    if path.exists() and not force:
        raise ValueError(f"{path} exists; pass --force to overwrite")
    cleaned = [{field: row.get(field, "") for field in SLATE_FIELDS} for row in rows]
    write_csv(path, cleaned, SLATE_FIELDS)
