from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ceminiparlays.odds import american_to_decimal
from ceminiparlays.payouts import SPORTSBOOK_PLATFORMS, normalize_platform, resolve_payout

MORE_SIDES = {"more", "over", "higher", "o"}
LESS_SIDES = {"less", "under", "lower", "u"}
YES_NO_SIDES = {"yes", "no", "atd"}
ML_SIDES = {"ml", "moneyline", "h2h"}
YES_TOKENS = {"yes", "y"}
NO_TOKENS = {"no", "n"}
WIN_TOKENS = {"win", "won", "w"}
LOSS_TOKENS = {"loss", "lose", "lost", "l"}
#: Optional ledger columns. Unknown extra columns are ignored, never fatal.
OPTIONAL_LEDGER_COLUMNS = ("ticket_id", "market", "stake_kind", "paid")


@dataclass
class GradeSummary:
    n_slips: int
    hits: int
    hit_rate: float
    stake: float
    pnl: float
    roi: float
    bonus_stake: float = 0.0
    ticket_ids: list[str] = field(default_factory=list)
    markets: list[str] = field(default_factory=list)
    stake_kinds: list[str] = field(default_factory=list)


def _canonical_discrete(token: str) -> str | None:
    text = token.strip().lower()
    if text in YES_TOKENS:
        return "yes"
    if text in NO_TOKENS:
        return "no"
    if text in WIN_TOKENS:
        return "win"
    if text in LOSS_TOKENS:
        return "loss"
    return None


def _parse_leg_token(part: str) -> str | float:
    discrete = _canonical_discrete(part)
    if discrete is not None:
        return discrete
    return float(part)


def _looks_american(text: str) -> bool:
    """True for +288 / -110 / 288 (integer, abs >= 100, no decimal point)."""

    if "." in text or "e" in text.lower():
        return False
    try:
        value = int(text)
    except ValueError:
        return False
    return abs(value) >= 100


def _parse_multiplier(raw: str | None) -> float | None:
    """Parse a ledger multiplier: American (+288) or decimal (3.88, 5.0)."""

    text = (raw or "").strip()
    if not text:
        return None
    if _looks_american(text):
        return american_to_decimal(int(text))
    return float(text)


def _parse_paid(raw: str | None) -> float | None:
    text = (raw or "").strip()
    if not text:
        return None
    return float(text)


def _discrete_expected(side: str) -> str | None:
    if side in ML_SIDES:
        return "win"
    if side in {"yes", "atd"}:
        return "yes"
    if side == "no":
        return "no"
    return None


def _grade_leg(side: str, actual: str | float, line: str | float) -> str:
    """Return 'hit', 'miss', or 'void' for one leg. Discrete equality is never a void."""

    expected = _discrete_expected(side)
    actual_discrete = isinstance(actual, str)
    line_discrete = isinstance(line, str)
    if expected is not None:
        if actual_discrete and actual == expected:
            return "hit"
        if actual_discrete and line_discrete and actual == line:
            return "hit"
        return "miss"
    if actual_discrete or line_discrete:
        if actual_discrete and line_discrete and actual == line:
            return "hit"
        return "miss"
    if actual == line:
        return "void"
    if side in MORE_SIDES and actual > line:
        return "hit"
    if side in LESS_SIDES and actual < line:
        return "hit"
    return "miss"


def _leg_outcomes(raw: dict[str, str]) -> tuple[int, int, int]:
    """Return (hits, misses, voids) for one ledger row.

    Numeric ``actual == line`` is a void (yardage / totals / spreads). Discrete
    yes/no and ML win/loss matching tokens are hits, never voids.
    """

    if raw.get("hits"):
        hits = int(raw["hits"])
        n_legs = int(raw.get("n_legs") or raw.get("legs") or hits)
        return hits, max(n_legs - hits, 0), 0
    sides = [part.strip().lower() for part in raw.get("sides", "").split("|") if part.strip()]
    actual_parts = [part.strip() for part in raw.get("actuals", "").split("|") if part.strip()]
    line_parts = [part.strip() for part in raw.get("lines", "").split("|") if part.strip()]
    if len(actual_parts) != len(sides) or len(line_parts) != len(sides):
        raise ValueError("sides, lines, and actuals must have the same length")
    hits = misses = voids = 0
    for side, actual_raw, line_raw in zip(sides, actual_parts, line_parts, strict=True):
        actual = _parse_leg_token(actual_raw)
        line = _parse_leg_token(line_raw)
        result = _grade_leg(side, actual, line)
        if result == "hit":
            hits += 1
        elif result == "void":
            voids += 1
        else:
            misses += 1
    return hits, misses, voids


