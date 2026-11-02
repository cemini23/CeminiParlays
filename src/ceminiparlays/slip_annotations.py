"""The 200-slip hand annotation.

Each slip is pasted text plus gold labels. The labels follow the rubric in
``gold_risk_band``. The sample date is 2026-11-01. The text is constructed.
It is not a live sportsbook capture and it is not a model output.

``gold_risk_band`` labels the sample. The live screen does not call it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ceminiparlays.numbered_span import tokenize
from ceminiparlays.slip_screen import (
    CORRELATION_LABELS,
    MARKET_LABELS,
    SAMPLE_DATE,
    format_implied,
)

GAMES = (
    ("BUF", "KC"),
    ("BAL", "CIN"),
    ("PHI", "DAL"),
    ("SF", "SEA"),
    ("DET", "MIN"),
    ("ATL", "MIA"),
)
ROSTER = {
    "KC": ("Patrick Mahomes", "Travis Kelce"),
    "BUF": ("Josh Allen", "James Cook"),
    "BAL": ("Lamar Jackson", "Derrick Henry"),
    "CIN": ("Joe Burrow", "Ja'Marr Chase"),
    "PHI": ("Jalen Hurts", "Saquon Barkley"),
    "DAL": ("Dak Prescott", "CeeDee Lamb"),
    "SF": ("Brock Purdy", "Christian McCaffrey"),
    "SEA": ("Geno Smith", "DK Metcalf"),
    "DET": ("Jared Goff", "Amon-Ra St. Brown"),
    "MIN": ("Justin Jefferson", "Jordan Addison"),
    "ATL": ("Bijan Robinson", "Drake London"),
    "MIA": ("Tyreek Hill", "De'Von Achane"),
}
PROP_MARKETS = ("pass_yds", "rush_yds", "rec_yds", "receptions", "anytime_td")
PHRASES = {
    "pass_yds": "pass yds",
    "rush_yds": "rush yds",
    "rec_yds": "rec yds",
    "receptions": "receptions",
    "anytime_td": "anytime td",
    "spread": "spread",
    "total": "total",
    "moneyline": "moneyline",
}
LINES = {
    "pass_yds": ("224.5", "249.5", "267.5", "274.5", "289.5"),
    "rush_yds": ("54.5", "68.5", "79.5", "86.5", "99.5"),
    "rec_yds": ("42.5", "58.5", "71.5", "84.5", "96.5"),
    "receptions": ("3.5", "4.5", "5.5", "6.5", "7.5"),
    "spread": ("-2.5", "-3.5", "-6.5", "+3.5", "+7.5"),
    "total": ("41.5", "44.5", "46.5", "48.5", "51.5"),
}
NO_LINE = frozenset({"anytime_td", "moneyline"})
ODDS = (
    "-135",
    "-125",
    "-120",
    "-115",
    "-110",
    "-105",
    "+100",
    "+110",
    "+125",
    "+140",
)
PARLAY_PRICES = (
    "+180",
    "+245",
    "+265",
    "+310",
    "+420",
    "+455",
    "+560",
    "+640",
    "+780",
    "+920",
    "+1100",
    "+1250",
    "+1400",
    "+1650",
    "+1800",
    "+2100",
    "+2400",
    "+2750",
)


def gold_risk_band(leg_count: int, correlation: str) -> str:
    """Annotation rubric for the 2026-11-01 sample.

    Five ordered levels. The first match wins. This function labels the
    frozen sample. It is not a cutoff and it does not label a live slip.
    """

    if leg_count >= 5:
        return "long"
    if correlation == "same_player":
        return "same_player"
    if correlation == "same_game":
        return "same_game"
    if leg_count >= 3:
        return "short_stack"
    return "plain"


def correlation_of(legs: list[dict[str, Any]]) -> str:
    players = [leg["player"] for leg in legs if leg["player"]]
    games = [leg["game"] for leg in legs]
    if len(players) != len(set(players)):
        return "same_player"
    if len(games) != len(set(games)):
        return "same_game"
    return "independent"


def build_annotated_slips() -> list[dict[str, Any]]:
    """Return the 200 gold slips. The builder is deterministic."""

    slips: list[dict[str, Any]] = []

    def push(legs: list[dict[str, Any]]) -> None:
        slips.append(_render(len(slips) + 1, legs))

    for i in range(40):
        first = GAMES[i % len(GAMES)]
        second = GAMES[(i + 2) % len(GAMES)]
        if i % 5 == 0:
            legs = [_spread_leg(first, 0, i), _prop_leg(second, 0, 0, "rec_yds", i + 1)]
        elif i % 5 == 1:
            legs = [_total_leg(first, i), _moneyline_leg(second, 1, i + 3)]
        else:
            market_a = PROP_MARKETS[i % len(PROP_MARKETS)]
            market_b = PROP_MARKETS[(i + 2) % len(PROP_MARKETS)]
            legs = [
                _prop_leg(
                    first,
                    0,
                    0,
                    market_a,
                    i,
                    under=i % 2 == 0 and market_a != "anytime_td",
                ),
                _prop_leg(second, 1, 1, market_b, i + 4),
            ]
        if i in (3, 13, 23) and legs[0]["line"] is not None:
            legs[0]["line"] = "115.5"
            legs[0]["odds"] = "-115"
        push(legs)

    for i in range(40):
        count = 3 if i < 20 else 4
        legs = []
        for k in range(count):
            market = PROP_MARKETS[(i + k) % len(PROP_MARKETS)]
            legs.append(
                _prop_leg(GAMES[(i + k) % len(GAMES)], k % 2, 0, market, i + 7 * k)
            )
        push(legs)

    people = ((0, 0), (0, 1), (1, 0), (1, 1))
    for i in range(40):
        game = GAMES[i % len(GAMES)]
        count = 2 if i < 20 else (3 if i < 30 else 4)
        legs = []
        for k in range(count):
            team_index, roster_index = people[k]
            market = PROP_MARKETS[(i + k) % len(PROP_MARKETS)]
            legs.append(_prop_leg(game, team_index, roster_index, market, i + 3 * k))
        push(legs)

    for i in range(40):
        game = GAMES[i % len(GAMES)]
        legs = [
            _prop_leg(game, 0, 0, "pass_yds", i),
            _prop_leg(game, 0, 0, "rush_yds", i + 5),
        ]
        if i >= 20:
            legs.append(_prop_leg(game, 0, 1, "receptions", i + 9))
        push(legs)

    for i in range(40):
        if i < 20:
            count = 5 if i < 10 else 6
            legs = []
            for k in range(count):
                market = PROP_MARKETS[(i + k) % len(PROP_MARKETS)]
                legs.append(_prop_leg(GAMES[k], 0, i % 2, market, i + k))
            push(legs)
            continue
        if i < 30:
            legs = [
                _prop_leg(GAMES[0], 0, 0, "pass_yds", i),
                _prop_leg(GAMES[0], 1, 0, "rec_yds", i + 2),
            ]
            for k, game in enumerate(GAMES[1:4]):
                legs.append(_prop_leg(game, 0, 0, PROP_MARKETS[k], i + 4 + k))
            push(legs)
            continue
        legs = [
            _prop_leg(GAMES[1], 0, 0, "pass_yds", i),
            _prop_leg(GAMES[1], 0, 0, "rush_yds", i + 1),
        ]
        for k, game in enumerate(GAMES[2:5]):
            legs.append(_prop_leg(game, 1, 1, PROP_MARKETS[k + 1], i + 3 + k))
        push(legs)

    if len(slips) != 200:
        raise RuntimeError(f"annotated set has {len(slips)} slips")
    for slip in slips:
        validate_annotation(slip)
    return slips


def validate_annotation(slip: dict[str, Any]) -> None:
    text = slip["text"]
    if slip["sample_date"] != SAMPLE_DATE:
        raise ValueError("sample date is not 2026-11-01")
    if "END_SLIP_TEXT" in text:
        raise ValueError("slip text contains the state marker")
    count = int(slip["leg_count"])
    if str(count) != slip["leg_count"] or count != len(slip["markets"]):
        raise ValueError("leg count does not match the market list")
    if slip["correlation"] not in CORRELATION_LABELS:
        raise ValueError("correlation label is outside the set")
    if gold_risk_band(count, slip["correlation"]) != slip["risk_band"]:
        raise ValueError(f"{slip['id']} risk band does not match the rubric")
    for market in slip["markets"]:
        if market not in MARKET_LABELS or market == "absent":
            raise ValueError("market label is outside the set")
    spans = slip["spans"]
    if "parlay_odds" not in spans:
        raise ValueError("missing parlay odds")
    tokens = tokenize(text)
    for name, span in spans.items():
        start = span["start"]
        end = span["end"]
        value = span["value"]
        if text[start:end] != value:
            raise ValueError(f"{slip['id']} {name} breaks the slice invariant")
        if span["start_index"] != span["end_index"]:
            raise ValueError("annotated price spans are one token")
        token = tokens[span["start_index"]]
        if token.start != start or token.end != end or token.text != value:
            raise ValueError(f"{name} index does not match the slice")
        if name.endswith("_odds"):
            format_implied(value)
    if format_implied(spans["parlay_odds"]["value"]) != slip["implied_probability"]:
        raise ValueError("implied probability does not match the parlay token")


def load_annotated(path: Path) -> list[dict[str, Any]]:
    slips = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(slips, list):
        raise ValueError("annotated file must be a list")
    for slip in slips:
        validate_annotation(slip)
    return slips


class _Text:
    def __init__(self) -> None:
        self._parts: list[str] = []

    def add(self, piece: str) -> tuple[int, int]:
        start = sum(len(part) for part in self._parts)
        self._parts.append(piece)
        return start, start + len(piece)

    def text(self) -> str:
        return "".join(self._parts)


def _game_label(game: tuple[str, str]) -> str:
    return f"{game[0]}@{game[1]}"


def _odds_for(salt: int, line: str | None) -> str:
    odds = ODDS[salt % len(ODDS)]
    if line is not None and odds == line:
        odds = ODDS[(salt + 1) % len(ODDS)]
    return odds


def _prop_leg(
    game: tuple[str, str],
    team_index: int,
    roster_index: int,
    market: str,
    salt: int,
    *,
    under: bool = False,
) -> dict[str, Any]:
    team = game[team_index]
    player = ROSTER[team][roster_index]
    line = None if market in NO_LINE else LINES[market][salt % len(LINES[market])]
    side = None if line is None else ("Under" if under else "Over")
    return {
        "player": player,
        "subject": player,
        "market": market,
        "phrase": PHRASES[market],
        "side": side,
        "line": line,
        "odds": _odds_for(salt, line),
        "game": _game_label(game),
    }


def _spread_leg(game: tuple[str, str], team_index: int, salt: int) -> dict[str, Any]:
    team = game[team_index]
    line = LINES["spread"][salt % len(LINES["spread"])]
    return {
        "player": None,
        "subject": team,
        "market": "spread",
        "phrase": "spread",
        "side": None,
        "line": line,
        "odds": _odds_for(salt, line),
        "game": _game_label(game),
    }


def _total_leg(game: tuple[str, str], salt: int) -> dict[str, Any]:
    line = LINES["total"][salt % len(LINES["total"])]
    return {
        "player": None,
        "subject": "total",
        "market": "total",
        "phrase": "total",
        "side": "Over",
        "line": line,
        "odds": _odds_for(salt + 2, line),
        "game": _game_label(game),
    }


def _moneyline_leg(
    game: tuple[str, str],
    team_index: int,
    salt: int,
) -> dict[str, Any]:
    return {
        "player": None,
        "subject": game[team_index],
        "market": "moneyline",
        "phrase": "moneyline",
        "side": None,
        "line": None,
        "odds": _odds_for(salt + 4, None),
        "game": _game_label(game),
    }


def _parlay_price(number: int, legs: list[dict[str, Any]]) -> str:
    used = {leg["odds"] for leg in legs}
    for shift in range(len(PARLAY_PRICES)):
        price = PARLAY_PRICES[(number + shift) % len(PARLAY_PRICES)]
        if price not in used:
            return price
    raise RuntimeError("no parlay price is free of the leg prices")


def _render(number: int, legs: list[dict[str, Any]]) -> dict[str, Any]:
    slip_id = f"s{number:03d}"
    parlay = _parlay_price(number, legs)
    buf = _Text()
    buf.add(f"SLIP {slip_id}\n")
    char_spans: dict[str, tuple[int, int, str]] = {}
    for index, leg in enumerate(legs, start=1):
        buf.add(f"LEG {index} ")
        buf.add(leg["subject"])
        if leg["phrase"] and leg["phrase"] != leg["subject"]:
            buf.add(" ")
            buf.add(leg["phrase"])
        if leg["side"]:
            buf.add(" ")
            buf.add(leg["side"])
        if leg["line"] is not None:
            buf.add(" ")
            start, end = buf.add(leg["line"])
            char_spans[f"leg{index}_line"] = (start, end, leg["line"])
        buf.add(" ")
        start, end = buf.add(leg["odds"])
        char_spans[f"leg{index}_odds"] = (start, end, leg["odds"])
        buf.add(f" game {leg['game']}\n")
    buf.add("Parlay ")
    start, end = buf.add(parlay)
    char_spans["parlay_odds"] = (start, end, parlay)
    buf.add("\nboard -110\n")
    text = buf.text()
    tokens = tokenize(text)
    spans: dict[str, dict[str, Any]] = {}
    for name, (start, end, value) in char_spans.items():
        matched = [token for token in tokens if token.start == start and token.end == end]
        if len(matched) != 1 or text[start:end] != value:
            raise RuntimeError(f"{slip_id} {name} is not one source token")
        token = matched[0]
        spans[name] = {
            "start_index": token.index,
            "end_index": token.index,
            "start": start,
            "end": end,
            "value": value,
        }
    correlation = correlation_of(legs)
    return {
        "id": slip_id,
        "sample_date": SAMPLE_DATE,
        "text": text,
        "leg_count": str(len(legs)),
        "markets": [leg["market"] for leg in legs],
        "correlation": correlation,
        "risk_band": gold_risk_band(len(legs), correlation),
        "implied_probability": format_implied(parlay),
        "spans": spans,
    }


def write_annotated(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(build_annotated_slips(), indent=2) + "\n",
        encoding="utf-8",
    )
