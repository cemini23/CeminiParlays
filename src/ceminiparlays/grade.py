from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ceminiparlays.closings import line_clv, read_prop_closes, side_implied
from ceminiparlays.ceminidfs import distribution_index
from ceminiparlays.io import read_games
from ceminiparlays.markets import is_two_plus_td
from ceminiparlays.odds import american_to_decimal
from ceminiparlays.payouts import SPORTSBOOK_PLATFORMS, normalize_platform, resolve_payout
from ceminiparlays.proppricing import p_dfs_over

#: A probability difference to basis points. CLV is stored as a difference.
BPS = 10_000.0

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
    "player_key",
    "bet_over",
    "bet_under",
    "close_over",
    "close_under",
    "close_lines",
    "clv_pp",
    "clv_line",
    "promo_terms",
    "promo_value",
    "promo_settled",
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
    clv_by_ticket: list[dict[str, object]] = field(default_factory=list)
    clv_mean_pp: float = 0.0
    #: One dict per leg that carries both the CeminiDFS forecast and the closing
    #: consensus: p_dfs_over, close_fair_prob, actual_hit. Empty without a handoff.
    brier_pairs: list[dict[str, float]] = field(default_factory=list)
    promo_terms: list[str] = field(default_factory=list)
    promo_value: float = 0.0
    promo_confirmed: bool = True
    net_pnl: float = 0.0
    hold_tickets: list[str] = field(default_factory=list)


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
    """True for an explicit American price: ``+288`` or ``-110``.

    A bare integer is a DECIMAL multiplier. ``120`` is 120.0x, not +120 (2.2x):
    on an 8-leg Underdog slip ``120`` is the table multiplier, and reading it as
    American turned a $1,190 win into $12 (A-10).
    """

    if "." in text or "e" in text.lower():
        return False
    if not text.startswith(("+", "-")):
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
        explicit = _EXPLICIT_LEG_STATUS.get(actual_raw.strip().lower())
        if explicit is not None and not _looks_numeric(actual_raw):
            if explicit == "HIT":
                hits += 1
            elif explicit == "VOID":
                voids += 1
            elif explicit == "MISS":
                misses += 1
            continue
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


_EXPLICIT_LEG_STATUS = {
    "miss": "MISS",
    "loss": "MISS",
    "lost": "MISS",
    "void": "VOID",
    "push": "VOID",
    "pending": "PENDING",
    "ungraded": "UNGRADED",
    "hit": "HIT",
    "win": "HIT",
    "won": "HIT",
}


def leg_status_labels(raw: dict[str, str]) -> list[str]:
    """One status per captured leg: ``HIT``, ``MISS``, ``VOID``, ``PENDING``, ``UNGRADED``.

    An explicit token is read before a numeric grade. A blank actual is
    ``UNGRADED``. A numeric push is ``VOID``.
    """

    sides = [part.strip().lower() for part in raw.get("sides", "").split("|") if part.strip()]
    actual_parts = [part.strip() for part in raw.get("actuals", "").split("|")]
    line_parts = [part.strip() for part in raw.get("lines", "").split("|")]
    market_parts = [part.strip() for part in raw.get("market", "").split("|") if part.strip()]
    if not sides and raw.get("leg_statuses"):
        return [part.strip().upper() for part in raw["leg_statuses"].split("|") if part.strip()]
    labels: list[str] = []
    width = max(len(sides), len(actual_parts), len(line_parts))
    for index in range(width):
        actual_raw = actual_parts[index].strip() if index < len(actual_parts) else ""
        explicit = _EXPLICIT_LEG_STATUS.get(actual_raw.lower())
        if explicit is not None and not _looks_numeric(actual_raw):
            labels.append(explicit)
            continue
        if not actual_raw:
            labels.append("UNGRADED")
            continue
        side = sides[index] if index < len(sides) else ""
        line_raw = line_parts[index] if index < len(line_parts) else ""
        try:
            actual = _parse_leg_token(actual_raw)
            line = _parse_leg_token(line_raw)
        except (TypeError, ValueError):
            labels.append("UNGRADED")
            continue
        stat_type = market_parts[index] if index < len(market_parts) else ""
        result = _grade_leg(side, actual, line, canonical_ledger_market(stat_type))
        labels.append({"hit": "HIT", "miss": "MISS", "void": "VOID"}[result])
    return labels


