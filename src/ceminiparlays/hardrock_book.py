"""Read Hard Rock's public odds board and map it onto the slate row shape.

The HTTP paths are the ones the book app and the public wrappers name.
``parse_capture`` does not open a socket. A saved capture file parses twice
to the same CSV. This module never sends ``placeBets`` and never builds a
bet slip.

Cited read paths, checked on 2026-10-17:

* ``GET /sportsbook/v1/api/getRootLadder`` and
  ``GET /sportsbook/api/public/events/tree`` from
  ``derekcnursey/codex_hoops-edge`` ``src/hrb_odds.py``. That repo has no
  license file (GitHub license API 404).
* ``GET /java-graphql/operation/GetEvents`` and
  ``GET /java-graphql/competitions/{id}/events`` from the book bundle
  ``https://app.hardrock.bet/dist/bundle.3.42.14235.js``
  (``baseGraphqlURL`` plus ``buildUrl``).
* ``POST /java-graphql/graphql?type=event_tree`` is the path in
  ``hrb_odds.py``. It returned HTTP 400 on this date, so the capture uses
  the GET that returned 200.
"""

from __future__ import annotations

import argparse
import csv
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ceminiparlays.cli import SLATE_FIELDS
from ceminiparlays.markets import LEGAL_MARKETS
from ceminiparlays.names import fold_name
from ceminiparlays.odds import american_to_implied
from ceminiparlays.resources import read_config_text

API_ORIGIN = "https://api.hardrocksportsbook.com"
LADDER_URL = f"{API_ORIGIN}/sportsbook/v1/api/getRootLadder"
GET_EVENTS_URL = f"{API_ORIGIN}/java-graphql/operation/GetEvents"
TREE_URL = f"{API_ORIGIN}/sportsbook/api/public/events/tree"
NFL_COMPETITION_ID = "2295257447167426824"
CHANNEL = "FLORIDA_ONLINE"
SEGMENT = "FL"
SLATE_ID = "2026-w06-nfl"
PLATFORM = "hardrock"

# Longer markers stay above the shorter family they could be confused with.
# PROPLNGREC does not contain PROPREC. The order is still explicit.
_KEEP_MARKERS = (
    "PROPLNGPSCMP",
    "PROPLNGREC",
    "PROPLNGRS",
    "PROPPSCMP",
    "PROPPSATT",
    "PROPINT",
    "PROPRSATT",
    "PROPFGM",
    "PROPKPT",
    "PROPEXTPTM",
    "PROPSACKS",
    "PROPTACKLES",
    "OUFGMOU",
    "OUKPTS",
    "PROPPSYDS",
    "PROPRCYDS",
    "PROPRSYDS",
    "PROPREC",
    "PROPALTRECEPTIONS",
    "PROPALTPSYDS",
    "PROPALTRECYDS",
    "PROPALTRUYDS",
    ":OU",
    ":SPRD",
    ":ML",
)
_STAT_MARKERS = (
    ("PROPLNGPSCMP", "pass_longest"),
    ("PROPLNGREC", "rec_longest"),
    ("PROPLNGRS", "rush_longest"),
    ("PROPPSCMP", "pass_completions"),
    ("PROPPSATT", "pass_attempts"),
    ("PROPINT", "interceptions"),
    ("PROPRSATT", "rush_att"),
    ("PROPFGM", "field_goals"),
    ("PROPKPT", "kicking_points"),
    ("PROPEXTPTM", "extra_points"),
    ("PROPSACKS", "sacks"),
    ("PROPTACKLES", "tackles"),
    ("OUFGMOU", "total_field_goals"),
    ("OUKPTS", "total_kicking_points"),
    ("PROPPSYDS", "pass_yds"),
    ("PROPRCYDS", "rec_yds"),
    ("PROPRSYDS", "rush_yds"),
    ("PROPREC", "receptions"),
    ("PROPALTRECEPTIONS", "receptions"),
    ("PROPALTPSYDS", "pass_yds"),
    ("PROPALTRECYDS", "rec_yds"),
    ("PROPALTRUYDS", "rush_yds"),
)


