"""Copy a dated Hard Rock card into the slate and recap folders.

This module does not open a socket and it does not submit a bet.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ceminiparlays.resources import REPO_ROOT


def sync_dated_card(
    csv_path: Path,
    md_path: Path,
    slate_date: str,
    roots: list[Path],
) -> list[Path]:
    """Copy the card CSV and markdown into ``root / slate_date`` for each root.

    The file names stay ``hardrock_card_YYYY-MM-DD.csv`` and
    ``card_YYYY-MM-DD.md``. A missing source raises ``FileNotFoundError``.
    """

    sources = [Path(csv_path), Path(md_path)]
    for source in sources:
        if not source.is_file():
            raise FileNotFoundError(f"card file missing: {source}")
    written: list[Path] = []
    for root in roots:
        dest = Path(root) / slate_date
        dest.mkdir(parents=True, exist_ok=True)
        for source in sources:
            target = dest / source.name
            shutil.copy2(source, target)
            written.append(target)
    return written


def default_sync_roots() -> list[Path]:
    """Repo slate folders, plus ``/workspace`` when that directory exists."""

    roots = [
        REPO_ROOT / "parlays-slate",
        REPO_ROOT / "parlays-recap",
    ]
    workspace = Path("/workspace")
    if workspace.is_dir():
        roots.extend(
            [
                workspace / "parlays-slate",
                workspace / "parlays-recap",
            ]
        )
    return roots
