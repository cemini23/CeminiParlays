"""Week-6 Hard Rock research card. This module does not place a bet.

Stakes are research sizes for a $15.00 bankroll. The operator types every
ticket. A same-game price is not the displayed SGP price.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from ceminiparlays.odds import american_to_decimal, decimal_to_american

BANKROLL_CENTS = 1500
GAME_CAP_CENTS = 450
MIN_EV = 0.08
ANCHOR_MIN_P = 0.60
LOTTO_DECIMAL = (5.5, 10.0)
TIER1_CENTS = 150
TIER2_CENTS = 75
TIER3_CENTS = 50
TIER1_COUNT = 6
TIER2_COUNT = 6
TIER3_COUNT = 3
PROMOTED = frozenset(
    {
        "rec_yds_q3",
        "rec_yds_q4",
        "receptions_q4",
        "rush_yds_q4",
        "pass_yds_q4",
        "interceptions",
        "total_q3",
    }
)
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def norm_name(value: str) -> str:
    """Lower-case name with punctuation and a generational suffix removed."""

    raw = value.lower().replace("'", "").replace(".", "")
    chars = [ch if ch.isalnum() or ch == " " else " " for ch in raw]
    parts = [part for part in "".join(chars).split() if part not in _SUFFIXES]
    return " ".join(parts)


def game_key(leg: dict) -> frozenset[str]:
    return frozenset({str(leg.get("team") or ""), str(leg.get("opp") or "")})


def _ev(leg: dict) -> float:
    return float(leg["ev"])


def _p(leg: dict) -> float:
    return float(leg["model_p"])


def _price(leg: dict) -> int:
    return int(float(leg["price"]))


def _player(leg: dict) -> str:
    return norm_name(str(leg.get("player_name") or ""))


def kick_et(commence: str) -> str:
    """Clock time in Eastern Daylight Time for an ISO kickoff."""

    hour = int(commence[11:13]) - 4
    minute = int(commence[14:16])
    if hour < 0:
        hour += 24
    suffix = "AM" if hour < 12 else "PM"
    show = hour % 12 or 12
    return f"{show}:{minute:02d} {suffix} ET"


def pass_over_blocked(leg: dict, blocked_games: set[frozenset[str]]) -> bool:
    """True for a blocked quarter passing over."""

    if str(leg.get("market")) != "pass_yds_q4" or str(leg.get("side")) != "over":
        return False
    if game_key(leg) in blocked_games:
        return True
    return str(leg.get("team") or "") == "CLE"


def qualifying_legs(
    legs: list[dict],
    *,
    never_enter: set[str],
    blocked_pass_games: set[frozenset[str]],
    slate_day: str = "2026-10-18",
) -> list[dict]:
    """Daytime promoted legs at or above the EV floor, with hard excludes off."""

    blocked = {norm_name(name) for name in never_enter}
    kept: list[dict] = []
    for leg in legs:
        if str(leg.get("market") or "") not in PROMOTED:
            continue
        try:
            ev = _ev(leg)
            _p(leg)
            _price(leg)
        except (TypeError, ValueError):
            continue
        if ev < MIN_EV:
            continue
        commence = str(leg.get("commence_time") or "")
        if not commence.startswith(slate_day):
            continue
        if _player(leg) in blocked:
            continue
        if pass_over_blocked(leg, blocked_pass_games):
            continue
        kept.append(leg)
    kept.sort(key=lambda leg: (-_ev(leg), str(leg.get("player_key") or ""), str(leg.get("market"))))
    return kept


def select_anchors(legs: list[dict], *, wait: set[str], count: int = TIER1_COUNT) -> list[dict]:
    """One high-probability leg per game. A wait name is skipped."""

    waiting = {norm_name(name) for name in wait}
    used_games: set[frozenset[str]] = set()
    used_players: set[str] = set()
    picked: list[dict] = []
    ordered = sorted(legs, key=lambda leg: (-_ev(leg), -_p(leg), str(leg.get("player_key") or "")))
    for leg in ordered:
        if _p(leg) < ANCHOR_MIN_P or _player(leg) in waiting:
            continue
        key = game_key(leg)
        player = _player(leg)
        if key in used_games or player in used_players:
            continue
        used_games.add(key)
        used_players.add(player)
        picked.append(leg)
        if len(picked) == count:
            break
    return picked


def select_sgps(
    priced: list[dict],
    *,
    used_players: set[str],
    exposure: dict[frozenset[str], int],
    wait: set[str],
    count: int = TIER2_COUNT,
) -> list[dict]:
    """One taxed 2-leg ticket per game. A used player stays off the slip."""

    waiting = {norm_name(name) for name in wait}
    taken = set(used_players)
    chosen: list[dict] = []
    seen_games: set[frozenset[str]] = set()
    ordered = sorted(priced, key=lambda row: -float(row["tax_adjusted_sgp_ev"]))
    for row in ordered:
        if int(row.get("n_legs") or 0) != 2:
            continue
        if not row.get("sgp_tax_applied"):
            continue
        if float(row["tax_adjusted_sgp_ev"]) < MIN_EV:
            continue
        slip = list(row["legs"])
        names = [_player(leg) for leg in slip]
        if any(name in waiting or name in taken for name in names):
            continue
        key = game_key(slip[0])
        if key in seen_games:
            continue
        if exposure.get(key, 0) + TIER2_CENTS > GAME_CAP_CENTS:
            continue
        seen_games.add(key)
        taken.update(names)
        exposure[key] = exposure.get(key, 0) + TIER2_CENTS
        chosen.append(row)
        if len(chosen) == count:
            break
    return chosen


def _product_decimal(legs: list[dict]) -> float:
    decimal = 1.0
    for leg in legs:
        decimal *= american_to_decimal(_price(leg))
    return decimal


def select_lottos(
    legs: list[dict],
    *,
    used_players: set[str],
    exposure: dict[frozenset[str], int],
    wait: set[str],
    count: int = TIER3_COUNT,
) -> list[list[dict]]:
    """Cross-game 3-leg tickets whose book product is +450 to +900."""

    waiting = {norm_name(name) for name in wait}
    pool = [
        leg
        for leg in legs
        if _player(leg) not in used_players and _player(leg) not in waiting and _player(leg)
    ]
    pool.sort(key=lambda leg: (-_ev(leg), str(leg.get("player_key") or "")))
    pool = pool[:36]
    candidates: list[tuple[float, list[dict]]] = []
    for combo in combinations(pool, 3):
        games = [game_key(leg) for leg in combo]
        if len(set(games)) < 3:
            continue
        players = [_player(leg) for leg in combo]
        if len(set(players)) < 3:
            continue
        decimal = _product_decimal(list(combo))
        if not LOTTO_DECIMAL[0] <= decimal <= LOTTO_DECIMAL[1]:
            continue
        joint = 1.0
        for leg in combo:
            joint *= _p(leg)
        ev = joint * decimal - 1.0
        if ev < MIN_EV:
            continue
        candidates.append((ev, list(combo)))
    candidates.sort(key=lambda item: (-item[0], _player(item[1][0])))
    taken = set(used_players)
    chosen: list[list[dict]] = []
    for _ev_value, combo in candidates:
        names = [_player(leg) for leg in combo]
        if any(name in taken for name in names):
            continue
        keys = [game_key(leg) for leg in combo]
        if any(exposure.get(key, 0) + TIER3_CENTS > GAME_CAP_CENTS for key in keys):
            continue
        taken.update(names)
        for key in keys:
            exposure[key] = exposure.get(key, 0) + TIER3_CENTS
        chosen.append(combo)
        if len(chosen) == count:
            break
    return chosen


@dataclass
class CardTicket:
    number: int
    tier: str
    game: str
    kick_et: str
    legs: list[dict]
    book_price: str
    model_p: float
    tax_ev: float
    stake_cents: int
    note: str
    kind: str = "single"


@dataclass
class SundayCard:
    mode: str
    tickets: list[CardTicket] = field(default_factory=list)
    qualifying_legs: int = 0
    qualifying_games: int = 0

    @property
    def stake_cents(self) -> int:
        return sum(ticket.stake_cents for ticket in self.tickets)


def _exposure_from_anchors(anchors: list[dict]) -> dict[frozenset[str], int]:
    exposure: dict[frozenset[str], int] = {}
    for leg in anchors:
        key = game_key(leg)
        exposure[key] = exposure.get(key, 0) + TIER1_CENTS
    return exposure


def build_sunday_card(
    legs: list[dict],
    priced_sgp: list[dict],
    *,
    never_enter: set[str],
    wait: set[str],
    blocked_pass_games: set[frozenset[str]],
    game_label,
    note_for,
) -> SundayCard:
    """Build the Mode A card. The caller supplies priced same-game rows."""

    kept = qualifying_legs(
        legs, never_enter=never_enter, blocked_pass_games=blocked_pass_games
    )
    games = {game_key(leg) for leg in kept}
    anchors = select_anchors(kept, wait=wait)
    if len(kept) < 10 or len(games) < 5 or len(anchors) < TIER1_COUNT:
        raise ValueError("the slate does not fill six daytime anchors")
    exposure = _exposure_from_anchors(anchors)
    used = {_player(leg) for leg in anchors}
    sgps = select_sgps(priced_sgp, used_players=used, exposure=exposure, wait=wait)
    if len(sgps) < TIER2_COUNT:
        raise ValueError("the slate does not fill six taxed two-leg tickets")
    for row in sgps:
        used.update(_player(leg) for leg in row["legs"])
    lottos = select_lottos(kept, used_players=used, exposure=exposure, wait=wait)
    if len(lottos) < TIER3_COUNT:
        raise ValueError("the slate does not fill three cross-game tickets")
    tickets: list[CardTicket] = []
    number = 1
    for leg in anchors:
        tickets.append(
            CardTicket(
                number=number,
                tier="1",
                game=game_label(leg),
                kick_et=kick_et(str(leg["commence_time"])),
                legs=[leg],
                book_price=_american(_price(leg)),
                model_p=_p(leg),
                tax_ev=_ev(leg),
                stake_cents=TIER1_CENTS,
                note=note_for([leg], "single"),
                kind="single",
            )
        )
        number += 1
    for row in sgps:
        slip = list(row["legs"])
        decimal = float(row["decimal_sgp"])
        tickets.append(
            CardTicket(
                number=number,
                tier="2",
                game=game_label(slip[0]),
                kick_et=kick_et(str(slip[0]["commence_time"])),
                legs=slip,
                book_price=f"SGP not captured; haircut decimal {decimal:.3f}",
                model_p=float(row["joint_p"]),
                tax_ev=float(row["tax_adjusted_sgp_ev"]),
                stake_cents=TIER2_CENTS,
                note=note_for(slip, "sgp"),
                kind="sgp",
            )
        )
        number += 1
    for combo in lottos:
        decimal = _product_decimal(combo)
        joint = 1.0
        for leg in combo:
            joint *= _p(leg)
        tickets.append(
            CardTicket(
                number=number,
                tier="3",
                game=" / ".join(game_label(leg) for leg in combo),
                kick_et=" / ".join(kick_et(str(leg["commence_time"])) for leg in combo),
                legs=combo,
                book_price=_american(decimal_to_american(decimal)),
                model_p=joint,
                tax_ev=joint * decimal - 1.0,
                stake_cents=TIER3_CENTS,
                note=note_for(combo, "cross"),
                kind="cross",
            )
        )
        number += 1
    card = SundayCard(
        mode="A",
        tickets=tickets,
        qualifying_legs=len(kept),
        qualifying_games=len(games),
    )
    validate_card(card, never_enter=never_enter)
    return card


def _american(price: int) -> str:
    return f"+{price}" if price > 0 else str(price)


def validate_card(card: SundayCard, *, never_enter: set[str]) -> None:
    """Raise when the stake, the game cap, or a hard exclude fails."""

    from ceminiparlays.compose import redundant_quarter_pair

    if card.stake_cents != BANKROLL_CENTS:
        raise ValueError(f"stakes sum to {card.stake_cents} cents")
    blocked = {norm_name(name) for name in never_enter}
    exposure: dict[frozenset[str], int] = {}
    for ticket in card.tickets:
        if any(_player(leg) in blocked for leg in ticket.legs):
            raise ValueError("a never_enter player is on the card")
        for left, right in combinations(ticket.legs, 2):
            if _player(left) and _player(left) == _player(right):
                if redundant_quarter_pair(left, right):
                    raise ValueError("a degenerate quarter pair is on the card")
        if ticket.kind == "single":
            key = game_key(ticket.legs[0])
            exposure[key] = exposure.get(key, 0) + ticket.stake_cents
        elif ticket.kind == "sgp":
            key = game_key(ticket.legs[0])
            exposure[key] = exposure.get(key, 0) + ticket.stake_cents
        else:
            for leg in ticket.legs:
                key = game_key(leg)
                exposure[key] = exposure.get(key, 0) + ticket.stake_cents
    if any(cents > GAME_CAP_CENTS for cents in exposure.values()):
        raise ValueError("a game is over the $4.50 cap")


def leg_text(leg: dict) -> str:
    line = float(leg["line"])
    return (
        f"{leg['player_name']} {leg['market']} {leg['side']} {line:.1f} "
        f"({_american(_price(leg))})"
    )


def main() -> int:
    """Print the research card from the scored leg file. Does not submit."""

    import csv
    from pathlib import Path

    from ceminiparlays.compose import rank_same_game

    legs_path = Path("data/cache/matchup_legs.csv")
    if not legs_path.exists():
        raise SystemExit("scored legs file is missing")
    with legs_path.open(newline="", encoding="utf-8") as handle:
        legs = list(csv.DictReader(handle))
    never = set(OPERATOR_NEVER) | set(REPORT_OUT)
    wait = set(OPERATOR_WAIT)
    homes, wind = _slate_context()
    blocked_pass = {frozenset({"PIT", "TB"}), frozenset({"HOU", "JAX"})}
    wind_games = {frozenset({"LAC", "KC"}), frozenset({"CAR", "PHI"})}
    kept = qualifying_legs(legs, never_enter=never, blocked_pass_games=blocked_pass)
    priced = rank_same_game(kept)

    def game_label(leg: dict) -> str:
        teams = {str(leg.get("team") or ""), str(leg.get("opp") or "")}
        home = homes.get(frozenset(teams), "")
        if home and home in teams:
            away = next(iter(teams - {home}))
            return f"{away} @ {home}"
        return " vs ".join(sorted(teams))

    def note_for(slip: list[dict], kind: str) -> str:
        notes: list[str] = []
        if kind == "sgp":
            notes.append("Displayed SGP price is not in the capture")
        if kind == "cross":
            notes.append("Cross-game product. Rho is 0. Haircut does not apply")
        for leg in slip:
            key = game_key(leg)
            if key in wind_games and str(leg.get("market")) in {"pass_yds_q4", "first_td"}:
                notes.append("[WIND_REVIEW_NOTE]")
            if key == frozenset({"PIT", "TB"}):
                mph, gust = wind.get(key, (None, None))
                notes.append(f"PIT@TB wind {mph} mph, gust {gust}. Pass overs stay off")
            if key == frozenset({"HOU", "JAX"}) and str(leg.get("market")) == "pass_yds_q4":
                mph, gust = wind.get(key, (None, None))
                side = str(leg.get("side") or "")
                notes.append(
                    f"HOU@JAX wind {mph} mph, gust {gust}. Side is {side}. Pass overs stay off"
                )
            if _player(leg) == "tyler huntley":
                notes.append("Lamar Jackson is on the operator scratch list")
            if _player(leg) == "james cook" and str(leg.get("side")) == "under":
                notes.append("Validated side is the quarter under")
            if _player(leg) in {norm_name(name) for name in wait}:
                notes.append("[WAIT_FOR_T90_INACTIVES]")
        if not notes:
            notes.append("none")
        # Keep the first copy of each note.
        unique: list[str] = []
        for note in notes:
            if note not in unique:
                unique.append(note)
        return "; ".join(unique)

    card = build_sunday_card(
        legs,
        priced,
        never_enter=never,
        wait=wait,
        blocked_pass_games=blocked_pass,
        game_label=game_label,
        note_for=note_for,
    )
    print(f"mode={card.mode} qualifying_legs={card.qualifying_legs} games={card.qualifying_games}")
    print(f"stake_cents={card.stake_cents}")
    print(render_table(card))
    return 0


def _slate_context() -> tuple[dict[frozenset[str], str], dict[frozenset[str], tuple[float, float]]]:
    """Home teams and wind from the week-6 weather file, when it is present."""

    homes: dict[frozenset[str], str] = {}
    wind: dict[frozenset[str], tuple[float, float]] = {}
    try:
        import pandas as pd
    except ImportError:
        return homes, wind
    path = (
        "/Users/claudiobarone/Projects/CeminiDFS/artifacts/cache/2026/week_6/weather.parquet"
    )
    frame = pd.read_parquet(path)
    alias = {"LA": "LAR", "JAC": "JAX", "WSH": "WAS"}
    for row in frame.itertuples(index=False):
        away = alias.get(str(row.away_team), str(row.away_team))
        home = alias.get(str(row.home_team), str(row.home_team))
        key = frozenset({away, home})
        homes[key] = home
        if row.wind_speed_10m_mph == row.wind_speed_10m_mph:
            wind[key] = (float(row.wind_speed_10m_mph), float(row.wind_gusts_10m_mph))
    return homes, wind


REPORT_OUT = (
    "Talanoa Hufanga",
    "Pat Surtain II",
    "Chazz Surratt",
    "Drake Thomas",
    "Zach Charbonnet",
)
OPERATOR_NEVER = (
    "Jalen Hurts",
    "Saquon Barkley",
    "Will Shipley",
    "Lamar Jackson",
    "Baker Mayfield",
    "Dillon Gabriel",
    "Rashee Rice",
    "Breece Hall",
    "Adonai Mitchell",
    "David Montgomery",
    "Tank Dell",
    "Kyle Monangai",
    "Jeremiyah Love",
    "James Conner",
    "Tre' Harris",
    "Alec Pierce",
    "Ashton Dulin",
    "Theo Johnson",
    "AJ Dillon",
    "Jonathon Brooks",
    "Michael Pittman Jr.",
    "Roman Wilson",
    "Ben Skowronek",
    "David Sills",
)
OPERATOR_WAIT = (
    "Caleb Williams",
    "DK Metcalf",
    "Chris Olave",
    "Alvin Kamara",
    "A.J. Brown",
    "TreVeyon Henderson",
    "Tyler Warren",
    "Quinshon Judkins",
    "DJ Moore",
    "Josh Palmer",
    "Tyler Higbee",
)


def render_table(card: SundayCard) -> str:
    """Markdown table for the research card."""

    lines = [
        "| Ticket | Tier | Game and kick ET | Legs and side | Book price | Model prob | Tax-adjusted EV % | Stake | T-90 note |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for ticket in card.tickets:
        legs = "; ".join(leg_text(leg) for leg in ticket.legs)
        stake = f"${ticket.stake_cents / 100:.2f}"
        ev_pct = f"{ticket.tax_ev * 100:.1f}%"
        lines.append(
            f"| {ticket.number} | {ticket.tier} | {ticket.game}, {ticket.kick_et} | {legs} | "
            f"{ticket.book_price} | {ticket.model_p:.6f} | {ev_pct} | {stake} | {ticket.note} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