def _looks_numeric(text: str) -> bool:
    try:
        float(text)
    except (TypeError, ValueError):
        return False
    return True


def ticket_is_lost(labels: list[str]) -> bool:
    """A single ``MISS`` loses the parlay before a void or a pending leg matters."""

    return any(label == "MISS" for label in labels)


def ticket_is_held(labels: list[str]) -> bool:
    """Hold only when the ticket is not already lost and a leg is still open."""

    if ticket_is_lost(labels):
        return False
    return any(label in {"PENDING", "UNGRADED"} for label in labels)


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
    """Read the ticket ids off a compose card. CSV or card.json is allowed.

    A CSV card carries a ``ticket_id`` column. A ``card.json`` carries a
    ``tickets`` list, each with a ``ticket_id``. An empty ticket list (a null
    card) is legal and yields no ids, so every booked ticket is off-card.
    """

    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        tickets = data.get("tickets") if isinstance(data, dict) else None
        if not isinstance(tickets, list):
            raise ValueError(f"{path} has no tickets list")
        return {
            str(item.get("ticket_id", "")).strip()
            for item in tickets
            if isinstance(item, dict) and str(item.get("ticket_id", "")).strip()
        }
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


def _cells(raw: dict[str, str], key: str) -> list[str]:
    """Split a ``|``-joined ledger cell. Blank parts are dropped."""

    return [part.strip() for part in (raw.get(key) or "").split("|") if part.strip()]


def _cell_int(parts: list[str], index: int) -> int | None:
    if index >= len(parts):
        return None
    text = parts[index]
    try:
        return int(text)
    except ValueError:
        return None


def _cell_float(parts: list[str], index: int) -> float | None:
    if index >= len(parts):
        return None
    try:
        return float(parts[index])
    except ValueError:
        return None


def _actual_hit(side: str, actual_raw: str, line: object, stat_type: str) -> float | None:
    """1.0 for a hit, 0.0 for a miss, ``None`` for a void or an unreadable leg."""

    if not str(actual_raw or "").strip() or not str(line or "").strip():
        return None
    try:
        actual = _parse_leg_token(str(actual_raw))
        parsed_line = _parse_leg_token(str(line))
        result = _grade_leg(side, actual, parsed_line, stat_type)
    except (ValueError, TypeError):
        return None
    if result == "hit":
        return 1.0
    if result == "void":
        return None
    return 0.0


#: Ledger cells that carry a per-leg CLV.
_CLV_CELLS = (
    "sides",
    "lines",
    "player_key",
    "market",
    "actuals",
    "bet_over",
    "bet_under",
    "close_over",
    "close_under",
    "close_lines",
)


def _typed_or_snapshot(value, fallback):
    """A typed cell wins. The closing snapshot fills a blank cell."""

    return fallback if value is None else value


def _leg_prices(index: int, cells: dict[str, list[str]], close) -> tuple:
    """Bet and close prices for one leg, with the snapshot filling the blanks."""

    bet_line = _cell_float(cells["lines"], index)
    close_line = _cell_float(cells["close_lines"], index)
    over_close = _cell_int(cells["close_over"], index)
    under_close = _cell_int(cells["close_under"], index)
    if close is not None:
        over_close = _typed_or_snapshot(over_close, close.over)
        under_close = _typed_or_snapshot(under_close, close.under)
        close_line = _typed_or_snapshot(close_line, close.line)
    return (
        _cell_int(cells["bet_over"], index),
        _cell_int(cells["bet_under"], index),
        over_close,
        under_close,
        bet_line,
        close_line,
    )


