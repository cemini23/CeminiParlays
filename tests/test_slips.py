from pathlib import Path

from ceminiparlays.io import read_distributions, read_manual_lines
from ceminiparlays.payouts import breakeven_per_leg, resolve_payout
from ceminiparlays.slips import evaluate_legs, rank_slips

ROOT = Path(__file__).resolve().parents[1]


def test_rank_skips_out_and_same_team_only() -> None:
    lines = read_manual_lines(ROOT / "examples" / "manual_lines.csv")
    dists = read_distributions(ROOT / "examples" / "distributions.csv")
    table = resolve_payout("underdog", "standard", 2)
    legs = evaluate_legs(lines, dists, implied_p=breakeven_per_leg(table.all_hit, 2))
    assert any(leg.warn == "scratch" for leg in legs)
    slips = rank_slips(legs, "underdog", "standard", 2, n_sims=4000, seed=1)
    assert slips
    for slip in slips:
        teams = {leg.line.team for leg in slip.legs}
        assert len(teams) >= 2
        names = {leg.line.player_name for leg in slip.legs}
        assert "Isiah Pacheco" not in names


def test_same_game_stack_joint_exceeds_naive() -> None:
    lines = read_manual_lines(ROOT / "examples" / "manual_lines.csv")
    dists = read_distributions(ROOT / "examples" / "distributions.csv")
    table = resolve_payout("underdog", "standard", 2)
    legs = evaluate_legs(lines, dists, implied_p=breakeven_per_leg(table.all_hit, 2))
    slips = rank_slips(legs, "underdog", "standard", 2, n_sims=8000, seed=2)
    stack = next(
        slip
        for slip in slips
        if {leg.line.player_name for leg in slip.legs} == {"Patrick Mahomes", "Josh Allen"}
    )
    assert stack.p_joint > stack.p_naive


def test_same_player_opposite_sides_rejected() -> None:
    lines = read_manual_lines(ROOT / "examples" / "manual_lines.csv")
    dists = read_distributions(ROOT / "examples" / "distributions.csv")
    extra = [row for row in lines if row.player_name == "Patrick Mahomes"][0]
    opposite = type(extra)(**{**extra.__dict__, "side": "less", "team": ""})
    mixed = lines + [opposite]
    table = resolve_payout("underdog", "standard", 2)
    legs = evaluate_legs(mixed, dists, implied_p=breakeven_per_leg(table.all_hit, 2))
    slips = rank_slips(legs, "underdog", "standard", 2, n_sims=2000, seed=3)
    for slip in slips:
        keys = [(leg.line.player_key, leg.line.stat_type) for leg in slip.legs]
        assert len(keys) == len(set(keys))
