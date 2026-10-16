"""Verification for the five Jev/Parlays subsystems.

Every test here runs offline: the Jev HTTP paths use an injected opener, so no
test opens a socket. That keeps the ``test_no_network`` guarantee honest.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import urllib.error
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from ceminiparlays.ceminidfs import load_ceminidfs_handoff
from ceminiparlays.clv import LegCLV
from ceminiparlays.correlation import LegRef
from ceminiparlays.delta_rho import (
    adjusted_correlation,
    bounded_delta,
    game_key_for,
    min_eigenvalue,
    pair_delta,
)
from ceminiparlays.jev_client import (
    JevClient,
    JevProviderError,
    expected_score,
)
from ceminiparlays.jev_sizing import (
    DEFAULT_SLATE_PCT,
    SIZING_COLUMNS,
    TicketInput,
    apply_slate_cap,
    raw_ticket_stake,
    shrinkage_factor,
    size_ticket,
    size_tickets,
    write_sizing_report,
)
from ceminiparlays.proppricing import (
    BookQuote,
    Z85,
    consensus_fair_p_over,
    disagreement_edge_bps,
    posterior_fair,
    price_prop,
    split_normal,
)
from ceminiparlays.season_ledger import (
    BrierPair,
    append_ledger,
    brier_delta,
    dfs_handoff_brier_lift,
    ledger_row,
    read_ledger,
    realized_roi_pct,
)

# --------------------------------------------------------------------------
# HTTP doubles. No test here opens a socket.
# --------------------------------------------------------------------------


class _Response:
    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class _Opener:
    """Returns queued payloads or raises queued exceptions, in order."""

    def __init__(self, queued: list[object]) -> None:
        self.queued = list(queued)
        self.urls: list[str] = []

    def open(self, request, timeout=None):  # noqa: ANN001 - mirrors urllib
        self.urls.append(request.full_url)
        nxt = self.queued.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return _Response(nxt)


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", code, "err", {}, None)  # type: ignore[arg-type]


def _openrouter_noul(value: float) -> dict:
    return {"choices": [{"message": {"content": json.dumps({"noul": value})}}]}


def _clear_jev_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in (
        "TYPESAFE_API_KEY",
        "TYPESAFE_AI_API_KEY",
        "OPENROUTER_API_KEY",
        "JEV_MCP_BIN",
        "TYPESAFE_API_BASE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TYPESAFE_KEY_FILE", str(tmp_path / "absent"))


# --------------------------------------------------------------------------
# Item 1. Tiered provider failover and fail-closed behaviour.
# --------------------------------------------------------------------------


def test_expected_score_is_probability_weighted_mean() -> None:
    probabilities = {-2: 0.0, -1: 0.1, 0: 0.2, 1: 0.4, 2: 0.3}
    assert expected_score(probabilities) == pytest.approx(0.9)


def test_all_providers_unconfigured_fails_closed(tmp_path, monkeypatch) -> None:
    _clear_jev_env(monkeypatch, tmp_path)
    client = JevClient(cache_dir=tmp_path / "cache")
    with pytest.raises(JevProviderError) as caught:
        client.jev_noul({"x": 1}, "q")
    assert caught.value.unconfigured is True


def test_typesafe_transient_failure_fails_over_to_openrouter(tmp_path, monkeypatch) -> None:
    _clear_jev_env(monkeypatch, tmp_path)
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    opener = _Opener([_http_error(503), _openrouter_noul(0.7)])
    client = JevClient(cache_dir=tmp_path / "cache", opener=opener)

    result = client.jev_noul({"state": 1}, "is it?")

    assert result.provider_used == "openrouter_backup"
    assert result.noul == pytest.approx(0.7)
    assert len(opener.urls) == 2


def test_typesafe_permanent_failure_does_not_fail_over(tmp_path, monkeypatch) -> None:
    _clear_jev_env(monkeypatch, tmp_path)
    monkeypatch.setenv("TYPESAFE_API_KEY", "bad-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    opener = _Opener([_http_error(401)])
    client = JevClient(cache_dir=tmp_path / "cache", opener=opener)

    with pytest.raises(JevProviderError) as caught:
        client.jev_noul({"state": 1}, "is it?")

    assert caught.value.transient is False
    assert len(opener.urls) == 1, "a 401 must not bill the backup provider"


def test_typesafe_score_bundle_caches_to_disk(tmp_path, monkeypatch) -> None:
    _clear_jev_env(monkeypatch, tmp_path)
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-key")
    payload = {
        "results": [
            {"id": "q0", "probabilities": {"-1": 0.1, "0": 0.2, "1": 0.7}, "confidence": 0.8},
            {"id": "q1", "probabilities": {"-2": 0.05, "2": 0.95}, "confidence": 0.9},
        ]
    }
    opener = _Opener([payload])
    cache = tmp_path / "cache"
    client = JevClient(cache_dir=cache, opener=opener)

    first = client.score_bundle({"g": 1}, [("q one", None), ("q two", None)])
    assert [result.provider_used for result in first] == ["typesafe", "typesafe"]
    assert first[0].probabilities == {-1: 0.1, 0: 0.2, 1: 0.7}
    assert cache.glob("*.json"), "a bundled call must be cached on disk"

    # A second client with no opener and no key still answers from the cache.
    cached_client = JevClient(cache_dir=cache, opener=_Opener([]))
    second = cached_client.score_bundle({"g": 1}, [("q one", None), ("q two", None)])
    assert second[0].expected_score == pytest.approx(first[0].expected_score)


def test_explicit_provider_never_fails_over(tmp_path, monkeypatch) -> None:
    _clear_jev_env(monkeypatch, tmp_path)
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    opener = _Opener([_http_error(503)])
    client = JevClient(provider="typesafe", cache_dir=tmp_path / "cache", opener=opener)

    with pytest.raises(JevProviderError):
        client.jev_noul({"state": 1}, "is it?")
    assert len(opener.urls) == 1


# --------------------------------------------------------------------------
# Item 2. Delta_rho mapping and PSD projection.
# --------------------------------------------------------------------------


@dataclass
class _Score:
    expected_score: float
    confidence: float


def test_bounded_delta_respects_the_clip() -> None:
    assert bounded_delta(2.0, 1.0) == pytest.approx(0.15)
    assert bounded_delta(-2.0, 1.0) == pytest.approx(-0.15)
    assert bounded_delta(2.0, 0.5) == pytest.approx(0.075)


def test_pair_delta_matches_the_regime_mechanism() -> None:
    qb = LegRef("qb1", "KC", "BUF", "pass_yds", "more")
    wr = LegRef("wr1", "KC", "BUF", "rec_yds", "more")
    scores = {"weather_ground_compression": _Score(2.0, 0.9)}
    delta, fired = pair_delta(qb, wr, scores)
    assert fired == ("weather_ground_compression",)
    assert delta == pytest.approx(0.135)


def test_adjusted_correlation_records_bounded_deltas() -> None:
    """Two legal same-team legs: the delta is applied, bounded, and auditable."""

    qb = LegRef("qb1", "KC", "BUF", "pass_yds", "more")
    wr = LegRef("wr1", "KC", "BUF", "rec_yds", "more")
    scores = {
        game_key_for("KC", "BUF"): {
            "weather_ground_compression": _Score(2.0, 1.0),
            "pressure_checkdown_funnel": _Score(2.0, 1.0),
        }
    }
    perturbed = adjusted_correlation([qb, wr], scores)

    assert min_eigenvalue(perturbed.matrix) >= 0.0
    assert np.allclose(np.diag(perturbed.matrix), 1.0)
    record = perturbed.records[0]
    assert record.rho_base == pytest.approx(0.45), "the base prior for pass_yds/rec_yds"
    # Two regimes fire at +0.15 each; the pair total is clipped back to +0.15.
    assert record.delta_rho == pytest.approx(0.15)
    assert record.rho_adj == pytest.approx(0.60)
    assert set(record.regimes) == {"weather_ground_compression", "pressure_checkdown_funnel"}


def test_adjusted_correlation_leaves_an_unscored_game_alone() -> None:
    qb = LegRef("qb1", "KC", "BUF", "pass_yds", "more")
    wr = LegRef("wr1", "KC", "BUF", "rec_yds", "more")
    perturbed = adjusted_correlation([qb, wr], {})
    assert perturbed.records[0].delta_rho == 0.0
    assert perturbed.records[0].rho_adj == pytest.approx(0.45)


def test_adjusted_correlation_inherits_the_unmodeled_refusal() -> None:
    """A same-game pair with no prior still fails closed, exactly as base does."""

    from ceminiparlays.correlation import UnmodeledCorrelationError

    qb = LegRef("qb1", "KC", "BUF", "pass_yds", "more")
    rb = LegRef("rb1", "BUF", "KC", "rush_yds", "more")
    with pytest.raises(UnmodeledCorrelationError):
        adjusted_correlation([qb, rb], {})


def test_non_psd_sigma_adj_projects_to_psd() -> None:
    """A deliberately non-PSD Sigma_adj must come back with a non-negative spectrum."""

    from ceminiparlays.copula import nearest_correlation

    sigma_adj = np.array([[1.0, 0.9, 0.9], [0.9, 1.0, -0.9], [0.9, -0.9, 1.0]])
    assert min_eigenvalue(sigma_adj) < 0.0, "the fixture must start non-PSD"

    projected = nearest_correlation(sigma_adj)

    assert min_eigenvalue(projected) >= 0.0
    assert np.allclose(np.diag(projected), 1.0)
    assert np.all(np.abs(projected) <= 1.0)



# --------------------------------------------------------------------------
# Item 3. Continuous Kelly shrinkage and the slate cap.
# --------------------------------------------------------------------------


@dataclass
class _Choice:
    probabilities: dict
    confidence: float
    provider_used: str


class _FakeJev:
    def __init__(self, p_jev: float, c_jev: float) -> None:
        self.p_jev = p_jev
        self.c_jev = c_jev

    def jev_choice(self, state, question, choices):  # noqa: ANN001
        return _Choice({"coherent_supported": self.p_jev}, self.c_jev, "typesafe")


class _DeadJev:
    def jev_choice(self, state, question, choices):  # noqa: ANN001
        raise JevProviderError("down", transient=False)


ENVIRONMENT = {
    "implied_total": 48.5,
    "spread": -2.5,
    "roof": "open",
    "weather_exposed": True,
    "wind_mph": 12.0,
    "precip_pop": 0.2,
}
LEGS = [{"player_name": "QB One", "stat_type": "pass_yds", "side": "more", "line": 250.5}]


def _ticket(ticket_id: str, kelly: float = 0.2, **overrides) -> TicketInput:
    base = {
        "ticket_id": ticket_id,
        "legs": LEGS,
        "platform": "fanduel",
        "environment": ENVIRONMENT,
        "kelly_f_star": kelly,
    }
    base.update(overrides)
    return TicketInput(**base)


def test_below_the_coherence_floor_gets_zero_stake() -> None:
    size = size_ticket(_FakeJev(0.50, 0.90), _ticket("T1"))
    assert size.gate_status == "BLOCKED"
    assert size.reason == "below_coherence_floor"
    assert size.final_stake_pct == 0.0


def test_shrinkage_scales_with_confidence() -> None:
    assert shrinkage_factor(0.90, 0.95) == pytest.approx(1.0)
    assert shrinkage_factor(0.60, 0.90) == pytest.approx((0.54 - 0.50) / 0.35)
    assert shrinkage_factor(0.10, 0.10) == 0.0


def test_high_confidence_ticket_takes_the_full_ticket_cap() -> None:
    size = size_ticket(_FakeJev(0.90, 0.95), _ticket("T2"))
    assert size.gate_status == "PASS"
    assert size.raw_kelly_pct == pytest.approx(0.015)
    assert raw_ticket_stake(0.2, 1.0) == pytest.approx(0.015)


def test_missing_environment_field_blocks_the_ticket() -> None:
    size = size_ticket(_FakeJev(0.9, 0.95), _ticket("T3", environment={"implied_total": 48.5}))
    assert size.gate_status == "BLOCKED"
    assert size.reason.startswith("missing_environment:")


def test_inactive_player_blocks_the_ticket() -> None:
    size = size_ticket(
        _FakeJev(0.9, 0.95), _ticket("T4", regime_flags={"QB One": "pre_game_inactive"})
    )
    assert size.gate_status == "BLOCKED"
    assert size.reason.startswith("inactive_player:")


def test_all_providers_down_blocks_the_ticket() -> None:
    size = size_ticket(_DeadJev(), _ticket("T5"))
    assert size.gate_status == "BLOCKED"
    assert size.reason.startswith("providers_unavailable:")


def test_five_tickets_never_exceed_the_slate_cap() -> None:
    sizes = size_tickets(_FakeJev(0.90, 0.95), [_ticket(f"S{i}") for i in range(5)])
    total = sum(size.final_stake_pct for size in sizes)
    assert total == pytest.approx(DEFAULT_SLATE_PCT)
    for size in sizes:
        assert size.final_stake_pct == pytest.approx(DEFAULT_SLATE_PCT / 5)


def test_slate_cap_leaves_a_small_slate_untouched() -> None:
    sizes = size_tickets(_FakeJev(0.90, 0.95), [_ticket("A"), _ticket("B")])
    assert sum(size.final_stake_pct for size in sizes) == pytest.approx(0.03)


def test_slate_cap_skips_blocked_tickets() -> None:
    passed = size_ticket(_FakeJev(0.90, 0.95), _ticket("P"))
    blocked = size_ticket(_FakeJev(0.10, 0.10), _ticket("B"))
    scaled = apply_slate_cap([passed, blocked], DEFAULT_SLATE_PCT)
    assert scaled[1].final_stake_pct == 0.0
    assert scaled[1].gate_status == "BLOCKED"


def test_sizing_report_writes_the_named_columns(tmp_path) -> None:
    sizes = size_tickets(_FakeJev(0.90, 0.95), [_ticket("A")])
    path = tmp_path / "jev_gate_sizing.csv"
    write_sizing_report(path, sizes)
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert reader.fieldnames == SIZING_COLUMNS
    assert rows[0]["gate_status"] == "PASS"
    assert float(rows[0]["final_stake_pct"]) == pytest.approx(0.015)


# --------------------------------------------------------------------------
# Item 4. Split-normal pricing and non-circular de-vig.
# --------------------------------------------------------------------------


def test_split_normal_matches_the_symmetric_normal_when_unskewed() -> None:
    from scipy.stats import norm

    split = split_normal(250.0, 250.0 - Z85 * 40.0, 250.0 + Z85 * 40.0)
    assert split.cdf(250.0) == pytest.approx(0.5, abs=1e-12)
    for line in (200.0, 250.0, 290.0, 330.0):
        assert split.p_over(line) == pytest.approx(1.0 - norm.cdf(line, 250.0, 40.0), abs=1e-9)


def test_split_normal_keeps_asymmetric_tails() -> None:
    symmetric = split_normal(250.0, 250.0 - Z85 * 40.0, 250.0 + Z85 * 40.0)
    skewed = split_normal(250.0, 250.0 - Z85 * 20.0, 250.0 + Z85 * 60.0)
    assert skewed.p_over(290.0) > symmetric.p_over(290.0)


def test_non_circular_devig_excludes_the_target_book() -> None:
    quotes = [
        BookQuote("fanduel", -110, -110),
        BookQuote("draftkings", -108, -112),
        BookQuote("betmgm", -105, -115),
    ]
    all_books = consensus_fair_p_over(quotes)
    non_circular = consensus_fair_p_over(quotes, target_book="fanduel")

    assert all_books is not None and all_books.books == ("fanduel", "draftkings", "betmgm")
    assert non_circular is not None
    assert "fanduel" not in non_circular.books
    assert non_circular.fair_p_over != all_books.fair_p_over


def test_devig_fails_closed_when_only_the_target_book_exists() -> None:
    only_target = [BookQuote("fanduel", -110, -110)]
    assert consensus_fair_p_over(only_target, target_book="fanduel") is None


def test_posterior_blend_and_disagreement_flag() -> None:
    assert posterior_fair(0.50, 0.60, 1.0) == pytest.approx(0.535)
    assert posterior_fair(0.50, 0.60, 0.0) == pytest.approx(0.50)
    assert disagreement_edge_bps(0.60, 0.50) == pytest.approx(1000.0)


def _write_handoff(tmp_path: Path) -> Path:
    path = tmp_path / "ceminidfs_handoff.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "player",
                "team",
                "game",
                "implied_total",
                "pass_yds_median",
                "pass_yds_sigma",
                "pass_yds_p15",
                "pass_yds_p85",
                "rush_yds_median",
                "rush_yds_sigma",
            ]
        )
        writer.writerow(
            ["QB One", "KC", "BUF@KC", "48.5", "255", "45", "210", "310", "70", "18"]
        )
    return path


def test_handoff_reader_parses_the_disaggregated_columns(tmp_path) -> None:
    handoff = load_ceminidfs_handoff(_write_handoff(tmp_path))
    row = handoff.rows[0]
    dist = row.distribution_for("pass_yds")
    assert dist is not None
    assert (dist.median, dist.sigma, dist.p15, dist.p85) == (255.0, 45.0, 210.0, 310.0)
    assert dist.has_quantiles is True
    rush = row.distribution_for("rush_yds")
    assert rush is not None and rush.has_quantiles is False


def test_prop_price_uses_the_handoff_distribution(tmp_path) -> None:
    handoff = load_ceminidfs_handoff(_write_handoff(tmp_path))
    dist = handoff.rows[0].distribution_for("pass_yds")
    quotes = [
        BookQuote("fanduel", -110, -110),
        BookQuote("draftkings", -108, -112),
        BookQuote("betmgm", -105, -115),
    ]
    price = price_prop(
        dist=dist,
        line=250.5,
        side="more",
        quotes=quotes,
        target_book="fanduel",
        jev_regime_conf=0.8,
        stat_type="pass_yds",
    )
    assert price is not None
    assert price.family == "split_normal"
    assert "fanduel" not in price.consensus_books
    assert price.w_dfs == pytest.approx(0.35 * 0.8)
    assert price.p_fair_posterior == pytest.approx(
        (1.0 - price.w_dfs) * price.p_market_fair + price.w_dfs * price.p_dfs_over
    )
    assert price.disagreement_edge_bps == pytest.approx(
        (price.p_dfs_over - price.p_market_fair) * 10_000.0
    )


def test_prop_price_returns_none_without_a_distribution() -> None:
    quotes = [BookQuote("draftkings", -108, -112)]
    assert price_prop(dist=None, line=250.5, side="more", quotes=quotes) is None


# --------------------------------------------------------------------------
# Item 5. Closing line value and the persistent season ledger.
# --------------------------------------------------------------------------


def _leg(platform: str, stat: str, clv_pp: float) -> LegCLV:
    return LegCLV(
        platform=platform,
        stat_type=stat,
        market=stat,
        side="more",
        clv_pp=clv_pp,
        clv_line=None,
        basis="reference",
    )


def test_brier_delta_sign_convention() -> None:
    better = BrierPair(p_dfs_over=0.90, close_fair_prob=0.60, actual_hit=1.0)
    worse = BrierPair(p_dfs_over=0.20, close_fair_prob=0.60, actual_hit=1.0)
    assert brier_delta(better) < 0.0
    assert brier_delta(worse) > 0.0
    assert dfs_handoff_brier_lift([better]) > 0.0
    assert dfs_handoff_brier_lift([]) is None


def test_realized_roi_guards_a_zero_stake() -> None:
    assert realized_roi_pct(100.0, 25.0) == pytest.approx(25.0)
    assert realized_roi_pct(0.0, 25.0) is None


def test_ledger_row_computes_bps_and_t_stat() -> None:
    legs = [_leg("fanduel", "pass_yds", 0.02), _leg("fanduel", "rush_yds", 0.03),
            _leg("draftkings", "rec_yds", -0.01), _leg("draftkings", "receptions", 0.05)]
    row = ledger_row(
        week="5",
        legs=legs,
        run_date="2026-10-15",
        stake=100.0,
        pnl=25.0,
        brier_pairs=[
            BrierPair(p_dfs_over=0.9, close_fair_prob=0.6, actual_hit=1.0),
            BrierPair(p_dfs_over=0.3, close_fair_prob=0.4, actual_hit=0.0),
        ],
    )
    values = [0.02, 0.03, -0.01, 0.05]
    mean = statistics.fmean(values)
    expected_t = mean / (statistics.stdev(values) / math.sqrt(len(values)))

    assert row["n_legs"] == "4"
    assert float(row["mean_clv_bps"]) == pytest.approx(mean * 10_000.0)
    assert float(row["t_stat"]) == pytest.approx(expected_t, abs=1e-6)
    assert float(row["realized_roi_pct"]) == pytest.approx(25.0)
    assert float(row["dfs_handoff_brier_lift"]) == pytest.approx(
        statistics.fmean(
            [
                -brier_delta(BrierPair(0.9, 0.6, 1.0)),
                -brier_delta(BrierPair(0.3, 0.4, 0.0)),
            ]
        )
    )


def test_ledger_row_leaves_brier_blank_without_pairs() -> None:
    row = ledger_row(week="5", legs=[_leg("fanduel", "pass_yds", 0.02)], run_date="2026-10-15")
    assert row["dfs_handoff_brier_lift"] == ""
    assert row["realized_roi_pct"] == ""
    assert row["n_brier_legs"] == "0"


def test_append_ledger_writes_one_header_and_accumulates(tmp_path) -> None:
    path = tmp_path / "reports" / "season_clv_ledger.csv"
    legs = [_leg("fanduel", "pass_yds", 0.02)]
    append_ledger(path, ledger_row(week="4", legs=legs, run_date="2026-10-08"))
    append_ledger(path, ledger_row(week="5", legs=legs, run_date="2026-10-15"))

    with path.open(newline="", encoding="utf-8") as handle:
        text = handle.read()
    assert text.count("run_date") == 1, "the header must be written once"
    rows = read_ledger(path)
    assert [row["week"] for row in rows] == ["4", "5"]


def test_read_ledger_of_a_missing_file_is_empty(tmp_path) -> None:
    assert read_ledger(tmp_path / "absent.csv") == []


# --------------------------------------------------------------------------
# CLI wiring: the pure helpers behind the new flags.
# --------------------------------------------------------------------------


def test_closing_snapshot_skips_a_blank_td_row() -> None:
    """A TD leg carries no line and no price. Writing it would break the join."""

    from ceminiparlays.cli import _closing_snapshot_rows

    rows = [
        {
            "platform": "hardrock",
            "player_key": "qb_one",
            "stat_type": "pass_yds",
            "line": 224.5,
            "book_over": -110,
            "book_under": -110,
        },
        {
            "platform": "hardrock",
            "player_key": "qb_one",
            "stat_type": "anytime_td",
            "line": "",
            "book_over": "",
            "book_under": "",
        },
    ]
    closes = _closing_snapshot_rows(rows, "2026-10-15T20:00:00Z")

    assert len(closes) == 2, "one row per side, and the blank TD row is dropped"
    assert {row["side"] for row in closes} == {"more", "less"}
    assert all(row["line"] == 224.5 for row in closes)
    assert all(row["over"] == -110 for row in closes)


def test_closing_snapshot_keeps_only_the_first_alternate_line() -> None:
    from ceminiparlays.cli import _closing_snapshot_rows

    base = {
        "platform": "fanduel",
        "player_key": "qb_one",
        "stat_type": "pass_yds",
        "book_over": -110,
        "book_under": -110,
    }
    rows = [{**base, "line": 224.5}, {**base, "line": 234.5}]
    closes = _closing_snapshot_rows(rows, "2026-10-15T20:00:00Z")
    assert [row["line"] for row in closes] == [224.5, 224.5]


def test_kelly_by_ticket_scales_quarter_kelly_back_to_full(tmp_path) -> None:
    from ceminiparlays.cli import _kelly_by_ticket

    path = tmp_path / "edges.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ticket_id", "kelly_quarter"])
        writer.writerow(["T1", "0.05"])
        writer.writerow(["T1", "0.99"])  # a duplicate ticket keeps the first row
        writer.writerow(["", "0.10"])
    out = _kelly_by_ticket(path)
    assert out == {"T1": pytest.approx(0.20)}
    assert _kelly_by_ticket(None) == {}


def test_env_metrics_for_legs_matches_the_first_known_team() -> None:
    from ceminiparlays.cli import _env_metrics_for_legs
    from ceminiparlays.environment import EnvRow

    row = EnvRow(
        game_id="BUF@KC",
        team="KC",
        opponent="BUF",
        implied_total=48.5,
        spread=-2.5,
        roof="open",
        weather_exposed=True,
        wind_mph=14.0,
        precip_pop=0.2,
    )
    environment = {("KC", "BUF"): row, "BUF@KC": row}
    metrics = _env_metrics_for_legs([{"team": "KC"}, {"team": "BUF"}], environment)
    assert metrics is not None
    assert metrics["implied_total"] == 48.5
    assert metrics["wind_mph"] == 14.0
    assert _env_metrics_for_legs([{"team": "ZZ"}], environment) is None


def test_game_key_is_order_independent() -> None:
    assert game_key_for("KC", "BUF") == game_key_for("BUF", "KC")


def _handoff_with_stats(tmp_path: Path) -> Path:
    path = tmp_path / "handoff_dist.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "player",
                "team",
                "game",
                "implied_total",
                "pass_yds_median",
                "pass_yds_sigma",
                "pass_yds_p15",
                "pass_yds_p85",
            ]
        )
        writer.writerow(["Caleb Williams", "CHI", "CHI@DET", "47.5", "250", "50", "210", "300"])
    return path


def test_distribution_index_joins_on_the_folded_name(tmp_path) -> None:
    from ceminiparlays.ceminidfs import distribution_index, load_ceminidfs_handoff

    handoff = load_ceminidfs_handoff(_handoff_with_stats(tmp_path))
    index = distribution_index(handoff)

    assert ("caleb_williams", "pass_yds") in index
    assert index[("caleb_williams", "pass_yds")].median == 250.0
    assert distribution_index(None) == {}


def test_actual_hit_maps_hit_miss_and_void() -> None:
    from ceminiparlays.grade import _actual_hit

    assert _actual_hit("more", "260", "224.5", "pass_yds") == 1.0
    assert _actual_hit("more", "200", "224.5", "pass_yds") == 0.0
    assert _actual_hit("more", "224.5", "224.5", "pass_yds") is None, "a push is a void"
    assert _actual_hit("more", "", "224.5", "pass_yds") is None, "no actual is not a miss"


def test_row_clv_adds_bps_and_the_brier_delta(tmp_path) -> None:
    """The per-leg columns the ledger needs, checked against the formula."""

    from ceminiparlays.ceminidfs import distribution_index, load_ceminidfs_handoff
    from ceminiparlays.grade import _row_clv

    raw = {
        "platform": "hardrock",
        "sides": "more|more",
        "lines": "224.5|52.5",
        "actuals": "260|70",
        "market": "pass_yds|rec_yds",
        "player_key": "caleb_williams|dj_moore",
        "bet_over": "-150|-130",
        "bet_under": "130|-110",
        "close_over": "-140|-125",
        "close_under": "120|-105",
    }
    index = distribution_index(load_ceminidfs_handoff(_handoff_with_stats(tmp_path)))
    result = _row_clv(raw, None, "hardrock", handoff_index=index)
    leg = result["legs"][0]

    assert leg["leg_clv_bps"] == pytest.approx(leg["clv_pp"] * 10_000.0)
    assert leg["actual_hit"] == 1.0
    assert leg["p_dfs_over"] is not None
    assert leg["dfs_vs_close_brier_delta"] == pytest.approx(
        (leg["p_dfs_over"] - 1.0) ** 2 - (leg["close_implied_p"] - 1.0) ** 2
    )
    # The second leg has no handoff row, so it stays blank rather than guessed.
    assert result["legs"][1]["p_dfs_over"] is None


def test_row_clv_without_a_handoff_leaves_the_new_columns_blank() -> None:
    from ceminiparlays.grade import _row_clv

    raw = {
        "platform": "hardrock",
        "sides": "more",
        "lines": "224.5",
        "actuals": "260",
        "market": "pass_yds",
        "player_key": "caleb_williams",
        "bet_over": "-150",
        "bet_under": "130",
        "close_over": "-140",
        "close_under": "120",
    }
    leg = _row_clv(raw, None, "hardrock")["legs"][0]
    assert leg["clv_pp"] is not None
    assert leg["leg_clv_bps"] == pytest.approx(leg["clv_pp"] * 10_000.0)
    assert leg["p_dfs_over"] is None
    assert leg["dfs_vs_close_brier_delta"] is None


def test_row_clv_leaves_bps_blank_without_close_prices() -> None:
    from ceminiparlays.grade import _row_clv

    raw = {
        "platform": "hardrock",
        "sides": "more",
        "lines": "224.5",
        "actuals": "260",
        "market": "pass_yds",
        "player_key": "caleb_williams",
        "bet_over": "-150",
        "bet_under": "130",
    }
    leg = _row_clv(raw, None, "hardrock")["legs"][0]
    assert leg["clv_pp"] is None
    assert leg["leg_clv_bps"] is None, "no close price means no basis points"


def test_dfs_pricing_prices_a_leg_against_the_reference_book(tmp_path) -> None:
    """The non-circular path end to end, through the CLI helper."""

    from ceminiparlays.ceminidfs import load_ceminidfs_handoff
    from ceminiparlays.cli import _apply_dfs_pricing
    from ceminiparlays.slips import EvaluatedLeg
    from ceminiparlays.io import LineRow

    line = LineRow(
        slate_id="w5",
        platform="hardrock",
        player_name="Caleb Williams",
        player_key="caleb_williams",
        team="CHI",
        opponent="DET",
        stat_type="pass_yds",
        line=224.5,
        side="more",
        line_type="standard",
        captured_at="",
        displayed_multiplier=None,
        injury_status="",
        book_over=-110,
        book_under=-110,
        ref_book_over=-108,
        ref_book_under=-112,
    )
    leg = EvaluatedLeg(
        line=line,
        fair_p=0.5,
        implied_p=0.5,
        edge=0.0,
        source="model",
        family="lognormal",
        median=250.0,
        warn="",
    )
    handoff = load_ceminidfs_handoff(_handoff_with_stats(tmp_path))
    priced = _apply_dfs_pricing([leg], handoff, "hardrock", 0.8)

    assert priced == 1
    assert leg.p_dfs_over is not None
    assert leg.p_market_fair is not None
    assert leg.disagreement_edge_bps == pytest.approx(
        (leg.p_dfs_over - leg.p_market_fair) * 10_000.0
    )
    # w_dfs = 0.35 * 0.8, so the blend must sit between the two inputs.
    assert leg.p_fair_posterior == pytest.approx(
        0.72 * leg.p_market_fair + 0.28 * leg.p_dfs_over
    )


def test_dfs_pricing_skips_a_leg_with_no_reference_price(tmp_path) -> None:
    from ceminiparlays.ceminidfs import load_ceminidfs_handoff
    from ceminiparlays.cli import _apply_dfs_pricing
    from ceminiparlays.slips import EvaluatedLeg
    from ceminiparlays.io import LineRow

    line = LineRow(
        slate_id="w5",
        platform="hardrock",
        player_name="Caleb Williams",
        player_key="caleb_williams",
        team="CHI",
        opponent="DET",
        stat_type="pass_yds",
        line=224.5,
        side="more",
        line_type="standard",
        captured_at="",
        displayed_multiplier=None,
        injury_status="",
        book_over=-110,
        book_under=-110,
    )
    leg = EvaluatedLeg(
        line=line,
        fair_p=0.5,
        implied_p=0.5,
        edge=0.0,
        source="model",
        family="lognormal",
        median=250.0,
        warn="",
    )
    handoff = load_ceminidfs_handoff(_handoff_with_stats(tmp_path))
    assert _apply_dfs_pricing([leg], handoff, "hardrock", 0.8) == 0
    assert leg.p_dfs_over is None
