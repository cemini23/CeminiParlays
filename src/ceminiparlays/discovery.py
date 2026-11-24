"""Local-first market discovery.

The discovery feed reads snapshot files that another process writes and diffs
them against a persisted state file. It never opens a socket and never places a
bet. The output is a list of net-new series, net-new markets, and RFQ listings.

A snapshot is a CSV with ``venue``, ``series``, ``market_id``, and ``title``.
``ticker`` stands in for ``market_id`` and ``name`` stands in for ``title`` when
the primary column is absent. A row whose ``kind`` is ``series`` declares a
series and is not itself a market.
"""

from __future__ import annotations

import copy
import csv
import json
import os
import re
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from ceminiparlays.book_team import canonical_team
from ceminiparlays.names import fold_name
from ceminiparlays.resources import read_config_text
from ceminiparlays.roster import TEAM_ALIASES, normalize_team

KINDS = frozenset({"series", "listed", "rfq"})
DEFAULT_STATE = {"version": 1, "series": {}, "markets": {}}

_TEAM_SPLIT = re.compile(r"@|/|-|\bvs\b|\bv\b", re.IGNORECASE)
_CELL_SPLIT = re.compile(r"[|;]")
_VENUE_FOLD = re.compile(r"[\s-]+")


@dataclass(frozen=True)
class MarketOffer:
    venue: str
    series: str
    market_id: str
    title: str
    kind: str = "listed"
    teams: tuple[str, ...] = ()
    players: tuple[str, ...] = ()
    opened_at: str = ""


@dataclass(frozen=True)
class DiscoveryAlert:
    kind: str
    key: str
    venue: str
    series: str
    market_id: str
    title: str
    teams: tuple[str, ...]
    players: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class DiscoveryDiff:
    alerts: tuple[DiscoveryAlert, ...]
    state: dict
    new_market_count: int
    rfq_count: int


@lru_cache(maxsize=1)
def _known_codes() -> frozenset[str]:
    """Every club code the alias table and the team-name table can produce."""

    codes = {str(code).strip().upper() for code in TEAM_ALIASES.values()}
    try:
        raw = json.loads(read_config_text("nfl_teams.json"))
    except (FileNotFoundError, ValueError):
        raw = {}
    if isinstance(raw, dict):
        codes.update(str(code).strip().upper() for code in raw.values())
    codes.discard("")
    return frozenset(codes)


def normalize_team_token(text: str) -> str:
    """Map one team token onto an nflverse code, or ``""`` when unknown.

    The alias table runs first, so ``JAC`` becomes ``JAX`` and ``WSH`` becomes
    ``WAS``. The full-name table runs second, so ``Jaguars`` also lands on
    ``JAX``. A token that maps onto no known code is dropped rather than kept.
    """

    raw = (text or "").strip().upper()
    if not raw:
        return ""
    code = canonical_team(normalize_team(raw))
    return code if code in _known_codes() else ""


def parse_teams(text: str) -> tuple[str, ...]:
    """Split one teams cell into sorted, de-duplicated canonical codes."""

    tokens = _TEAM_SPLIT.split(text or "")
    codes = {normalize_team_token(token) for token in tokens}
    codes.discard("")
    return tuple(sorted(codes))


def _fold_venue(venue: str) -> str:
    folded = _VENUE_FOLD.sub("_", (venue or "").strip().lower())
    return folded.strip("_")


def _fold_kind(kind: str) -> str:
    token = (kind or "").strip().lower()
    return token if token in KINDS else "listed"


def _team_codes(tokens: tuple[str, ...]) -> set[str]:
    """Canonical codes for a tuple of team tokens.

    A snapshot cell normally carries one code, but ``teams`` may also hold a
    whole matchup such as ``JAC @ WSH`` in a single token. ``parse_teams``
    splits that case, so an alias spelling still yields the same codes.
    """

    codes: set[str] = set()
    for token in tokens:
        code = normalize_team_token(token)
        if code:
            codes.add(code)
            continue
        codes.update(parse_teams(token))
    codes.discard("")
    return codes


def normalize_offer(offer: MarketOffer) -> MarketOffer:
    """Canonicalize every field that a second source may spell differently."""

    teams = _team_codes(offer.teams)
    players = {fold_name(player) for player in offer.players}
    players.discard("")
    return replace(
        offer,
        venue=_fold_venue(offer.venue),
        series=(offer.series or "").strip().upper(),
        market_id=(offer.market_id or "").strip(),
        title=(offer.title or "").strip(),
        kind=_fold_kind(offer.kind),
        teams=tuple(sorted(teams)),
        players=tuple(sorted(players)),
        opened_at=(offer.opened_at or "").strip(),
    )


def offer_key(offer: MarketOffer) -> str:
    """Stable ``venue|series|market_id`` key after normalization."""

    folded = normalize_offer(offer)
    return f"{folded.venue}|{folded.series}|{folded.market_id}"


def _column(fields: list[str], primary: str, alias: str | None = None) -> str:
    if primary in fields:
        return primary
    if alias is not None and alias in fields:
        return alias
    raise ValueError(f"snapshot missing column: {primary}")


def _cell(raw: dict, column: str) -> str:
    return str(raw.get(column) or "").strip()


def _split_cell(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in _CELL_SPLIT.split(value) if part.strip())


