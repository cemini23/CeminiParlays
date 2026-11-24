"""Venue-mix sizing: fee-adjusted Kelly, venue/group/total caps, and CLI."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from ceminiparlays.cli import main
from ceminiparlays.kelly import slip_kelly
from ceminiparlays.venue_mix import (
    VenueCandidate,
    VenueProfile,
    addressable_share,
    allocate_venue_mix,
    effective_odds,
    read_candidates,
    read_venue_profiles,
    venue_kelly,
    write_venue_mix,
)

TOTAL_CAP = 0.06
GROUP_CAP = 0.045
EPS = 1e-9


def _by_venue(result):
    return {row.venue: row for row in result.stakes}


def test_venue_cap_clamps_and_redistributes() -> None:
    profiles = [
        VenueProfile("venue_a", 0.5, 0.5, 0.0, 0.01),
        VenueProfile("venue_b", 0.5, 0.5, 0.0, 0.05),
    ]
    candidates = [
        VenueCandidate("venue_a", 0.70, 2.10),
        VenueCandidate("venue_b", 0.55, 2.00),
    ]
    result = allocate_venue_mix(candidates, profiles, bankroll=1000.0)
    rows = _by_venue(result)

    assert rows["venue_a"].stake_pct == pytest.approx(0.01)
    assert rows["venue_a"].cap_reason == "venue_cap"
    # A is clamped, so B absorbs the rest of the budget.
    assert rows["venue_b"].stake_pct == pytest.approx(0.05)
    assert result.total_pct == pytest.approx(TOTAL_CAP)
    assert result.total_dollars == pytest.approx(60.0)


def test_venue_cap_binds_across_candidates_of_one_venue() -> None:
    profiles = [VenueProfile("kalshi", 1.0, 1.0, 0.0, 0.02)]
    candidates = [
        VenueCandidate("kalshi", 0.70, 2.10),
        VenueCandidate("kalshi", 0.65, 2.00),
    ]
    result = allocate_venue_mix(candidates, profiles, bankroll=1000.0)

    venue_total = sum(row.stake_pct for row in result.stakes)
    assert venue_total <= 0.02 + EPS
    assert venue_total == pytest.approx(0.02)
    assert all(row.cap_reason == "venue_cap" for row in result.stakes)


def test_group_cap_clamps_correlated_exposure() -> None:
    profiles = [
        VenueProfile("kalshi", 0.5, 0.5, 0.0, 0.05, group="pm"),
        VenueProfile("polymarket", 0.5, 0.5, 0.0, 0.05, group="pm"),
    ]
    candidates = [
        VenueCandidate("kalshi", 0.60, 1.90),
        VenueCandidate("polymarket", 0.60, 1.90),
    ]
    result = allocate_venue_mix(candidates, profiles, bankroll=1000.0)

    group_total = sum(row.stake_pct for row in result.stakes)
    assert group_total <= GROUP_CAP + EPS
    assert group_total == pytest.approx(GROUP_CAP)
    assert {row.cap_reason for row in result.stakes} == {"group_cap"}
    # Released money is not moved into another group, so the slate under-spends.
    assert result.total_pct < TOTAL_CAP


def test_total_and_kelly_bounds() -> None:
    profiles = [
        VenueProfile("kalshi", 0.10, 0.90, 0.02, 0.05, group="pm"),
        VenueProfile("polymarket", 0.08, 0.85, 0.00, 0.05, group="pm"),
        VenueProfile("fanduel", 0.52, 0.35, 0.05, 0.05, group="book"),
        VenueProfile("draftkings", 0.30, 0.40, 0.06, 0.05, group="book"),
    ]
    candidates = [
        VenueCandidate("kalshi", 0.62, 1.85),
        VenueCandidate("polymarket", 0.60, 1.90),
        VenueCandidate("fanduel", 0.58, 1.95),
        VenueCandidate("draftkings", 0.40, 2.20),
    ]
    result = allocate_venue_mix(candidates, profiles, bankroll=1000.0)

    assert result.total_pct <= TOTAL_CAP + EPS
    assert result.total_pct <= sum(row.kelly_pct for row in result.stakes) + EPS
    assert result.total_pct <= min(
        sum(row.kelly_pct for row in result.stakes), TOTAL_CAP
    ) + EPS
    for row in result.stakes:
        assert 0.0 <= row.stake_pct <= 0.05 + EPS
        assert row.kelly_pct == pytest.approx(
            slip_kelly(row.model_p, row.effective_odds, 0.25)
        )
    groups: dict[str, float] = {}
    for row in result.stakes:
        groups[row.group] = groups.get(row.group, 0.0) + row.stake_pct
    assert groups["pm"] <= GROUP_CAP + EPS
    assert groups["book"] <= GROUP_CAP + EPS


def test_fee_lowers_the_stake() -> None:
    candidate = VenueCandidate("kalshi", 0.55, 2.10)
    free = VenueProfile("kalshi", 1.0, 1.0, 0.00, 1.0)
    taxed = VenueProfile("kalshi", 1.0, 1.0, 0.10, 1.0)

    free_result = allocate_venue_mix([candidate], [free], bankroll=1000.0)
    taxed_result = allocate_venue_mix([candidate], [taxed], bankroll=1000.0)

    free_row = free_result.stakes[0]
    taxed_row = taxed_result.stakes[0]
    assert taxed_row.effective_odds < free_row.effective_odds
    assert taxed_row.effective_odds == pytest.approx(1 + (2.10 - 1) * 0.90)
    assert taxed_row.kelly_pct < free_row.kelly_pct
    assert taxed_row.stake_pct < free_row.stake_pct
    assert taxed_row.stake_pct == pytest.approx(taxed_row.kelly_pct)


def test_zero_edge_venue_gets_nothing() -> None:
    loser_profile = VenueProfile("kalshi", 1.0, 1.0, 0.0, 1.0)
    loser = VenueCandidate("kalshi", 0.40, 2.00)
    assert venue_kelly(loser, loser_profile) == 0.0

    # Pure loser slate: budget is zero and every input still gets a zeroed row.
    empty = allocate_venue_mix(
        [loser, VenueCandidate("kalshi", 0.30, 1.50)],
        [loser_profile],
        bankroll=500.0,
    )
    assert len(empty.stakes) == 2
    assert all(row.stake_pct == 0.0 and row.stake_dollars == 0.0 for row in empty.stakes)
    assert empty.total_pct == 0.0 and empty.total_dollars == 0.0
    assert all(row.cap_reason == "" for row in empty.stakes)

    # Mixed slate: the loser is dropped while the winner keeps the budget.
    winner_profile = VenueProfile("fanduel", 1.0, 1.0, 0.0, 0.05)
    winner = VenueCandidate("fanduel", 0.60, 1.90)
    result = allocate_venue_mix(
        [loser, winner], [loser_profile, winner_profile], bankroll=500.0
    )
    rows = _by_venue(result)
    assert rows["kalshi"].stake_pct == 0.0
    assert rows["kalshi"].net_edge < 0.0
    assert rows["fanduel"].stake_pct > 0.0
    assert result.total_pct > 0.0


def test_dollars_follow_bankroll_and_caps() -> None:
    bankroll = 2500.0
    profiles = [
        VenueProfile("kalshi", 0.2, 0.9, 0.02, 0.012, group="pm"),
        VenueProfile("polymarket", 0.1, 0.85, 0.0, 0.02, group="pm"),
        VenueProfile("fanduel", 0.5, 0.35, 0.05, 0.05, group="book"),
    ]
    candidates = [
        VenueCandidate("kalshi", 0.64, 1.80),
        VenueCandidate("polymarket", 0.62, 1.85),
        VenueCandidate("fanduel", 0.55, 2.05),
    ]
    result = allocate_venue_mix(candidates, profiles, bankroll=bankroll)
    for row in result.stakes:
        assert row.stake_dollars == round(bankroll * row.stake_pct, 2)
    assert result.total_dollars == pytest.approx(
        sum(row.stake_dollars for row in result.stakes), abs=0.01
    )
    assert result.total_dollars <= bankroll * TOTAL_CAP + 0.01
    assert sum(row.stake_dollars for row in result.stakes) <= bankroll * TOTAL_CAP + 0.01


@pytest.fixture()
def mix_fixtures(tmp_path: Path) -> tuple[Path, Path]:
    venues = tmp_path / "venues.csv"
    venues.write_text(
        "venue,volume_share,parlay_share,fee_rate,max_stake_pct,group\n"
        "kalshi,0.10,0.90,0.02,0.012,pm\n"
        "polymarket,0.08,0.85,0.00,0.02,pm\n"
        "fanduel,0.52,0.35,0.05,0.05,book\n",
        encoding="utf-8",
    )
    prices = tmp_path / "prices.csv"
    prices.write_text(
        "venue,model_p,decimal_odds,ticket_id\n"
        "kalshi,0.64,1.80,T-1\n"
        "polymarket,0.62,1.85,T-2\n"
        "fanduel,0.55,2.05,T-3\n",
        encoding="utf-8",
    )
    return venues, prices


def test_cli_venue_mix_writes_csv(
    tmp_path: Path, mix_fixtures: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    venues, prices = mix_fixtures
    out = tmp_path / "mix" / "venue_mix.csv"
    code = main(
        [
            "venue-mix",
            "--venues",
            str(venues),
            "--prices",
            str(prices),
            "--bankroll",
            "1000",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "VENUE_MIX_TOTAL" in printed
    assert "VENUE_MIX venue=kalshi" in printed
    assert out.is_file()

    with out.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == [
            "venue",
            "group",
            "model_p",
            "decimal_odds",
            "effective_odds",
            "net_edge",
            "kelly_pct",
            "stake_pct",
            "stake_dollars",
            "cap_reason",
        ]
        rows = list(reader)
    assert len(rows) == 3
    assert {row["venue"] for row in rows} == {"kalshi", "polymarket", "fanduel"}
    # The CSV prints six decimals, so allow for that rounding in the sum.
    assert sum(float(row["stake_pct"]) for row in rows) <= TOTAL_CAP + 1e-5
    for row in rows:
        dollars = float(row["stake_dollars"])
        assert abs(dollars - 1000.0 * float(row["stake_pct"])) <= 0.01


def test_effective_odds_and_kelly_helpers() -> None:
    assert effective_odds(2.00, 0.00) == pytest.approx(2.00)
    assert effective_odds(2.00, 0.10) == pytest.approx(1.90)
    assert effective_odds(1.00, 0.10) == 1.0
    assert effective_odds(0.50, 0.10) == 1.0

    profile = VenueProfile("kalshi", 1.0, 1.0, 0.05, 0.05)
    candidate = VenueCandidate("kalshi", 0.60, 2.00)
    assert venue_kelly(candidate, profile) == pytest.approx(
        slip_kelly(0.60, effective_odds(2.00, 0.05), 0.25)
    )
    assert venue_kelly(candidate, profile, 0.50) > venue_kelly(candidate, profile, 0.25)


def test_addressable_share_normalizes_and_validates() -> None:
    shares = addressable_share(
        [
            VenueProfile("kalshi", 0.20, 0.50, 0.0, 0.05),
            VenueProfile("fanduel", 0.80, 0.25, 0.0, 0.05),
        ]
    )
    assert sum(shares.values()) == pytest.approx(1.0)
    assert shares["fanduel"] == pytest.approx(0.6666666667, rel=1e-6)
    assert addressable_share([]) == {}
    assert (
        addressable_share(
            [
                VenueProfile("kalshi", 0.0, 0.50, 0.0, 0.05),
                VenueProfile("fanduel", 0.0, 0.25, 0.0, 0.05),
            ]
        )
        == {}
    )
    with pytest.raises(ValueError):
        addressable_share(
            [
                VenueProfile("kalshi", 0.2, 0.5, 0.0, 0.05),
                VenueProfile("kalshi", 0.2, 0.5, 0.0, 0.05),
            ]
        )


def test_allocator_rejects_bad_input() -> None:
    profile = VenueProfile("kalshi", 1.0, 1.0, 0.0, 0.05)
    candidate = VenueCandidate("kalshi", 0.60, 2.00)
    with pytest.raises(ValueError):
        allocate_venue_mix([candidate], [profile], bankroll=-1.0)
    with pytest.raises(ValueError):
        allocate_venue_mix([candidate], [profile], bankroll=100.0, total_cap_pct=0.0)
    with pytest.raises(ValueError):
        allocate_venue_mix([candidate], [profile], bankroll=100.0, group_cap_pct=1.5)
    with pytest.raises(ValueError):
        allocate_venue_mix([candidate], [profile], bankroll=100.0, kelly_fraction=0.0)
    with pytest.raises(ValueError):
        allocate_venue_mix(
            [VenueCandidate("other", 0.60, 2.00)], [profile], bankroll=100.0
        )
    with pytest.raises(ValueError):
        allocate_venue_mix(
            [VenueCandidate("kalshi", 1.00, 2.00)], [profile], bankroll=100.0
        )
    with pytest.raises(ValueError):
        allocate_venue_mix(
            [VenueCandidate("kalshi", 0.60, 1.00)], [profile], bankroll=100.0
        )


def test_readers_and_writer_round_trip(
    tmp_path: Path, mix_fixtures: tuple[Path, Path]
) -> None:
    venues, prices = mix_fixtures
    profiles = read_venue_profiles(venues)
    candidates = read_candidates(prices)
    assert [profile.venue for profile in profiles] == [
        "kalshi",
        "polymarket",
        "fanduel",
    ]
    assert profiles[0].group == "pm"
    assert [candidate.venue for candidate in candidates] == [
        "kalshi",
        "polymarket",
        "fanduel",
    ]

    result = allocate_venue_mix(candidates, profiles, bankroll=1000.0)
    out = tmp_path / "roundtrip.csv"
    write_venue_mix(out, result)
    with out.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(result.stakes)
    assert [row["venue"] for row in rows] == [stake.venue for stake in result.stakes]

    with pytest.raises(FileNotFoundError):
        read_venue_profiles(tmp_path / "absent.csv")
    with pytest.raises(FileNotFoundError):
        read_candidates(tmp_path / "absent.csv")

    bad = tmp_path / "bad.csv"
    bad.write_text(
        "venue,volume_share,parlay_share,fee_rate,max_stake_pct\n"
        "kalshi,1.5,0.9,0.02,0.012\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        read_venue_profiles(bad)

    blank = tmp_path / "blank.csv"
    blank.write_text(
        "venue,volume_share,parlay_share,fee_rate,max_stake_pct\n"
        ",0.2,0.9,0.02,0.012\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        read_venue_profiles(blank)

    bad_price = tmp_path / "bad_price.csv"
    bad_price.write_text(
        "venue,model_p,decimal_odds\nkalshi,0.60,1.00\n", encoding="utf-8"
    )
    with pytest.raises(ValueError):
        read_candidates(bad_price)


def test_json_summary_includes_share_table(
    tmp_path: Path, mix_fixtures: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    venues, prices = mix_fixtures
    code = main(
        [
            "venue-mix",
            "--venues",
            str(venues),
            "--prices",
            str(prices),
            "--bankroll",
            "1000",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload["addressable_share"]) == {"kalshi", "polymarket", "fanduel"}
    assert payload["total_pct"] <= TOTAL_CAP + EPS
    assert len(payload["stakes"]) == 3
