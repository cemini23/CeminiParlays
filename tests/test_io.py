from pathlib import Path

import pytest

from ceminiparlays.io import is_flagged, is_scratched, read_games, read_manual_lines
from ceminiparlays.payouts import breakeven_per_leg, resolve_payout
from ceminiparlays.slips import evaluate_legs

COLUMNS = [
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


def _row(**overrides: str) -> str:
    row = {
        "slate_id": "s",
        "platform": "underdog",
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
    return ",".join(row[column] for column in COLUMNS) + "\n"


def _write(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "lines.csv"
    path.write_text(",".join(COLUMNS) + "\n" + "".join(rows), encoding="utf-8")
    return path


def _evaluate(rows):
    table = resolve_payout("underdog", "standard", 2)
    return evaluate_legs(rows, {}, implied_p=breakeven_per_leg(table.all_hit, 2))


def test_blank_team_is_collected_and_excluded(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [
            _row(player_name="Blank Team", team="", opp="BUF"),
            _row(player_name="Good One", team="KC", opp="BUF"),
        ],
    )
    invalid: list[tuple[object, str]] = []
    rows = read_manual_lines(path, invalid=invalid)
    assert len(rows) == 2
    assert [reason for _, reason in invalid] == ["no-team"]

    live, excluded = _evaluate(rows)
    assert [leg.line.player_name for leg in excluded] == ["Blank Team"]
    assert excluded[0].warn == "no-team"
    assert [leg.line.player_name for leg in live] == ["Good One"]


def test_blank_team_aborts_in_strict_mode(tmp_path: Path) -> None:
    path = _write(tmp_path, [_row(player_name="Blank Team", team="", opp="BUF")])
    with pytest.raises(ValueError, match="needs both team and opp"):
        read_manual_lines(path, strict=True)


def test_book_line_mismatch_is_excluded(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [_row(player_name="Lounge Five", team="KC", opp="BUF", line="5.5", book_line="4.5")],
    )
    rows = read_manual_lines(path)
    assert rows[0].book_line == 4.5
    live, excluded = _evaluate(rows)
    assert live == []
    assert excluded[0].warn == "book-line-mismatch"


def test_book_line_match_is_kept(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [_row(player_name="Same Line", team="KC", opp="BUF", line="5.5", book_line="5.5")],
    )
    rows = read_manual_lines(path)
    live, excluded = _evaluate(rows)
    assert len(live) == 1
    assert excluded == []


def test_injury_tokens() -> None:
    for status in ["out", "ir", "inactive", "doubtful", "nfi", "pup", "suspended"]:
        assert is_scratched(status) is True
    for status in ["q", "questionable", "gtd", "game-time", "limited", "dnp"]:
        assert is_flagged(status) is True
    assert is_scratched("questionable") is False
    assert is_flagged("out") is False


def test_blank_line_reads_as_nan_and_is_a_no_line_drop(tmp_path: Path) -> None:
    path = _write(tmp_path, [_row(player_name="Blank Line", team="KC", opp="BUF", line="")])
    rows = read_manual_lines(path)
    assert rows[0].line != rows[0].line  # NaN
    live, excluded = _evaluate(rows)
    assert live == []
    assert excluded[0].warn == "no-line"


def test_non_numeric_line_is_a_no_line_drop(tmp_path: Path) -> None:
    path = _write(tmp_path, [_row(player_name="Bad Line", team="KC", opp="BUF", line="abc")])
    rows = read_manual_lines(path)
    live, excluded = _evaluate(rows)
    assert live == []
    assert excluded[0].warn == "no-line"


def test_optional_columns_are_read(tmp_path: Path) -> None:
    path = tmp_path / "lines.csv"
    path.write_text(
        "player_name,stat_type,side,line,team,opp,ticket_id,fair_p,contract_price\n"
        "A One,first_td,more,,KC,BUF,t1,0.16,0.42\n",
        encoding="utf-8",
    )
    row = read_manual_lines(path)[0]
    assert row.ticket_id == "t1"
    assert row.fair_p == 0.16
    assert row.contract_price == 0.42
    assert row.line != row.line  # blank line is NaN, not an abort


def test_read_games(tmp_path: Path) -> None:
    path = tmp_path / "games.csv"
    path.write_text(
        "slate_id,kick,away,home,away_itt,home_itt,spread_home,total,roof\n"
        "s,13:00,CHI,CAR,25.25,22.25,,47.5,open\n",
        encoding="utf-8",
    )
    games = read_games(path)
    assert len(games) == 1
    assert games[0].game_id == "CHI@CAR"
    assert games[0].away_itt == 25.25
