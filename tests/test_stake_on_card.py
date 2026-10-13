"""The stake decision is recorded on the card."""

import json
from pathlib import Path

from ceminiparlays.cli import main

LINE_COLUMNS = [
    "slate_id",
    "platform",
    "player_name",
    "player_key",
    "team",
    "opp",
    "stat_type",
    "line",
    "side",
    "line_type",
    "captured_at",
    "injury_status",
    "book_over",
    "book_under",
    "slip_multiplier",
    "book_line",
]
DIST_HEADER = "player_name,player_key,stat_type,median,sd,family\n"


def _row(**overrides: str) -> str:
    row = {
        "slate_id": "s",
        "platform": "",
        "player_name": "P",
        "player_key": "",
        "team": "AAA",
        "opp": "BBB",
        "stat_type": "pass_yds",
        "line": "250.5",
        "side": "more",
        "line_type": "standard",
        "captured_at": "",
        "injury_status": "",
        "book_over": "-110",
        "book_under": "-110",
        "slip_multiplier": "",
        "book_line": "",
    }
    row.update(overrides)
    return ",".join(row[column] for column in LINE_COLUMNS) + "\n"


def _fixtures(tmp_path: Path) -> tuple[Path, Path]:
    lines = tmp_path / "lines.csv"
    lines.write_text(
        ",".join(LINE_COLUMNS)
        + "\n"
        + _row(player_key="a", team="AAA", opp="BBB")
        + _row(player_key="b", team="CCC", opp="DDD", stat_type="rush_yds", line="80.5"),
        encoding="utf-8",
    )
    dists = tmp_path / "distributions.csv"
    dists.write_text(
        DIST_HEADER + "Alpha,a,pass_yds,320,40,lognormal\nBravo,b,rush_yds,110,15,lognormal\n",
        encoding="utf-8",
    )
    return lines, dists


def _compose(tmp_path: Path, lines: Path, dists: Path, extra: list[str]) -> dict:
    out_dir = tmp_path / "compose"
    code = main(
        [
            "compose",
            "--lines",
            str(lines),
            "--distributions",
            str(dists),
            "--no-roster",
            "--legs",
            "2",
            "--n-tickets",
            "1",
            "--out-dir",
            str(out_dir),
            *extra,
        ]
    )
    assert code == 0
    return json.loads((out_dir / "card.json").read_text(encoding="utf-8"))


def test_stake_is_recorded_and_capped_at_five_percent(tmp_path: Path, capsys) -> None:
    lines, dists = _fixtures(tmp_path)
    payload = _compose(tmp_path, lines, dists, ["--bankroll", "100"])
    capsys.readouterr()
    stake = payload["tickets"][0]["stake"]
    assert stake is not None
    assert 0.0 <= stake <= 5.0
    assert payload["stake_rule"] == "quarter-kelly 5% cap"
    assert payload["bankroll"] == 100.0


def test_no_bankroll_records_no_stake(tmp_path: Path, capsys) -> None:
    lines, dists = _fixtures(tmp_path)
    payload = _compose(tmp_path, lines, dists, [])
    capsys.readouterr()
    assert payload["tickets"][0]["stake"] is None
    assert payload["stake_rule"] == "no-bankroll"
    assert payload["bankroll"] is None
