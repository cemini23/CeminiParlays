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


def test_wrong_team_dj_moore_is_dropped(tmp_path: Path, capsys) -> None:
    lines = _write_lines(
        tmp_path,
        [
            _line_row(player_name="DJ Moore", team="CHI", opp="CAR", stat_type="rec_yds"),
            _line_row(player_name="A One", team="KC", opp="BUF"),
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
            "--displayed-odds",
            "260",
            "--out",
            str(tmp_path / "e.csv"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 2
    assert "wrong-team" in out
    assert "BUF" in out


def test_min_odds_filters_short_tickets(tmp_path: Path, capsys) -> None:
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
            "--displayed-odds",
            "260",
            "--min-odds",
            "400",
            "--out",
            str(tmp_path / "e.csv"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "odds-filter dropped" in out
    assert "No slips cleared the filters" in out


def test_legs_flag_overrides_slip_size(tmp_path: Path, capsys) -> None:
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
            "--displayed-odds",
            "260",
            "--slip-size",
            "2",
            "--legs",
            "3",
            "--out",
            str(tmp_path / "e.csv"),
        ]
    )
    err = capsys.readouterr()
    assert code == 2
    assert "one ticket" in err.err or "displayed odds" in err.err or "live legs" in err.err


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


def test_version_is_0_3_0(capsys) -> None:
    import pytest

    with pytest.raises(SystemExit):
        main(["--version"])
    assert "0.3.0" in capsys.readouterr().out


def test_fetch_fixture_cli_prints_credits(tmp_path: Path, capsys) -> None:
    import csv

    from ceminiparlays.cli import SLATE_FIELDS

    out = tmp_path / "lines.csv"
    code = main(
        [
            "fetch",
            "--fixture",
            str(ROOT / "tests" / "fixtures" / "odds_api_nfl.json"),
            "--out",
            str(out),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "x-requests-remaining=472" in captured.out
    assert "do not submit" in captured.out.lower()
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert csv.DictReader(out.open(encoding="utf-8")).fieldnames == SLATE_FIELDS
    stats = {row["stat_type"] for row in rows}
    assert "pass_yds" in stats
    assert "anytime_td" in stats or "first_td" in stats


def test_slate_writes_moore_as_buf_with_blank_lines(tmp_path: Path, capsys) -> None:
    import csv

    out = tmp_path / "slate.csv"
    code = main(
        [
            "slate",
            "--games",
            str(ROOT / "examples" / "games_sunday_afternoon.csv"),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert rows
    moore = next(row for row in rows if row["player_name"] == "DJ Moore")
    assert moore["team"] == "BUF"
    assert moore["opp"] == "HOU"
    assert moore["line"] == ""
    assert {row["line"] for row in rows} == {""}
    assert "do not submit" in capsys.readouterr().out.lower()


def test_rank_blank_line_drops_no_line_and_exits_two(tmp_path: Path, capsys) -> None:
    lines = _write_lines(
        tmp_path,
        [_line_row(player_name="Blank Line", team="KC", opp="BUF", line="")],
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
    assert code == 2
    assert "no-line" in out
    assert not (tmp_path / "e.csv").is_file()


def test_rank_non_numeric_line_is_no_line(tmp_path: Path, capsys) -> None:
    lines = _write_lines(
        tmp_path,
        [_line_row(player_name="Bad Line", team="KC", opp="BUF", line="abc")],
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
    assert code == 2
    assert "dropped Bad Line: no-line" in out


def test_compose_auto_writes_five_tickets(tmp_path: Path, capsys) -> None:
    out_dir = tmp_path / "compose"
    code = main(
        [
            "compose",
            "--auto",
            "--lines",
            str(ROOT / "examples" / "sunday_lines.csv"),
            "--environment",
            str(ROOT / "examples" / "environment.csv"),
            "--out-dir",
            str(out_dir),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "composed=5 requested=5" in out
    for index in range(1, 6):
        assert (out_dir / f"ticket-{index:03d}.csv").is_file()
    card = (out_dir / "card.txt").read_text(encoding="utf-8")
    assert "do not submit" in card.lower()
    assert "do not submit" in out.lower()


def test_compose_auto_flags_override_defaults(tmp_path: Path, capsys) -> None:
    import csv

    out_dir = tmp_path / "compose"
    code = main(
        [
            "compose",
            "--auto",
            "--markets",
            "rush_yds",
            "--n-tickets",
            "2",
            "--lines",
            str(ROOT / "examples" / "sunday_lines.csv"),
            "--out-dir",
            str(out_dir),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "composed=2 requested=2" in out
    rows = list(csv.DictReader((out_dir / "ticket-001.csv").open(encoding="utf-8")))
    assert {row["stat_type"] for row in rows} == {"rush_yds"}


def test_compose_auto_window_can_leave_no_tickets(tmp_path: Path, capsys) -> None:
    out_dir = tmp_path / "compose"
    code = main(
        [
            "compose",
            "--auto",
            "--min-odds",
            "1000",
            "--lines",
            str(ROOT / "examples" / "sunday_lines.csv"),
            "--out-dir",
            str(out_dir),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "composed=0 requested=5" in out
    assert "No slips cleared the filters" in out


def test_bankroll_cli_prints_flat_and_kelly(capsys) -> None:
    assert main(["bankroll", "--bankroll", "25", "--n-tickets", "5"]) == 0
    out = capsys.readouterr().out
    assert "flat $5.00" in out
    assert "$1.25" in out


def test_rank_markets_filter_first_td_only(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "rank",
            "--lines",
            str(ROOT / "examples" / "first_td_ticket.csv"),
            "--distributions",
            str(ROOT / "examples" / "distributions.csv"),
            "--platform",
            "hardrock",
            "--markets",
            "first_td",
            "--no-roster",
            "--out",
            str(tmp_path / "e.csv"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "lines=2 live=2" in out
    assert "first_td" in out
    assert "ticket=ftd-001" in out


def test_rank_ticket_id_groups_displayed_odds(tmp_path: Path, capsys) -> None:
    lines = tmp_path / "tickets.csv"
    lines.write_text(
        "slate_id,platform,player_name,player_key,team,opp,stat_type,line,side,"
        "line_type,book_over,book_under,slip_odds,ticket_id\n"
        "s,hardrock,A One,,CIN,TB,pass_yds,265.5,more,standard,-110,-110,260,t1\n"
        "s,hardrock,B One,,DET,NO,pass_yds,258.5,more,standard,-110,-110,260,t1\n"
        "s,hardrock,C One,,BUF,HOU,pass_yds,252.5,more,standard,-110,-110,150,t2\n"
        "s,hardrock,D One,,PHI,WAS,pass_yds,231.5,more,standard,-110,-110,150,t2\n",
        encoding="utf-8",
    )
    code = main(
        [
            "rank",
            "--lines",
            str(lines),
            "--distributions",
            str(_write_distributions(tmp_path)),
            "--platform",
            "hardrock",
            "--no-roster",
            "--out",
            str(tmp_path / "e.csv"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "M=3.6 (+260 slip_odds)" in out
    assert "M=2.5 (+150 slip_odds)" in out
    assert "ticket=t1" in out
    assert "ticket=t2" in out


def test_rank_cli_displayed_odds_two_ticket_ids_exits_two(tmp_path: Path, capsys) -> None:
    lines = tmp_path / "tickets.csv"
    lines.write_text(
        "slate_id,platform,player_name,player_key,team,opp,stat_type,line,side,"
        "line_type,book_over,book_under,ticket_id\n"
        "s,hardrock,A One,,CIN,TB,pass_yds,265.5,more,standard,-110,-110,t1\n"
        "s,hardrock,B One,,DET,NO,pass_yds,258.5,more,standard,-110,-110,t1\n"
        "s,hardrock,C One,,BUF,HOU,pass_yds,252.5,more,standard,-110,-110,t2\n"
        "s,hardrock,D One,,PHI,WAS,pass_yds,231.5,more,standard,-110,-110,t2\n",
        encoding="utf-8",
    )
    code = main(
        [
            "rank",
            "--lines",
            str(lines),
            "--distributions",
            str(_write_distributions(tmp_path)),
            "--platform",
            "hardrock",
            "--no-roster",
            "--displayed-odds",
            "260",
            "--out",
            str(tmp_path / "e.csv"),
        ]
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "one ticket" in err


def test_rank_cli_displayed_odds_one_ticket_id_still_needs_size(
    tmp_path: Path, capsys
) -> None:
    lines = tmp_path / "ticket.csv"
    lines.write_text(
        "slate_id,platform,player_name,player_key,team,opp,stat_type,line,side,"
        "line_type,book_over,book_under,ticket_id\n"
        "s,hardrock,A One,,CIN,TB,pass_yds,265.5,more,standard,-110,-110,t1\n"
        "s,hardrock,B One,,DET,NO,pass_yds,258.5,more,standard,-110,-110,t1\n"
        "s,hardrock,C One,,BUF,HOU,pass_yds,252.5,more,standard,-110,-110,t1\n",
        encoding="utf-8",
    )
    shared = [
        "rank",
        "--lines",
        str(lines),
        "--distributions",
        str(_write_distributions(tmp_path)),
        "--platform",
        "hardrock",
        "--no-roster",
        "--displayed-odds",
        "260",
        "--out",
        str(tmp_path / "e.csv"),
    ]
    assert main(shared) == 2
    err = capsys.readouterr().err
    assert "one ticket" in err
    assert "does not relax" in err
    assert main([*shared, "--legs", "3"]) == 0
    out = capsys.readouterr().out
    assert "M=3.6" in out


def test_polymarket_contract_product_is_unconfirmed(tmp_path: Path, capsys) -> None:
    lines = tmp_path / "pm.csv"
    lines.write_text(
        "slate_id,platform,player_name,player_key,team,opp,stat_type,line,side,"
        "line_type,contract_price\n"
        "s,polymarket,A One,,CIN,TB,pass_yds,265.5,more,standard,0.42\n"
        "s,polymarket,B One,,DET,NO,pass_yds,258.5,more,standard,0.55\n",
        encoding="utf-8",
    )
    code = main(
        [
            "rank",
            "--lines",
            str(lines),
            "--distributions",
            str(_write_distributions(tmp_path)),
            "--platform",
            "polymarket",
            "--no-roster",
            "--out",
            str(tmp_path / "e.csv"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "contract_product" in out
    assert "unconfirmed" in out
    assert "quarter_kelly=0.0000" in out
    assert "PREDICTION COMBOS" in out


def test_polymarket_displayed_odds_is_confirmed(tmp_path: Path, capsys) -> None:
    lines = tmp_path / "pm.csv"
    lines.write_text(
        "slate_id,platform,player_name,player_key,team,opp,stat_type,line,side,"
        "line_type,contract_price\n"
        "s,kalshi,A One,,CIN,TB,pass_yds,265.5,more,standard,0.42\n"
        "s,kalshi,B One,,DET,NO,pass_yds,258.5,more,standard,0.55\n",
        encoding="utf-8",
    )
    code = main(
        [
            "rank",
            "--lines",
            str(lines),
            "--distributions",
            str(_write_distributions(tmp_path)),
            "--platform",
            "kalshi",
            "--no-roster",
            "--displayed-odds",
            "400",
            "--out",
            str(tmp_path / "e.csv"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "M=5 (" in out
    assert "contract_product" not in out


def test_betmgm_platform_uses_displayed_american(tmp_path: Path, capsys) -> None:
    lines = _write_lines(
        tmp_path,
        [
            _line_row(player_name="A One", team="KC", opp="BUF"),
            _line_row(player_name="B One", team="BUF", opp="KC"),
        ],
    )
    text = lines.read_text(encoding="utf-8").replace(",underdog,", ",betmgm,")
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
            "betmgm",
            "--displayed-odds",
            "260",
            "--out",
            str(tmp_path / "e.csv"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "betmgm" in out
    assert "+260" in out
