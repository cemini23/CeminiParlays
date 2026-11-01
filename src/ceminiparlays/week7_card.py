"""Week-7 Hard Rock research card for a $25.00 bankroll.

The module prices the Q4 running-back checkdown, the seven validated
quarter markets, and the named full-game scheme leans. It writes a local
ledger. It does not read Hard Rock history, it does not submit a bet, and
it does not invent a price. A missing lines file writes a blocked note and
returns 2.

Quarter target counts stay on the week-6 player file. That file is one week
behind the week-7 cache. This module does not rebuild that file.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from ceminiparlays.book_team import canonical_team
from ceminiparlays.compose import joint_ticket, rank_same_game, redundant_quarter_pair
from ceminiparlays.grade_card import LEDGER_COLUMNS, archive_card_copies
from ceminiparlays.half_edge import normal_over_prob
from ceminiparlays.jev_sizing import (
    HARDROCK_BANKROLL_CENTS,
    HARDROCK_GAME_CAP_CENTS,
    HARDROCK_MIN_EV,
    HARDROCK_TICKET_CAP_CENTS,
    DollarPlay,
    allocate_hardrock_dollars,
)
from ceminiparlays.matchup_math import (
    YPC_SD_FLOOR,
    baseline_volume,
    clip_main_line_prob,
    defense_multiplier,
    fair_over_prob,
    full_game_yard_sigma,
    leg_ev,
)
from ceminiparlays.matchup_score import MAIN_LINES
from ceminiparlays.names import fold_name
from ceminiparlays.odds import american_to_decimal
from ceminiparlays.q4_checkdown import (
    CHECKDOWN_MARKETS,
    CheckdownInputs,
    price_checkdown,
)
from ceminiparlays.sunday_card import PROMOTED, norm_name

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LINES = ROOT / "data/cache/hardrock_nfl_20261025.csv"
DEFAULT_REPORT = ROOT / "docs/2026-10-25-sunday-hardrock-card.md"
DEFAULT_LEDGER = ROOT / "data/bets/2026-10-25_hardrock_card.csv"
DEFAULT_SCRATCHES = ROOT / "parlays-slate/2026-10-25/scratches.csv"
DEFAULT_PLAYERS = ROOT / "data/cache/matchup_players_2026w06.csv"
DEFAULT_TEAMS = ROOT / "data/cache/matchup_teams_2026w06.csv"
DEFAULT_CACHE = Path("/Users/claudiobarone/Projects/CeminiDFS/data/shared_cache/2026_w07")
SLATE_DAY = "2026-10-25"
MISSING_BOARD = (
    "Blocked. The public Hard Rock read returned HTTP 403 CF_WAF_A_CR_DFD7. "
    "No week-7 lines file is on disk. This card does not invent book_american_odds. "
    "No ledger was written."
)
_SCRATCH_TOKENS = frozenset({"out", "ir", "inactive", "doubtful", "nfi", "pup", "suspended"})
_REQUIRED_NEVER = (
    "Lamar Jackson",
    "Davante Adams",
    "Mike Evans",
    "Deebo Samuel Sr.",
    "Emeka Egbuka",
    "Tyler Warren",
    "Theo Johnson",
    "David Montgomery",
    "Brian Robinson",
    "Jeremiyah Love",
    "James Conner",
    "De'Von Achane",
    "Dillon Gabriel",
    "Alec Pierce",
    "Luke Musgrave",
    "Micah Parsons",
    "Kerby Joseph",
    "Sauce Gardner",
)
_PRIORITY = frozenset(
    {
        "kyren williams",
        "christian mccaffrey",
        "bijan robinson",
        "chuba hubbard",
        "bucky irving",
        "alvin kamara",
        "jahmyr gibbs",
        "josh jacobs",
        "tony pollard",
        "tyler allgeier",
        "bam knight",
        "jonathan taylor",
    }
)
_Q_WATCH = frozenset(
    {
        "baker mayfield",
        "puka nacua",
        "breece hall",
        "calvin ridley",
        "carson beck",
        "tyjae spears",
        "rico dowdle",
    }
)
_SCHEME = {
    frozenset({"GB", "DET"}): (("pass_yds", "GB"), ("rec_yds", "GB")),
    frozenset({"CIN", "BAL"}): (("rush_yds", "BAL"),),
    frozenset({"MIA", "NYJ"}): (("rush_yds", "MIA"),),
    frozenset({"TB", "CAR"}): (("rush_yds", "TB"),),
    frozenset({"PIT", "NO"}): (("rush_yds", "PIT"),),
    frozenset({"SF", "ATL"}): (("rush_yds", "SF"), ("rush_yds", "ATL")),
}
_TIER = {"checkdown": "1", "core": "2", "sgp": "3"}


@dataclass(frozen=True)
class GameWindow:
    game_id: str
    away: str
    home: str
    kick_et: str
    wind_mph: float
    roof: str
    pass_fade: bool = False
    pass_note: bool = False


SUNDAY_GAMES = (
    GameWindow("2026_07_PIT_NO", "PIT", "NO", "9:30 AM ET", 17, "open", pass_note=True),
    GameWindow("2026_07_CIN_BAL", "CIN", "BAL", "1:00 PM ET", 2, "open"),
    GameWindow("2026_07_CLE_TEN", "CLE", "TEN", "1:00 PM ET", 0, "open"),
    GameWindow("2026_07_IND_MIN", "IND", "MIN", "1:00 PM ET", 0, "dome"),
    GameWindow("2026_07_MIA_NYJ", "MIA", "NYJ", "1:00 PM ET", 2, "open"),
    GameWindow("2026_07_TB_CAR", "TB", "CAR", "1:00 PM ET", 12, "open", pass_note=True),
    GameWindow("2026_07_NYG_HOU", "NYG", "HOU", "1:00 PM ET", 10, "tbd", pass_note=True),
    GameWindow("2026_07_SF_ATL", "SF", "ATL", "1:00 PM ET", 15, "open", pass_fade=True, pass_note=True),
    GameWindow("2026_07_DEN_ARI", "DEN", "ARI", "4:05 PM ET", 0, "tbd"),
    GameWindow("2026_07_GB_DET", "GB", "DET", "4:25 PM ET", 0, "dome"),
    GameWindow("2026_07_LA_LV", "LAR", "LV", "4:25 PM ET", 0, "dome"),
)
_BY_TEAMS = {frozenset({game.away, game.home}): game for game in SUNDAY_GAMES}


@dataclass(frozen=True)
class PlayView:
    play_id: str
    pool: str
    game_label: str
    kick_et: str
    game_id: str
    legs: tuple[dict, ...]
    display_p: float
    ticket_ev: float
    book_price: str
    note: str


@dataclass(frozen=True)
class WeekTicket:
    ticket_id: str
    tier: str
    pool: str
    game_label: str
    kick_et: str
    game_id: str
    legs: tuple[dict, ...]
    book_price: str
    model_p: float
    tax_ev: float
    stake_cents: int
    note: str


@dataclass(frozen=True)
class WeekCard:
    mode: str
    tickets: tuple[WeekTicket, ...]

    @property
    def stake_cents(self) -> int:
        return sum(ticket.stake_cents for ticket in self.tickets)


def _finite(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _american_int(value: object) -> int | None:
    try:
        number = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if number == 0 or -100 < number < 100:
        return None
    return number


def _american_text(price: int) -> str:
    return f"+{price}" if price > 0 else str(price)


def market_stem(market: str) -> str:
    """Drop a quarter suffix. ``receptions_q4`` and ``receptions`` share a stem."""

    text = (market or "").strip().lower()
    for quarter in ("1", "2", "3", "4"):
        suffix = f"_q{quarter}"
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def _player_token(leg: dict) -> str:
    key = str(leg.get("player_key") or "").strip()
    if key:
        return key
    return norm_name(str(leg.get("player_name") or ""))


def pair_ok(left: dict, right: dict) -> bool:
    """Distinct players stay. Same-player legs need different stat stems."""

    left_key = _player_token(left)
    right_key = _player_token(right)
    if left_key and right_key and left_key != right_key:
        return True
    if redundant_quarter_pair(left, right):
        return False
    left_stem = market_stem(str(left.get("market") or ""))
    right_stem = market_stem(str(right.get("market") or ""))
    return bool(left_stem) and left_stem != right_stem


def is_sunday_kick(commence: str) -> bool:
    """True for a Sunday kickoff from 9:30 AM ET through 4:25 PM ET."""

    text = str(commence or "")
    if len(text) < 13 or not text.startswith(SLATE_DAY):
        return False
    try:
        hour = int(text[11:13])
    except ValueError:
        return False
    return 13 <= hour <= 20


def game_for(team: str, opp: str) -> GameWindow | None:
    away = canonical_team(team)
    home = canonical_team(opp)
    if not away or not home:
        return None
    return _BY_TEAMS.get(frozenset({away, home}))


def load_never(path: Path) -> set[str]:
    """Union the scratch file with the named hard excludes.

    A questionable row stays off this set. A missing file is an error when
    a card is built from lines. The named list is still applied.
    """

    names = {norm_name(name) for name in _REQUIRED_NEVER}
    if not path.is_file():
        raise ValueError(f"scratch file is missing: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            token = str(row.get("token") or "").strip().lower()
            if token not in _SCRATCH_TOKENS:
                continue
            player = norm_name(str(row.get("player") or ""))
            if player:
                names.add(player)
    return names


def confirmed_starters(rows: list[dict], never: set[str]) -> dict[str, str]:
    """One quarterback key per team. Baltimore is Huntley. Cleveland is empty."""

    blocked = {norm_name(name) for name in never}
    best: dict[str, tuple[float, str]] = {}
    huntley = ""
    for row in rows:
        if str(row.get("position") or "").upper() != "QB":
            continue
        name = str(row.get("player_name") or "")
        if norm_name(name) in blocked:
            continue
        team = canonical_team(str(row.get("team") or ""))
        if not team:
            continue
        key = fold_name(name)
        if norm_name(name) == "tyler huntley":
            huntley = key
        yards = _finite(row.get("pass_yds_per_game")) or 0.0
        current = best.get(team)
        if current is None or yards > current[0]:
            best[team] = (yards, key)
    starters = {team: key for team, (_yards, key) in best.items()}
    starters["BAL"] = huntley or "tyler_huntley"
    starters["CLE"] = ""
    return starters


def gate_reason(leg: dict, never: set[str], starters: dict[str, str]) -> str | None:
    """Return a short block code, or ``None`` when the leg may enter."""

    name = norm_name(str(leg.get("player_name") or ""))
    if name in never:
        return "never_enter"
    team = canonical_team(str(leg.get("team") or ""))
    opp = canonical_team(str(leg.get("opp") or ""))
    game = game_for(team, opp)
    if game is None:
        return "off_slate"
    commence = str(leg.get("commence_time") or "")
    if commence and not is_sunday_kick(commence):
        return "off_window"
    market = str(leg.get("market") or "")
    side = str(leg.get("side") or "").lower()
    position = str(leg.get("position") or "").upper()
    if game.pass_fade and market == "pass_yds" and side == "over":
        return "wind_pass_fade"
    pass_market = market.startswith("pass") or market == "interceptions"
    if team == "CLE" and (pass_market or position == "QB"):
        return "cle_unconfirmed"
    if pass_market and position in {"", "QB"}:
        starter = starters.get(team, "")
        token = _player_token(leg)
        if not starter or (token != starter and name != norm_name(starter)):
            return "backup_qb"
    return None


def t90_flags(leg: dict) -> str:
    """Review notes. A note does not remove the leg."""

    notes: list[str] = []
    team = canonical_team(str(leg.get("team") or ""))
    opp = canonical_team(str(leg.get("opp") or ""))
    game = game_for(team, opp)
    market = str(leg.get("market") or "")
    name = norm_name(str(leg.get("player_name") or ""))
    status = str(leg.get("injury_status") or "")
    if game is not None and game.pass_note and (market.startswith("pass") or market == "first_td"):
        notes.append("[WIND_REVIEW_NOTE]")
    if game is not None and game.roof == "tbd":
        notes.append("roof TBD confirm at T-90")
    if name in _Q_WATCH or status.upper().startswith("Q"):
        notes.append("Q confirm at inactives")
    if name == "tyler huntley":
        notes.append("Huntley confirmed starter")
    if leg.get("scheme"):
        notes.append("scheme lean")
    return "; ".join(dict.fromkeys(notes)) if notes else "none"


def funnel_lines(rows: list[dict]) -> list[dict]:
    """Keep one two-way 0.5 line per player and checkdown market.

    A 3.5 line is not a stand-in for the 0.5 funnel.
    """

    chosen: dict[tuple[str, str], dict] = {}
    for row in rows:
        market = str(row.get("stat_type") or row.get("market") or "")
        if market not in CHECKDOWN_MARKETS:
            continue
        line = _finite(row.get("line"))
        if line is None or abs(line - 0.5) > 1e-9:
            continue
        if _american_int(row.get("book_over")) is None:
            continue
        if _american_int(row.get("book_under")) is None:
            continue
        key = (str(row.get("player_key") or ""), market)
        if key[0]:
            chosen[key] = row
    return [chosen[key] for key in sorted(chosen)]


def price_scheme_line(
    *,
    games: float,
    yards_per_game: float,
    def_rate: float | None,
    league_rate: float | None,
    line: float,
    book_over: int,
    book_under: int,
    market: str = "rush_yds",
    player_rmse: float | None = None,
) -> dict | None:
    """Full-game scheme over. The side rule keeps an over only.

    The mean is the full-game yards rate times one defense factor. Pass and
    receiving use the defense Q4 completion rate. Rush uses the light-box
    rate. This is a scheme lean. It is not a two-key validated cell.

    Dispersion is anchored to the full-game RMSE floor, and the printed
    probability stays inside the vig-stripped book band and ``[0.18, 0.78]``.
    """

    base = baseline_volume(games, yards_per_game)
    if base is None:
        return None
    mean = base * defense_multiplier(def_rate, league_rate)
    if mean <= 0.0:
        return None
    try:
        sigma = full_game_yard_sigma(market, float(line), player_rmse)
        p_raw = normal_over_prob(float(line), mean, sigma)
        fair = fair_over_prob(int(book_over), int(book_under))
        p_over = clip_main_line_prob(p_raw, fair)
    except (TypeError, ValueError):
        return None
    if p_over <= fair:
        return None
    ev = leg_ev(p_over, int(book_over))
    if ev < HARDROCK_MIN_EV:
        return None
    return {
        "side": "over",
        "line": float(line),
        "price": int(book_over),
        "model_p": p_over,
        "ev": ev,
        "scheme": True,
    }


def _slip_key(legs: list[dict]) -> tuple:
    return tuple(
        sorted(
            (
                str(leg.get("player_key") or ""),
                str(leg.get("market") or ""),
                str(leg.get("side") or ""),
                str(leg.get("line") or ""),
            )
            for leg in legs
        )
    )


def same_game_slips(legs: list[dict]) -> list[dict]:
    """Taxed same-game pairs plus distinct-player triples from the top six legs."""

    from ceminiparlays.correlation import LegRef, UnmodeledCorrelationError, correlation_matrix

    priced = list(rank_same_game(legs))
    seen = {_slip_key(list(row["legs"])) for row in priced}
    grouped: dict[frozenset[str], list[dict]] = {}
    for leg in legs:
        team = str(leg.get("team") or "")
        opp = str(leg.get("opp") or "")
        if team and opp:
            grouped.setdefault(frozenset({team, opp}), []).append(leg)
    for game_legs in grouped.values():
        ordered = sorted(game_legs, key=lambda item: -float(item.get("ev") or 0.0))[:6]
        for combo in combinations(ordered, 3):
            slip = list(combo)
            if _slip_key(slip) in seen:
                continue
            if any(not pair_ok(left, right) for left, right in combinations(slip, 2)):
                continue
            if len({_player_token(leg) for leg in slip}) < 2:
                continue
            refs = [
                LegRef(
                    player_key=str(leg.get("player_key") or ""),
                    team=str(leg.get("team") or ""),
                    opponent=str(leg.get("opp") or ""),
                    stat_type=str(leg.get("market") or ""),
                    side=str(leg.get("side") or ""),
                )
                for leg in slip
            ]
            try:
                corr = correlation_matrix(refs, regime="neutral")
                ticket = joint_ticket(
                    [float(leg["model_p"]) for leg in slip],
                    [int(float(leg["price"])) for leg in slip],
                    corr,
                )
            except (UnmodeledCorrelationError, TypeError, ValueError):
                continue
            ticket["legs"] = slip
            ticket["n_legs"] = 3
            priced.append(ticket)
            seen.add(_slip_key(slip))
    return priced


def _note_for(legs: list[dict]) -> str:
    notes: list[str] = []
    for leg in legs:
        for note in t90_flags(leg).split("; "):
            if note and note != "none" and note not in notes:
                notes.append(note)
    return "; ".join(notes) if notes else "none"


def _game_label(leg: dict) -> tuple[str, str, str]:
    game = game_for(str(leg.get("team") or ""), str(leg.get("opp") or ""))
    if game is None:
        label = f"{leg.get('team') or ''} @ {leg.get('opp') or ''}"
        return label, str(leg.get("kick_et") or ""), str(leg.get("game_id") or "")
    return f"{game.away} @ {game.home}", game.kick_et, game.game_id


def _stake_keys(legs: list[dict]) -> tuple[str, ...]:
    keys: list[str] = []
    for leg in legs:
        if str(leg.get("market") or "") == "total_q3":
            game = str(leg.get("game_id") or "")
            keys.append(f"total:{game}" if game else "total")
            continue
        token = _player_token(leg)
        if token:
            keys.append(token)
    return tuple(dict.fromkeys(keys))


def _single_pool(leg: dict) -> str | None:
    market = str(leg.get("market") or "")
    side = str(leg.get("side") or "").lower()
    position = str(leg.get("position") or "").upper()
    try:
        ev = float(leg["ev"])
    except (TypeError, ValueError, KeyError):
        return None
    if ev < HARDROCK_MIN_EV:
        return None
    if market in CHECKDOWN_MARKETS and side == "over" and position == "RB" and leg.get("funnel"):
        return "checkdown"
    if market in PROMOTED or leg.get("scheme"):
        return "core"
    return None


def candidate_plays(
    legs: list[dict],
    slips: list[dict],
    *,
    never: set[str],
    starters: dict[str, str],
) -> tuple[list[DollarPlay], dict[str, PlayView]]:
    """Qualifying singles and taxed same-game slips. One view per play id."""

    plays: list[DollarPlay] = []
    views: dict[str, PlayView] = {}
    for leg in legs:
        if gate_reason(leg, never, starters):
            continue
        pool = _single_pool(leg)
        if pool is None:
            continue
        keys = _stake_keys([leg])
        if not keys:
            continue
        price = _american_int(leg.get("price"))
        if price is None:
            continue
        label, kick, game_id = _game_label(leg)
        play_id = f"{pool}:{keys[0]}:{leg.get('market')}:{leg.get('side')}:{leg.get('line')}"
        priority = 0 if pool == "checkdown" and norm_name(str(leg.get("player_name") or "")) in _PRIORITY else 1
        view = PlayView(
            play_id=play_id,
            pool=pool,
            game_label=label,
            kick_et=kick,
            game_id=str(leg.get("game_id") or game_id),
            legs=(leg,),
            display_p=float(leg["model_p"]),
            ticket_ev=float(leg["ev"]),
            book_price=_american_text(price),
            note=_note_for([leg]),
        )
        plays.append(
            DollarPlay(
                play_id=play_id,
                pool=pool,
                game_ids=(view.game_id,),
                player_keys=keys,
                ev=view.ticket_ev,
                model_p=view.display_p,
                decimal_odds=american_to_decimal(price),
                priority=priority,
            )
        )
        views[play_id] = view
    for row in slips:
        slip = list(row.get("legs") or [])
        if len(slip) not in {2, 3}:
            continue
        if not row.get("sgp_tax_applied"):
            continue
        try:
            tax_ev = float(row["tax_adjusted_sgp_ev"])
            joint_p = float(row["joint_p"])
            decimal = float(row["decimal_sgp"])
        except (TypeError, ValueError, KeyError):
            continue
        if tax_ev < HARDROCK_MIN_EV or decimal <= 1.0:
            continue
        if any(gate_reason(leg, never, starters) for leg in slip):
            continue
        if any(not pair_ok(left, right) for left, right in combinations(slip, 2)):
            continue
        keys = _stake_keys(slip)
        if len(keys) < 2:
            continue
        label, kick, game_id = _game_label(slip[0])
        stored_game = str(slip[0].get("game_id") or game_id)
        play_id = "sgp:" + "|".join(
            f"{leg.get('player_key')}:{leg.get('market')}:{leg.get('side')}:{leg.get('line')}"
            for leg in slip
        )
        view = PlayView(
            play_id=play_id,
            pool="sgp",
            game_label=label,
            kick_et=kick,
            game_id=stored_game,
            legs=tuple(slip),
            display_p=joint_p,
            ticket_ev=tax_ev,
            book_price=f"SGP not captured; haircut decimal {decimal:.3f}",
            note=_note_for(slip),
        )
        plays.append(
            DollarPlay(
                play_id=play_id,
                pool="sgp",
                game_ids=(stored_game,),
                player_keys=keys,
                ev=tax_ev,
                model_p=joint_p,
                decimal_odds=decimal,
                priority=1,
            )
        )
        views[play_id] = view
    unique: dict[str, DollarPlay] = {}
    for play in plays:
        current = unique.get(play.play_id)
        if current is None or play.ev > current.ev:
            unique[play.play_id] = play
    return list(unique.values()), views


def exposure_cents(card: WeekCard) -> dict[str, int]:
    """Full ticket stake on every game the ticket touches."""

    exposure: dict[str, int] = {}
    for ticket in card.tickets:
        games = {str(leg.get("game_id") or ticket.game_id) for leg in ticket.legs}
        games.discard("")
        if not games and ticket.game_id:
            games.add(ticket.game_id)
        for game in games:
            exposure[game] = exposure.get(game, 0) + ticket.stake_cents
    return exposure


def validate_week7(card: WeekCard, never: set[str]) -> None:
    """Raise when the stake, the caps, a scratch, or a degenerate pair fails."""

    blocked = {norm_name(name) for name in never}
    if card.stake_cents != HARDROCK_BANKROLL_CENTS:
        raise ValueError(f"stakes sum to {card.stake_cents} cents")
    if card.mode == "A":
        counts = Counter(ticket.stake_cents for ticket in card.tickets)
        if len(card.tickets) != 17 or counts[175] != 6 or counts[170] != 5 or counts[100] != 6:
            raise ValueError("mode A bands are not 6 x $1.75, 5 x $1.70, and 6 x $1.00")
    elif card.mode == "B":
        if not 7 <= len(card.tickets) <= 9:
            raise ValueError("mode B needs 7 to 9 tickets")
    else:
        raise ValueError(f"unknown mode {card.mode}")
    people: set[str] = set()
    for ticket in card.tickets:
        if ticket.stake_cents <= 0 or ticket.stake_cents > HARDROCK_TICKET_CAP_CENTS:
            raise ValueError("a ticket is outside the $4.00 cap")
        if card.mode == "B" and ticket.stake_cents < 200:
            raise ValueError("a mode B ticket is under $2.00")
        for leg in ticket.legs:
            if norm_name(str(leg.get("player_name") or "")) in blocked:
                raise ValueError("a never_enter player is on the card")
        for left, right in combinations(ticket.legs, 2):
            if not pair_ok(left, right):
                raise ValueError("a degenerate pair is on the card")
        for key in _stake_keys(list(ticket.legs)):
            if key.startswith("total:"):
                continue
            if key in people:
                raise ValueError("a player is on two tickets")
            people.add(key)
    if any(cents > HARDROCK_GAME_CAP_CENTS for cents in exposure_cents(card).values()):
        raise ValueError("a game is over the $6.25 cap")


def card_from_plays(
    plays: list[DollarPlay],
    views: dict[str, PlayView],
    never: set[str],
) -> WeekCard:
    """Allocate $25.00 and validate the card. Raises when the caps fail."""

    mode, stakes = allocate_hardrock_dollars(plays)
    tickets: list[WeekTicket] = []
    for index, stake in enumerate(stakes, start=1):
        view = views[stake.play_id]
        tier = "B" if mode == "B" else _TIER[stake.pool]
        tickets.append(
            WeekTicket(
                ticket_id=str(index),
                tier=tier,
                pool=stake.pool,
                game_label=view.game_label,
                kick_et=view.kick_et,
                game_id=view.game_id,
                legs=view.legs,
                book_price=view.book_price,
                model_p=view.display_p,
                tax_ev=view.ticket_ev,
                stake_cents=stake.stake_cents,
                note=view.note,
            )
        )
    card = WeekCard(mode=mode, tickets=tuple(tickets))
    validate_week7(card, never)
    return card


def _leg_text(leg: dict) -> str:
    price = _american_int(leg.get("price"))
    shown = _american_text(price) if price is not None else ""
    line = float(leg["line"])
    return f"{leg.get('player_name')} {leg.get('market')} {leg.get('side')} {line:.1f} ({shown})"


def format_table(card: WeekCard) -> str:
    header = (
        "| Ticket # | Tier | Game & Kick ET | Exact Legs & Side | Book Price | "
        "Model Prob | Tax-Adjusted EV % | Stake $ | T-90 Check Note |"
    )
    rule = "| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |"
    rows = [header, rule]
    for ticket in card.tickets:
        legs = "; ".join(_leg_text(leg) for leg in ticket.legs)
        game = f"{ticket.game_label}, {ticket.kick_et}"
        rows.append(
            "| {tid} | {tier} | {game} | {legs} | {price} | {prob:.6f} | {ev:.1f}% | "
            "${stake:.2f} | {note} |".format(
                tid=ticket.ticket_id,
                tier=ticket.tier,
                game=game,
                legs=legs,
                price=ticket.book_price,
                prob=ticket.model_p,
                ev=ticket.tax_ev * 100.0,
                stake=ticket.stake_cents / 100.0,
                note=ticket.note,
            )
        )
    return "\n".join(rows)


def render_card(card: WeekCard) -> str:
    exposure = exposure_cents(card)
    highest = max(exposure.values()) if exposure else 0
    lines = [
        "# Week 7 Sunday Hard Rock card, 2026-10-25",
        "",
        "Do not type a ticket. Do not submit a bet. This file is a research card for a $25.00 bankroll.",
        "",
        "The slate is unplayed. Model EV is not realized EV. A same-game haircut decimal is not a Hard Rock price.",
        "",
        "## Verdict",
        "",
        (
            f"Mode {card.mode}. The stake sum is $25.00 across {len(card.tickets)} tickets. "
            f"The highest game exposure is ${highest / 100:.2f}. The game cap is $6.25. "
            "The ticket cap is $4.00."
        ),
        "",
        "Quarter target counts come from the week-6 player file. That file lags the week-7 cache by one week.",
        "",
        "## Card",
        "",
        format_table(card),
        "",
        "## Exposure",
        "",
        "| Game | Exposure |",
        "| --- | ---: |",
    ]
    labels = {ticket.game_id: ticket.game_label for ticket in card.tickets}
    for game, cents in sorted(exposure.items(), key=lambda item: -item[1]):
        lines.append(f"| {labels.get(game, game)} | ${cents / 100:.2f} |")
    lines.extend(
        [
            "",
            "## Rules that built the rows",
            "",
            "1. Sunday daytime is 2026-10-25 from 9:30 AM ET through 4:25 PM ET. Thursday, Sunday night, and Monday stay off.",
            "2. A single needs EV after vig of at least 0.08. Tier 1 is a running-back checkdown over at 0.5.",
            "3. Tier 2 is a validated quarter market or a named scheme over. A scheme row is a lean, not a two-key cell.",
            "4. A same-game slip uses distinct players, or orthogonal stats for one player. The 55% tax must apply. Tax-adjusted EV must be at least 0.08.",
            "5. The same player does not appear on two tickets. `receptions_qX` and `rec_yds_qX` do not share a slip.",
            "6. Out, IR, and doubtful players stay off. Cleveland pass props stay off until a quarterback is confirmed. Baltimore passes use Tyler Huntley.",
            "7. `grade_card.py` settles a saved ledger from play-by-play. It does not open Hard Rock history.",
            "",
        ]
    )
    return "\n".join(lines)


def render_blocked(reason: str) -> str:
    return "\n".join(
        [
            "# Week 7 Sunday Hard Rock card, 2026-10-25",
            "",
            "Do not type a ticket. Do not submit a bet.",
            "",
            "## Verdict",
            "",
            reason,
            "",
            "The Q4 checkdown pricer, the $25.00 allocator, and the offline grader are in the package.",
            "When a saved lines file is present, run `python3 -m ceminiparlays.week7_card`.",
            "",
            "No ledger was written. The slate is unplayed. There are no settled actuals yet.",
            "",
            "## Rules that are ready",
            "",
            "1. Hard excludes cover every Out, IR, and doubtful name in `parlays-slate/2026-10-25/scratches.csv`, plus the named list.",
            "2. Tyler Huntley is the Baltimore starter. Cleveland pass props stay off until inactives confirm a quarterback.",
            "3. `SF @ ATL` blocks a full-game `pass_yds` over. A pass leg in wind keeps `[WIND_REVIEW_NOTE]`.",
            "4. A same-game slip cannot pair `receptions_qX` with `rec_yds_qX` for one player.",
            "5. The allocator places exactly $25.00. A ticket cap is $4.00. A game cap is $6.25.",
            "",
        ]
    )


def ledger_rows(card: WeekCard) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for ticket in card.tickets:
        for index, leg in enumerate(ticket.legs, start=1):
            price = _american_int(leg.get("price"))
            rows.append(
                {
                    "ticket_id": ticket.ticket_id,
                    "tier": ticket.tier,
                    "leg_num": str(index),
                    "game_id": str(leg.get("game_id") or ticket.game_id),
                    "kick_et": str(leg.get("kick_et") or ticket.kick_et),
                    "player_name": str(leg.get("player_name") or ""),
                    "gsis_id": str(leg.get("gsis_id") or ""),
                    "team": canonical_team(str(leg.get("team") or "")),
                    "opp": canonical_team(str(leg.get("opp") or "")),
                    "market": str(leg.get("market") or ""),
                    "side": str(leg.get("side") or ""),
                    "line": f"{float(leg['line']):.1f}",
                    "book_american_odds": "" if price is None else str(price),
                    "model_prob": f"{float(leg['model_p']):.6f}",
                    "tax_adj_ev": f"{ticket.tax_ev:.6f}",
                    "ticket_stake_usd": f"{ticket.stake_cents / 100:.2f}",
                    "t90_flag": ticket.note,
                }
            )
    return rows


def write_ledger(card: WeekCard, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(LEDGER_COLUMNS), lineterminator="\n")
        writer.writeheader()
        writer.writerows(ledger_rows(card))
    match = re.search(r"(20\d{2}-\d{2}-\d{2})", path.name)
    if match:
        archive_card_copies(path, match.group(1))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _mean(rows: list[dict], field: str) -> float | None:
    values = [value for row in rows if (value := _finite(row.get(field))) is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _index_telemetry(rows: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    by_gsis: dict[str, dict] = {}
    by_key: dict[str, dict] = {}
    for row in rows:
        gsis = str(row.get("player_id") or "")
        key = fold_name(str(row.get("player_name") or ""))
        if gsis:
            by_gsis[gsis] = row
        if key:
            by_key[key] = row
    return by_gsis, by_key


def _prepare_players(players: list[dict], by_gsis: dict[str, dict]) -> list[dict]:
    prepared = []
    for row in players:
        copied = dict(row)
        source = by_gsis.get(str(copied.get("gsis_id") or ""))
        if source is not None and source.get("team"):
            copied["team"] = canonical_team(str(source.get("team") or ""))
        prepared.append(copied)
    return prepared


def _sunday_lines(lines: list[dict]) -> list[dict]:
    kept = []
    for row in lines:
        if not is_sunday_kick(str(row.get("commence_time") or "")):
            continue
        team = canonical_team(str(row.get("team") or ""))
        opp = canonical_team(str(row.get("opp") or ""))
        game = game_for(team, opp)
        if game is None:
            continue
        copied = dict(row)
        copied["team"] = team
        copied["opp"] = opp
        copied["game_id"] = game.game_id
        copied["kick_et"] = game.kick_et
        kept.append(copied)
    return kept


def _attach_identity(leg: dict, by_key: dict[str, dict]) -> dict | None:
    copied = dict(leg)
    copied["team"] = canonical_team(str(copied.get("team") or ""))
    copied["opp"] = canonical_team(str(copied.get("opp") or ""))
    game = game_for(copied["team"], copied["opp"])
    if game is None:
        return None
    copied["game_id"] = game.game_id
    copied["kick_et"] = game.kick_et
    source = by_key.get(str(copied.get("player_key") or ""))
    if source is not None:
        cache_team = canonical_team(str(source.get("team") or ""))
        if cache_team and copied["team"] and cache_team != copied["team"]:
            return None
        copied["position"] = str(source.get("position") or copied.get("position") or "")
        copied["gsis_id"] = str(source.get("player_id") or copied.get("gsis_id") or "")
    return copied


def _checkdown_leg(
    line: dict,
    player: dict,
    defense: dict | None,
    offense: dict | None,
    counts: dict | None,
    league_trail: float,
    league_cushion: float | None,
    league_comp: float | None,
    league_yac: float | None,
) -> dict | None:
    market = str(line.get("stat_type") or line.get("market") or "")
    quarter = 3 if market.endswith("_q3") else 4
    over = _american_int(line.get("book_over"))
    under = _american_int(line.get("book_under"))
    posted = _finite(line.get("line"))
    if over is None or under is None or posted is None:
        return None
    count_row = counts or {}
    opps_field = "q3_target_n" if quarter == 3 else "q4_target_n"
    sd_field = "q3_ypc_sd" if quarter == 3 else "q4_ypc_sd"
    cushion = _finite(player.get("avg_cushion"))
    if cushion is None or cushion <= 0.0:
        cushion = _finite((defense or {}).get("cushion_allowed"))
    p_gain = _finite((offense or {}).get("p0_rec"))
    if p_gain is None:
        p_gain = 1.0
    inputs = CheckdownInputs(
        games=_finite(player.get("games")) or 0.0,
        receptions_per_game=_finite(player.get("receptions_per_game")) or 0.0,
        rec_yds_per_game=_finite(player.get("rec_yds_per_game")) or 0.0,
        targets_per_game=_finite(player.get("targets_per_game")) or 0.0,
        opps_q=_finite(count_row.get(opps_field)) or 0.0,
        opps_total=_finite(count_row.get("target_n")) or 0.0,
        q4_trail_target_share=_finite(player.get("q4_trail_target_share")),
        vacated_target_boost=_finite(player.get("vacated_target_boost")) or 0.0,
        avg_cushion=cushion,
        def_q4_comp_rate=_finite((defense or {}).get("def_q4_comp_rate")),
        def_q4_yac=_finite((defense or {}).get("def_q4_yac")),
        league_trail_share=league_trail,
        league_cushion=league_cushion,
        league_comp=league_comp,
        league_yac=league_yac,
        quarter=quarter,
        ypc_sd=_finite(count_row.get(sd_field)) or YPC_SD_FLOOR,
        p_gain=p_gain,
        spread=_finite(line.get("spread")),
        game_total=_finite(line.get("game_total")),
        third_down_route_share=_finite(player.get("third_down_route_share")),
        require_script=_finite(line.get("spread")) is not None,
    )
    try:
        priced = price_checkdown(inputs, market, posted, over, under)
    except ValueError:
        return None
    if priced is None:
        return None
    leg = {
        "market": priced.market,
        "player_name": line.get("player_name") or player.get("player_name") or "",
        "player_key": line.get("player_key") or fold_name(str(player.get("player_name") or "")),
        "team": line.get("team") or "",
        "opp": line.get("opp") or "",
        "line": priced.line,
        "side": priced.side,
        "price": priced.price,
        "model_p": priced.model_p,
        "ev": priced.ev,
        "commence_time": line.get("commence_time") or "",
        "injury_status": line.get("injury_status") or "",
        "game_id": line.get("game_id") or "",
        "kick_et": line.get("kick_et") or "",
        "position": "RB",
        "gsis_id": str(player.get("player_id") or ""),
        "funnel": True,
        "scheme": False,
    }
    return leg


def _scheme_legs(
    lines: list[dict],
    by_key: dict[str, dict],
    defense_by_team: dict[str, dict],
    league_comp: float | None,
    league_box: float | None,
    starters: dict[str, str],
) -> list[dict]:
    grouped: dict[tuple[str, str, str], dict] = {}
    for row in lines:
        market = str(row.get("stat_type") or "")
        if market not in {"pass_yds", "rec_yds", "rush_yds"}:
            continue
        if str(row.get("line_type") or "") not in MAIN_LINES:
            continue
        team = canonical_team(str(row.get("team") or ""))
        opp = canonical_team(str(row.get("opp") or ""))
        game = game_for(team, opp)
        if game is None:
            continue
        sides = _SCHEME.get(frozenset({game.away, game.home}), ())
        if (market, team) not in sides:
            continue
        player_key = str(row.get("player_key") or "")
        slot = (player_key, market, str(row.get("commence_time") or ""))
        current = grouped.get(slot)
        if current is None:
            grouped[slot] = row
            continue
        new_over = _american_int(row.get("book_over"))
        new_under = _american_int(row.get("book_under"))
        old_over = _american_int(current.get("book_over"))
        old_under = _american_int(current.get("book_under"))
        if new_over is None or new_under is None:
            continue
        if old_over is None or old_under is None:
            grouped[slot] = row
            continue
        try:
            old_fair = fair_over_prob(old_over, old_under)
            new_fair = fair_over_prob(new_over, new_under)
        except (TypeError, ValueError):
            continue
        if abs(new_fair - 0.5) < abs(old_fair - 0.5):
            grouped[slot] = row
    legs = []
    for row in grouped.values():
        market = str(row.get("stat_type") or "")
        team = canonical_team(str(row.get("team") or ""))
        opp = canonical_team(str(row.get("opp") or ""))
        player = by_key.get(str(row.get("player_key") or ""))
        if player is None:
            continue
        position = str(player.get("position") or "").upper()
        key = str(row.get("player_key") or "")
        if market == "pass_yds" and not (position == "QB" and starters.get(team) == key):
            continue
        if market == "rush_yds" and position not in {"RB", "QB"}:
            continue
        if market == "rush_yds" and position == "QB" and starters.get(team) != key:
            continue
        if market == "rec_yds" and position not in {"WR", "TE", "RB"}:
            continue
        rate_name = "def_light_box_rate" if market == "rush_yds" else "def_q4_comp_rate"
        league = league_box if market == "rush_yds" else league_comp
        yards_name = {
            "pass_yds": "pass_yds_per_game",
            "rush_yds": "rush_yds_per_game",
            "rec_yds": "rec_yds_per_game",
        }[market]
        over = _american_int(row.get("book_over"))
        under = _american_int(row.get("book_under"))
        posted = _finite(row.get("line"))
        if over is None or under is None or posted is None:
            continue
        defense = defense_by_team.get(opp)
        priced = price_scheme_line(
            games=_finite(player.get("games")) or 0.0,
            yards_per_game=_finite(player.get(yards_name)) or 0.0,
            def_rate=_finite((defense or {}).get(rate_name)),
            league_rate=league,
            line=posted,
            book_over=over,
            book_under=under,
            market=market,
            player_rmse=_finite(player.get(f"{market}_sd")),
        )
        if priced is None:
            continue
        legs.append(
            {
                "market": market,
                "player_name": row.get("player_name") or "",
                "player_key": key,
                "team": team,
                "opp": opp,
                "line": priced["line"],
                "side": priced["side"],
                "price": priced["price"],
                "model_p": priced["model_p"],
                "ev": priced["ev"],
                "commence_time": row.get("commence_time") or "",
                "injury_status": row.get("injury_status") or "",
                "game_id": row.get("game_id") or "",
                "kick_et": row.get("kick_et") or "",
                "position": position,
                "gsis_id": str(player.get("player_id") or ""),
                "funnel": False,
                "scheme": True,
            }
        )
    return legs


def build_from_lines(
    lines_path: Path,
    scratches_path: Path = DEFAULT_SCRATCHES,
    cache_dir: Path = DEFAULT_CACHE,
    players_path: Path = DEFAULT_PLAYERS,
    teams_path: Path = DEFAULT_TEAMS,
) -> WeekCard:
    """Score a saved lines file. Raise when the card cannot place $25.00."""

    from ceminiparlays.feature_cache import load_feature_cache, overlay_pit
    from ceminiparlays.matchup_score import score_board

    never = load_never(scratches_path)
    loaded = load_feature_cache(cache_dir)
    if loaded.get("status") != "ready":
        raise ValueError("the week-7 feature cache is absent")
    frames = loaded["frames"]
    telemetry = frames["player_telemetry_pit.parquet"].to_dict("records")
    defense_rows = frames["defense_counterpart_pit.parquet"].to_dict("records")
    by_gsis, by_key = _index_telemetry(telemetry)
    overlaid_players, teams = overlay_pit(_read_csv(players_path), _read_csv(teams_path), frames)
    players = _prepare_players(overlaid_players, by_gsis)
    sunday = _sunday_lines(_read_csv(lines_path))
    if not sunday:
        raise ValueError("the lines file has no Sunday daytime props")
    starters = confirmed_starters(telemetry, never)
    _summaries, board_legs = score_board(sunday, players, teams)
    counts_by_key = {str(row.get("player_key") or ""): row for row in players}
    counts_by_gsis = {str(row.get("gsis_id") or ""): row for row in players}
    defense_by_team = {canonical_team(str(row.get("team") or "")): row for row in defense_rows}
    team_rows = {canonical_team(str(row.get("team") or "")): row for row in teams}
    league_trail_values = [
        value
        for row in telemetry
        if str(row.get("position") or "").upper() == "RB"
        and (value := _finite(row.get("q4_trail_target_share"))) is not None
    ]
    league_trail = sum(league_trail_values) / len(league_trail_values) if league_trail_values else 0.20
    league_comp = _mean(defense_rows, "def_q4_comp_rate")
    league_yac = _mean(defense_rows, "def_q4_yac")
    league_box = _mean(defense_rows, "def_light_box_rate")
    league_cushion = _mean(list(team_rows.values()), "cushion_allowed")
    replaced: set[tuple[str, str, float]] = set()
    funnel_legs: list[dict] = []
    for line in funnel_lines(sunday):
        player = by_key.get(str(line.get("player_key") or ""))
        if player is None:
            continue
        if str(player.get("position") or "").upper() != "RB":
            continue
        targets = _finite(player.get("targets_per_game")) or 0.0
        if targets < 1.0:
            continue
        if norm_name(str(player.get("player_name") or "")) in never:
            continue
        cache_team = canonical_team(str(player.get("team") or ""))
        book_team = canonical_team(str(line.get("team") or ""))
        if cache_team and book_team and cache_team != book_team:
            continue
        opp = canonical_team(str(line.get("opp") or ""))
        defense = dict(defense_by_team.get(opp) or {})
        team_row = team_rows.get(opp) or {}
        if team_row.get("cushion_allowed") not in (None, ""):
            defense["cushion_allowed"] = team_row.get("cushion_allowed")
        gsis = str(player.get("player_id") or "")
        counts = counts_by_gsis.get(gsis) or counts_by_key.get(str(line.get("player_key") or ""))
        leg = _checkdown_leg(
            line,
            player,
            defense,
            team_rows.get(book_team),
            counts,
            league_trail,
            league_cushion,
            league_comp,
            league_yac,
        )
        if leg is None:
            continue
        funnel_legs.append(leg)
        replaced.add((str(leg["player_key"]), str(leg["market"]), round(float(leg["line"]), 3)))
    merged: list[dict] = []
    for leg in board_legs:
        market = str(leg.get("market") or "")
        if market not in PROMOTED:
            continue
        attached = _attach_identity(leg, by_key)
        if attached is None:
            continue
        key = (
            str(attached.get("player_key") or ""),
            market,
            round(float(attached.get("line") or 0.0), 3),
        )
        if key in replaced:
            continue
        attached["funnel"] = False
        attached["scheme"] = False
        merged.append(attached)
    merged.extend(funnel_legs)
    merged.extend(
        _scheme_legs(sunday, by_key, defense_by_team, league_comp, league_box, starters)
    )
    eligible = []
    for leg in merged:
        if gate_reason(leg, never, starters):
            continue
        try:
            ev = float(leg["ev"])
        except (TypeError, ValueError, KeyError):
            continue
        if ev < HARDROCK_MIN_EV:
            continue
        eligible.append(leg)
    slips = same_game_slips(eligible)
    plays, views = candidate_plays(eligible, slips, never=never, starters=starters)
    if not plays:
        raise ValueError("no qualifying play cleared the gates and the 0.08 EV floor")
    return card_from_plays(plays, views, never)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ceminiparlays.week7_card")
    parser.add_argument("--lines", type=Path, default=DEFAULT_LINES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--scratches", type=Path, default=DEFAULT_SCRATCHES)
    args = parser.parse_args(argv)
    if not args.lines.is_file():
        text = render_blocked(MISSING_BOARD)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
        print(text)
        return 2
    try:
        card = build_from_lines(args.lines, args.scratches)
    except ValueError as exc:
        text = render_blocked(str(exc))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
        print(text)
        return 2
    write_ledger(card, args.ledger)
    text = render_card(card)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(text, encoding="utf-8")
    print(format_table(card))
    print(
        f"mode={card.mode} tickets={len(card.tickets)} stake_usd=25.00 ledger={args.ledger}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
