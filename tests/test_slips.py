import json
from pathlib import Path

import pytest

from ceminiparlays import slips as slips_module
from ceminiparlays.io import LineRow, read_distributions, read_manual_lines
from ceminiparlays.payouts import breakeven_per_leg, resolve_payout
from ceminiparlays.slips import evaluate_legs, rank_slips, slip_as_row

ROOT = Path(__file__).resolve().parents[1]


def _line(
    name: str,
    team: str,
    opp: str,
    *,
    side: str = "more",
    line: float = 250.5,
    stat: str = "pass_yds",
    mult: float | None = None,
    line_type: str = "standard",
    book_over: int | None = -110,
    book_under: int | None = -110,
    injury: str = "",
    book_line: float | None = None,
) -> LineRow:
    return LineRow(
        slate_id="s",
        platform="underdog",
        player_name=name,
        player_key=name.lower().replace(" ", "_"),
        team=team,
        opponent=opp,
        stat_type=stat,
        line=line,
        side=side,
        line_type=line_type,
        captured_at="",
        displayed_multiplier=mult,
        injury_status=injury,
        book_over=book_over,
        book_under=book_under,
        book_line=book_line,
    )


def _evaluate(lines: list[LineRow], allow_integer_lines: bool = False):
    table = resolve_payout("underdog", "standard", 2)
    return evaluate_legs(
        lines,
        {},
        implied_p=breakeven_per_leg(table.all_hit, 2),
        allow_integer_lines=allow_integer_lines,
    )


def _example():
    lines = read_manual_lines(ROOT / "examples" / "manual_lines.csv")
    dists = read_distributions(ROOT / "examples" / "distributions.csv")
    table = resolve_payout("underdog", "standard", 2)
    live, excluded = evaluate_legs(
        lines, dists, implied_p=breakeven_per_leg(table.all_hit, 2)
    )
    return live, excluded


def test_evaluate_legs_names_the_exclusions() -> None:
    live, excluded = _example()
    assert [leg.line.player_name for leg in excluded] == ["Isiah Pacheco"]
    assert excluded[0].warn == "scratch"
    assert {leg.line.player_name for leg in live} == {
        "Patrick Mahomes",
        "Travis Kelce",
        "Josh Allen",
        "James Cook",
    }


def test_rank_skips_same_team_pairs() -> None:
    live, _ = _example()
    slips = rank_slips(live, "underdog", "standard", 2, n_sims=4000, seed=1)
    assert slips
    for slip in slips:
        teams = {leg.line.team for leg in slip.legs}
        assert len(teams) >= 2
        names = {leg.line.player_name for leg in slip.legs}
        assert "Isiah Pacheco" not in names


def test_same_game_stack_joint_exceeds_naive() -> None:
    live, _ = _example()
    slips = rank_slips(live, "underdog", "standard", 2, n_sims=8000, seed=2)
    stack = next(
        slip
        for slip in slips
        if {leg.line.player_name for leg in slip.legs} == {"Patrick Mahomes", "Josh Allen"}
    )
    assert stack.p_joint > stack.p_naive
    assert stack.p_all_se == 0.0


def test_same_player_opposite_sides_rejected() -> None:
    lines = read_manual_lines(ROOT / "examples" / "manual_lines.csv")
    dists = read_distributions(ROOT / "examples" / "distributions.csv")
    extra = [row for row in lines if row.player_name == "Patrick Mahomes"][0]
    opposite = type(extra)(**{**extra.__dict__, "side": "less"})
    assert opposite.team == "KC"
    mixed = lines + [opposite]
    table = resolve_payout("underdog", "standard", 2)
    live, _ = evaluate_legs(mixed, dists, implied_p=breakeven_per_leg(table.all_hit, 2))
    slips = rank_slips(live, "underdog", "standard", 2, n_sims=2000, seed=3)
    assert slips
    for slip in slips:
        keys = [leg.line.player_key for leg in slip.legs]
        assert len(keys) == len(set(keys))


def test_blank_team_never_enters_a_slip() -> None:
    live, excluded = _evaluate([_line("Ghost", "", "")])
    assert live == []
    assert excluded[0].warn == "no-team"


def test_one_sided_book_is_dropped() -> None:
    live, excluded = _evaluate([_line("Half Book", "AAA", "BBB", book_under=None)])
    assert live == []
    assert excluded[0].warn == "one-sided-book"


def test_integer_line_excluded_until_allowed() -> None:
    lines = [_line("Integer", "AAA", "BBB", line=250.0)]
    live, excluded = _evaluate(lines)
    assert live == []
    assert excluded[0].warn == "integer-line"
    live2, excluded2 = _evaluate(lines, allow_integer_lines=True)
    assert len(live2) == 1
    assert excluded2 == []


def test_questionable_leg_is_kept_with_warning() -> None:
    live, excluded = _evaluate([_line("Q Player", "AAA", "BBB", injury="questionable")])
    assert excluded == []
    assert live[0].warn == "questionable"
    assert live[0].fair_p > 0.0


def test_same_player_multi_stat_rejected() -> None:
    lines = [
        _line("Dup", "AAA", "BBB", stat="pass_yds"),
        _line("Dup", "BBB", "AAA", stat="pass_tds", line=1.5),
    ]
    live, _ = _evaluate(lines)
    assert len(live) == 2
    notes: list[str] = []
    slips = rank_slips(live, "underdog", "standard", 2, notes=notes)
    assert slips == []
    assert any("same-player" in note for note in notes)