def _request_json(url: str, timeout: int = 60) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "origin": "https://app.hardrock.bet",
            "referer": "https://app.hardrock.bet/",
            "user-agent": "CeminiParlays/hardrock-read",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:180]
        raise ValueError(f"Hard Rock read failed [{exc.code}] {exc.reason}: {detail}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Hard Rock read did not return a JSON object")
    return payload


def _query(extra: dict[str, str]) -> str:
    from urllib.parse import urlencode

    params = {
        "channel": CHANNEL,
        "segment": SEGMENT,
        "region": "us",
        "language": "enus",
    }
    params.update(extra)
    return urlencode(params)


def fetch_ladder() -> dict[str, dict[str, str]]:
    """Return ``rootIndex -> {decimal, moneyline}`` from the public ladder."""

    payload = _request_json(LADDER_URL)
    rows = (
        payload.get("PriceAdjustmentDetailsResponse", {}).get("rootLadder")
        or payload.get("rootLadder")
        or []
    )
    ladder: dict[str, dict[str, str]] = {}
    for row in rows:
        try:
            index = str(int(row["rootIndex"]))
        except (KeyError, TypeError, ValueError):
            continue
        ladder[index] = {
            "decimal": str(row.get("decimal") or ""),
            "moneyline": str(row.get("moneyline") or ""),
        }
    if not ladder:
        raise ValueError("Hard Rock root ladder was empty")
    return ladder


def fetch_event_list() -> list[dict[str, Any]]:
    url = (
        f"{API_ORIGIN}/java-graphql/competitions/{NFL_COMPETITION_ID}/events?"
        + _query(
            {
                "displayed": "true",
                "outright": "false",
                "includeMarkets": "false",
                "includeCount": "true",
                "offset": "0",
                "limit": "30",
            }
        )
    )
    payload = _request_json(url)
    events = payload.get("data")
    if not isinstance(events, list) or not events:
        raise ValueError("Hard Rock NFL event list was empty")
    return [event for event in events if isinstance(event, dict)]


def fetch_event_markets(event_id: str) -> dict[str, Any]:
    url = GET_EVENTS_URL + "?" + _query({"ids": event_id, "includeMarkets": "true"})
    payload = _request_json(url, timeout=90)
    events = (
        payload.get("data", {}).get("betSync", {}).get("events", {}).get("data") or []
    )
    if not events:
        raise ValueError(f"Hard Rock returned no event for id {event_id}")
    return events[0]


def _keep_market(market: dict[str, Any]) -> bool:
    if market.get("displayed") is False:
        return False
    if str(market.get("state") or "OPEN").upper() not in {"OPEN", ""}:
        return False
    market_type = str(market.get("type") or "")
    return any(marker in market_type for marker in _KEEP_MARKERS)


def _slim_market(market: dict[str, Any]) -> dict[str, Any]:
    selections = []
    for selection in market.get("selection") or []:
        if selection.get("displayed") is False:
            continue
        selections.append(
            {
                "type": selection.get("type") or "",
                "name": selection.get("name") or "",
                "rootIdx": selection.get("rootIdx"),
            }
        )
    return {
        "type": market.get("type") or "",
        "name": market.get("name") or "",
        "subtype": market.get("subtype") or "",
        "period": market.get("period") or "",
        "selection": selections,
    }


