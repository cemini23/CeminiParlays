"""Grade a saved Hard Rock card from play-by-play or a summary JSON.

The grader does not open Hard Rock. A quarter leg uses ``qtr``. A full-game
leg uses every quarter. A push leg drops out of a same-game slip and the
remaining legs are repriced. A loss loses the stake. Profit is cash only.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ceminiparlays.names import AliasRequiredError, names_match, unique_box_alias
from ceminiparlays.odds import american_to_decimal

_FINAL_STATUS = {"STATUS_FINAL", "FINAL", "FINAL/OT"}

CORE_LEDGER_COLUMNS = (
    "ticket_id",
    "tier",
    "leg_num",
    "game_id",
    "kick_et",
    "player_name",
    "gsis_id",
    "team",
    "opp",
    "market",
    "side",
    "line",
    "book_american_odds",
    "model_prob",
    "tax_adj_ev",
    "ticket_stake_usd",
    "t90_flag",
)
EXTRA_LEDGER_COLUMNS = (
    "boost_pct",
    "displayed_boosted_payout",
    "off_card",
    "leg_statuses",
    # Marginal probability of this leg. ``model_prob`` on a multi-leg slip is
    # the ticket joint. A blank cell means the file did not store a marginal.
    "leg_model_prob",
)
LEDGER_COLUMNS = CORE_LEDGER_COLUMNS + EXTRA_LEDGER_COLUMNS

# (id column, name column, value column, quarter or None, how)
_SPECS: dict[str, tuple[str, str, str, int | None, str]] = {
    "receptions": ("receiver_player_id", "receiver_player_name", "complete_pass", None, "sum"),
    "receptions_q3": ("receiver_player_id", "receiver_player_name", "complete_pass", 3, "sum"),
    "receptions_q4": ("receiver_player_id", "receiver_player_name", "complete_pass", 4, "sum"),
    "rec_yds": ("receiver_player_id", "receiver_player_name", "receiving_yards", None, "sum"),
    "rec_yds_q3": ("receiver_player_id", "receiver_player_name", "receiving_yards", 3, "sum"),
    "rec_yds_q4": ("receiver_player_id", "receiver_player_name", "receiving_yards", 4, "sum"),
    "rush_yds": ("rusher_player_id", "rusher_player_name", "rushing_yards", None, "sum"),
    "rush_yds_q3": ("rusher_player_id", "rusher_player_name", "rushing_yards", 3, "sum"),
    "rush_yds_q4": ("rusher_player_id", "rusher_player_name", "rushing_yards", 4, "sum"),
    "pass_yds": ("passer_player_id", "passer_player_name", "passing_yards", None, "sum"),
    "pass_yds_q3": ("passer_player_id", "passer_player_name", "passing_yards", 3, "sum"),
    "pass_yds_q4": ("passer_player_id", "passer_player_name", "passing_yards", 4, "sum"),
    "interceptions": ("passer_player_id", "passer_player_name", "interception", None, "sum"),
    "total_q3": ("", "", "", 3, "game_points"),
}


@dataclass
class LegGrade:
    ticket_id: str
    leg_num: int
    market: str
    result: str
    actual: float | None
    model_p: float


@dataclass
class CardGrade:
    tickets: int
    settled_tickets: int
    stake: float
    profit: float
    roi: float
    brier: float | None
    legs: list[LegGrade] = field(default_factory=list)
    ledger_rows: list[dict[str, str]] = field(default_factory=list)
    hold_rows: list[dict[str, str]] = field(default_factory=list)


def read_ledger(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if rows:
        missing = [column for column in CORE_LEDGER_COLUMNS if column not in rows[0]]
        if missing:
            raise ValueError("ledger is missing columns: " + ", ".join(missing))
        for row in rows:
            for column in EXTRA_LEDGER_COLUMNS:
                row.setdefault(column, "")
    return rows


def _num(play: dict, field_name: str) -> float:
    try:
        value = float(play.get(field_name) or 0)
    except (TypeError, ValueError):
        return 0.0
    if value != value:
        return 0.0
    return value


def _quarter(play: dict) -> int | None:
    try:
        value = int(float(play.get("qtr")))
    except (TypeError, ValueError):
        return None
    return value


def _points(play: dict) -> float:
    points = 0.0
    if _num(play, "touchdown") >= 1:
        points += 6
    if str(play.get("extra_point_result") or "").lower() == "good":
        points += 1
    if str(play.get("two_point_conv_result") or "").lower() == "success":
        points += 2
    if str(play.get("field_goal_result") or "").lower() == "made":
        points += 3
    if _num(play, "safety") >= 1:
        points += 2
    if points == 0.0 and play.get("points") not in (None, ""):
        points = _num(play, "points")
    return points


def _is_final_play(play: dict) -> bool:
    """A blank status means the supplied box is final."""

    status = str(play.get("status") or play.get("game_status") or "").strip()
    if not status:
        return True
    token = status.upper().replace(" ", "")
    return token in _FINAL_STATUS


def _same_player(play: dict, id_field: str, name_field: str, leg: dict) -> bool:
    gsis = str(leg.get("gsis_id") or "").strip()
    if gsis and str(play.get(id_field) or "").strip() == gsis:
        return True
    return names_match(str(play.get(name_field) or ""), str(leg.get("player_name") or ""))


def _player_in_game(plays: list[dict], leg: dict) -> bool:
    fields = (
        ("receiver_player_id", "receiver_player_name"),
        ("rusher_player_id", "rusher_player_name"),
        ("passer_player_id", "passer_player_name"),
    )
    for play in plays:
        if not _same_game(play, leg):
            continue
        for id_field, name_field in fields:
            if _same_player(play, id_field, name_field, leg):
                return True
    return False


def _box_players(plays: list[dict], leg: dict) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    fields = (
        ("receiver_player_name", "receiver_position"),
        ("rusher_player_name", "rusher_position"),
        ("passer_player_name", "passer_position"),
    )
    for play in plays:
        if not _same_game(play, leg):
            continue
        for name_field, pos_field in fields:
            name = str(play.get(name_field) or "").strip()
            if not name:
                continue
            position = str(play.get(pos_field) or play.get("position") or "")
            team = str(play.get("posteam") or "")
            key = (name, team, position)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"name": name, "team": team, "position": position})
    return rows


def _same_game(play: dict, leg: dict) -> bool:
    game = str(leg.get("game_id") or "").strip()
    if game and str(play.get("game_id") or "").strip() == game:
        return True
    teams = {str(leg.get("team") or ""), str(leg.get("opp") or "")}
    play_teams = {str(play.get("posteam") or ""), str(play.get("defteam") or "")}
    if "" in teams or "" in play_teams:
        return not game
    return teams == play_teams


def actual_stat(plays: list[dict], leg: dict) -> float | None:
    """Settled stat for one leg. ``None`` when the market or the quarter is absent."""

    market = str(leg.get("market") or "")
    spec = _SPECS.get(market)
    if spec is None:
        return None
    id_field, name_field, value_field, quarter, how = spec
    usable = [play for play in plays if _is_final_play(play)]
    total = 0.0
    seen = False
    for play in usable:
        if not _same_game(play, leg):
            continue
        play_quarter = _quarter(play)
        if quarter is not None and play_quarter != quarter:
            continue
        if how == "game_points":
            total += _points(play)
            seen = True
            continue
        if not _same_player(play, id_field, name_field, leg):
            continue
        total += _num(play, value_field)
        seen = True
    if not seen:
        if _player_in_game(usable, leg):
            return None
        team = str(leg.get("team") or "")
        position = str(leg.get("position") or "")
        match = unique_box_alias(
            str(leg.get("player_name") or ""),
            team,
            position,
            _box_players(usable, leg),
        )
        if match:
            raise AliasRequiredError(str(leg.get("player_name") or ""), match, team, position)
        return None
    return total


def _result(side: str, line: float, actual: float) -> str:
    if actual == line:
        return "push"
    token = side.strip().lower()
    if token in {"over", "more", "higher"}:
        return "win" if actual > line else "loss"
    if token in {"under", "less", "lower"}:
        return "win" if actual < line else "loss"
    raise ValueError(f"unknown side: {side}")


def _parse_stake(value: object) -> float | None:
    """A dollar stake, or ``0.0`` for a paper ``TBD`` cell.

    ``0``, ``0.00``, and ``TBD`` are paper stakes. A blank cell is absent.
    """

    text = str(value or "").strip()
    if not text:
        return None
    if text.lower() == "tbd":
        return 0.0
    try:
        number = round(float(text), 2)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _stake(group: list[dict[str, str]]) -> float:
    values = []
    for row in group:
        parsed = _parse_stake(row.get("ticket_stake_usd"))
        if parsed is None:
            continue
        values.append(parsed)
    if not values:
        raise ValueError("a ticket has no stake")
    if any(abs(value - values[0]) > 0.001 for value in values):
        raise ValueError("ticket stake differs across legs")
    return values[0]


def _money(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _status_label(result: str) -> str:
    token = str(result or "").strip().lower()
    if token in {"loss", "miss"}:
        return "MISS"
    if token in {"win", "hit"}:
        return "HIT"
    if token in {"push", "void"}:
        return "VOID"
    if token == "pending":
        return "PENDING"
    return "UNGRADED"


def _ticket_profit(group: list[dict[str, str]], results: list[str]) -> tuple[str, float]:
    """Return the ticket result and the cash profit.

    A ``MISS`` settles the ticket as a loss before a ``VOID``, ``PENDING``,
    or ``UNGRADED`` leg can hold it. A winning ticket with
    ``displayed_boosted_payout > 0`` pays that amount minus the stake.
    """

    stake = _stake(group)
    labels = [str(result).strip().lower() for result in results]
    if any(label in {"loss", "miss"} for label in labels):
        return "loss", -stake
    if any(label in {"ungraded", "pending"} for label in labels):
        return "ungraded", 0.0
    live = [
        (row, result)
        for row, result in zip(group, results, strict=True)
        if str(result).strip().lower() not in {"push", "void"}
    ]
    if not live:
        return "push", 0.0
    boosted = _money(group[0].get("displayed_boosted_payout"))
    if boosted is not None and boosted > 0.0:
        return "win", boosted - stake
    # A paper card can settle the result and the Brier term before a price exists.
    if stake == 0.0 and any(
        not str(row.get("book_american_odds") or "").strip() for row, _result_name in live
    ):
        return "win", 0.0
    decimal = 1.0
    for row, _result_name in live:
        decimal *= american_to_decimal(int(float(row["book_american_odds"])))
    return "win", stake * (decimal - 1.0)


def _tag_leg_statuses(group: list[dict[str, str]], results: list[str]) -> list[dict[str, str]]:
    tagged: list[dict[str, str]] = []
    for row, result in zip(group, results, strict=True):
        copied = {column: str(row.get(column) or "") for column in LEDGER_COLUMNS}
        copied["leg_statuses"] = _status_label(result)
        tagged.append(copied)
    return tagged


def archive_card_copies(
    card_path: Path,
    slate_date: str,
    workspace: Path | None = None,
    doc_path: Path | None = None,
) -> list[Path]:
    """Copy a card into the slate and recap folders when ``/workspace`` exists.

    The CSV names stay ``compose_card_{date}.csv`` and ``hardrock_card_{date}.csv``.
    A markdown path is copied into both folders under its own file name.
    """

    root = workspace if workspace is not None else Path("/workspace")
    if not root.is_dir():
        return []
    source = Path(card_path)
    if not source.is_file():
        raise FileNotFoundError(f"card file missing: {source}")
    written: list[Path] = []
    folders = ("parlays-slate", "parlays-recap")
    csv_names = (
        f"compose_card_{slate_date}.csv",
        f"hardrock_card_{slate_date}.csv",
    )
    for folder, name in zip(folders, csv_names, strict=True):
        target = root / folder / slate_date / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        written.append(target)
    document = Path(doc_path) if doc_path is not None else None
    if document is not None and document.is_file():
        for folder in folders:
            target = root / folder / slate_date / document.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(document, target)
            written.append(target)
    return written


#: A typed leg status wins over the play-by-play result.
_EXPLICIT_RESULTS = {
    "miss": "loss",
    "loss": "loss",
    "win": "win",
    "hit": "win",
    "won": "win",
    "void": "void",
    "push": "void",
    "pending": "pending",
    "ungraded": "ungraded",
}


def _grade_leg_row(
    row: dict[str, str], plays: list[dict]
) -> tuple[str, float | None, float | None]:
    """``(result, actual, model_p)``. A row with no line or model is ungraded."""

    try:
        line = float(row["line"])
        model_p = float(row["model_prob"])
    except (TypeError, ValueError, KeyError):
        return "ungraded", None, None
    result = _EXPLICIT_RESULTS.get(str(row.get("leg_status") or "").strip().lower())
    if result is not None:
        return result, None, model_p
    actual = actual_stat(plays, row)
    if actual is None:
        return "ungraded", None, model_p
    return _result(str(row.get("side") or ""), line, actual), actual, model_p


def _held(results: list[str]) -> bool:
    """A ticket with no loss and an open leg waits. It is not settled."""

    if any(str(result).strip().lower() in {"loss", "miss"} for result in results):
        return False
    return any(
        str(result).strip().lower() in {"ungraded", "pending"} for result in results
    )


def _ticket_joint_prob(ordered: list[dict[str, str]]) -> float | None:
    """The ticket joint, when ``model_prob`` is not a per-leg marginal.

    A multi-leg ledger repeats the joint on every row. ``leg_model_prob`` is
    the explicit marginal. Equal ``model_prob`` cells are the same joint.
    One leg, or unequal marginals, returns ``None`` so each leg keeps its term.
    """

    if len(ordered) < 2:
        return None
    values: list[float] = []
    for row in ordered:
        try:
            values.append(float(row["model_prob"]))
        except (TypeError, ValueError, KeyError):
            return None
    explicit = any(str(row.get("leg_model_prob") or "").strip() for row in ordered)
    same = all(abs(value - values[0]) <= 1e-9 for value in values)
    if explicit or same:
        return values[0]
    return None


def _grade_ticket_legs(
    ordered: list[dict[str, str]],
    plays: list[dict],
    ticket_id: str,
    *,
    ticket_brier: bool = False,
) -> tuple[list[str], list[LegGrade], list[float]]:
    """The results, the leg grades, and the leg-level Brier terms.

    ``ticket_brier`` skips the leg terms. The caller scores the joint once.
    """

    results: list[str] = []
    leg_grades: list[LegGrade] = []
    brier_terms: list[float] = []
    for row in ordered:
        result, actual, model_p = _grade_leg_row(row, plays)
        results.append(result)
        leg_grades.append(
            LegGrade(
                ticket_id,
                int(float(row.get("leg_num") or 0)),
                str(row.get("market") or ""),
                result,
                actual,
                0.0 if model_p is None else model_p,
            )
        )
        if ticket_brier or result not in {"win", "loss"}:
            continue
        outcome = 1.0 if result == "win" else 0.0
        brier_terms.append(((model_p or 0.0) - outcome) ** 2)
    return results, leg_grades, brier_terms


def grade_rows(rows: list[dict[str, str]], plays: list[dict]) -> CardGrade:
    """Grade ledger rows. ``plays`` are nflverse-shaped dicts or summary rows."""

    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault(str(row.get("ticket_id") or ""), []).append(row)
    leg_grades: list[LegGrade] = []
    ledger_rows: list[dict[str, str]] = []
    hold_rows: list[dict[str, str]] = []
    stake = 0.0
    profit = 0.0
    settled = 0
    brier_terms: list[float] = []
    for ticket_id, group in groups.items():
        ordered = sorted(group, key=lambda row: int(float(row.get("leg_num") or 1)))
        joint = _ticket_joint_prob(ordered)
        results, ticket_legs, ticket_brier = _grade_ticket_legs(
            ordered, plays, ticket_id, ticket_brier=joint is not None
        )
        leg_grades.extend(ticket_legs)
        ticket_result, ticket_profit = _ticket_profit(ordered, results)
        # One joint term per settled ticket. Do not score the joint against
        # each leg outcome.
        if joint is not None:
            if ticket_result in {"win", "loss"}:
                outcome = 1.0 if ticket_result == "win" else 0.0
                ticket_model_p = float(ordered[0]["model_prob"])
                brier_terms.append((ticket_model_p - outcome) ** 2)
        else:
            brier_terms.extend(ticket_brier)
        tagged = _tag_leg_statuses(ordered, results)
        if _held(results):
            hold_rows.extend(tagged)
        else:
            ledger_rows.extend(tagged)
        if ticket_result != "ungraded":
            settled += 1
            stake += _stake(ordered)
            profit += ticket_profit
    roi = profit / stake if stake else 0.0
    brier = sum(brier_terms) / len(brier_terms) if brier_terms else None
    return CardGrade(
        tickets=len(groups),
        settled_tickets=settled,
        stake=stake,
        profit=profit,
        roi=roi,
        brier=brier,
        legs=leg_grades,
        ledger_rows=ledger_rows,
        hold_rows=hold_rows,
    )


def _first_value(default, *candidates):
    """The first non-empty candidate, else ``default``. Type is preserved."""

    for candidate in candidates:
        if candidate:
            return candidate
    return default


def _copied_play(play: dict, game_status: str) -> dict:
    copied = dict(play)
    if game_status and not copied.get("status") and not copied.get("game_status"):
        copied["status"] = game_status
    return copied


def _player_play(player: dict, game_status: str) -> dict:
    """One row that stands in for a player at every skill position."""

    quarter = player.get("qtr")
    position = _first_value("", player.get("position"))
    name = _first_value("", player.get("player_name"), player.get("name"))
    gsis = _first_value("", player.get("gsis_id"))
    return {
        "game_id": _first_value("", player.get("game_id")),
        "qtr": quarter if quarter not in (None, "") else None,
        "posteam": _first_value("", player.get("team")),
        "defteam": _first_value("", player.get("opp")),
        "status": _first_value(
            "", player.get("status"), player.get("game_status"), game_status
        ),
        "position": position,
        "receiver_player_id": gsis,
        "receiver_player_name": name,
        "receiver_position": position,
        "rusher_player_id": gsis,
        "rusher_player_name": name,
        "rusher_position": position,
        "passer_player_id": gsis,
        "passer_player_name": name,
        "passer_position": position,
        "complete_pass": _first_value(0, player.get("receptions")),
        "receiving_yards": _first_value(0, player.get("rec_yds")),
        "rushing_yards": _first_value(0, player.get("rush_yds")),
        "passing_yards": _first_value(0, player.get("pass_yds")),
        "interception": _first_value(0, player.get("interceptions")),
        "points": _first_value(0, player.get("points")),
    }


def _quarter_play(score: dict) -> dict:
    return {
        "game_id": _first_value("", score.get("game_id")),
        "qtr": score.get("qtr"),
        "posteam": _first_value("", score.get("team")),
        "defteam": _first_value("", score.get("opp")),
        "points": _first_value(0, score.get("points")),
    }


def plays_from_summary(summary: dict) -> list[dict]:
    """Normalize an ESPN-style summary or a ``plays`` list into grader plays.

    A player row with no ``qtr`` cannot settle a quarter market. Put the
    quarter on the row, or pass play-by-play in ``plays``.
    """

    game_status = str(
        _first_value("", summary.get("status"), summary.get("game_status"))
    )
    if "plays" in summary:
        return [_copied_play(play, game_status) for play in summary["plays"]]
    plays = [
        _player_play(player, game_status) for player in summary.get("players") or []
    ]
    plays.extend(_quarter_play(score) for score in summary.get("quarters") or [])
    return plays


def grade_card(path: Path, plays: list[dict] | None = None, summary: dict | None = None) -> CardGrade:
    """Grade ``path``. Pass ``plays`` or ``summary``. Do not pass both sources."""

    if plays is not None and summary is not None:
        raise ValueError("pass plays or a summary, not both")
    if summary is not None:
        plays = plays_from_summary(summary)
    if plays is None:
        raise ValueError("a play-by-play list or a summary is required")
    return grade_rows(read_ledger(path), plays)


def format_grade(grade: CardGrade) -> str:
    brier = "na" if grade.brier is None else f"{grade.brier:.6f}"
    return (
        f"tickets={grade.tickets} settled={grade.settled_tickets} "
        f"stake={grade.stake:.2f} profit={grade.profit:.2f} "
        f"roi={grade.roi * 100:.1f}% brier={brier}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ceminiparlays.grade_card")
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--pbp", type=Path, default=None)
    parser.add_argument("--summary", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.pbp is None and args.summary is None:
        print("grade needs --pbp or --summary. Hard Rock history is not read.")
        return 2
    if args.pbp is not None and args.summary is not None:
        print("pass --pbp or --summary, not both")
        return 2
    if args.summary is not None:
        summary = json.loads(args.summary.read_text(encoding="utf-8"))
        grade = grade_card(args.ledger, summary=summary)
    else:
        import pandas as pd

        frame = pd.read_parquet(args.pbp) if args.pbp.suffix == ".parquet" else pd.read_csv(args.pbp)
        grade = grade_card(args.ledger, plays=frame.to_dict("records"))
    print(format_grade(grade))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