def read_snapshot(path: Path) -> list[MarketOffer]:
    """Read one snapshot CSV. A missing file or column raises."""

    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"snapshot missing: {resolved}")
    offers: list[MarketOffer] = []
    with resolved.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        venue_col = _column(fields, "venue")
        series_col = _column(fields, "series")
        market_col = _column(fields, "market_id", "ticker")
        title_col = _column(fields, "title", "name")
        kind_col = "kind" if "kind" in fields else None
        teams_col = "teams" if "teams" in fields else None
        players_col = "players" if "players" in fields else None
        opened_col = "opened_at" if "opened_at" in fields else None
        for raw in reader:
            offers.append(
                MarketOffer(
                    venue=_cell(raw, venue_col),
                    series=_cell(raw, series_col),
                    market_id=_cell(raw, market_col),
                    title=_cell(raw, title_col),
                    kind=_cell(raw, kind_col) if kind_col else "listed",
                    teams=_split_cell(_cell(raw, teams_col)) if teams_col else (),
                    players=_split_cell(_cell(raw, players_col)) if players_col else (),
                    opened_at=_cell(raw, opened_col) if opened_col else "",
                )
            )
    return offers


def load_state(path: Path) -> dict:
    """Read the persisted state. A missing file starts empty."""

    resolved = Path(path)
    if not resolved.is_file():
        return copy.deepcopy(DEFAULT_STATE)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"state file is not valid JSON: {resolved}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"state file is not a JSON object: {resolved}")
    payload.setdefault("version", 1)
    payload.setdefault("series", {})
    payload.setdefault("markets", {})
    return payload


def _section(state: dict, key: str) -> dict:
    value = state.get(key) if isinstance(state, dict) else None
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _series_message(offer: MarketOffer) -> str:
    parts = ["NEW SERIES", offer.venue, offer.series]
    return " ".join(part for part in parts if part)


def _market_message(offer: MarketOffer) -> str:
    label = "NEW RFQ" if offer.kind == "rfq" else "NEW MARKET"
    parts = [label, offer.venue, offer.series, offer.market_id, offer.title]
    return " ".join(part for part in parts if part)


def _series_alert(offer: MarketOffer) -> DiscoveryAlert:
    return DiscoveryAlert(
        kind="new_series",
        key=f"{offer.venue}|{offer.series}",
        venue=offer.venue,
        series=offer.series,
        market_id="",
        title="",
        teams=(),
        players=(),
        message=_series_message(offer),
    )


def _market_alert(offer: MarketOffer) -> DiscoveryAlert:
    return DiscoveryAlert(
        kind="rfq_market" if offer.kind == "rfq" else "new_market",
        key=offer_key(offer),
        venue=offer.venue,
        series=offer.series,
        market_id=offer.market_id,
        title=offer.title,
        teams=offer.teams,
        players=offer.players,
        message=_market_message(offer),
    )


def diff_feed(
    offers: list[MarketOffer],
    state: dict,
    *,
    seen_at: str | None = None,
) -> DiscoveryDiff:
    """Diff a snapshot against persisted state. Never mutates the input."""

    stamp = seen_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    old_series = _section(state, "series")
    old_markets = _section(state, "markets")
    new_series = copy.deepcopy(old_series)
    new_markets = copy.deepcopy(old_markets)

    normalized: list[MarketOffer] = []
    seen: set[str] = set()
    for offer in offers:
        folded = normalize_offer(offer)
        key = offer_key(folded)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(folded)

    series_alerts: list[DiscoveryAlert] = []
    market_alerts: list[DiscoveryAlert] = []
    for offer in normalized:
        pair = f"{offer.venue}|{offer.series}"
        # Check the accumulating section, not the persisted one: several net-new
        # markets under one brand-new series emit exactly one series alert.
        if pair not in new_series:
            new_series[pair] = {"first_seen": stamp}
            series_alerts.append(_series_alert(offer))
        if offer.kind == "series":
            continue
        key = offer_key(offer)
        if key in old_markets:
            continue
        new_markets[key] = {
            "first_seen": stamp,
            "kind": offer.kind,
            "title": offer.title,
        }
        market_alerts.append(_market_alert(offer))

    series_alerts.sort(key=lambda alert: alert.key)
    market_alerts.sort(key=lambda alert: alert.key)
    alerts = tuple(series_alerts + market_alerts)

    base = copy.deepcopy(state) if isinstance(state, dict) else {}
    base["version"] = state.get("version", 1) if isinstance(state, dict) else 1
    base["series"] = new_series
    base["markets"] = new_markets
    return DiscoveryDiff(
        alerts=alerts,
        state=base,
        new_market_count=len(market_alerts),
        rfq_count=sum(1 for alert in market_alerts if alert.kind == "rfq_market"),
    )


def write_state(path: Path, state: dict) -> None:
    """Write state atomically through a temp file and ``os.replace``."""

    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(state, indent=2, sort_keys=True) + "\n"
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(resolved.parent),
        prefix=f".{resolved.name}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(text)
        os.replace(temp_path, resolved)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def format_alerts(diff: DiscoveryDiff) -> str:
    """One ``DISCOVERY`` line per alert. An empty diff prints ``DISCOVERY none``."""

    if not diff.alerts:
        return "DISCOVERY none"
    lines = []
    for alert in diff.alerts:
        parts = ["DISCOVERY", alert.kind, alert.venue, alert.series, alert.market_id, alert.title]
        lines.append(" ".join(part for part in parts if part))
    return "\n".join(lines)


def summary_payload(diff: DiscoveryDiff) -> dict:
    """JSON-ready summary of one diff."""

    return {
        "new_series": sum(1 for alert in diff.alerts if alert.kind == "new_series"),
        "new_markets": diff.new_market_count,
        "rfq": diff.rfq_count,
        "alerts": [
            {
                "kind": alert.kind,
                "key": alert.key,
                "venue": alert.venue,
                "series": alert.series,
                "market_id": alert.market_id,
                "title": alert.title,
                "teams": list(alert.teams),
                "players": list(alert.players),
                "message": alert.message,
            }
            for alert in diff.alerts
        ],
    }
