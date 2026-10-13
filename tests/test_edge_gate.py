"""The modeled-edge gate: model P vs market implied P, per leg."""

import json
from pathlib import Path

from ceminiparlays.cli import main
from ceminiparlays.io import DistRow, LineRow
from ceminiparlays.slips import (
    EvaluatedLeg,
    edge_failures,
    edge_status,
    market_implied_for_line,
    model_prob_for_line,
)

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
        "platform": "hardrock",
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


def _write_distributions(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "distributions.csv"
    path.write_text(DIST_HEADER + body, encoding="utf-8")
    return path


def _line(**overrides) -> LineRow:
    base = dict(
        slate_id="s",
        platform="hardrock",
        player_name="P",
        player_key="p",
        team="AAA",
        opponent="BBB",
        stat_type="pass_yds",
        line=250.5,
        side="more",
        line_type="standard",
        captured_at="",
        displayed_multiplier=None,
        injury_status="",
        book_over=-110,
        book_under=-110,
    )
    base.update(overrides)
    return LineRow(**base)


def _leg(**overrides) -> EvaluatedLeg:
    base = dict(
        line=_line(),
        fair_p=0.5,
        implied_p=0.5,
        edge=0.0,
        source="book_devig",
        family="book",
        median=0.0,
        warn="",
    )
    base.update(overrides)
    return EvaluatedLeg(**base)


def test_model_p_prefers_a_typed_fair_p() -> None:
    line = _line(fair_p=0.58)
    prob, source = model_prob_for_line(line, None)
    assert prob == 0.58
    assert source == "fair_p"


def test_model_p_comes_from_the_projection_when_no_typed_fair_p() -> None:
    line = _line()
    dist = DistRow("p", "P", "pass_yds", median=320.0, sigma=40.0, family="lognormal")
    prob, source = model_prob_for_line(line, dist)
    assert source == "distribution"
    assert prob > 0.9


def test_model_p_is_none_without_a_typed_fair_p_or_projection() -> None:
    prob, source = model_prob_for_line(_line(), None)
    assert prob is None
    assert source == ""


def test_market_implied_devigs_the_two_way_book() -> None:
    prob, source = market_implied_for_line(_line())
    assert source == "book_devig"
    assert abs(prob - 0.5) < 0.01


def test_market_implied_falls_back_to_leg_odds_for_a_td_market() -> None:
    line = _line(stat_type="first_td", book_over=None, book_under=None, leg_odds=290)
    prob, source = market_implied_for_line(line)
    assert source == "leg_odds_implied"
    assert abs(prob - 1.0 / 3.9) < 1e-9


def test_edge_status_separates_no_edge_from_weak_edge() -> None:
    assert edge_status(_leg(prop_edge=None), 0.01) == "no-edge"
    assert edge_status(_leg(prop_edge=-0.02), 0.01) == "weak-edge"
    assert edge_status(_leg(prop_edge=0.005), 0.01) == "weak-edge"
    assert edge_status(_leg(prop_edge=0.02), 0.01) == ""


def test_edge_failures_reports_every_failing_leg_in_order() -> None:
    legs = [
        _leg(prop_edge=0.05),
        _leg(prop_edge=-0.01),
        _leg(prop_edge=None),
    ]
    failures = edge_failures(legs, 0.01)
    assert [token for _leg, token in failures] == ["weak-edge", "no-edge"]


def test_a_weak_edge_leg_fails_closed(tmp_path: Path, capsys) -> None:
    lines = _write_lines(
        tmp_path,
        [
            _row(player_key="a", team="AAA", opp="BBB", stat_type="pass_yds"),
            _row(
                player_key="b",
                team="CCC",
                opp="DDD",
                stat_type="rush_yds",
                line="80.5",
            ),
        ],
    )
    dists = _write_distributions(
        tmp_path,
        "Alpha,a,pass_yds,200,40,lognormal\nBravo,b,rush_yds,40,15,lognormal\n",
    )
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
        ]
    )
    out = capsys.readouterr().out
    assert code == 2
    assert "EDGE-GATE weak-edge" in out
    payload = json.loads((out_dir / "card.json").read_text(encoding="utf-8"))
    assert payload["edge_gate"] == "fail"
    assert payload["tickets"][0]["legs"][0]["prop_edge"] < 0


def test_a_leg_with_no_model_is_flagged_but_does_not_fail(tmp_path: Path, capsys) -> None:
    lines = _write_lines(
        tmp_path,
        [
            _row(player_key="a", team="AAA", opp="BBB", stat_type="pass_yds"),
            _row(
                player_key="b",
                team="CCC",
                opp="DDD",
                stat_type="rush_yds",
                line="80.5",
            ),
        ],
    )
    out_dir = tmp_path / "compose"
    code = main(
        [
            "compose",
            "--lines",
            str(lines),
            "--no-roster",
            "--legs",
            "2",
            "--n-tickets",
            "1",
            "--out-dir",
            str(out_dir),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "EDGE-GATE no-edge" in out
    payload = json.loads((out_dir / "card.json").read_text(encoding="utf-8"))
    assert payload["edge_gate"] == "no-model"
    leg = payload["tickets"][0]["legs"][0]
    assert leg["model_p"] is None
    assert leg["market_implied_p"] is not None
    assert leg["edge_status"] == "no-edge"


def test_min_edge_floor_is_configurable(tmp_path: Path, capsys) -> None:
    lines = _write_lines(
        tmp_path,
        [
            _row(player_key="a", team="AAA", opp="BBB", stat_type="pass_yds"),
            _row(
                player_key="b",
                team="CCC",
                opp="DDD",
                stat_type="rush_yds",
                line="80.5",
            ),
        ],
    )
    dists = _write_distributions(
        tmp_path,
        "Alpha,a,pass_yds,200,40,lognormal\nBravo,b,rush_yds,40,15,lognormal\n",
    )
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
            "--min-edge",
            "-10",
            "--out-dir",
            str(out_dir),
        ]
    )
    capsys.readouterr()
    assert code == 0
    payload = json.loads((out_dir / "card.json").read_text(encoding="utf-8"))
    assert payload["edge_gate"] == "pass"
