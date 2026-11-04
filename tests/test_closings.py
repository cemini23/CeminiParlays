from pathlib import Path

from ceminiparlays.closings import PROP_CLOSE_FIELDS, read_prop_closes, write_prop_closes

CLOSE_ROW = {
    "platform": "hardrock",
    "player_key": "alpha",
    "stat_type": "pass_yds",
    "side": "more",
    "line": 252.5,
    "over": -150,
    "under": 130,
    "captured_at": "2026-11-03T12:00:00Z",
}


def test_write_prop_closes_writes_the_fixed_header(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "closes.csv"
    write_prop_closes(path, [CLOSE_ROW])
    assert path.read_text(encoding="utf-8").splitlines()[0] == ",".join(PROP_CLOSE_FIELDS)


def test_write_prop_closes_round_trips_through_the_reader(tmp_path: Path) -> None:
    path = tmp_path / "closes.csv"
    write_prop_closes(path, [CLOSE_ROW])
    closes = read_prop_closes(path)
    close = closes[("hardrock", "alpha", "pass_yds", "more")]
    assert close.line == 252.5
    assert close.over == -150
    assert close.under == 130


def test_write_prop_closes_writes_the_header_when_there_are_no_rows(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    write_prop_closes(path, [])
    assert path.read_text(encoding="utf-8").strip() == ",".join(PROP_CLOSE_FIELDS)