def grade_ledger(
    path: Path,
    profile_dir: Path | None = None,
    default_platform: str | None = None,
) -> GradeSummary:
    slips = 0
    hits = 0
    stake_total = 0.0
    pnl = 0.0
    bonus_stake = 0.0
    ticket_ids: list[str] = []
    markets: list[str] = []
    stake_kinds: list[str] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row_index, raw in enumerate(csv.DictReader(handle), start=2):
            slips += 1
            stake = float(raw.get("stake", 1.0) or 1.0)
            stake_total += stake
            stake_kind = (raw.get("stake_kind") or "").strip().lower()
            if stake_kind:
                if stake_kind not in stake_kinds:
                    stake_kinds.append(stake_kind)
                if stake_kind == "bonus":
                    bonus_stake += stake
            ticket_id = (raw.get("ticket_id") or "").strip()
            if ticket_id and ticket_id not in ticket_ids:
                ticket_ids.append(ticket_id)
            market = (raw.get("market") or "").strip()
            if market and market not in markets:
                markets.append(market)
            raw_legs = raw.get("n_legs") or raw.get("legs") or ""
            try:
                n_legs = int(raw_legs)
            except (TypeError, ValueError):
                n_legs = 0
            if n_legs <= 0:
                n_legs = len([p for p in raw.get("sides", "").split("|") if p.strip()])
            raw_platform = (raw.get("platform") or "").strip()
            platform = normalize_platform(
                raw_platform or default_platform or "underdog"
            )
            mode = raw.get("mode") or "standard"
            displayed = _parse_multiplier(raw.get("multiplier"))
            paid_value = _parse_paid(raw.get("paid"))
            hit_count, miss_count, void_count = _leg_outcomes(raw)
            if hit_count == n_legs:
                hits += 1
            if paid_value is not None:
                pnl += paid_value - stake
                continue
            sportsbook = platform in SPORTSBOOK_PLATFORMS
            row_label = raw.get("legs") or raw.get("slip_id") or f"row {row_index}"
            if void_count:
                payout = _void_payout(
                    platform,
                    mode,
                    n_legs,
                    void_count,
                    hit_count,
                    miss_count,
                    displayed,
                    profile_dir,
                    row_label=str(row_label),
                )
            elif sportsbook and miss_count > 0:
                payout = 0.0
            else:
                table = resolve_payout(
                    platform,
                    mode,
                    n_legs,
                    displayed_multiplier=displayed,
                    profile_dir=profile_dir,
                )
                payout = table.multiplier_for_hits(hit_count)
            pnl += stake * (payout - 1.0)
    hit_rate = hits / slips if slips else 0.0
    roi = pnl / stake_total if stake_total else 0.0
    return GradeSummary(
        n_slips=slips,
        hits=hits,
        hit_rate=hit_rate,
        stake=stake_total,
        pnl=pnl,
        roi=roi,
        bonus_stake=bonus_stake,
        ticket_ids=ticket_ids,
        markets=markets,
        stake_kinds=stake_kinds,
    )


def _void_payout(
    platform: str,
    mode: str,
    n_legs: int,
    void_count: int,
    hit_count: int,
    miss_count: int,
    displayed: float | None,
    profile_dir: Path | None,
    row_label: str,
) -> float:
    """Payout after voids: sportsbook miss is 0x; all-void is 1x; else settle."""

    effective_legs = n_legs - void_count
    if effective_legs < 1:
        return 1.0
    sportsbook = normalize_platform(platform) in SPORTSBOOK_PLATFORMS
    if sportsbook:
        if miss_count > 0:
            return 0.0
        if displayed is None:
            raise ValueError(
                f"{row_label}: sportsbook void with remaining hits needs the "
                "settled reduced-ticket multiplier (type the in-app price; "
                "Cemini does not invent SGP step-downs)"
            )
        table = resolve_payout(
            platform,
            mode,
            effective_legs,
            displayed_multiplier=displayed,
            profile_dir=profile_dir,
        )
        return table.all_hit
    try:
        table = resolve_payout(platform, mode, effective_legs, profile_dir=profile_dir)
    except (ValueError, FileNotFoundError):
        return 1.0
    return table.multiplier_for_hits(hit_count)


def write_grade(summary: GradeSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(summary), indent=2) + "\n", encoding="utf-8")
