import json
from pathlib import Path

from ceminiparlays.cli import main

ROOT = Path(__file__).resolve().parents[1]
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


def _line_row(**overrides: str) -> str:
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
    return ",".join(row[column] for column in LINE_COLUMNS) + "\n"


def _write_lines(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "lines.csv"
    path.write_text(",".join(LINE_COLUMNS) + "\n" + "".join(rows), encoding="utf-8")
    return path


def _write_distributions(tmp_path: Path, body: str = "") -> Path:
    path = tmp_path / "distributions.csv"
    path.write_text(DIST_HEADER + body, encoding="utf-8")
    return path


def test_devig_cli(capsys) -> None:
    assert main(["devig", "--over", "-155", "--under", "120"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["p_over"] > 0.57
    assert payload["spread_pp"] >= 0
    assert payload["unstable_devig"] is False


def test_devig_cli_flags_unstable_market(capsys) -> None:
    assert main(["devig", "--over", "-300", "--under", "200"]) == 0
    out = capsys.readouterr().out
    assert "UNSTABLE_DEVIG" in out


def test_fair_cli(capsys) -> None:
    assert (
        main(
            [
                "fair",
                "--player",
                "Patrick Mahomes",
                "--stat",
                "pass_yds",
                "--line",
                "275.5",
                "--median",
                "268",
                "--sd",
                "55",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "fair_p" in out
    assert "p_over_at_median" in out
    assert "do not submit" in out.lower() or "Research only" in out


def test_run_cli_lists_scratches_and_does_not_vanish_players(tmp_path: Path, capsys) -> None:
    out_dir = tmp_path / "slate"
    assert (
        main(
            [
                "run",
                "--lines",
                str(ROOT / "examples" / "manual_lines.csv"),
                "--distributions",
                str(ROOT / "examples" / "distributions.csv"),
                "--platform",
                "underdog",
                "--slip-size",
                "2",
                "--n-sims",
                "3000",
                "--displayed-multiplier",
                "3.5",
                "--out-dir",
                str(out_dir),
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "lines=5 live=4 dropped=0 scratched=1" in out
    assert "scratched Isiah Pacheco" in out
    report = (out_dir / "report.txt").read_text(encoding="utf-8")
    assert "do not submit" in report.lower()


def test_rank_strict_aborts_on_dropped_leg(tmp_path: Path, capsys) -> None:
    lines = _write_lines(
        tmp_path,
        [
            _line_row(player_name="A One", team="AAA", opp="BBB"),
            _line_row(
                player_name="Dropped Guy",
                team="CCC",
                opp="DDD",
                book_over="",
                book_under="",
            ),
        ],
    )
    dists = _write_distributions(tmp_path)
    out_csv = tmp_path / "edges.csv"
    code = main(
        [
            "rank",
            "--lines",
            str(lines),
            "--distributions",
            str(dists),
            "--platform",
            "underdog",
            "--out",
            str(out_csv),
        ]
    )
    out = capsys.readouterr().out
    assert code == 2
    assert "dropped=1" in out
    assert "dropped Dropped Guy: dropped" in out
    assert not out_csv.is_file()


def test_rank_no_strict_continues_after_dropped_leg(tmp_path: Path, capsys) -> None:
    lines = _write_lines(
        tmp_path,
        [
            _line_row(player_name="A One", team="AAA", opp="BBB"),
            _line_row(
                player_name="Dropped Guy",
                team="CCC",
                opp="DDD",
                book_over="",
                book_under="",
            ),
        ],
    )
    dists = _write_distributions(tmp_path)
    code = main(
        [
            "rank",
            "--lines",
            str(lines),
            "--distributions",
            str(dists),
            "--platform",
            "underdog",
            "--no-strict",
            "--out",
            str(tmp_path / "edges.csv"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "dropped Dropped Guy" in out


def test_rank_strict_aborts_on_integer_line(tmp_path: Path) -> None:
    lines = _write_lines(
        tmp_path,
        [
            _line_row(player_name="A One", team="AAA", opp="BBB", line="250.0"),
            _line_row(player_name="B One", team="BBB", opp="AAA"),
        ],
    )
    dists = _write_distributions(tmp_path)
    code = main(
        [
            "rank",
            "--lines",
            str(lines),
            "--distributions",
            str(dists),
            "--platform",
            "underdog",
            "--out",
            str(tmp_path / "e.csv"),
        ]
    )
    assert code == 2


def test_rank_integer_lines_allowed(tmp_path: Path) -> None:
    lines = _write_lines(
        tmp_path,
        [
            _line_row(player_name="A One", team="AAA", opp="BBB", line="250.0"),
            _line_row(player_name="B One", team="BBB", opp="AAA"),
        ],
    )
    dists = _write_distributions(tmp_path)
    code = main(
        [
            "rank",
            "--lines",
            str(lines),
            "--distributions",
            str(dists),
            "--platform",
            "underdog",
            "--allow-integer-lines",
            "--out",
            str(tmp_path / "edges.csv"),
        ]
    )
    assert code == 0


def test_rank_unconfirmed_multiplier_banner(tmp_path: Path, capsys) -> None:
    lines = _write_lines(
        tmp_path,
        [
            _line_row(player_name="A One", team="AAA", opp="BBB"),
            _line_row(player_name="B One", team="BBB", opp="AAA"),
        ],
    )
    dists = _write_distributions(tmp_path)
    code = main(
        [
            "rank",
            "--lines",
            str(lines),
            "--distributions",
            str(dists),
            "--platform",
            "underdog",
            "--out",
            str(tmp_path / "e.csv"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "UNCONFIRMED TABLE MULTIPLIER" in out
    assert "table unconfirmed" in out


def test_rank_zero_multiplier_exits_two(tmp_path: Path) -> None:
    lines = _write_lines(
        tmp_path,
        [
            _line_row(player_name="A One", team="AAA", opp="BBB"),
            _line_row(player_name="B One", team="BBB", opp="AAA"),
        ],
    )
    dists = _write_distributions(tmp_path)
    code = main(
        [
            "rank",
            "--lines",
            str(lines),
            "--distributions",
            str(dists),
            "--platform",
            "underdog",
            "--displayed-multiplier",
            "0",
            "--out",
            str(tmp_path / "e.csv"),
        ]
    )
    assert code == 2


def test_rank_row_multiplier_shows_on_card(tmp_path: Path, capsys) -> None:
    lines = _write_lines(
        tmp_path,
        [
            _line_row(player_name="A One", team="AAA", opp="BBB", slip_multiplier="2.4"),
            _line_row(player_name="B One", team="BBB", opp="AAA", slip_multiplier="2.4"),
        ],
    )
    dists = _write_distributions(tmp_path)
    code = main(
        [
            "rank",
            "--lines",
            str(lines),
            "--distributions",
            str(dists),
            "--platform",
            "underdog",
            "--out",
            str(tmp_path / "e.csv"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "M=2.4 (row)" in out


def test_default_run_sportsbook_without_platform(tmp_path: Path, capsys) -> None:
    out_dir = tmp_path / "sb"
    code = main(
        [
            "run",
            "--lines",
            str(ROOT / "examples" / "sportsbook_lines.csv"),
            "--distributions",
            str(ROOT / "examples" / "distributions.csv"),
            "--slip-size",
            "2",
            "--out-dir",
            str(out_dir),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "hardrock" in out
    assert "Patrick Mahomes" in out
    assert "do not submit" in out.lower()
    assert (out_dir / "edges.csv").is_file()


def test_hardrock_run_example(tmp_path: Path, capsys) -> None:
    out_dir = tmp_path / "hr"
    code = main(
        [
            "run",
            "--lines",
            str(ROOT / "examples" / "hardrock_lines.csv"),
            "--distributions",
            str(ROOT / "examples" / "distributions.csv"),
            "--platform",
            "hardrock",
            "--slip-size",
            "2",
            "--out-dir",
            str(out_dir),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "hardrock" in out
    assert "Patrick Mahomes" in out
    assert "Travis Kelce" in out
    assert (out_dir / "edges.csv").is_file()


def test_hardrock_displayed_odds_cli(tmp_path: Path, capsys) -> None:
    lines = _write_lines(
        tmp_path,
        [
            _line_row(player_name="A One", team="KC", opp="BUF"),
            _line_row(player_name="B One", team="KC", opp="BUF"),
        ],
    )
    # rewrite platform to hardrock
    text = lines.read_text(encoding="utf-8").replace(",underdog,", ",hardrock,")
    lines.write_text(text, encoding="utf-8")
    dists = _write_distributions(tmp_path)
    code = main(
        [
            "rank",
            "--lines",
            str(lines),
            "--distributions",
            str(dists),
            "--platform",
            "hardrock",
            "--displayed-odds",
            "260",
            "--out",
            str(tmp_path / "e.csv"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "+260" in out
    assert "M=3.6" in out


def test_hardrock_displayed_odds_on_example_ticket(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "rank",
            "--lines",
            str(ROOT / "examples" / "hardrock_ticket.csv"),
            "--distributions",
            str(ROOT / "examples" / "distributions.csv"),
            "--platform",
            "hardrock",
            "--displayed-odds",
            "260",
            "--out",
            str(tmp_path / "e.csv"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "+260" in out
    assert "M=3.6" in out


def test_hardrock_displayed_odds_on_multi_row_slate_exits_two(
    tmp_path: Path, capsys
) -> None:
    code = main(
        [
            "rank",
            "--lines",
            str(ROOT / "examples" / "hardrock_lines.csv"),
            "--distributions",
            str(ROOT / "examples" / "distributions.csv"),
            "--platform",
            "hardrock",
            "--displayed-odds",
            "260",
            "--out",
            str(tmp_path / "e.csv"),
        ]
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "one ticket" in err
    assert not (tmp_path / "e.csv").is_file()


def test_hardrock_allow_integer_lines_still_drops(tmp_path: Path, capsys) -> None:
    lines = _write_lines(
        tmp_path,
        [
            _line_row(
                player_name="A One",
                platform="hardrock",
                team="KC",
                opp="BUF",
                line="250.0",
            ),
            _line_row(
                player_name="B One",
                platform="hardrock",
                team="KC",
                opp="BUF",
            ),
        ],
    )
    dists = _write_distributions(tmp_path)
    code = main(
        [
            "rank",
            "--lines",
            str(lines),
            "--distributions",
            str(dists),
            "--platform",
            "hardrock",
            "--allow-integer-lines",
            "--displayed-odds",
            "260",
            "--out",
            str(tmp_path / "e.csv"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 2
    assert "integer-line" in out


def test_hardrock_flex_exits_two(tmp_path: Path) -> None:
    lines = _write_lines(
        tmp_path,
        [
            _line_row(player_name="A One", team="KC", opp="BUF"),
            _line_row(player_name="B One", team="BUF", opp="KC"),
        ],
    )
    text = lines.read_text(encoding="utf-8").replace(",underdog,", ",hardrock,")
    lines.write_text(text, encoding="utf-8")
    dists = _write_distributions(tmp_path)
    code = main(
        [
            "rank",
            "--lines",
            str(lines),
            "--distributions",
            str(dists),
            "--platform",
            "hardrock",
            "--mode",
            "flex",
            "--displayed-odds",
            "200",
            "--out",
            str(tmp_path / "e.csv"),
        ]
    )
    assert code == 2
