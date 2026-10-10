from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ceminiparlays.markets import is_two_plus_td
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
#: ``boost`` is a note. Payout uses ``multiplier`` only, never ``(1 + boost)``.
OPTIONAL_LEDGER_COLUMNS = ("ticket_id", "market", "stake_kind", "paid", "boost", "slate_id", "book_actual", "official_actual")


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
    slate_ids: list[str] = field(default_factory=list)
    cash_pnl: float = 0.0
    bonus_in: float = 0.0
    bonus_out: float = 0.0
    review_flags: list[str] = field(default_factory=list)
    hard_rock_rule_note: str = ""
    book_actuals: list[str] = field(default_factory=list)
    official_actuals: list[str] = field(default_factory=list)


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


#: ``stake_kind`` values that are settled on the No Sweat path. The stake is
#: real cash and is never refunded, so the cash loss stands. Any book-returned
#: amount is a bonus, never cash.
NO_SWEAT_KINDS = {"no_sweat", "nosweat", "no-sweat"}


def _grade_two_plus_td(side: str, actual: str | float, line: str | float) -> str:
    """Grade ``two_plus_td``: 2 or more hits, under 2 misses. 2 is never a void."""

    if isinstance(actual, str) or isinstance(line, str):
        return "miss"
    if actual >= 2:
        return "hit"
    return "miss"


