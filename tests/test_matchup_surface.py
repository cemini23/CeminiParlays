"""The Hard Rock surface report: what the book posts, and what it does not."""

import json
from pathlib import Path

from ceminiparlays.matchup_surface import FIELDS, classify, load_types, write_surface


def test_classify_marks_every_catalog_key_absent_without_a_census() -> None:
    rows = classify([])
    assert rows
    assert all(row["feed_status"] == "absent" for row in rows)
    assert all(row["feed"] == "none" for row in rows)
    assert set(rows[0]) == set(FIELDS)


def test_classify_marks_a_matching_market_live_and_sums_the_count() -> None:
    types = [
        {"type": "PROPPSATT", "period": "game", "count": 4},
        {"type": "PROPPSATT", "period": "game", "markets": 6},
    ]
    rows = {row["catalog_key"]: row for row in classify(types)}
    row = rows["player_pass_attempts"]
    assert row["feed_status"] == "live"
    assert row["feed"] == "hardrock_getevents"
    assert row["book_markets"] == "10"


def test_load_types_reads_a_json_document(tmp_path: Path) -> None:
    path = tmp_path / "types.json"
    path.write_text(json.dumps({"market_types": [{"type": "X"}, "bad"]}), encoding="utf-8")
    assert load_types(path) == [{"type": "X"}]


def test_load_types_reads_a_csv(tmp_path: Path) -> None:
    path = tmp_path / "types.csv"
    path.write_text("type,period,count\nA,game,2\n", encoding="utf-8")
    assert load_types(path) == [{"type": "A", "period": "game", "count": "2"}]


def test_write_surface_writes_the_fixed_header(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "surface.csv"
    write_surface(path, [dict.fromkeys(FIELDS, "")])
    assert path.read_text(encoding="utf-8").splitlines()[0] == ",".join(FIELDS)