def _attach_handoff(
    leg: dict[str, object],
    index: int,
    cells: dict[str, list[str]],
    handoff_index: dict | None,
    side: str,
    stat: str,
    bet_line: float | None,
    close_implied: float | None,
) -> None:
    """Score the handoff forecast against the close, when both are present."""

    if not handoff_index or close_implied is None or bet_line is None:
        return
    dist = handoff_index.get((leg["player_key"], stat))
    actuals = cells["actuals"]
    lines = cells["lines"]
    hit = _actual_hit(
        side,
        actuals[index] if index < len(actuals) else "",
        lines[index] if index < len(lines) else "",
        stat,
    )
    if dist is None or hit is None:
        return
    try:
        p_dfs, _family = p_dfs_over(dist, bet_line, stat_type=stat)
    except (ValueError, TypeError):
        return
    leg["p_dfs_over"] = p_dfs
    leg["actual_hit"] = hit
    leg["dfs_vs_close_brier_delta"] = (p_dfs - hit) ** 2 - (close_implied - hit) ** 2


def _clv_leg(
    index: int,
    side: str,
    stat: str,
    player_key: str,
    cells: dict[str, list[str]],
    close,
    method: str,
    handoff_index: dict | None,
) -> dict[str, object]:
    over_bet, under_bet, over_close, under_close, bet_line, close_line = _leg_prices(
        index, cells, close
    )
    bet_implied = side_implied(side, over_bet, under_bet, method=method)
    close_implied = side_implied(side, over_close, under_close, method=method)
    clv_pp = (
        close_implied - bet_implied
        if bet_implied is not None and close_implied is not None
        else None
    )
    clv_move = (
        line_clv(side, bet_line, close_line)
        if bet_line is not None and close_line is not None
        else None
    )
    leg: dict[str, object] = {
        "player_key": player_key,
        "stat_type": stat,
        "side": side,
        "bet_line": bet_line,
        "close_line": close_line,
        "bet_implied_p": bet_implied,
        "close_implied_p": close_implied,
        "clv_pp": clv_pp,
        "clv_line": clv_move,
        "leg_clv_bps": None if clv_pp is None else clv_pp * BPS,
        "p_dfs_over": None,
        "actual_hit": None,
        "dfs_vs_close_brier_delta": None,
    }
    _attach_handoff(leg, index, cells, handoff_index, side, stat, bet_line, close_implied)
    return leg


def _row_clv(
    raw: dict[str, str],
    closes: dict | None,
    platform: str,
    method: str = "power",
    handoff_index: dict[tuple[str, str], object] | None = None,
) -> dict[str, object]:
    """Per-leg CLV for one ledger row. Blank when the prices are not typed.

    The bet-time and closing prices come from the ledger cells ``bet_over`` /
    ``bet_under`` / ``close_over`` / ``close_under``. A blank close cell is
    filled from the closing snapshot by (platform, player_key, stat_type, side).
    CLV is the closing implied minus the bet implied. Positive beats the close.

    ``leg_clv_bps`` is that same difference in basis points. When a CeminiDFS
    handoff supplies a distribution, ``dfs_vs_close_brier_delta`` compares the
    handoff's forecast against the closing consensus on the realized result.
    """

    cells = {key: _cells(raw, key) for key in _CLV_CELLS}
    stats = [canonical_ledger_market(part) for part in cells["market"]]
    legs: list[dict[str, object]] = []
    values: list[float] = []
    for index, side in enumerate(cells["sides"]):
        stat = stats[index] if index < len(stats) else ""
        player_key = cells["player_key"][index] if index < len(cells["player_key"]) else ""
        close = _closing_row(closes, platform, player_key, stat, side)
        leg = _clv_leg(
            index, side, stat, player_key, cells, close, method, handoff_index
        )
        if leg["clv_pp"] is not None:
            values.append(leg["clv_pp"])  # type: ignore[arg-type]
        legs.append(leg)
    mean = sum(values) / len(values) if values else 0.0
    return {"legs": legs, "mean_pp": mean, "n": len(values)}


def _closing_row(closes: dict | None, platform: str, player_key: str, stat: str, side: str):
    if closes is None or not player_key or not stat:
        return None
    return closes.get((platform, player_key, stat, side.lower()))


@dataclass
class _LedgerEnv:
    """The files and indexes one grade run reads."""

    window: dict | None
    card_ids: set[str] | None
    closes: dict | None
    handoff_index: dict
    default_platform: str | None
    profile_dir: Path | None


