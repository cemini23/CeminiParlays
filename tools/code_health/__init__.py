"""A code-health queue for CeminiParlays.

The queue is a state file that survives between sessions. It is not a report.
Work an item down, then mark it done. A re-scan keeps the status.

No third-party dependency. The mechanical checks use the standard library.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src" / "ceminiparlays"
TESTS_DIR = REPO_ROOT / "tests"
STATE_DIR = REPO_ROOT / ".code-health"
QUEUE_PATH = STATE_DIR / "queue.json"
PACKET_DIR = STATE_DIR / "packets"
