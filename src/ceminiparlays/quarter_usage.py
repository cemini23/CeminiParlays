"""Player quarter target and rush counts.

Empirical Bayes shares use ``quarter_share``. Both counts at zero keep the
0.25 prior. A running back is a fourth-quarter clock grinder when his rush
share is high and his pass share is low. The same test runs on the season
sum and on the latest game with at least eight rushes, so one clock-kill
game is not hidden by earlier pass-catching weeks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ceminiparlays.book_team import canonical_team
from ceminiparlays.names import canonical_person, loose_name

HEAVY_RUSH_ATT = 8.0
RUSH_SHARE_MIN = 0.30
TARGET_SHARE_MAX = 0.20
PASS_RATIO_MAX = 0.18
COUNT_FIELDS = (
    "q3_targets",
    "q4_targets",
    "total_targets",
    "q4_rush_att",
    "total_rush_att",
    "q4_trail_targets",
    "q4_lead_rush_att",
)


@dataclass(frozen=True)
class QuarterCounts:
    q3_targets: float = 0.0
    q4_targets: float = 0.0
    total_targets: float = 0.0
    q4_rush_att: float = 0.0
    total_rush_att: float = 0.0
    q4_trail_targets: float = 0.0
    q4_lead_rush_att: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "q3_targets": self.q3_targets,
            "q4_targets": self.q4_targets,
            "total_targets": self.total_targets,
            "q4_rush_att": self.q4_rush_att,
            "total_rush_att": self.total_rush_att,
            "q4_trail_targets": self.q4_trail_targets,
            "q4_lead_rush_att": self.q4_lead_rush_att,
        }


@dataclass(frozen=True)
class UsageBundle:
    season: QuarterCounts
    recent: QuarterCounts | None = None


def _finite(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def q4_pass_ratio(q4_targets: float, q4_rush_att: float) -> float:
    """Smoothed share of fourth-quarter chances that are targets.

    ``(targets + 1.5) / (targets + rushes + 6)``.
    """

    targets = max(0.0, float(q4_targets))
    rushes = max(0.0, float(q4_rush_att))
    return (targets + 1.5) / (targets + rushes + 6.0)


def _share(part: float, total: float) -> float:
    if total <= 0.0:
        return 0.0
    return max(0.0, float(part)) / float(total)


def is_q4_clock_grinder(position: str, counts: QuarterCounts) -> bool:
    """True for a back who runs the fourth-quarter clock and rarely catches.

    Rush share must be above 0.30. Target share must be below 0.20, or the
    pass-to-run ratio must be below 0.18. A zero target total counts as a
    zero target share.
    """

    if str(position or "").strip().upper() != "RB":
        return False
    if _share(counts.q4_rush_att, counts.total_rush_att) <= RUSH_SHARE_MIN:
        return False
    low_targets = _share(counts.q4_targets, counts.total_targets) < TARGET_SHARE_MAX
    low_ratio = q4_pass_ratio(counts.q4_targets, counts.q4_rush_att) < PASS_RATIO_MAX
    return low_targets or low_ratio


def clock_grinder_role(
    position: str,
    season: QuarterCounts,
    recent: QuarterCounts | None = None,
) -> bool:
    """Season counts or the latest heavy rush game mark the role."""

    if is_q4_clock_grinder(position, season):
        return True
    if recent is not None and is_q4_clock_grinder(position, recent):
        return True
    return False


def counts_from_row(row: dict) -> QuarterCounts | None:
    """Read the seven count fields. ``None`` when every field is absent."""

    present = [field for field in COUNT_FIELDS if _finite(row.get(field)) is not None]
    if not present:
        return None
    values = {field: _finite(row.get(field)) or 0.0 for field in COUNT_FIELDS}
    return QuarterCounts(**values)


def _empty_bucket() -> dict[str, float]:
    return {field: 0.0 for field in COUNT_FIELDS}


def _bucket_counts(bucket: dict[str, float]) -> QuarterCounts:
    return QuarterCounts(**{field: float(bucket[field]) for field in COUNT_FIELDS})


def _add_play(bucket: dict[str, float], play: dict) -> None:
    quarter = _finite(play.get("qtr"))
    if quarter is None:
        return
    qtr = int(quarter)
    score = _finite(play.get("score_differential"))
    pass_attempt = _finite(play.get("pass_attempt")) or 0.0
    rush_attempt = _finite(play.get("rush_attempt")) or 0.0
    if pass_attempt > 0.0 and str(play.get("receiver_player_name") or "").strip():
        bucket["total_targets"] += pass_attempt
        if qtr == 3:
            bucket["q3_targets"] += pass_attempt
        elif qtr == 4:
            bucket["q4_targets"] += pass_attempt
            if score is not None and score < 0.0:
                bucket["q4_trail_targets"] += pass_attempt
    if rush_attempt > 0.0 and str(play.get("rusher_player_name") or "").strip():
        bucket["total_rush_att"] += rush_attempt
        if qtr == 4:
            bucket["q4_rush_att"] += rush_attempt
            if score is not None and score > 0.0:
                bucket["q4_lead_rush_att"] += rush_attempt


def _play_kept(play: dict, before_week: int | None) -> bool:
    if before_week is None:
        return True
    week = _finite(play.get("week"))
    if week is None:
        return True
    return int(week) < int(before_week)


def _person_key(name: str, team: str) -> tuple[str, str]:
    return canonical_team(team), canonical_person(name)


def counts_from_plays(
    plays: list[dict],
    *,
    before_week: int | None = None,
) -> dict[tuple[str, str], UsageBundle]:
    """Sum targets and rushes from local play-by-play.

    The key is ``(team, canonical person)``. ``before_week`` drops that week
    and every later week when the play has a week number.
    """

    season: dict[tuple[str, str], dict[str, float]] = {}
    by_week: dict[tuple[tuple[str, str], int], dict[str, float]] = {}
    for play in plays:
        if not _play_kept(play, before_week):
            continue
        team = canonical_team(str(play.get("posteam") or ""))
        if not team:
            continue
        week_value = _finite(play.get("week"))
        week = int(week_value) if week_value is not None else None
        names: list[tuple[str, str]] = []
        if (_finite(play.get("pass_attempt")) or 0.0) > 0.0:
            receiver = str(play.get("receiver_player_name") or "").strip()
            if receiver:
                names.append(("pass", receiver))
        if (_finite(play.get("rush_attempt")) or 0.0) > 0.0:
            rusher = str(play.get("rusher_player_name") or "").strip()
            if rusher:
                names.append(("rush", rusher))
        seen: set[tuple[str, str]] = set()
        for _kind, name in names:
            key = _person_key(name, team)
            if key in seen or not key[1]:
                continue
            seen.add(key)
            season.setdefault(key, _empty_bucket())
            _add_play(season[key], play)
            if week is not None:
                week_key = (key, week)
                by_week.setdefault(week_key, _empty_bucket())
                _add_play(by_week[week_key], play)
    bundles: dict[tuple[str, str], UsageBundle] = {}
    for key, bucket in season.items():
        recent: QuarterCounts | None = None
        weeks = sorted(week for (person, week) in by_week if person == key)
        for week in reversed(weeks):
            sample = _bucket_counts(by_week[(key, week)])
            if sample.total_rush_att >= HEAVY_RUSH_ATT:
                recent = sample
                break
        bundles[key] = UsageBundle(season=_bucket_counts(bucket), recent=recent)
    return bundles


def _initial(name: str) -> str:
    parts = loose_name(name).split()
    if not parts:
        return ""
    return parts[0][:1]


def _last(name: str) -> str:
    parts = loose_name(name).split()
    if not parts:
        return ""
    return parts[-1]


def match_usage(
    player: dict,
    bundles: dict[tuple[str, str], UsageBundle],
) -> UsageBundle | None:
    """Join a telemetry row to play-by-play counts.

    Exact canonical name wins. A unique first-initial and last-name pair on
    the same team is the fallback. ``K.Gainwell`` joins ``Kenneth Gainwell``.
    """

    team = canonical_team(str(player.get("team") or ""))
    name = str(player.get("player_name") or "")
    if not team or not loose_name(name):
        return None
    direct = bundles.get((team, canonical_person(name)))
    if direct is not None:
        return direct
    initial = _initial(name)
    last = _last(name)
    if not initial or not last:
        return None
    hits: list[UsageBundle] = []
    for (row_team, person), bundle in bundles.items():
        if row_team != team or _last(person) != last or _initial(person) != initial:
            continue
        hits.append(bundle)
    if len(hits) == 1:
        return hits[0]
    return None


def attach_quarter_counts(
    players: list[dict],
    plays: list[dict] | None,
    *,
    before_week: int | None = None,
) -> list[str]:
    """Write count fields onto each player row. Return blocked-role names.

    A row that already has the count fields keeps those numbers. Play-by-play
    still supplies the latest heavy rush game for the grinder test.
    """

    bundles = counts_from_plays(plays or [], before_week=before_week)
    blocked: list[str] = []
    for player in players:
        bundle = match_usage(player, bundles) if bundles else None
        typed = counts_from_row(player)
        season = typed if typed is not None else (bundle.season if bundle else None)
        if season is None:
            player["q4_clock_grinder"] = False
            continue
        if typed is None:
            player.update(season.as_dict())
        recent = bundle.recent if bundle is not None else None
        position = str(player.get("position") or "")
        grinder = clock_grinder_role(position, season, recent)
        player["q4_clock_grinder"] = grinder
        if grinder:
            blocked.append(str(player.get("player_name") or ""))
    return blocked


def reception_over_blocked(player: dict, market: str, side: str) -> bool:
    """True when a clock grinder must not take a fourth-quarter catch over."""

    if str(side or "") != "over":
        return False
    if str(market or "") not in {"receptions_q4", "rec_yds_q4"}:
        return False
    return bool(player.get("q4_clock_grinder"))