@dataclass
class _Row:
    """One settled ledger row, once the refusals and the hold are behind it."""

    stake: float
    hit_count: int
    miss_count: int
    void_count: int
    labels: list[str]
    effective_n_legs: int
    ticket_id: str
    stake_kind: str
    off_card: bool


def _row_identity(raw: dict[str, str]) -> tuple[bool, bool, str, int | None, int]:
    """(id_refuse, clipped, id_label, visible N-Bet, captured legs)."""

    raw_ticket_id = (raw.get("ticket_id") or "").strip()
    id_refuse, clipped, id_label = _classify_ticket_id(
        raw_ticket_id,
        raw.get("ticket_id_clipped") or "",
    )
    return id_refuse, clipped, id_label, _visible_n_bet(raw), _count_captured_legs(raw)


def _refusal_reasons(
    id_refuse: bool, n_bet_count: int | None, captured_legs: int
) -> list[str]:
    reasons: list[str] = []
    if n_bet_count is not None and captured_legs != n_bet_count:
        reasons.append("n_bet")
    if id_refuse:
        reasons.append("ticket_id")
    return reasons


def _pipe_cells(raw: dict[str, str], key: str) -> list[str]:
    return [part.strip() for part in raw.get(key, "").split("|") if part.strip()]


def _player_cells(raw: dict[str, str]) -> list[str]:
    """The player_name column, or the legs column when that one is blank."""

    players = _pipe_cells(raw, "player_name")
    if not players and raw.get("legs"):
        return _pipe_cells(raw, "legs")
    return players


def _record_partial(
    raw: dict[str, str],
    id_label: str,
    clipped: bool,
    n_bet_count: int | None,
    captured_legs: int,
    reasons: list[str],
    off_card: bool,
) -> tuple[str, dict[str, object]]:
    """The refusal note and the partial-ticket record."""

    status = id_label if id_label.startswith("PARTIAL") else "PARTIAL"
    note = f"{status}: capture incomplete"
    if "n_bet" in reasons:
        note += f" — captured legs {captured_legs} != N-Bet {n_bet_count}"
    if clipped:
        note += " — ticket_id clipped"
    return note, {
        "status": status,
        "ticket_id": id_label,
        "clipped": clipped,
        "visible_n_bet": n_bet_count,
        "captured_legs": captured_legs,
        "stake": (raw.get("stake") or "").strip(),
        "reasons": reasons,
        "off_card": off_card,
    }


