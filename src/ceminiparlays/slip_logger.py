"""Fast pre-lock slip logger.

A manual app bet can miss the pre-lock card gate. This module types the slip,
checks the quarterback starters file and the scratches file, then writes
``entered_tickets_DATE.csv`` and ``hardrock_card_DATE.csv``. The caller syncs
the two files into ``parlays-slate/DATE`` and ``parlays-recap/DATE``.

The module does not price a leg, it does not open a socket, and it does not
submit a bet.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

from ceminiparlays.card_sync import sync_named_files
from ceminiparlays.compose import TICKET_FIELDS
from ceminiparlays.inactive_gate import load_scratches
from ceminiparlays.io import write_csv
from ceminiparlays.markets import is_td_market
from ceminiparlays.names import fold_name
from ceminiparlays.slips import LESS_SIDES, MORE_SIDES
from ceminiparlays.sunday_card import norm_name

PLATFORM = "hardrock"
DEFAULT_TICKET_ID = "MANUAL-1"
#: Pipe-separated order for ``--leg`` and the interactive prompt.
LEG_FIELDS = ("player", "market", "side", "line", "book_american_odds", "stake")
SLIP_CSV_FIELDS = ("ticket_id", *LEG_FIELDS)
ENTERED_FIELDS = [
    "ticket_id",
    "leg_num",
    "player_name",
    "market",
    "side",
    "line",
    "american_odds",
    "stake_usd",
    "note",
]
_STARTER_COLUMNS = ("player", "starter")


class SlipInputError(ValueError):
    """A typed leg is not a legal slip row."""


class SlipRejected(ValueError):
    """The slip failed the QB check or the scratch check."""

    def __init__(self, failures: list[str]) -> None:
        self.failures = list(failures)
        super().__init__("slip rejected: " + "; ".join(self.failures))


@dataclass(frozen=True)
class SlipLeg:
    player: str
    market: str
    side: str
    line: float
    book_american_odds: int
    stake: float
    ticket_id: str = DEFAULT_TICKET_ID

    @property
    def stat_type(self) -> str:
        return self.market.strip().lower()

    @property
    def is_pass(self) -> bool:
        return self.stat_type.startswith("pass")


def _clean_side(value: str) -> str:
    token = str(value or "").strip().lower()
    if token in MORE_SIDES or token == "yes":
        return "over"
    if token in LESS_SIDES or token == "no":
        return "under"
    raise SlipInputError(f"side must be over or under: {value!r}")


def _clean_odds(value: object) -> int:
    text = str(value or "").strip().replace("+", "")
    try:
        odds = int(float(text))
    except (TypeError, ValueError) as exc:
        raise SlipInputError(f"American odds are not a number: {value!r}") from exc
    if -100 < odds < 100 or odds == 0:
        raise SlipInputError(f"American odds are outside -100 and +100: {value!r}")
    return odds


def _clean_line(value: object, market: str) -> float:
    text = str(value or "").strip()
    if not text:
        if is_td_market(market):
            return 0.0
        raise SlipInputError(f"line is blank for market {market!r}")
    try:
        line = float(text)
    except ValueError as exc:
        raise SlipInputError(f"line is not a number: {value!r}") from exc
    if not math.isfinite(line) or line < 0.0:
        raise SlipInputError(f"line is not a finite non-negative number: {value!r}")
    return line


def _clean_stake(value: object) -> float:
    try:
        stake = float(str(value or "").strip().lstrip("$"))
    except ValueError as exc:
        raise SlipInputError(f"stake is not a number: {value!r}") from exc
    if not math.isfinite(stake) or stake <= 0.0:
        raise SlipInputError(f"stake must be a positive dollar amount: {value!r}")
    return stake


def _clean_text(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise SlipInputError(f"{field} is blank")
    return text


def build_leg(
    player: object,
    market: object,
    side: object,
    line: object,
    book_american_odds: object,
    stake: object,
    ticket_id: str = DEFAULT_TICKET_ID,
) -> SlipLeg:
    """Validate six typed cells and return one slip leg. Raises on a bad cell."""

    name = _clean_text(player, "player")
    stat = _clean_text(market, "market").lower()
    return SlipLeg(
        player=name,
        market=stat,
        side=_clean_side(str(side or "")),
        line=_clean_line(line, stat),
        book_american_odds=_clean_odds(book_american_odds),
        stake=_clean_stake(stake),
        ticket_id=_clean_text(ticket_id or DEFAULT_TICKET_ID, "ticket_id"),
    )


def parse_leg_text(text: str, ticket_id: str = DEFAULT_TICKET_ID) -> SlipLeg:
    """Parse ``player|market|side|line|odds|stake`` into one leg."""

    parts = [part.strip() for part in str(text or "").split("|")]
    if len(parts) != len(LEG_FIELDS):
        raise SlipInputError(
            "a leg needs six pipe-separated fields: " + "|".join(LEG_FIELDS)
        )
    return build_leg(*parts, ticket_id=ticket_id)


def load_slip_csv(path: Path, default_ticket_id: str = DEFAULT_TICKET_ID) -> list[SlipLeg]:
    """Read a manual slip CSV. ``ticket_id`` is optional; one value fills all rows."""

    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"slip CSV missing: {resolved}")
    legs: list[SlipLeg] = []
    with resolved.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [field for field in LEG_FIELDS if field not in (reader.fieldnames or [])]
        if missing:
            raise SlipInputError("slip CSV is missing columns: " + ", ".join(missing))
        for index, raw in enumerate(reader, start=2):
            ticket_id = (raw.get("ticket_id") or "").strip() or default_ticket_id
            try:
                legs.append(
                    build_leg(
                        raw.get("player"),
                        raw.get("market"),
                        raw.get("side"),
                        raw.get("line"),
                        raw.get("book_american_odds"),
                        raw.get("stake"),
                        ticket_id=ticket_id,
                    )
                )
            except SlipInputError as exc:
                raise SlipInputError(f"{resolved.name} row {index}: {exc}") from exc
    if not legs:
        raise SlipInputError(f"slip CSV has no legs: {resolved}")
    return legs


def read_interactive_legs(
    ticket_id: str = DEFAULT_TICKET_ID,
    prompt=input,
) -> list[SlipLeg]:
    """Prompt for legs until a blank line. One line per leg, pipe separated."""

    legs: list[SlipLeg] = []
    hint = "|".join(LEG_FIELDS)
    while True:
        try:
            text = prompt(f"leg ({hint}) or blank: ")
        except EOFError:
            break
        if not str(text or "").strip():
            break
        legs.append(parse_leg_text(str(text), ticket_id=ticket_id))
    return legs


def _starter_index(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """Map a folded starter name and a folded backup name to its team row."""

    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"qb starters file missing: {resolved}")
    starters: dict[str, dict[str, str]] = {}
    backups: dict[str, dict[str, str]] = {}
    with resolved.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            column = next((name for name in _STARTER_COLUMNS if raw.get(name)), None)
            if column is None:
                continue
            name = norm_name(str(raw.get(column) or ""))
            if name:
                starters[name] = raw
            for part in str(raw.get("backups_hard_exclude") or "").split(";"):
                backup = norm_name(part.split("(")[0].strip())
                if backup:
                    backups.setdefault(backup, raw)
    return starters, backups


def _scratch_statuses(path: Path, names: list[str]) -> dict[str, tuple[str, str]]:
    """Fold the scratches file into ``{folded_name: (status, source)}``."""

    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"scratches file missing: {resolved}")
    return load_scratches(resolved, names)


def validate_slip(
    legs: list[SlipLeg],
    starters: Path | None = None,
    scratches: Path | None = None,
) -> list[str]:
    """Return one failure line per bad leg. An empty list is a clean slip.

    A pass-market leg needs a starters file and must name a listed starter.
    A backup or an unknown name fails. A scratched name fails for every
    market. A missing source file raises ``FileNotFoundError``.
    """

    failures: list[str] = []
    starter_rows: dict[str, dict[str, str]] = {}
    backup_rows: dict[str, dict[str, str]] = {}
    if starters is not None:
        starter_rows, backup_rows = _starter_index(starters)
    for leg in legs:
        if not leg.is_pass:
            continue
        name = norm_name(leg.player)
        if starters is None:
            failures.append(f"QB_STARTERS_MISSING {leg.player} {leg.market}")
            continue
        if name in backup_rows:
            failures.append(
                f"BACKUP_QB {leg.player} {leg.market} "
                f"starter={backup_rows[name].get('starter', '')}"
            )
            continue
        if name not in starter_rows:
            failures.append(f"UNKNOWN_QB {leg.player} {leg.market}")
    if scratches is not None:
        names = [leg.player for leg in legs]
        statuses = _scratch_statuses(scratches, names)
        for leg in legs:
            for key in {fold_name(leg.player), norm_name(leg.player)}:
                if key and key in statuses:
                    status, source = statuses[key]
                    failures.append(
                        f"SCRATCH {leg.player} {leg.market} status={status} source={source}"
                    )
                    break
    return failures


def _entered_rows(legs: list[SlipLeg]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    counters: dict[str, int] = {}
    for leg in legs:
        counters[leg.ticket_id] = counters.get(leg.ticket_id, 0) + 1
        rows.append(
            {
                "ticket_id": leg.ticket_id,
                "leg_num": counters[leg.ticket_id],
                "player_name": leg.player,
                "market": leg.market,
                "side": leg.side,
                "line": f"{leg.line:.2f}",
                "american_odds": f"+{leg.book_american_odds}"
                if leg.book_american_odds > 0
                else str(leg.book_american_odds),
                "stake_usd": f"{leg.stake:.2f}",
                "note": "logged before lock",
            }
        )
    return rows


def _card_rows(legs: list[SlipLeg], slate_date: str, platform: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for leg in legs:
        price = (
            f"+{leg.book_american_odds}" if leg.book_american_odds > 0 else str(leg.book_american_odds)
        )
        rows.append(
            {
                "ticket_id": leg.ticket_id,
                "slate_id": slate_date,
                "platform": platform,
                "player_name": leg.player,
                "player_key": fold_name(leg.player),
                "team": "",
                "opp": "",
                "stat_type": leg.market,
                "line": f"{leg.line:.2f}",
                "side": leg.side,
                "book_over": price if leg.side == "over" else "",
                "book_under": price if leg.side == "under" else "",
                "leg_odds": price,
                "slip_odds": "",
                "slip_multiplier": "",
                "contract_price": "",
                "fair_p": "",
                "injury_status": "",
            }
        )
    return rows


def write_slip_files(
    out_dir: Path,
    slate_date: str,
    legs: list[SlipLeg],
    platform: str = PLATFORM,
) -> tuple[Path, Path]:
    """Write ``hardrock_card_DATE.csv`` and ``entered_tickets_DATE.csv``."""

    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    card_path = folder / f"hardrock_card_{slate_date}.csv"
    entered_path = folder / f"entered_tickets_{slate_date}.csv"
    write_csv(card_path, _card_rows(legs, slate_date, platform), TICKET_FIELDS)
    write_csv(entered_path, _entered_rows(legs), ENTERED_FIELDS)
    return card_path, entered_path


def log_slip(
    legs: list[SlipLeg],
    *,
    slate_date: str,
    out_dir: Path,
    starters: Path | None = None,
    scratches: Path | None = None,
    sync_roots: list[Path] | None = None,
    platform: str = PLATFORM,
) -> tuple[Path, Path, list[Path]]:
    """Validate, write, and sync one typed slip.

    Raises ``SlipRejected`` before any write when a leg fails a check. A
    write happens only for a clean slip.
    """

    if not legs:
        raise SlipInputError("the slip has no legs")
    failures = validate_slip(legs, starters, scratches)
    if failures:
        raise SlipRejected(failures)
    card_path, entered_path = write_slip_files(out_dir, slate_date, legs, platform)
    synced = sync_named_files([card_path, entered_path], slate_date, list(sync_roots or []))
    return card_path, entered_path, synced