def test_row_multiplier_beats_cli_and_varies_per_slip() -> None:
    lines = [
        _line("A One", "AAA", "BBB", mult=2.0),
        _line("B One", "BBB", "AAA", mult=2.0),
        _line("C One", "CCC", "DDD", mult=3.0),
        _line("D One", "DDD", "CCC", mult=3.0),
    ]
    live, _ = _evaluate(lines)
    notes: list[str] = []
    slips = rank_slips(
        live,
        "underdog",
        "standard",
        2,
        n_sims=1000,
        notes=notes,
        displayed_multiplier=5.0,
    )
    assert sorted({slip.multiplier for slip in slips}) == [2.0, 3.0]
    assert all(slip.multiplier_source == "row" for slip in slips)
    assert all(slip.multiplier_unconfirmed is False for slip in slips)
    assert any("overrides CLI" in note for note in notes)


def test_conflicting_row_multipliers_skip_combo() -> None:
    lines = [
        _line("A One", "AAA", "BBB", mult=2.0),
        _line("B One", "BBB", "AAA", mult=2.0),
        _line("C One", "CCC", "DDD", mult=3.0),
    ]
    live, _ = _evaluate(lines)
    notes: list[str] = []
    slips = rank_slips(live, "underdog", "standard", 2, n_sims=1000, notes=notes)
    assert [slip.multiplier for slip in slips] == [2.0]
    assert any("conflicting row slip_multiplier" in note for note in notes)


def test_table_multiplier_is_marked_unconfirmed() -> None:
    live, _ = _evaluate([_line("A One", "AAA", "BBB"), _line("B One", "BBB", "AAA")])
    slips = rank_slips(live, "underdog", "standard", 2)
    assert slips
    assert all(slip.multiplier_source == "table" for slip in slips)
    assert all(slip.multiplier_unconfirmed is True for slip in slips)
    assert all(
        any("multiplier_unconfirmed" in note for note in slip.notes) for slip in slips
    )


def test_alt_line_type_needs_multiplier() -> None:
    lines = [
        _line("A One", "AAA", "BBB", line_type="demon"),
        _line("B One", "BBB", "AAA", line_type="demon"),
    ]
    live, _ = _evaluate(lines)
    notes: list[str] = []
    assert rank_slips(live, "underdog", "standard", 2, notes=notes) == []
    assert any("alt-needs-m" in note for note in notes)
    priced = rank_slips(live, "underdog", "standard", 2, displayed_multiplier=3.0)
    assert priced


def test_shade_lowers_ev() -> None:
    live, _ = _evaluate([_line("A One", "AAA", "BBB"), _line("B One", "BBB", "AAA")])
    base = rank_slips(live, "underdog", "standard", 2)[0]
    shaded = rank_slips(live, "underdog", "standard", 2, shade_pp=0.02)[0]
    assert shaded.p_joint < base.p_joint
    assert shaded.ev < base.ev
    assert shaded.shade_pp == 0.02
    assert any("shade_pp" in note for note in shaded.notes)


def test_flex_suppresses_kelly() -> None:
    lines = [
        _line("A One", "AAA", "BBB"),
        _line("B One", "BBB", "CCC"),
        _line("C One", "CCC", "AAA"),
    ]
    live, _ = _evaluate(lines)
    slips = rank_slips(live, "underdog", "flex", 3, n_sims=2000, seed=5)
    assert slips
    for slip in slips:
        assert slip.kelly == 0.0
        assert any("flex proxy suppressed" in note for note in slip.notes)
        assert any("flex_partials=table" in note for note in slip.notes)
        assert slip_as_row(slip, 1)["kelly_quarter"] == ""


def test_corr_repaired_flag_surfaces(tmp_path: Path) -> None:
    priors_path = tmp_path / "priors.json"
    priors_path.write_text(
        json.dumps(
            {
                "default_cross_game": -0.9,
                "pairs": [
                    {"stat_a": "pass_yds", "stat_b": "rec_yds", "same_team": True, "rho": 0.9},
                    {"stat_a": "pass_yds", "stat_b": "pass_yds", "opponents": True, "rho": 0.9},
                ],
            }
        ),
        encoding="utf-8",
    )
    lines = [
        _line("A One", "KC", "BUF", stat="pass_yds"),
        _line("B One", "KC", "BUF", stat="rec_yds"),
        _line("C One", "BUF", "KC", stat="pass_yds"),
    ]
    live, _ = _evaluate(lines)
    slips = rank_slips(live, "underdog", "standard", 3, priors_path=priors_path)
    assert slips
    assert slips[0].corr_repaired is True
    assert any("corr_repaired=yes" in note for note in slips[0].notes)


def test_combo_budget_aborts_and_can_be_overridden(monkeypatch) -> None:
    lines = [_line(f"P{i}", f"T{i}", f"T{i + 1}") for i in range(6)]
    live, _ = _evaluate(lines)
    monkeypatch.setattr(slips_module, "COMBO_BUDGET", 5)
    with pytest.raises(ValueError, match="budget"):
        rank_slips(live, "underdog", "standard", 2)
    slips = rank_slips(live, "underdog", "standard", 2, allow_large_enum=True, max_slips=3)
    assert len(slips) == 3