def _payout_for(
    raw: dict[str, str],
    row_index: int,
    labels: list[str],
    hit_count: int,
    miss_count: int,
    void_count: int,
    effective_n_legs: int,
    mode: str,
    displayed: float | None,
    platform: str,
    profile_dir: Path | None,
) -> float:
    """The payout multiplier for a settled ticket."""

    sportsbook = platform in SPORTSBOOK_PLATFORMS
    open_leg = any(label in {"PENDING", "UNGRADED"} for label in labels)
    row_label = raw.get("legs") or raw.get("slip_id") or f"row {row_index}"
    # A miss settles before a void or a still-open leg can hold the ticket. A
    # numeric pick'em push stays on ``_void_payout``.
    if ticket_is_lost(labels) and (sportsbook or open_leg):
        return 0.0
    if void_count:
        return _void_payout(
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
    if sportsbook and miss_count > 0:
        return 0.0
    table = resolve_payout(
        platform,
        mode,
        effective_n_legs,
        displayed_multiplier=displayed,
        profile_dir=profile_dir,
    )
    return table.multiplier_for_hits(hit_count)


def _paid_row(
    stake: float, stake_kind: str, paid_value: float, miss_count: int
) -> tuple[float, float, float, float]:
    """(pnl, cash, bonus in, bonus out) when the ledger states what was paid."""

    net = paid_value - stake
    if stake_kind == "bonus":
        return net, 0.0, stake, paid_value
    if stake_kind in NO_SWEAT_KINDS and miss_count > 0:
        # A lost No Sweat ticket keeps the cash loss. The book return is a bonus.
        return -stake, -stake, 0.0, paid_value
    return net, net, 0.0, 0.0


def _settled_row(
    raw: dict[str, str],
    row_index: int,
    stake: float,
    stake_kind: str,
    labels: list[str],
    hit_count: int,
    miss_count: int,
    void_count: int,
    effective_n_legs: int,
    mode: str,
    displayed: float | None,
    platform: str,
    profile_dir: Path | None,
) -> tuple[float, float, float, float]:
    """(pnl, cash, bonus in, bonus out) when the ledger is settled from prices."""

    payout = _payout_for(
        raw,
        row_index,
        labels,
        hit_count,
        miss_count,
        void_count,
        effective_n_legs,
        mode,
        displayed,
        platform,
        profile_dir,
    )
    net = stake * (payout - 1.0)
    boosted = _parse_paid(raw.get("displayed_boosted_payout"))
    full_win = (
        miss_count == 0
        and void_count == 0
        and hit_count == effective_n_legs
        and effective_n_legs > 0
    )
    if boosted is not None and boosted > 0.0 and full_win:
        net = boosted - stake
        payout = (boosted / stake) if stake else 0.0
    if stake_kind == "bonus":
        return net, 0.0, stake, stake * payout
    if stake_kind in NO_SWEAT_KINDS and miss_count > 0:
        # A lost ticket keeps the cash loss. A hit uses the cash net.
        return net, -stake, 0.0, 0.0
    return net, net, 0.0, 0.0


@dataclass
class _LedgerState:
    """Every accumulator ``grade_ledger`` writes, and the steps that write them."""

    slips: int = 0
    hits: int = 0
    stake_total: float = 0.0
    pnl: float = 0.0
    cash_pnl: float = 0.0
    bonus_in: float = 0.0
    bonus_out: float = 0.0
    bonus_stake: float = 0.0
    ticket_ids: list[str] = field(default_factory=list)
    markets: list[str] = field(default_factory=list)
    stake_kinds: list[str] = field(default_factory=list)
    slate_ids: list[str] = field(default_factory=list)
    review_flags: list[str] = field(default_factory=list)
    book_actuals: list[str] = field(default_factory=list)
    official_actuals: list[str] = field(default_factory=list)
    partial_tickets: list[dict[str, object]] = field(default_factory=list)
    hold_tickets: list[str] = field(default_factory=list)
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
    replay_reversals: list[str] = field(default_factory=list)
    stat_deltas: list[str] = field(default_factory=list)
    clv_by_ticket: list[dict[str, object]] = field(default_factory=list)
    clv_total: float = 0.0
    clv_count: int = 0
    brier_pairs: list[dict[str, float]] = field(default_factory=list)
    promo_terms: list[str] = field(default_factory=list)
    promo_value: float = 0.0
    promo_confirmed: bool = True

    def add_row(
        self, raw: dict[str, str], row_index: int, env: _LedgerEnv
    ) -> None:
        """One ledger row. A refusal or a hold ends the row early."""

        row = self._open_row(raw, row_index, env)
        if row is None:
            return
        self._close_row(raw, row_index, env, row)

    def _open_row(
        self, raw: dict[str, str], row_index: int, env: _LedgerEnv
    ) -> _Row | None:
        """The refusals and the hold. None means the row is already recorded."""

        id_refuse, clipped, id_label, n_bet_count, captured_legs = _row_identity(raw)
        off_card = _row_off_card(raw, env.window, env.card_ids)
        reasons = _refusal_reasons(id_refuse, n_bet_count, captured_legs)
        if reasons:
            # Refuse finalize. Keep the typed stake text. Do not fill a blank
            # stake, a missing leg, or the cut-off digits.
            note, record = _record_partial(
                raw, id_label, clipped, n_bet_count, captured_legs, reasons, off_card
            )
            self.review_flags.append(note)
            self.partial_tickets.append(record)
            return None

        stake_text = (raw.get("stake") or "").strip()
        if not stake_text:
            raise ValueError(
                f"{id_label or 'row ' + str(row_index)}: blank stake; "
                "type the stake or remove the row"
            )
        # Width check lives in ``_leg_outcomes``. A short actuals cell still
        # raises. It is not an open leg.
        hit_count, miss_count, void_count = _leg_outcomes(raw)
        labels = leg_status_labels(raw)
        if ticket_is_held(labels):
            # A ticket with no miss and an open leg is not a loss and not a
            # win. Keep it off the settled stake.
            hold_label = id_label or f"row {row_index}"
            if hold_label not in self.hold_tickets:
                self.hold_tickets.append(hold_label)
            return None
        return _Row(
            stake=float(stake_text),
            hit_count=hit_count,
            miss_count=miss_count,
            void_count=void_count,
            labels=labels,
            effective_n_legs=n_bet_count if n_bet_count is not None else captured_legs,
            ticket_id=id_label,
            stake_kind=(raw.get("stake_kind") or "").strip().lower(),
            off_card=off_card,
        )

    def _close_row(
        self,
        raw: dict[str, str],
        row_index: int,
        env: _LedgerEnv,
        row: _Row,
    ) -> None:
        """A settled row: the claims, the CLV, the notes, and the money."""

        self._claim_ticket(row.stake, row.stake_kind, row.ticket_id, raw)
        platform = normalize_platform(
            (raw.get("platform") or "").strip() or env.default_platform or "underdog"
        )
        self._record_clv(raw, row.ticket_id, row_index, platform, env)
        self._record_promo(raw)
        mode = raw.get("mode") or "standard"
        displayed = _parse_multiplier(raw.get("multiplier"))
        paid_value = _parse_paid(raw.get("paid"))
        self._record_actuals(raw)
        if row.hit_count == row.effective_n_legs:
            self.hits += 1
        self._record_reviews(raw)
        self._record_notes(raw)
        self.slips += 1
        if paid_value is not None:
            amounts = _paid_row(
                row.stake, row.stake_kind, paid_value, row.miss_count
            )
        else:
            amounts = _settled_row(
                raw,
                row_index,
                row.stake,
                row.stake_kind,
                row.labels,
                row.hit_count,
                row.miss_count,
                row.void_count,
                row.effective_n_legs,
                mode,
                displayed,
                platform,
                env.profile_dir,
            )
        self._post_pnl(amounts, row.off_card, row.ticket_id, row_index)

    def _claim_ticket(
        self, stake: float, stake_kind: str, ticket_id: str, raw: dict[str, str]
    ) -> None:
        self.stake_total += stake
        if stake_kind:
            if stake_kind not in self.stake_kinds:
                self.stake_kinds.append(stake_kind)
            if stake_kind == "bonus":
                self.bonus_stake += stake
        if ticket_id and ticket_id not in self.ticket_ids:
            self.ticket_ids.append(ticket_id)
        self._claim_labels(raw)

    def _claim_labels(self, raw: dict[str, str]) -> None:
        market = (raw.get("market") or "").strip()
        if market:
            canonical_market = _canonical_market_cell(market)
            if canonical_market and canonical_market not in self.markets:
                self.markets.append(canonical_market)
        slate_id = (raw.get("slate_id") or "").strip()
        if slate_id and slate_id not in self.slate_ids:
            self.slate_ids.append(slate_id)

    def _record_clv(
        self,
        raw: dict[str, str],
        ticket_id: str,
        row_index: int,
        platform: str,
        env: _LedgerEnv,
    ) -> None:
        clv = _row_clv(raw, env.closes, platform, handoff_index=env.handoff_index)
        if clv["n"]:
            self.clv_by_ticket.append(
                {"ticket_id": ticket_id or f"row {row_index}", **clv}
            )
            self.clv_total += float(clv["mean_pp"]) * int(clv["n"])
            self.clv_count += int(clv["n"])
        for leg in clv["legs"]:
            delta = leg.get("dfs_vs_close_brier_delta")
            if delta is None:
                continue
            self.brier_pairs.append(
                {
                    "p_dfs_over": float(leg["p_dfs_over"]),
                    "close_fair_prob": float(leg["close_implied_p"]),
                    "actual_hit": float(leg["actual_hit"]),
                }
            )

    def _record_promo(self, raw: dict[str, str]) -> None:
        promo_terms_raw = (raw.get("promo_terms") or "").strip()
        if promo_terms_raw and promo_terms_raw not in self.promo_terms:
            self.promo_terms.append(promo_terms_raw)
        promo_row = _parse_paid(raw.get("promo_value"))
        if promo_row is not None:
            self.promo_value += promo_row
        if promo_terms_raw and not _flag_true(raw.get("promo_settled") or ""):
            self.promo_confirmed = False
            promo_flag = (
                f"PROMO_UNCONFIRMED: {promo_terms_raw} — record the settled "
                "result before you count the bonus"
            )
            if promo_flag not in self.review_flags:
                self.review_flags.append(promo_flag)

    def _record_actuals(self, raw: dict[str, str]) -> None:
        book_actual_raw = (raw.get("book_actual") or "").strip()
        official_actual_raw = (raw.get("official_actual") or "").strip()
        if book_actual_raw:
            self.book_actuals.append(book_actual_raw)
        if official_actual_raw:
            self.official_actuals.append(official_actual_raw)
        if (
            book_actual_raw
            and official_actual_raw
            and book_actual_raw != official_actual_raw
        ):
            self.stat_deltas.append(
                f"STAT_DELTA: book_actual={book_actual_raw} "
                f"official_actual={official_actual_raw}"
            )

    def _record_reviews(self, raw: dict[str, str]) -> None:
        market = (raw.get("market") or "").strip()
        sides = [part.lower() for part in _pipe_cells(raw, "sides")]
        actual_parts = _pipe_cells(raw, "actuals")
        line_parts = _pipe_cells(raw, "lines")
        markets_per_leg = _pipe_cells(raw, "market")
        players_per_leg = _player_cells(raw)
        for index, (_side, actual_raw, line_raw) in enumerate(
            zip(sides, actual_parts, line_parts, strict=True)
        ):
            if _EXPLICIT_LEG_STATUS.get(actual_raw.strip().lower()) and not _looks_numeric(
                actual_raw
            ):
                continue
            actual = _parse_leg_token(actual_raw)
            line = _parse_leg_token(line_raw)
            player = (
                players_per_leg[index]
                if index < len(players_per_leg)
                else f"leg {index + 1}"
            )
            raw_stat = markets_per_leg[index] if index < len(markets_per_leg) else market
            stat_type = canonical_ledger_market(raw_stat)
            yards_review = _check_yards_review(line, actual, player, stat_type)
            if yards_review:
                self.review_flags.append(yards_review)
            first_td_review = _check_first_td_review(player, stat_type)
            if first_td_review:
                self.review_flags.append(first_td_review)

    def _record_notes(self, raw: dict[str, str]) -> None:
        for alert in _injury_alerts(raw):
            if alert not in self.injury_alerts:
                self.injury_alerts.append(alert)
        for note in _replay_notes(raw):
            if note not in self.replay_reversals:
                self.replay_reversals.append(note)

    def _post_pnl(
        self,
        amounts: tuple[float, float, float, float],
        off_card: bool,
        ticket_id: str,
        row_index: int,
    ) -> None:
        row_pnl, row_cash, row_bonus_in, row_bonus_out = amounts
        self.pnl += row_pnl
        self.cash_pnl += row_cash
        self.bonus_in += row_bonus_in
        self.bonus_out += row_bonus_out
        if off_card:
            self.off_card_pnl += row_pnl
            self.off_card_cash_pnl += row_cash
            self.off_card_bonus_in += row_bonus_in
            self.off_card_bonus_out += row_bonus_out
            label = ticket_id or f"row {row_index}"
            if label not in self.off_card_tickets:
                self.off_card_tickets.append(label)
            return
        self.on_card_pnl += row_pnl
        self.on_card_cash_pnl += row_cash
        self.on_card_bonus_in += row_bonus_in
        self.on_card_bonus_out += row_bonus_out

    def summary(self) -> GradeSummary:
        hit_rate = self.hits / self.slips if self.slips else 0.0
        roi = self.pnl / self.stake_total if self.stake_total else 0.0
        return GradeSummary(
            n_slips=self.slips,
            hits=self.hits,
            hit_rate=hit_rate,
            stake=self.stake_total,
            pnl=self.pnl,
            roi=roi,
            bonus_stake=self.bonus_stake,
            ticket_ids=self.ticket_ids,
            markets=self.markets,
            stake_kinds=self.stake_kinds,
            slate_ids=self.slate_ids,
            cash_pnl=self.cash_pnl,
            bonus_in=self.bonus_in,
            bonus_out=self.bonus_out,
            review_flags=self.review_flags,
            hard_rock_rule_note=_hard_rock_injury_rule_note(),
            book_actuals=self.book_actuals,
            official_actuals=self.official_actuals,
            partial_tickets=self.partial_tickets,
            on_card_pnl=self.on_card_pnl,
            off_card_pnl=self.off_card_pnl,
            on_card_cash_pnl=self.on_card_cash_pnl,
            off_card_cash_pnl=self.off_card_cash_pnl,
            on_card_bonus_in=self.on_card_bonus_in,
            off_card_bonus_in=self.off_card_bonus_in,
            on_card_bonus_out=self.on_card_bonus_out,
            off_card_bonus_out=self.off_card_bonus_out,
            off_card_tickets=self.off_card_tickets,
            injury_alerts=self.injury_alerts,
            stay_live_rule=STAY_LIVE_RULE,
            replay_reversals=self.replay_reversals,
            stat_deltas=self.stat_deltas,
            clv_by_ticket=self.clv_by_ticket,
            clv_mean_pp=(self.clv_total / self.clv_count if self.clv_count else 0.0),
            brier_pairs=self.brier_pairs,
            promo_terms=self.promo_terms,
            promo_value=self.promo_value,
            promo_confirmed=self.promo_confirmed,
            net_pnl=self.cash_pnl + self.promo_value,
            hold_tickets=self.hold_tickets,
        )


def grade_ledger(
    path: Path,
    profile_dir: Path | None = None,
    default_platform: str | None = None,
    games_path: Path | None = None,
    card_path: Path | None = None,
    closings_path: Path | None = None,
    handoff: object | None = None,
) -> GradeSummary:
    env = _LedgerEnv(
        window=_window_index(games_path) if games_path is not None else None,
        card_ids=_card_ticket_ids(card_path) if card_path is not None else None,
        closes=read_prop_closes(closings_path) if closings_path is not None else None,
        handoff_index=distribution_index(handoff),
        default_platform=default_platform,
        profile_dir=profile_dir,
    )
    state = _LedgerState()
    with path.open(newline="", encoding="utf-8") as handle:
        for row_index, raw in enumerate(csv.DictReader(handle), start=2):
            state.add_row(raw, row_index, env)
    return state.summary()


def export_settled_and_hold(
    source: Path,
    hold_ids: list[str],
    ledger_out: Path,
    hold_out: Path,
) -> None:
    """Write settled rows to ``ledger_out`` and open rows to ``hold_out``.

    A lost ticket stays on the settled ledger when another leg is void or
    pending. Only a ticket id in ``hold_ids`` goes to the hold file.
    """

    hold = {item.strip() for item in hold_ids if item.strip()}
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    settled: list[dict[str, str]] = []
    held: list[dict[str, str]] = []
    for index, row in enumerate(rows, start=2):
        ticket = (row.get("ticket_id") or "").strip() or f"row {index}"
        if ticket in hold:
            held.append(row)
        else:
            settled.append(row)
    for path, body in ((ledger_out, settled), (hold_out, held)):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(body)


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
        if mode.lower() == "flex" and effective_legs == 2:
            # A 3-leg Flex with one void steps down to a 2-leg ticket. Flex has
            # no 2-leg row, so settle it as the 2-leg Standard / Power payout
            # (3.5x / 3.0x) instead of refunding (A-10).
            try:
                table = resolve_payout(
                    platform, "standard", effective_legs, profile_dir=profile_dir
                )
            except (ValueError, FileNotFoundError):
                return 1.0
        else:
            return 1.0
    return table.multiplier_for_hits(hit_count)


def write_grade(summary: GradeSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(summary), indent=2) + "\n", encoding="utf-8")
