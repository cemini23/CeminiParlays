"""Entry point that works with ``python -m code_health`` and as a script."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from code_health.cli import main  # noqa: E402

sys.exit(main())