def _grade_leg(
    side: str,
    actual: str | float,
    line: str | float,
    stat_type: str = "",
) -> str:
    """Return 'hit', 'miss', or 'void' for one leg. Discrete equality is never a void."""

    if is_two_plus_td(stat_type):
        return _grade_two_plus_td(side, actual, line)
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
    yes/no and ML win/loss matching tokens are hits, never voids. ``two_plus_td``
    is the one market where equality is not a void: 2 or more hits.
    """

    if raw.get("hits"):
        hits = int(raw["hits"])
        n_legs = int(raw.get("n_legs") or raw.get("legs") or hits)
        return hits, max(n_legs - hits, 0), 0
    sides = [part.strip().lower() for part in raw.get("sides", "").split("|") if part.strip()]
    actual_parts = [part.strip() for part in raw.get("actuals", "").split("|") if part.strip()]
    line_parts = [part.strip() for part in raw.get("lines", "").split("|") if part.strip()]
    market_parts = [part.strip() for part in raw.get("market", "").split("|") if part.strip()]
    if len(actual_parts) != len(sides) or len(line_parts) != len(sides):
        raise ValueError("sides, lines, and actuals must have the same length")
    hits = misses = voids = 0
    for index, (side, actual_raw, line_raw) in enumerate(
        zip(sides, actual_parts, line_parts, strict=True)
    ):
        actual = _parse_leg_token(actual_raw)
        line = _parse_leg_token(line_raw)
        stat_type = market_parts[index] if index < len(market_parts) else ""
        result = _grade_leg(side, actual, line, stat_type)
        if result == "hit":
            hits += 1
        elif result == "void":
            voids += 1
        else:
            misses += 1
    return hits, misses, voids


def _parse_n_bet_count(raw_n_legs: str, raw_legs: str) -> int | None:
    """Parse the on-screen N-Bet count from n_legs or legs column.
    
    Returns the N-Bet count if clearly determinable, otherwise None.
    - n_legs column: if valid integer, use it
    - legs column: if pipe-separated list, count parts
    - Otherwise: return None (don't enforce gate)
    """
    # First try n_legs column
    raw_n_legs = (raw_n_legs or "").strip()
    if raw_n_legs:
        try:
            return int(raw_n_legs)
        except ValueError:
            pass
    
    # Then try legs column if it's pipe-separated
    raw_legs = (raw_legs or "").strip()
    if raw_legs and "|" in raw_legs:
        return len([p for p in raw_legs.split("|") if p.strip()])
    
    # Can't determine N-Bet count clearly
    return None


def _count_captured_legs(raw: dict[str, str]) -> int:
    """Count the number of captured legs from sides/lines/actuals."""
    sides = [p for p in raw.get("sides", "").split("|") if p.strip()]
    return len(sides)


def _check_yards_review(line: float, actual: float, player: str, stat_type: str) -> str | None:
    """Check if a prop is within 2 yards of the line. Returns review message or None."""
    if isinstance(line, (int, float)) and isinstance(actual, (int, float)):
        diff = abs(actual - line)
        if diff <= 2.0:
            return f"REVIEW: {player} {stat_type} projection {actual} within 2 yards of line {line}"
    return None


def _check_first_td_review(player: str, stat_type: str) -> str | None:
    """Check if leg is first_td. Returns review message or None."""
    if stat_type == "first_td":
        return f"REVIEW: {player} first_td — first score can be an unfeatured player, including a return"
    return None


def _hard_rock_injury_rule_note() -> str:
    """Return the Hard Rock rule for a player hurt after a snap, or NO_EVIDENCE."""
    return (
        "Operator 2026-09-30, no public URL: if the only missed leg is a player "
        "hurt before halftime, Hard Rock pays a bonus bet equal to the original "
        "stake. It is not cash. Week 3 Jefferson $5 ticket qualified and the "
        "bonus was used Monday. Do not build a void. Do not build a cashout."
    )


def grade_ledger(
    path: Path,
    profile_dir: Path | None = None,
    default_platform: str | None = None,
) -> GradeSummary:
    slips = 0
    hits = 0
    stake_total = 0.0
    pnl = 0.0
    cash_pnl = 0.0
    bonus_in = 0.0
    bonus_out = 0.0
    bonus_stake = 0.0
    ticket_ids: list[str] = []
    markets: list[str] = []
    stake_kinds: list[str] = []
    slate_ids: list[str] = []
    review_flags: list[str] = []
    book_actuals: list[str] = []
    official_actuals: list[str] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row_index, raw in enumerate(csv.DictReader(handle), start=2):
            stake = float(raw.get("stake", 1.0) or 1.0)
            stake_kind = (raw.get("stake_kind") or "").strip().lower()
            ticket_id = (raw.get("ticket_id") or "").strip()
            market = (raw.get("market") or "").strip()
            slate_id = (raw.get("slate_id") or "").strip()
            raw_n_legs = raw.get("n_legs") or ""
            raw_legs = raw.get("legs") or ""
            n_bet_count = _parse_n_bet_count(raw_n_legs, raw_legs)
            captured_legs = _count_captured_legs(raw)
            
            # N-Bet count gate: stop/skip when captured legs != on-screen N-Bet count
            if n_bet_count is not None and n_bet_count > 0 and captured_legs != n_bet_count:
                review_flags.append(
                    f"GATE: ticket {ticket_id or f'row {row_index}'} skipped — "
                    f"captured legs ({captured_legs}) != N-Bet count ({n_bet_count})"
                )
                continue
            
            stake_total += stake
            if stake_kind:
                if stake_kind not in stake_kinds:
                    stake_kinds.append(stake_kind)
                if stake_kind == "bonus":
                    bonus_stake += stake
            
            if ticket_id and ticket_id not in ticket_ids:
                ticket_ids.append(ticket_id)
            if market and market not in markets:
                markets.append(market)
            if slate_id and slate_id not in slate_ids:
                slate_ids.append(slate_id)
            
            raw_platform = (raw.get("platform") or "").strip()
            platform = normalize_platform(
                raw_platform or default_platform or "underdog"
            )
            mode = raw.get("mode") or "standard"
            displayed = _parse_multiplier(raw.get("multiplier"))
            paid_value = _parse_paid(raw.get("paid"))
            
            book_actual_raw = (raw.get("book_actual") or "").strip()
            official_actual_raw = (raw.get("official_actual") or "").strip()
            if book_actual_raw:
                book_actuals.append(book_actual_raw)
            if official_actual_raw:
                official_actuals.append(official_actual_raw)
            
            hit_count, miss_count, void_count = _leg_outcomes(raw)
            effective_n_legs = n_bet_count if n_bet_count is not None else captured_legs
            if hit_count == effective_n_legs:
                hits += 1
            
            # Check for review flags on each leg
            sides = [part.strip().lower() for part in raw.get("sides", "").split("|") if part.strip()]
            actual_parts = [part.strip() for part in raw.get("actuals", "").split("|") if part.strip()]
            line_parts = [part.strip() for part in raw.get("lines", "").split("|") if part.strip()]
            markets_per_leg = [part.strip() for part in raw.get("market", "").split("|") if part.strip()]
            players_per_leg = [part.strip() for part in raw.get("player_name", "").split("|") if part.strip()]
            
            # If no player_name column, try to infer from legs column
            if not players_per_leg and raw.get("legs"):
                players_per_leg = [p.strip() for p in raw.get("legs", "").split("|") if p.strip()]
            
            for i, (side, actual_raw, line_raw) in enumerate(zip(sides, actual_parts, line_parts, strict=True)):
                actual = _parse_leg_token(actual_raw)
                line = _parse_leg_token(line_raw)
                player = players_per_leg[i] if i < len(players_per_leg) else f"leg {i+1}"
                stat_type = markets_per_leg[i] if i < len(markets_per_leg) else market
                
                # ±2 yards review
                yards_review = _check_yards_review(line, actual, player, stat_type)
                if yards_review:
                    review_flags.append(yards_review)
                
                # first_td review
                first_td_review = _check_first_td_review(player, stat_type)
                if first_td_review:
                    review_flags.append(first_td_review)
            
            slips += 1
            
            if paid_value is not None:
                net = paid_value - stake
                if stake_kind == "bonus":
                    pnl += net
                    bonus_in += stake
                    bonus_out += paid_value
                elif stake_kind in NO_SWEAT_KINDS and miss_count > 0:
                    # A lost No Sweat ticket keeps the cash loss. The book
                    # return is a bonus. A winning No Sweat ticket stays cash.
                    pnl -= stake
                    cash_pnl -= stake
                    bonus_out += paid_value
                else:
                    pnl += net
                    cash_pnl += net
                continue
            
            sportsbook = platform in SPORTSBOOK_PLATFORMS
            row_label = raw.get("legs") or raw.get("slip_id") or f"row {row_index}"
            if void_count:
                payout = _void_payout(
                    platform,
                    mode,
                    effective_n_legs,
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
                    effective_n_legs,
                    displayed_multiplier=displayed,
                    profile_dir=profile_dir,
                )
                payout = table.multiplier_for_hits(hit_count)
            net = stake * (payout - 1.0)
            pnl += net
            if stake_kind == "bonus":
                bonus_in += stake
                bonus_out += stake * payout
            elif stake_kind in NO_SWEAT_KINDS and miss_count > 0:
                # A lost ticket keeps the cash loss. A hit uses the cash net.
                cash_pnl -= stake
            else:
                cash_pnl += net
    
    hit_rate = hits / slips if slips else 0.0
    roi = pnl / stake_total if stake_total else 0.0
    hard_rock_note = _hard_rock_injury_rule_note()
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
        slate_ids=slate_ids,
        cash_pnl=cash_pnl,
        bonus_in=bonus_in,
        bonus_out=bonus_out,
        review_flags=review_flags,
        hard_rock_rule_note=hard_rock_note,
        book_actuals=book_actuals,
        official_actuals=official_actuals,
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
