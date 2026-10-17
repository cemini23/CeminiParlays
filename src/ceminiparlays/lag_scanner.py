"""Scan captures for derivative markets that lag their anchor.

A derivative market is a key of ``ANCHOR`` in
``ceminiparlays.matchup_math``; its anchor stat and elasticity share come
from that table. When the anchor line runs and the derivative line does
not follow its locked elasticity share, and the leg is +EV after vig in
the supplied legs file, the row is written to the report CSV.

Without ``--legs`` there is no EV, so nothing is flagged: this module
never invents an edge. It reads two captures, writes one CSV, and places
no bet.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from ceminiparlays.matchup_math import ANCHOR, LAG_ELASTIC_SHARE, LAG_IMPLIED, LAG_YARDS
from ceminiparlays.odds import american_to_implied

MAIN_LINE_TYPES = frozenset({"standard", "half", "quarter"})
REQUIRED_COLUMNS = ("stat_type", "player_key", "line", "book_over", "book_under", "commence_time")
REQUIRED_LEG_COLUMNS = ("market", "player_key", "line", "ev")
EV_THRESHOLD = 0.02
OUTPUT_FIELDS = [
    "player_key",
    "market",
    "anchor",
    "anchor_move",
    "derivative_move",
    "theoretical_move",
    "ev",
    "commence_time",
]
row_key = tuple[str, str, str]  # commence_time, player_key, stat_type


def _price(value: object) -> int | None:
    try:
        price = int(round(float(str(value))))
    except (TypeError, ValueError):
        return None
    if -100 < price < 100 or price == 0:
        return None
    return price


def _line_value(value: object) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _format_line(value: float) -> str:
    return f"{value:.1f}"


def _implied_gap(row: dict[str, str]) -> float:
    over = _price(row.get("book_over"))
    under = _price(row.get("book_under"))
    if over is None or under is None:
        return float("inf")
    return abs(american_to_implied(over) - american_to_implied(under))


def _load_rows(path: Path) -> list[dict[str, str]]:
    """Read one capture path: a Hard Rock JSON capture or a slate CSV."""

    if path.suffix.lower() == ".json":
        from ceminiparlays.hardrock_book import load_capture, parse_capture

        parsed = parse_capture(load_capture(path))
    else:
        with path.open("r", encoding="utf-8", newline="") as handle:
            parsed = list(csv.DictReader(handle))
    rows: list[dict[str, str]] = []
    for raw in parsed:
        row = {str(key): str("" if value is None else value) for key, value in raw.items()}
        missing = [column for column in REQUIRED_COLUMNS if not row.get(column)]
        if missing:
            raise ValueError(f"{path} is missing required columns: {', '.join(missing)}")
        rows.append(row)
    return rows


def _load_legs(path: Path) -> dict[tuple[str, str, str], float]:
    """Index the legs file by (market, player_key, line)."""

    legs: dict[tuple[str, str, str], float] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            row = {str(key): str("" if value is None else value) for key, value in raw.items()}
            missing = [column for column in REQUIRED_LEG_COLUMNS if not row.get(column)]
            if missing:
                raise ValueError(f"{path} is missing required columns: {', '.join(missing)}")
            market = row["market"]
            if market not in ANCHOR:
                continue
            key = (market, row["player_key"], _format_line(_line_value(row["line"])))
            value = _line_value(row["ev"])
            if key not in legs:
                legs[key] = value
    return legs


def main_rows(rows: list[dict[str, str]]) -> dict[row_key, dict[str, str]]:
    """Keep one main line per (commence_time, player_key, stat_type).

    A ``line_type`` column restricts rows to ``standard`` / ``half`` /
    ``quarter``. When it is absent, the row with the smallest gap between
    its over and under implied probabilities wins.
    """

    has_line_types = any("line_type" in row for row in rows)
    groups: dict[row_key, list[dict[str, str]]] = {}
    for row in rows:
        if has_line_types and row.get("line_type") not in MAIN_LINE_TYPES:
            continue
        if _price(row.get("book_over")) is None or _price(row.get("book_under")) is None:
            continue
        key = (row["commence_time"], row["player_key"], row["stat_type"])
        groups.setdefault(key, []).append(row)
    mains: dict[row_key, dict[str, str]] = {}
    for key, candidates in groups.items():
        mains[key] = min(
            candidates,
            key=lambda row: (_implied_gap(row), abs(_line_value(row["line"])), row["line"]),
        )
    return mains


def scan(
    prev_rows: list[dict[str, str]],
    curr_rows: list[dict[str, str]],
    legs: dict[tuple[str, str, str], float] | None = None,
) -> list[dict[str, object]]:
    """Flag derivative legs that lag a moved anchor and carry a real EV."""

    prev_mains = main_rows(prev_rows)
    curr_mains = main_rows(curr_rows)
    ev_map = legs or {}
    flags: list[tuple[tuple[str, str, float], dict[str, object]]] = []
    for curr_key, curr_row in curr_mains.items():
        market = curr_key[2]
        if market not in ANCHOR:
            continue
        anchor_stat, elasticity = ANCHOR[market]
        anchor_key = (curr_key[0], curr_key[1], anchor_stat)
        prev_derivative = prev_mains.get(curr_key)
        prev_anchor = prev_mains.get(anchor_key)
        curr_anchor = curr_mains.get(anchor_key)
        if prev_derivative is None or prev_anchor is None or curr_anchor is None:
            continue
        anchor_move = _line_value(curr_anchor["line"]) - _line_value(prev_anchor["line"])
        prev_over, curr_over = _price(prev_anchor["book_over"]), _price(curr_anchor["book_over"])
        if prev_over is None or curr_over is None:
            continue
        implied_move = american_to_implied(curr_over) - american_to_implied(prev_over)
        if abs(anchor_move) < LAG_YARDS and abs(implied_move) < LAG_IMPLIED:
            continue
        if anchor_move != 0.0:
            theoretical_move = elasticity * anchor_move
        elif implied_move > 0:
            theoretical_move = elasticity * LAG_YARDS
        else:
            theoretical_move = -elasticity * LAG_YARDS
        derivative_move = _line_value(curr_row["line"]) - _line_value(prev_derivative["line"])
        if abs(derivative_move) >= LAG_ELASTIC_SHARE * abs(theoretical_move):
            continue
        ev = ev_map.get((market, curr_key[1], _format_line(_line_value(curr_row["line"]))))
        if ev is None or ev < EV_THRESHOLD:
            continue
        flags.append(
            (
                (market, curr_key[1], _line_value(curr_row["line"])),
                {
                    "player_key": curr_key[1],
                    "market": market,
                    "anchor": anchor_stat,
                    "anchor_move": f"{anchor_move:.1f}",
                    "derivative_move": f"{derivative_move:.1f}",
                    "theoretical_move": f"{theoretical_move:.2f}",
                    "ev": f"{ev:.4f}",
                    "commence_time": curr_key[0],
                },
            )
        )
    flags.sort(key=lambda item: item[0])
    return [report for _, report in flags]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ceminiparlays.lag_scanner")
    parser.add_argument("--prev-capture", type=Path, required=True)
    parser.add_argument("--curr-capture", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--legs", type=Path, default=None)
    args = parser.parse_args(argv)

    leg_rows: dict[tuple[str, str, str], float] = {}
    prev_rows = _load_rows(args.prev_capture)
    curr_rows = _load_rows(args.curr_capture)
    if args.legs is not None:
        leg_rows = _load_legs(args.legs)
    report = scan(prev_rows, curr_rows, leg_rows)
    if args.out.parent and not args.out.parent.exists():
        args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(report)
    print(f"flag_count={len(report)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
