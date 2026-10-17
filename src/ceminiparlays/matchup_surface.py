"""Map the expanded market list to the feed that actually posts it.

``the_odds_api`` is ``not_fetched`` only when this repo's client already has
the full-game key. This module does not call that API. A key it does not
name is ``absent``. Hard Rock status comes from the capture census.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from ceminiparlays.odds_api import MARKET_TO_STAT

# (catalog key, stat token, period, book marker, odds-api key or "")
# Marker match is a substring of the book type. Period ``game`` ignores quarter types.
SURFACE = (
    ("player_pass_attempts", "pass_attempts", "game", "PROPPSATT", ""),
    ("player_pass_completions", "pass_completions", "game", "PROPPSCMP", ""),
    ("player_pass_interceptions", "interceptions", "game", "PROPINT", ""),
    ("player_rush_attempts", "rush_att", "game", "PROPRSATT", "player_rush_attempts"),
    ("player_rush_reception_yds", "rush_rec_yds", "game", "PROPRSPRCYDS", ""),
    ("player_rush_reception_tds", "rush_rec_tds", "game", "PROPRSPRCTD", ""),
    ("player_sacks", "sacks", "game", "PROPSACKS", ""),
    ("player_solo_tackles", "solo_tackles", "game", "PROPTACKLES", ""),
    ("player_tackles_assists", "tackles_assists", "game", "PROPTACKLES", ""),
    ("player_reception_longest", "rec_longest", "game", "PROPLNGREC", ""),
    ("player_rush_longest", "rush_longest", "game", "PROPLNGRS", ""),
    ("player_pass_longest_completion", "pass_longest", "game", "PROPLNGPSCMP", ""),
    ("player_kicking_points", "kicking_points", "game", "PROPKPT", ""),
    ("player_field_goals", "field_goals", "game", "PROPFGM", ""),
    ("player_pats", "extra_points", "game", "PROPEXTPTM", ""),
    ("h2h_q1", "moneyline_q1", "q1", ":ML", ""),
    ("h2h_q2", "moneyline_q2", "q2", ":ML", ""),
    ("h2h_q3", "moneyline_q3", "q3", ":ML", ""),
    ("h2h_q4", "moneyline_q4", "q4", ":ML", ""),
    ("h2h_h1", "moneyline_h1", "h1", ":ML", ""),
    ("h2h_h2", "moneyline_h2", "h2", ":ML", ""),
    ("spreads_q1", "spread_q1", "q1", ":SPRD", ""),
    ("spreads_q2", "spread_q2", "q2", ":SPRD", ""),
    ("spreads_q3", "spread_q3", "q3", ":SPRD", ""),
    ("spreads_q4", "spread_q4", "q4", ":SPRD", ""),
    ("spreads_h1", "spread_h1", "h1", ":SPRD", ""),
    ("spreads_h2", "spread_h2", "h2", ":SPRD", ""),
    ("totals_q1", "total_q1", "q1", ":OU", ""),
    ("totals_q2", "total_q2", "q2", ":OU", ""),
    ("totals_q3", "total_q3", "q3", ":OU", ""),
    ("totals_q4", "total_q4", "q4", ":OU", ""),
    ("totals_h1", "total_h1", "h1", ":OU", ""),
    ("totals_h2", "total_h2", "h2", ":OU", ""),
    ("team_totals", "team_total", "game", ":OU", ""),
    ("player_1st_td", "first_td", "game", "PROP1STTD", "player_1st_td"),
    ("player_last_td", "last_td", "game", "PROPLSTTD", ""),
)
_PARTIAL = {"player_solo_tackles", "player_tackles_assists"}
FIELDS = [
    "catalog_key",
    "stat_token",
    "period",
    "feed",
    "feed_status",
    "odds_api",
    "book_markets",
    "note",
]


def _hits(types: list[dict], marker: str, period: str) -> list[dict]:
    found = []
    for item in types:
        market_type = str(item.get("type") or item.get("book_type") or "")
        item_period = str(item.get("period") or "")
        if period and item_period != period:
            continue
        if marker and marker not in market_type:
            continue
        if not marker:
            name = str(item.get("sample_name") or "").lower()
            kind = market_type.upper()
            if "RUSH+REC" in name.upper() or "RSPR" in kind or "SCRIMMAGE" in kind:
                found.append(item)
            continue
        found.append(item)
    return found


def classify(types: list[dict]) -> list[dict[str, str]]:
    """One row per catalog key. Counts are the sum of matching census rows."""

    rows = []
    for key, stat, period, marker, odds_key in SURFACE:
        hits = _hits(types, marker, period if key != "team_totals" else "")
        if key == "team_totals":
            hits = [
                item
                for item in hits
                if "total points" in str(item.get("sample_name") or "").lower()
                and str(item.get("sample_name") or "").lower()
                not in {"total points", "1st half total points", "2nd half total points"}
            ]
        count = sum(int(item.get("count") or item.get("markets") or 0) for item in hits)
        if key in _PARTIAL and hits:
            status = "partial"
            note = "book posts combined tackles, not solo versus assists"
        elif key.startswith("player_rush_reception") and not hits:
            status = "absent"
            note = "no rush-plus-reception type in this census"
        elif hits:
            status = "live"
            note = ""
        else:
            status = "absent"
            note = "not in the Hard Rock census"
        if odds_key and odds_key in MARKET_TO_STAT and period == "game":
            odds_api = "not_fetched"
        else:
            odds_api = "absent"
        feed = "hardrock_getevents" if hits else "none"
        rows.append(
            {
                "catalog_key": key,
                "stat_token": stat,
                "period": period,
                "feed": feed,
                "feed_status": status,
                "odds_api": odds_api,
                "book_markets": str(count),
                "note": note,
            }
        )
    return rows


def load_types(path: Path) -> list[dict]:
    if path.suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        types = payload.get("market_types") or []
        return [item for item in types if isinstance(item, dict)]
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_surface(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ceminiparlays.matchup_surface")
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = classify(load_types(args.capture))
    write_surface(args.out, rows)
    live = sum(1 for row in rows if row["feed_status"] == "live")
    partial = sum(1 for row in rows if row["feed_status"] == "partial")
    absent = sum(1 for row in rows if row["feed_status"] == "absent")
    print(f"surface={len(rows)} live={live} partial={partial} absent={absent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