def build_capture(captured_at: str | None = None) -> dict[str, Any]:
    """Download one NFL board and keep the lines the parser can price."""

    stamp = captured_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ladder = fetch_ladder()
    listing = fetch_event_list()
    events: list[dict[str, Any]] = []
    census: dict[tuple[str, str], dict[str, Any]] = {}
    for item in listing:
        event_id = str(item.get("id") or "")
        if not event_id:
            continue
        full = fetch_event_markets(event_id)
        kept: list[dict[str, Any]] = []
        for market in full.get("markets") or []:
            if not isinstance(market, dict):
                continue
            if market.get("displayed") is False:
                continue
            if str(market.get("state") or "OPEN").upper() not in {"OPEN", ""}:
                continue
            market_type = str(market.get("type") or "")
            period = _period_token(market_type, str(market.get("period") or ""))
            slot = census.get((market_type, period))
            if slot is None:
                census[(market_type, period)] = {
                    "type": market_type,
                    "period": period,
                    "sample_name": str(market.get("name") or ""),
                    "count": 1,
                }
            else:
                slot["count"] += 1
            if _keep_market(market):
                kept.append(_slim_market(market))
        kept.sort(key=lambda market: (market["type"], market["name"], market["subtype"]))
        events.append(
            {
                "id": str(full.get("id") or event_id),
                "name": str(full.get("name") or item.get("name") or ""),
                "eventTime": full.get("eventTime") or item.get("eventTime"),
                "markets": kept,
            }
        )
    events.sort(key=lambda event: (int(event["eventTime"] or 0), event["id"]))
    market_types = [census[key] for key in sorted(census)]
    return {
        "captured_at": stamp,
        "slate_id": SLATE_ID,
        "platform": PLATFORM,
        "competition_id": NFL_COMPETITION_ID,
        "source": GET_EVENTS_URL,
        "ladder": ladder,
        "market_types": market_types,
        "events": events,
    }


