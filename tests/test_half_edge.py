from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ceminiparlays.half_edge import (
    EV_FIELDS,
    SHARE_FIELDS,
    MarketScore,
    _ShareIndex,
    build_shares,
    format_report,
    is_real_split,
    normal_over_prob,
    pick_side,
    read_csv,
    sample_sd,
    score_markets,
    select_legs,
    shrink_share,
    typed_question,
    write_scores,
)
from ceminiparlays.names import fold_name

ROOT = Path(__file__).resolve().parents[1]


def test_shrink_and_split_rules() -> None:
    assert shrink_share(8, 0.8, 0.5) == (8 * 0.8 + 8 * 0.5) / 16
    assert is_real_split(8, 0.65, 0.5, 0.1) is True
    assert is_real_split(7, 0.9, 0.5, 0.01) is False
    assert is_real_split(10, 0.5, 0.5, 0.01) is False
    assert pick_side(60.0, 50.0) == "over"
    assert pick_side(40.0, 50.0) == "under"
    assert pick_side(50.0, 50.0) is None


def test_module_does_not_import_jev() -> None:
    tree = ast.parse((ROOT / "src" / "ceminiparlays" / "half_edge.py").read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    assert "ceminiparlays.jev_client" not in modules
    assert "jev_client" not in modules


def _share(stat: str, player: str, **fields: str) -> dict[str, str]:
    row = {name: "" for name in SHARE_FIELDS}
    initial, last = ("", "")
    if player:
        text = player.replace(".", " ")
        parts = text.split()
        initial, last = parts[0][0].lower(), fold_name(parts[-1])
    row.update(
        {
            "stat": stat,
            "player_key": fold_name(player) if player else "",
            "match_initial": initial,
            "match_last": last,
            "full_name": player,
            "n_games": "10",
            "shrunk_share": "0.70",
            "league_share": "0.50",
            "share_se": "0.010000",
            "sigma_h1": "10",
        }
    )
    row.update(fields)
    return row


def _line(
    stat: str,
    player: str,
    *,
    line: str,
    line_type: str,
    commence: str,
    over: str,
    under: str,
    team: str = "HOU",
    opp: str = "JAX",
) -> dict[str, str]:
    return {
        "stat_type": stat,
        "player_name": player,
        "player_key": fold_name(player) if player else "",
        "team": team,
        "opp": opp,
        "line": line,
        "line_type": line_type,
        "commence_time": commence,
        "book_over": over,
        "book_under": under,
    }


def test_positive_identical_legs_pass() -> None:
    lines = []
    for index in range(20):
        kick = f"2026-10-18T18:{index:02d}:00Z"
        lines.append(
            _line(
                "pass_yds_h1",
                "C.J. Stroud",
                line="100.5",
                line_type="half",
                commence=kick,
                over="-110",
                under="-110",
            )
        )
        lines.append(
            _line(
                "pass_yds",
                "C.J. Stroud",
                line="200.5",
                line_type="standard",
                commence=kick,
                over="-110",
                under="-110",
            )
        )
    shares = [_share("pass_yds", "C.J. Stroud")]
    scores, _dropped, _index = score_markets(lines, shares)
    passed = next(row for row in scores if row.market == "pass_yds_h1")
    assert passed.n_legs == 20
    assert passed.verdict == "pass"
    assert passed.mean_ev is not None and passed.mean_ev > 0
    assert passed.ci_low is not None and passed.ci_low > 0
    assert passed.cluster_ci_low is not None and passed.cluster_ci_low > 0
    legs, _, _ = select_legs(lines, shares)
    assert {leg.side for leg in legs["pass_yds_h1"]} == {"over"}


def test_side_is_the_model_sign_not_the_better_price() -> None:
    lines = []
    for index in range(20):
        kick = f"2026-10-19T18:{index:02d}:00Z"
        lines.append(
            _line(
                "rush_yds_h1",
                "Travis Etienne",
                line="50.5",
                line_type="half",
                commence=kick,
                over="-200",
                under="150",
                team="JAX",
                opp="HOU",
            )
        )
        lines.append(
            _line(
                "rush_yds",
                "Travis Etienne",
                line="100.5",
                line_type="standard",
                commence=kick,
                over="-110",
                under="-110",
                team="JAX",
                opp="HOU",
            )
        )
    shares = [
        _share(
            "rush_yds",
            "Travis Etienne",
            shrunk_share="0.60",
            league_share="0.45",
            share_se="0.020000",
            sigma_h1="40",
        )
    ]
    legs, _, _ = select_legs(lines, shares)
    assert len(legs["rush_yds_h1"]) == 20
    assert {leg.side for leg in legs["rush_yds_h1"]} == {"over"}
    assert all(leg.ev < 0 for leg in legs["rush_yds_h1"])
    under_p = 1.0 - legs["rush_yds_h1"][0].p_side
    under_ev = under_p * 2.5 - 1.0
    assert under_ev > 0
    scores, _, _ = score_markets(lines, shares)
    failed = next(row for row in scores if row.market == "rush_yds_h1")
    assert failed.verdict == "fail"
    assert failed.reason == "mean_ev_not_positive"


def test_too_few_legs_and_a_flat_share_fail() -> None:
    lines = []
    for index in range(3):
        kick = f"2026-10-20T18:{index:02d}:00Z"
        lines.append(
            _line(
                "receptions_h1",
                "Nico Collins",
                line="2.5",
                line_type="half",
                commence=kick,
                over="-115",
                under="-115",
            )
        )
        lines.append(
            _line(
                "receptions",
                "Nico Collins",
                line="6.5",
                line_type="standard",
                commence=kick,
                over="-115",
                under="-115",
            )
        )
        lines.append(
            _line(
                "rec_yds_h1",
                "Nico Collins",
                line="30.5",
                line_type="half",
                commence=kick,
                over="-115",
                under="-115",
            )
        )
        lines.append(
            _line(
                "rec_yds",
                "Nico Collins",
                line="70.5",
                line_type="standard",
                commence=kick,
                over="-115",
                under="-115",
            )
        )
    shares = [
        _share("receptions", "Nico Collins", sigma_h1="1.5"),
        _share("rec_yds", "Nico Collins", shrunk_share="0.50", league_share="0.50"),
    ]
    scores, dropped, _index = score_markets(lines, shares)
    receptions = next(row for row in scores if row.market == "receptions_h1")
    yards = next(row for row in scores if row.market == "rec_yds_h1")
    assert receptions.verdict == "fail"
    assert receptions.reason == "too_few_legs"
    assert receptions.n_legs == 3
    assert yards.n_legs == 0
    assert yards.reason == "too_few_legs"
    assert dropped["no_split"] == 3
    # The normal helper stays finite at the posted line.
    assert 0.5 < normal_over_prob(100.0, 140.0, 50.0) < 0.9


def _score() -> MarketScore:
    return MarketScore(
        market="rec_yds",
        n_legs=3,
        mean_ev=0.05,
        ci_low=0.01,
        ci_high=0.09,
        cluster_ci_low=0.0,
        cluster_ci_high=0.1,
        verdict="pass",
        reason="ok",
    )


def test_sample_sd_needs_two_values() -> None:
    assert sample_sd([]) is None
    assert sample_sd([1.0]) is None


def test_sample_sd_uses_the_n_minus_one_estimate() -> None:
    assert sample_sd([1.0, 2.0, 3.0, 4.0]) == pytest.approx(1.2909944, rel=1e-6)


def test_typed_question_names_the_player_and_the_stat() -> None:
    text = typed_question({"stat_type": "rec_yds", "player_name": "A Back"})
    assert "rec_yds" in text
    assert "A Back" in text
    assert text.endswith("pass or fail.")


def test_read_csv_returns_the_rows(tmp_path: Path) -> None:
    path = tmp_path / "rows.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    assert read_csv(path) == [{"a": "1", "b": "2"}]


def test_market_score_as_row_keys_every_ev_field() -> None:
    row = _score().as_row()
    assert list(row) == EV_FIELDS
    assert row["market"] == "rec_yds"
    assert row["n_legs"] == "3"


def test_write_scores_writes_the_ev_header(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "scores.csv"
    write_scores(path, [])
    assert path.read_text(encoding="utf-8").strip() == ",".join(EV_FIELDS)


def test_format_report_leads_with_the_drop_counts() -> None:
    dropped = {
        "unmatched": 0,
        "no_split": 0,
        "no_full_line": 0,
        "tie": 0,
        "no_price": 0,
    }
    lines = format_report([_score()], dropped, _ShareIndex([])).splitlines()
    assert lines[0] == "ngs_player_rows=0"
    assert lines[1] == "ngs_attached=0"
    assert lines[2] == "dropped_unmatched=0"
    assert lines[6] == "dropped_no_price=0"
    assert lines[7] == ",".join(EV_FIELDS)
    assert lines[8].startswith("rec_yds,3,")


def test_build_shares_names_a_missing_pbp_file(tmp_path: Path) -> None:
    pytest.importorskip("pandas")
    with pytest.raises(ValueError, match="pbp file is missing"):
        build_shares([tmp_path / "absent.parquet"], [], [], tmp_path / "shares.csv")
