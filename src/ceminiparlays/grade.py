from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ceminiparlays.io import read_games
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
OPTIONAL_LEDGER_COLUMNS = (
    "ticket_id",
    "ticket_id_clipped",
    "n_bet",
    "visible_n_bet",
    "market",
    "stake_kind",
    "paid",
    "boost",
    "slate_id",
    "book_actual",
    "official_actual",
    "game",
    "game_id",
    "games",
    "team",
    "opp",
    "opponent",
    "player_name",
    "injury_status",
    "replay_reversal",
    "off_card",
)
#: A Hard Rock ticket id from the bet slip is 18 or 19 digits. A shorter digit
#: string is a clipped OCR read. Do not pad it.
TICKET_ID_DIGITS = range(18, 20)


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
    partial_tickets: list[dict[str, object]] = field(default_factory=list)
    on_card_pnl: float = 0.0
    off_card_pnl: float = 0.0
    on_card_cash_pnl: float = 0.0
    off_card_cash_pnl: float = 0.0
    on_card_bonus_in: float = 0.0
    off_card_bonus_in: float = 0.0
    on_card_bonus_out: float = 0.0
    off_card_bonus_out: float = 0.0
    off_card_tickets: list[str] = field(default_factory=list)
    injury_alerts: list[str] = field(default_factory=list)
    stay_live_rule: str = ""
    replay_reversals: list[str] = field(default_factory=list)
    stat_deltas: list[str] = field(default_factory=list)


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
#: Paper ticket phrases that map onto ledger markets. This is a name map.
#: ``two_plus_td`` still uses the count rule. ``pass_td`` is ``pass_tds``.
_LEDGER_MARKETS = {
    "two_plus_td": "two_plus_td",
    "two+td": "two_plus_td",
    "2+td": "two_plus_td",
    "2+ td": "two_plus_td",
    "2+ tds": "two_plus_td",
    "to score 2+ td": "two_plus_td",
    "to score 2+ tds": "two_plus_td",
    "pass_td": "pass_tds",
    "pass_tds": "pass_tds",
    "passing td": "pass_tds",
    "passing tds": "pass_tds",
}


def canonical_ledger_market(token: str) -> str:
    """Map a ledger market phrase onto the CLI token. Unknown text stays as typed."""

    text = " ".join((token or "").strip().lower().split())
    return _LEDGER_MARKETS.get(text, text)


def _canonical_market_cell(cell: str) -> str:
    return "|".join(canonical_ledger_market(part) for part in (cell or "").split("|"))


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
        result = _grade_leg(side, actual, line, canonical_ledger_market(stat_type))
        if result == "hit":
            hits += 1
        elif result == "void":
            voids += 1
        else:
            misses += 1
    return hits, misses, voids