def write_capture(path: Path, captured_at: str | None = None) -> dict[str, Any]:
    payload = build_capture(captured_at)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def load_capture(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "events" not in payload or "ladder" not in payload:
        raise ValueError(f"{path} is not a Hard Rock capture")
    return payload


def _moneyline(ladder: dict[str, Any], root_idx: object) -> int | None:
    try:
        index = int(root_idx)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if index < 0:
        return None
    row = ladder.get(str(index))
    if not isinstance(row, dict):
        return None
    text = str(row.get("moneyline") or "").strip()
    if not text:
        return None
    try:
        price = int(round(float(text)))
    except ValueError:
        return None
    if -100 < price < 100 or price == 0:
        return None
    return price


def _line_number(text: str) -> float | None:
    import re

    match = re.search(r"(-?\d+(?:\.\d+)?)", text or "")
    if match is None:
        return None
    return round(float(match.group(1)), 1)


def _subtype_line(subtype: str) -> float | None:
    if "#" not in (subtype or ""):
        return None
    return _line_number(subtype.split("#", 1)[1])


def _nick_to_code() -> dict[str, str]:
    raw = json.loads(read_config_text("nfl_teams.json"))
    out: dict[str, str] = {}
    for full_name, code in raw.items():
        out[str(full_name).lower()] = str(code)
        out[str(full_name).split()[-1].lower()] = str(code)
    return out


def _team_from_label(label: str, nicks: dict[str, str]) -> str:
    text = (label or "").strip()
    for prefix in (
        "1st Half ",
        "2nd Half ",
        "1st Quarter ",
        "2nd Quarter ",
        "3rd Quarter ",
        "4th Quarter ",
    ):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    for suffix in (" Total Points", " Total Rushing Yards"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    if text.lower() in nicks:
        return nicks[text.lower()]
    last = text.split()[-1].lower() if text else ""
    return nicks.get(last, "")


def _side_letter(period: str, subtype: str) -> str:
    for text in (period or "", subtype or ""):
        parts = text.split(":")
        if len(parts) >= 2 and parts[1] in {"A", "B"}:
            return parts[1]
    return ""


def _type_letter(market_type: str) -> str:
    """Read side A or B from a market type such as ``FTOT:A:OU``."""

    for part in str(market_type or "").split(":"):
        if part in {"A", "B"}:
            return part
    return ""


def _period_token(market_type: str, period: str) -> str:
    for token in ("Q1", "Q2", "Q3", "Q4", "H1", "H2"):
        if market_type.endswith(token) or (period or "") == token or (period or "").startswith(token + ":"):
            return token.lower()
    return "game"


def _base_stat(market_type: str, market_name: str) -> str:
    for marker, stat in _STAT_MARKERS:
        if marker in market_type:
            return stat
    if market_type.endswith(":ML"):
        return "moneyline"
    if market_type.endswith(":SPRD"):
        return "spread"
    if market_type.endswith(":OU") and "Total Points" in market_name:
        if _teamish(market_name):
            return "team_total"
        return "total"
    return ""


def _teamish(market_name: str) -> bool:
    text = market_name
    for prefix in (
        "1st Half ",
        "2nd Half ",
        "1st Quarter ",
        "2nd Quarter ",
        "3rd Quarter ",
        "4th Quarter ",
    ):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    if text in {"Total Points", "Spread", "To Win"}:
        return False
    return text.endswith("Total Points") or text.endswith("Total Rushing Yards")


def _stat_token(base: str, period: str) -> str:
    if not base:
        return ""
    if period == "game":
        return base
    return f"{base}_{period}"


def _over_under(selection: dict[str, Any], fallback_line: float | None) -> tuple[str, float] | None:
    raw_type = str(selection.get("type") or "").strip()
    raw_name = str(selection.get("name") or "").strip()
    low = raw_type.lower()
    if low in {"over", "more"} or low.startswith("over"):
        side = "over"
    elif low in {"under", "less"} or low.startswith("under"):
        side = "under"
    else:
        return None
    line = _line_number(raw_type) if low.startswith(("over", "under")) and low not in {"over", "under"} else None
    if line is None:
        line = _line_number(raw_name)
    if line is None:
        line = fallback_line
    if line is None:
        return None
    return side, line


def _blank(payload: dict[str, Any], event: dict[str, Any]) -> dict[str, object]:
    commence = ""
    if event.get("eventTime"):
        commence = datetime.fromtimestamp(int(event["eventTime"]) / 1000, timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    return {
        "slate_id": payload.get("slate_id") or SLATE_ID,
        "platform": PLATFORM,
        "player_name": "",
        "player_key": "",
        "team": "",
        "opp": "",
        "stat_type": "",
        "line": "",
        "side": "more",
        "line_type": "standard",
        "captured_at": payload.get("captured_at") or "",
        "commence_time": commence,
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


def _event_sides(event: dict[str, Any], nicks: dict[str, str]) -> dict[str, str]:
    sides: dict[str, str] = {}
    for market in event.get("markets") or []:
        if "Total Points" not in str(market.get("name") or ""):
            continue
        letter = _side_letter(
            str(market.get("period") or ""), str(market.get("subtype") or "")
        ) or _type_letter(str(market.get("type") or ""))
        code = _team_from_label(str(market.get("name") or ""), nicks)
        if letter and code:
            sides.setdefault(letter, code)
    if "A" in sides and "B" in sides:
        return sides
    # Event names on this board are "<side A nick> vs <side B nick>".
    parts = str(event.get("name") or "").split(" vs ")
    if len(parts) == 2:
        sides.setdefault("A", _team_from_label(parts[0], nicks))
        sides.setdefault("B", _team_from_label(parts[1], nicks))
    return sides


def _pairs_for_market(
    market: dict[str, Any], ladder: dict[str, Any]
) -> list[tuple[float, int, int]]:
    fallback = _subtype_line(str(market.get("subtype") or ""))
    buckets: dict[float, dict[str, int]] = {}
    for selection in market.get("selection") or []:
        parsed = _over_under(selection, fallback)
        if parsed is None:
            continue
        side, line = parsed
        price = _moneyline(ladder, selection.get("rootIdx"))
        if price is None:
            continue
        buckets.setdefault(line, {})[side] = price
    pairs: list[tuple[float, int, int]] = []
    for line, sides in buckets.items():
        if "over" in sides and "under" in sides:
            pairs.append((line, sides["over"], sides["under"]))
    return pairs


def _spread_rows(
    market: dict[str, Any],
    *,
    payload: dict[str, Any],
    event: dict[str, Any],
    sides: dict[str, str],
    ladder: dict[str, Any],
    period: str,
) -> list[dict[str, object]]:
    quotes: dict[str, tuple[str, float, int]] = {}
    for selection in market.get("selection") or []:
        letter = str(selection.get("type") or "")[:1]
        code = sides.get(letter, "")
        price = _moneyline(ladder, selection.get("rootIdx"))
        signed = _line_number(str(selection.get("name") or ""))
        if not code or price is None or signed is None:
            continue
        quotes[code] = (str(selection.get("name") or code), signed, price)
    if len(quotes) < 2:
        return []
    rows: list[dict[str, object]] = []
    codes = sorted(quotes)
    for code in codes:
        other = next(item for item in codes if item != code)
        name, line, price = quotes[code]
        row = _blank(payload, event)
        row["player_name"] = name
        row["player_key"] = fold_name(name)
        row["team"] = code
        row["opp"] = other
        row["stat_type"] = _stat_token("spread", period)
        row["line"] = f"{line:.1f}"
        row["book_over"] = price
        row["book_under"] = quotes[other][2]
        row["leg_odds"] = price
        rows.append(row)
    return rows


def _moneyline_rows(
    market: dict[str, Any],
    *,
    payload: dict[str, Any],
    event: dict[str, Any],
    sides: dict[str, str],
    ladder: dict[str, Any],
    period: str,
) -> list[dict[str, object]]:
    quotes: dict[str, tuple[str, int]] = {}
    for selection in market.get("selection") or []:
        letter = str(selection.get("type") or "")[:1]
        code = sides.get(letter, "")
        price = _moneyline(ladder, selection.get("rootIdx"))
        if not code or price is None:
            continue
        quotes[code] = (str(selection.get("name") or code), price)
    if len(quotes) < 2:
        return []
    rows: list[dict[str, object]] = []
    for code, (name, price) in sorted(quotes.items()):
        other = next(item for item in quotes if item != code)
        row = _blank(payload, event)
        row["player_name"] = name
        row["player_key"] = fold_name(name)
        row["team"] = code
        row["opp"] = other
        row["stat_type"] = _stat_token("moneyline", period)
        row["line"] = "0.0"
        row["book_over"] = price
        row["book_under"] = quotes[other][1]
        row["leg_odds"] = price
        rows.append(row)
    return rows


def _player_name(market_name: str) -> str:
    if " - " not in market_name:
        return ""
    return market_name.split(" - ", 1)[0].strip()


def parse_capture(payload: dict[str, Any]) -> list[dict[str, object]]:
    """Map a capture object onto ``SLATE_FIELDS`` rows.

    One player, stat, and period keeps a single ``standard`` / ``half`` /
    ``quarter`` row: the two-way line whose prices are closest to each other.
    The other lines on that ladder are ``alternate``. Rows are sorted, so the
    same capture bytes produce the same row order.
    """

    ladder = payload.get("ladder") or {}
    nicks = _nick_to_code()
    pending: list[dict[str, object]] = []
    for event in payload.get("events") or []:
        sides = _event_sides(event, nicks)
        for market in event.get("markets") or []:
            market_type = str(market.get("type") or "")
            market_name = str(market.get("name") or "")
            period = _period_token(market_type, str(market.get("period") or ""))
            base = _base_stat(market_type, market_name)
            if base == "spread":
                pending.extend(
                    _spread_rows(
                        market,
                        payload=payload,
                        event=event,
                        sides=sides,
                        ladder=ladder,
                        period=period,
                    )
                )
                continue
            if base == "moneyline":
                pending.extend(
                    _moneyline_rows(
                        market,
                        payload=payload,
                        event=event,
                        sides=sides,
                        ladder=ladder,
                        period=period,
                    )
                )
                continue
            if not base:
                continue
            stat = _stat_token(base, period)
            player = _player_name(market_name)
            letter = _side_letter(str(market.get("period") or ""), str(market.get("subtype") or ""))
            team = sides.get(letter, "")
            if base == "team_total":
                team = _team_from_label(market_name, nicks) or team
                player = market_name
            elif base == "total":
                player = f"{sides.get('A', '')} vs {sides.get('B', '')} total".strip()
                team = sides.get("A", "")
            opp = ""
            if team and sides.get("A") and sides.get("B"):
                opp = sides["B"] if team == sides["A"] else sides["A"]
            for line, over_price, under_price in _pairs_for_market(market, ladder):
                row = _blank(payload, event)
                row["player_name"] = player or market_name
                row["player_key"] = fold_name(str(row["player_name"]))
                row["team"] = team
                row["opp"] = opp
                row["stat_type"] = stat
                row["line"] = f"{line:.1f}"
                row["book_over"] = over_price
                row["book_under"] = under_price
                row["leg_odds"] = over_price
                row["_event_id"] = str(event.get("id") or "")
                pending.append(row)
    _mark_main_lines(pending)
    for row in pending:
        row.pop("_event_id", None)
    pending.sort(
        key=lambda row: (
            str(row.get("commence_time") or ""),
            str(row.get("stat_type") or ""),
            str(row.get("player_key") or ""),
            str(row.get("line") or ""),
            str(row.get("line_type") or ""),
        )
    )
    return [{field: row.get(field, "") for field in SLATE_FIELDS} for row in pending]


def _mark_main_lines(rows: list[dict[str, object]]) -> None:
    groups: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for row in rows:
        if row.get("stat_type") in {"spread", "moneyline"} or str(row.get("stat_type", "")).startswith(
            "spread_"
        ):
            period = "game"
            stat = str(row.get("stat_type") or "")
            if stat != "moneyline" and stat != "spread":
                period = stat.split("_", 1)[1]
            kind = "standard" if period == "game" else ("quarter" if period.startswith("q") else "half")
            # Spreads stay as posted. The closest-to-even line is the main one.
            row["line_type"] = kind
            groups.setdefault(
                (str(row.get("_event_id") or row.get("commence_time")), stat, str(row.get("team") or "")),
                [],
            ).append(row)
            continue
        groups.setdefault(
            (
                str(row.get("_event_id") or ""),
                str(row.get("stat_type") or ""),
                str(row.get("player_key") or ""),
            ),
            [],
        ).append(row)
    for grouped in groups.values():
        ranked: list[tuple[float, float, float, dict[str, object]]] = []
        for row in grouped:
            try:
                over = int(row["book_over"])
                under = int(row["book_under"])
                line = float(row["line"])
            except (TypeError, ValueError):
                row["line_type"] = "alternate"
                continue
            gap = abs(american_to_implied(over) - american_to_implied(under))
            ranked.append((gap, abs(line), line, row))
        if not ranked:
            continue
        ranked.sort(key=lambda item: (item[0], item[1], item[2]))
        main = ranked[0][3]
        stat = str(main.get("stat_type") or "")
        period = "game"
        if "_" in stat and stat.rsplit("_", 1)[1] in {"h1", "h2", "q1", "q2", "q3", "q4"}:
            period = stat.rsplit("_", 1)[1]
        if period == "game":
            main["line_type"] = "standard"
        elif period.startswith("q"):
            main["line_type"] = "quarter"
        else:
            main["line_type"] = "half"
        for _, _, _, row in ranked[1:]:
            row["line_type"] = "alternate"


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SLATE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def inventory_from_rows(rows: list[dict[str, object]]) -> list[dict[str, str]]:
    """One row per posted ``stat_type`` the capture actually priced.

    ``covered`` is a full-game token already in ``LEGAL_MARKETS`` with one
    main line. ``partial`` is that token posted as a ladder of extra lines.
    ``absent`` is a period market or a token ``LEGAL_MARKETS`` does not name.
    The feed is the Hard Rock ``GetEvents`` read. It is ``live`` when this
    capture holds at least one price.
    """

    counts: dict[str, int] = {}
    for row in rows:
        stat = str(row.get("stat_type") or "")
        if stat:
            counts[stat] = counts.get(stat, 0) + 1
    out: list[dict[str, str]] = []
    for stat in sorted(counts):
        base = stat
        period = "game"
        if "_" in stat and stat.rsplit("_", 1)[1] in {"h1", "h2", "q1", "q2", "q3", "q4"}:
            base, period = stat.rsplit("_", 1)
        legal_base = base if base in LEGAL_MARKETS else ""
        if period != "game" or not legal_base:
            # A half or quarter line has no token, even when the full-game
            # family is legal. Fetch never requests it.
            gate = "absent"
        elif counts[stat] > 40:
            # The Odds API client requests one full-game key. A ladder of
            # extra lines is only partly covered.
            gate = "partial"
        else:
            gate = "covered"
        out.append(
            {
                "stat_type": stat,
                "base_stat": base,
                "period": period,
                "rows": str(counts[stat]),
                "repo_gate": gate,
                "legal_token": legal_base,
                "feed": "hardrock_getevents",
                "feed_status": "live",
            }
        )
    return out


INVENTORY_FIELDS = [
    "book_type",
    "sample_name",
    "period",
    "base_stat",
    "stat_type",
    "markets",
    "repo_gate",
    "legal_token",
    "feed",
    "feed_status",
    "odds_api",
]
ROW_INVENTORY_FIELDS = [
    "stat_type",
    "base_stat",
    "period",
    "rows",
    "repo_gate",
    "legal_token",
    "feed",
    "feed_status",
]


def inventory_from_capture(
    payload: dict[str, Any], priced_rows: list[dict[str, object]] | None = None
) -> list[dict[str, str]]:
    """One row per book market type and period on the capture.

    ``covered`` is a full-game token in ``LEGAL_MARKETS`` posted once per
    game. ``partial`` is that token posted as a ladder. ``absent`` is a
    period market or a type ``LEGAL_MARKETS`` does not name. The Odds API
    column is ``absent`` when ``MARKET_TO_STAT`` has no key for it. This
    capture does not call that API, so a mapped full-game stat is
    ``not_fetched``, not live.
    """

    types = payload.get("market_types")
    if not isinstance(types, list) or not types:
        return inventory_from_rows(priced_rows or [])
    from ceminiparlays.odds_api import STAT_TO_MARKET

    n_events = max(1, len(payload.get("events") or []))
    out: list[dict[str, str]] = []
    for item in types:
        if not isinstance(item, dict):
            continue
        market_type = str(item.get("type") or "")
        period = str(item.get("period") or "")
        name = str(item.get("sample_name") or "")
        base = _base_stat(market_type, name)
        stat = _stat_token(base, period) if base else ""
        count = int(item.get("count") or 0)
        legal = base in LEGAL_MARKETS
        if (not legal) or period != "game":
            gate = "absent"
        elif "ALT" in market_type or count > n_events:
            gate = "partial"
        else:
            gate = "covered"
        if period != "game" or base not in STAT_TO_MARKET or "ALT" in market_type:
            odds_api = "absent"
        else:
            odds_api = "not_fetched"
        out.append(
            {
                "book_type": market_type,
                "sample_name": name,
                "period": period,
                "base_stat": base,
                "stat_type": stat,
                "markets": str(count),
                "repo_gate": gate,
                "legal_token": base if legal else "",
                "feed": "hardrock_getevents",
                "feed_status": "live",
                "odds_api": odds_api,
            }
        )
    out.sort(key=lambda row: (row["book_type"], row["period"]))
    return out


def write_inventory(path: Path, rows: list[dict[str, str]]) -> None:
    if rows and "book_type" in rows[0]:
        fields = INVENTORY_FIELDS
    else:
        fields = ROW_INVENTORY_FIELDS
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    """Capture one board, or parse a saved capture twice to the same bytes."""

    parser = argparse.ArgumentParser(prog="python -m ceminiparlays.hardrock_book")
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture", help="Read one NFL board and write JSON")
    capture.add_argument("--out", type=Path, required=True)
    capture.add_argument("--captured-at", default=None)
    parse = sub.add_parser("parse", help="Write slate rows and the market inventory")
    parse.add_argument("--capture", type=Path, required=True)
    parse.add_argument("--rows", type=Path, required=True)
    parse.add_argument("--inventory", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "capture":
        write_capture(args.out, captured_at=args.captured_at)
        print(args.out)
        return 0
    payload = load_capture(args.capture)
    rows = parse_capture(payload)
    write_rows(args.rows, rows)
    write_inventory(args.inventory, inventory_from_capture(payload, rows))
    print(f"rows={len(rows)} inventory={args.inventory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
