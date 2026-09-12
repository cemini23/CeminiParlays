from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE_DIR = REPO_ROOT / "config" / "payout_profiles"

POWER_ALIASES = {"power", "standard"}
FLEX_ALIASES = {"flex"}


@dataclass(frozen=True)
class PayoutTable:
    platform: str
    mode: str
    legs: int
    all_hit: float
    minus_1: float = 0.0
    minus_2: float = 0.0

    def multiplier_for_hits(self, hits: int) -> float:
        misses = self.legs - hits
        if misses <= 0:
            return self.all_hit
        if misses == 1:
            return self.minus_1
        if misses == 2:
            return self.minus_2
        return 0.0


def load_profile(platform: str, profile_dir: Path | None = None) -> dict:
    directory = Path(profile_dir) if profile_dir else DEFAULT_PROFILE_DIR
    path = directory / f"{platform}.json"
    if not path.is_file():
        raise FileNotFoundError(f"payout profile not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _mode_block(profile: Mapping[str, object], mode: str) -> Mapping[str, object]:
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
    raise KeyError(f"mode {mode!r} missing from payout profile")


def resolve_payout(
    platform: str,
    mode: str,
    legs: int,
    displayed_multiplier: float | None = None,
    profile_dir: Path | None = None,
) -> PayoutTable:
    """Return the payout table. Prefer the in-app displayed all-hit multiplier."""

    profile = load_profile(platform, profile_dir)
    block = _mode_block(profile, mode)
    row = block.get(str(legs))
    if not isinstance(row, Mapping):
        raise KeyError(f"{platform} {mode} has no {legs}-leg row")
    all_hit = float(displayed_multiplier) if displayed_multiplier else float(row["all"])
    return PayoutTable(
        platform=str(profile.get("platform", platform)),
        mode=mode.lower(),
        legs=legs,
        all_hit=all_hit,
        minus_1=float(row.get("minus_1", 0.0)),
        minus_2=float(row.get("minus_2", 0.0)),
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