def _parse_n_bet_count(raw_n_legs: str, raw_legs: str) -> int | None:
    """Parse an integer N-Bet count. A non-integer is not a count."""

    text = (raw_n_legs or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _visible_n_bet(raw: dict[str, str]) -> int | None:
    """On-screen N-Bet. Prefer ``n_bet``, then ``n_legs``, then a pipe list.

    A single label in ``legs`` is not an N-Bet. Do not invent a count.
    """

    for key in ("n_bet", "visible_n_bet", "n_legs"):
        count = _parse_n_bet_count(raw.get(key) or "", "")
        if count is not None:
            return count
    legs = (raw.get("legs") or "").strip()
    if "|" in legs:
        return len([part for part in legs.split("|") if part.strip()])
    return None


def _count_captured_legs(raw: dict[str, str]) -> int:
    """Count captured legs from ``sides``. Do not invent a missing leg."""

    return len([part for part in raw.get("sides", "").split("|") if part.strip()])


def _flag_true(raw: str) -> bool:
    return (raw or "").strip().lower() in {"1", "true", "yes", "y", "clipped"}


def _classify_ticket_id(raw_id: str, clipped_raw: str) -> tuple[bool, bool, str]:
    """Return ``(refuse, clipped, label)`` for one OCR or operator id.

    A digit string of 18 or 19 characters is a full book id. Any other digit
    string is clipped. The label is ``PARTIAL-`` plus the visible digits.
    Do not pad and do not drop digits. A non-digit label is an operator id,
    not an OCR book id, unless the clipped flag is set.
    """

    ticket_id = (raw_id or "").strip()
    flagged = _flag_true(clipped_raw)
    if ticket_id.startswith("PARTIAL-"):
        return True, True, ticket_id
    if ticket_id.isdigit():
        # 18–19 digits is a full book id. 6 or more other digits is a clipped
        # OCR read (T5 → 7145520). A 1–5 digit value is an operator index
        # (Week 1 ticket ``3``), not an OCR id. Do not pad either one.
        full = len(ticket_id) in TICKET_ID_DIGITS
        if full and not flagged:
            return False, False, ticket_id
        if flagged or len(ticket_id) >= 6:
            return True, True, f"PARTIAL-{ticket_id}"
        return False, False, ticket_id
    if not ticket_id:
        if flagged:
            return True, True, "PARTIAL"
        return False, False, ""
    if flagged:
        return True, True, f"PARTIAL-{ticket_id}"
    return False, False, ticket_id


def _team_pair(away: str, home: str) -> tuple[str, str] | None:
    left = (away or "").strip().upper()
    right = (home or "").strip().upper()
    if not left or not right:
        return None
    return tuple(sorted({left, right}))


def _pairs_in_text(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for part in (text or "").split("|"):
        piece = part.strip().upper().replace(" ", "")
        if "@" not in piece:
            continue
        away, home = piece.split("@", 1)
        pair = _team_pair(away, home)
        if pair and pair not in pairs:
            pairs.append(pair)
    return pairs


def _row_game_pairs(raw: dict[str, str]) -> list[tuple[str, str]]:
    """Games named on the row. Do not invent a game that was not typed."""

    pairs: list[tuple[str, str]] = []
    for key in ("game", "game_id", "games"):
        for pair in _pairs_in_text(raw.get(key) or ""):
            if pair not in pairs:
                pairs.append(pair)
    if pairs:
        return pairs
    teams = [part.strip().upper() for part in (raw.get("team") or "").split("|") if part.strip()]
    opp_text = raw.get("opp") or raw.get("opponent") or ""
    opps = [part.strip().upper() for part in opp_text.split("|") if part.strip()]
    for team, opp in zip(teams, opps, strict=False):
        pair = _team_pair(team, opp)
        if pair and pair not in pairs:
            pairs.append(pair)
    return pairs


def _window_index(path: Path) -> dict[str, set[tuple[str, str]]]:
    """Slate id → team pairs. The empty key holds every pair in the file."""

    index: dict[str, set[tuple[str, str]]] = {"": set()}
    for game in read_games(path):
        pair = _team_pair(game.away, game.home)
        if pair is None:
            continue
        index.setdefault(game.slate_id, set()).add(pair)
        index[""].add(pair)
    return index


def _outside_window(raw: dict[str, str], index: dict[str, set[tuple[str, str]]]) -> bool:
    """True when a typed game is outside the slate file, or no game was typed."""

    slate = (raw.get("slate_id") or "").strip()
    if slate and slate not in index:
        return True
    window = index[slate] if slate else index.get("", set())
    pairs = _row_game_pairs(raw)
    if not pairs:
        return True
    return any(pair not in window for pair in pairs)


def _card_ticket_ids(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if "ticket_id" not in set(reader.fieldnames or []):
            raise ValueError(f"{path} missing column: ticket_id")
        return {
            (raw.get("ticket_id") or "").strip()
            for raw in reader
            if (raw.get("ticket_id") or "").strip()
        }


def _row_off_card(
    raw: dict[str, str],
    window: dict[str, set[tuple[str, str]]] | None,
    card_ids: set[str] | None,
) -> bool:
    """Tag a booked ticket that is outside the slate window or off the card.

    Either condition is enough. A missing window file does not invent a tag.
    A missing card file does not invent a tag.
    """

    if _flag_true(raw.get("off_card") or ""):
        return True
    outside = window is not None and _outside_window(raw, window)
    untraced = False
    if card_ids is not None:
        untraced = (raw.get("ticket_id") or "").strip() not in card_ids
    return outside or untraced


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


#: Booked-leg statuses that mean the player left during the game.
#: Not scratch tokens. Grade still uses the typed actual.
IN_GAME_LEDGER_STATUSES = {"exit", "left", "concussion"}
STAY_LIVE_RULE = (
    "Stay-live: a player who leaves during the game does not void the leg "
    "and does not cash out. Grade the typed actual. No auto-cashout. "
    "No invented void."
)


def _injury_alerts(raw: dict[str, str]) -> list[str]:
    """Alert for a booked player who left in-game. Do not void or cash out."""

    statuses = [part.strip().lower() for part in (raw.get("injury_status") or "").split("|")]
    players = [part.strip() for part in (raw.get("player_name") or "").split("|") if part.strip()]
    if not players and raw.get("legs"):
        players = [part.strip() for part in raw.get("legs", "").split("|") if part.strip()]
    alerts: list[str] = []
    for index, status in enumerate(statuses):
        if status not in IN_GAME_LEDGER_STATUSES:
            continue
        player = players[index] if index < len(players) else f"leg {index + 1}"
        alerts.append(
            f"IN_GAME_EXIT: {player} status {status} — leg stays live. No cashout."
        )
    return alerts


_REPLAY_TRUE = {"1", "true", "yes", "y", "reversal"}


def _replay_notes(raw: dict[str, str]) -> list[str]:
    """Near-miss notes for a replay reversal. They do not change the grade."""

    flags = [part.strip().lower() for part in (raw.get("replay_reversal") or "").split("|")]
    flags = [part for part in flags if part]
    if not flags:
        return []
    players = [part.strip() for part in (raw.get("player_name") or "").split("|") if part.strip()]
    if not players and raw.get("legs"):
        players = [part.strip() for part in raw.get("legs", "").split("|") if part.strip()]
    stats = [canonical_ledger_market(part) for part in (raw.get("market") or "").split("|") if part.strip()]
    notes: list[str] = []
    if len(flags) == 1:
        if flags[0] not in _REPLAY_TRUE:
            return []
        who = " | ".join(players) if players else "ticket"
        stat = stats[0] if len(stats) == 1 else ""
        label = f"{who} {stat}".strip()
        return [
            f"REPLAY_REVERSAL: {label} — near-miss noted separately. "
            "Grade uses the typed actual."
        ]
    for index, flag in enumerate(flags):
        if flag not in _REPLAY_TRUE:
            continue
        player = players[index] if index < len(players) else f"leg {index + 1}"
        stat = stats[index] if index < len(stats) else ""
        label = f"{player} {stat}".strip()
        notes.append(
            f"REPLAY_REVERSAL: {label} — near-miss noted separately. "
            "Grade uses the typed actual."
        )
    return notes


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
    games_path: Path | None = None,
    card_path: Path | None = None,
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
    partial_tickets: list[dict[str, object]] = []
    on_card_pnl = 0.0
    off_card_pnl = 0.0
    on_card_cash_pnl = 0.0
    off_card_cash_pnl = 0.0
    on_card_bonus_in = 0.0
    off_card_bonus_in = 0.0
    on_card_bonus_out = 0.0
    off_card_bonus_out = 0.0
    off_card_tickets: list[str] = []
    injury_alerts: list[str] = []
    replay_reversals: list[str] = []
    stat_deltas: list[str] = []
    window = _window_index(games_path) if games_path is not None else None
    card_ids = _card_ticket_ids(card_path) if card_path is not None else None
    with path.open(newline="", encoding="utf-8") as handle:
        for row_index, raw in enumerate(csv.DictReader(handle), start=2):
            stake_kind = (raw.get("stake_kind") or "").strip().lower()
            raw_ticket_id = (raw.get("ticket_id") or "").strip()
            market = (raw.get("market") or "").strip()
            slate_id = (raw.get("slate_id") or "").strip()
            n_bet_count = _visible_n_bet(raw)
            captured_legs = _count_captured_legs(raw)
            id_refuse, clipped, id_label = _classify_ticket_id(
                raw_ticket_id,
                raw.get("ticket_id_clipped") or "",
            )
            off_card = _row_off_card(raw, window, card_ids)
            reasons: list[str] = []
            if n_bet_count is not None and captured_legs != n_bet_count:
                reasons.append("n_bet")
            if id_refuse:
                reasons.append("ticket_id")
            if reasons:
                # Refuse finalize. Keep the typed stake text. Do not fill a
                # blank stake, a missing leg, or the cut-off digits.
                status = id_label if id_label.startswith("PARTIAL") else "PARTIAL"
                if not status:
                    status = "PARTIAL"
                note = f"{status}: capture incomplete"
                if "n_bet" in reasons:
                    note += f" — captured legs {captured_legs} != N-Bet {n_bet_count}"
                if clipped:
                    note += " — ticket_id clipped"
                review_flags.append(note)
                partial_tickets.append(
                    {
                        "status": status,
                        "ticket_id": id_label,
                        "clipped": clipped,
                        "visible_n_bet": n_bet_count,
                        "captured_legs": captured_legs,
                        "stake": (raw.get("stake") or "").strip(),
                        "reasons": reasons,
                        "off_card": off_card,
                    }
                )
                continue

            stake = float(raw.get("stake", 1.0) or 1.0)
            ticket_id = id_label
            stake_total += stake
            if stake_kind:
                if stake_kind not in stake_kinds:
                    stake_kinds.append(stake_kind)
                if stake_kind == "bonus":
                    bonus_stake += stake
            
            if ticket_id and ticket_id not in ticket_ids:
                ticket_ids.append(ticket_id)
            if market:
                canonical_market = _canonical_market_cell(market)
                if canonical_market and canonical_market not in markets:
                    markets.append(canonical_market)
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
            if book_actual_raw and official_actual_raw and book_actual_raw != official_actual_raw:
                stat_deltas.append(
                    f"STAT_DELTA: book_actual={book_actual_raw} "
                    f"official_actual={official_actual_raw}"
                )
            
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
                raw_stat = markets_per_leg[i] if i < len(markets_per_leg) else market
                stat_type = canonical_ledger_market(raw_stat)
                
                # ±2 yards review
                yards_review = _check_yards_review(line, actual, player, stat_type)
                if yards_review:
                    review_flags.append(yards_review)
                
                # first_td review
                first_td_review = _check_first_td_review(player, stat_type)
                if first_td_review:
                    review_flags.append(first_td_review)

            for alert in _injury_alerts(raw):
                if alert not in injury_alerts:
                    injury_alerts.append(alert)
            for note in _replay_notes(raw):
                if note not in replay_reversals:
                    replay_reversals.append(note)

            slips += 1
            row_pnl = 0.0
            row_cash = 0.0
            row_bonus_in = 0.0
            row_bonus_out = 0.0
            if paid_value is not None:
                net = paid_value - stake
                if stake_kind == "bonus":
                    row_pnl += net
                    row_bonus_in += stake
                    row_bonus_out += paid_value
                elif stake_kind in NO_SWEAT_KINDS and miss_count > 0:
                    # A lost No Sweat ticket keeps the cash loss. The book
                    # return is a bonus. A winning No Sweat ticket stays cash.
                    row_pnl -= stake
                    row_cash -= stake
                    row_bonus_out += paid_value
                else:
                    row_pnl += net
                    row_cash += net
            else:
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
                row_pnl += net
                if stake_kind == "bonus":
                    row_bonus_in += stake
                    row_bonus_out += stake * payout
                elif stake_kind in NO_SWEAT_KINDS and miss_count > 0:
                    # A lost ticket keeps the cash loss. A hit uses the cash net.
                    row_cash -= stake
                else:
                    row_cash += net
            pnl += row_pnl
            cash_pnl += row_cash
            bonus_in += row_bonus_in
            bonus_out += row_bonus_out
            if off_card:
                off_card_pnl += row_pnl
                off_card_cash_pnl += row_cash
                off_card_bonus_in += row_bonus_in
                off_card_bonus_out += row_bonus_out
                label = ticket_id or f"row {row_index}"
                if label not in off_card_tickets:
                    off_card_tickets.append(label)
            else:
                on_card_pnl += row_pnl
                on_card_cash_pnl += row_cash
                on_card_bonus_in += row_bonus_in
                on_card_bonus_out += row_bonus_out
    
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
        partial_tickets=partial_tickets,
        on_card_pnl=on_card_pnl,
        off_card_pnl=off_card_pnl,
        on_card_cash_pnl=on_card_cash_pnl,
        off_card_cash_pnl=off_card_cash_pnl,
        on_card_bonus_in=on_card_bonus_in,
        off_card_bonus_in=off_card_bonus_in,
        on_card_bonus_out=on_card_bonus_out,
        off_card_bonus_out=off_card_bonus_out,
        off_card_tickets=off_card_tickets,
        injury_alerts=injury_alerts,
        stay_live_rule=STAY_LIVE_RULE,
        replay_reversals=replay_reversals,
        stat_deltas=stat_deltas,
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
