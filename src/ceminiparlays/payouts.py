from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ceminiparlays.resources import read_config_text

POWER_ALIASES = {"power", "standard"}
FLEX_ALIASES = {"flex"}
DISPLAY_NAMES = {
    "underdog": "Underdog",
    "prizepicks": "PrizePicks",
    "hardrock": "Hard Rock",
    "fanduel": "FanDuel",
    "draftkings": "DraftKings",
    "betmgm": "BetMGM",
    "polymarket": "Polymarket",
    "kalshi": "Kalshi",
}
SPORTSBOOK_PLATFORMS = {"hardrock", "fanduel", "draftkings", "betmgm"}
#: Prediction venues. Each leg is a 0-1 contract; a combo is the product of
#: independently settled binaries (DKeX COMBOS), paper only.
PREDICTION_PLATFORMS = {"polymarket", "kalshi"}
PLATFORM_ALIASES = {
    "hard_rock": "hardrock",
    "hardrockbet": "hardrock",
    "hr": "hardrock",
    "hard-rock": "hardrock",
    "fd": "fanduel",
    "fan_duel": "fanduel",
    "dk": "draftkings",
    "draft_kings": "draftkings",
    "mgm": "betmgm",
    "bet_mgm": "betmgm",
    "bet-mgm": "betmgm",
    "poly": "polymarket",
    "polymarket": "polymarket",
    "kalshi": "kalshi",
}


def normalize_platform(platform: str) -> str:
    token = (platform or "").strip().lower()
    return PLATFORM_ALIASES.get(token, token)


@dataclass(frozen=True)
class PayoutTable:
    platform: str
    mode: str
    legs: int
    all_hit: float
    minus_1: float = 0.0
    minus_2: float = 0.0
    note: str = ""

    def multiplier_for_hits(self, hits: int) -> float:
        misses = self.legs - hits
        if misses <= 0:
            return self.all_hit
        if misses == 1:
            return self.minus_1
        if misses == 2:
            return self.minus_2
        return 0.0


def display_name(platform: str) -> str:
    return DISPLAY_NAMES.get(platform.lower(), platform.title())


def _missing_row_message(platform: str, mode: str, legs: int) -> str:
    display = display_name(platform)
    key = mode.lower()
    if key in FLEX_ALIASES:
        return f"{display} flex has no {legs}-leg row. Use standard or slip-size 3+."
    label = "standard" if key in POWER_ALIASES and platform.lower() == "underdog" else key
    return f"{display} {label} has no {legs}-leg row. Use slip-size 2-6."


def _missing_mode_message(platform: str, mode: str) -> str:
    return f"{display_name(platform)} has no {mode!r} payout block; pick standard, power, or flex."


def load_profile(platform: str, profile_dir: Path | None = None) -> dict:
    if profile_dir is not None:
        path = Path(profile_dir) / f"{platform}.json"
        if not path.is_file():
            raise FileNotFoundError(f"payout profile not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        text = read_config_text("payout_profiles", f"{platform}.json")
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"payout profile not found: {platform} (config/ or package data)"
        ) from exc
    return json.loads(text)


def _mode_block(profile: Mapping[str, object], platform: str, mode: str) -> Mapping[str, object]:
    key = mode.lower()
    if key in POWER_ALIASES:
        for alias in ("standard", "power"):
            block = profile.get(alias)
            if isinstance(block, Mapping):
                return block
    if key in FLEX_ALIASES:
        block = profile.get("flex")
        if isinstance(block, Mapping):
            return block
    raise ValueError(_missing_mode_message(platform, mode))


def resolve_payout(
    platform: str,
    mode: str,
    legs: int,
    displayed_multiplier: float | None = None,
    profile_dir: Path | None = None,
) -> PayoutTable:
    """Return the payout table. Prefer the in-app displayed all-hit multiplier."""

    platform = normalize_platform(platform)
    if platform in PREDICTION_PLATFORMS:
        display = display_name(platform)
        if mode.lower() in FLEX_ALIASES:
            raise ValueError(
                f"{display} COMBOS are independent binaries; flex is not modeled. "
                "Use --mode standard."
            )
        if displayed_multiplier is None:
            raise ValueError(
                f"{display} has no fixed table. Pass --displayed-odds (American), "
                "--displayed-multiplier (decimal), or type contract_price on every "
                "combo leg."
            )
        if displayed_multiplier <= 1:
            raise ValueError("displayed multiplier must be greater than 1")
        return PayoutTable(
            platform=platform,
            mode="standard",
            legs=legs,
            all_hit=float(displayed_multiplier),
            note=f"{platform}: COMBOS pay the product of independent binaries",
        )
    if platform in SPORTSBOOK_PLATFORMS:
        display = display_name(platform)
        if mode.lower() in FLEX_ALIASES:
            raise ValueError(
                f"{display} Flex Parlay is not modeled. Use standard and the "
                "displayed SGP / parlay American price."
            )
        if displayed_multiplier is None:
            raise ValueError(
                f"{display} has no fixed lounge table. Pass --displayed-odds "
                "(American) or --displayed-multiplier (decimal), or type "
                "slip_odds / slip_multiplier / leg_odds on the CSV."
            )
        if displayed_multiplier <= 1:
            raise ValueError("displayed multiplier must be greater than 1")
        return PayoutTable(
            platform=platform,
            mode="standard",
            legs=legs,
            all_hit=float(displayed_multiplier),
            note=f"{platform}: confirm the in-app American parlay/SGP price",
        )

    profile = load_profile(platform, profile_dir)
    block = _mode_block(profile, platform, mode)
    row = block.get(str(legs))
    if not isinstance(row, Mapping):
        raise ValueError(_missing_row_message(platform, mode, legs))
    if displayed_multiplier is not None:
        # ``is not None`` (not truthy): an explicit 0.0 is a bad multiplier, not
        # a missing one. Fail closed instead of silently pricing the table (I-19).
        if displayed_multiplier <= 0:
            raise ValueError("displayed multiplier must be positive")
        all_hit = float(displayed_multiplier)
    else:
        all_hit = float(row["all"])
    note = ""
    if mode.lower() in FLEX_ALIASES:
        # Flex minus_1 / minus_2 always come from the July table; an override of
        # all_hit does not reprice the partials (I-15).
        note = "flex_partials=table (July tables; confirm in-app)"
    return PayoutTable(
        platform=str(profile.get("platform", platform)),
        mode=mode.lower(),
        legs=legs,
        all_hit=all_hit,
        minus_1=float(row.get("minus_1", 0.0)),
        minus_2=float(row.get("minus_2", 0.0)),
        note=note,
    )


def breakeven_per_leg(multiplier: float, legs: int) -> float:
    """Independent equal-leg breakeven hit rate for an all-or-nothing slip."""

    if multiplier <= 0 or legs < 1:
        raise ValueError("multiplier and legs must be positive")
    return float(multiplier ** (-1.0 / legs))


def implied_slip_win(multiplier: float) -> float:
    if multiplier <= 0:
        raise ValueError("multiplier must be positive")
    return 1.0 / multiplier


def power_ev(p_joint: float, multiplier: float) -> float:
    return p_joint * multiplier - 1.0


def flex_ev(
    p_all: float,
    p_minus_1: float,
    p_minus_2: float,
    table: PayoutTable,
) -> float:
    return (
        p_all * table.all_hit
        + p_minus_1 * table.minus_1
        + p_minus_2 * table.minus_2
        - 1.0
    )
