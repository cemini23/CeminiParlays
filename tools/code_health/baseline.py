"""A frozen fingerprint of the scoring output.

The queue guards an evaluation module because a refactor there can move a
number while every test still passes. This harness answers the question the
tests cannot: did any printed value change?

Each command runs on a shipped example file. The fingerprint is the hash of
stdout plus the exit code. ``check`` compares against the stored snapshot. A
refactor that changes one number fails the check.

``update`` rewrites the snapshot. Use it only when a change is meant to move a
number, and say so in the commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = Path(__file__).resolve().parent / "baseline.json"

#: Commands that exercise the pricing, grading, and ranking paths on shipped
#: fixtures. Do not add a command that needs the network or pandas.
COMMANDS: list[list[str]] = [
    ["clv", "--ledger", "examples/ledger_week5_clv.csv"],
    ["clv", "--ledger", "examples/ledger_week5_clv.csv", "--json"],
    ["clv", "--ledger", "examples/ledger_week5.csv"],
    ["grade", "--ledger", "examples/ledger.csv"],
    ["grade", "--ledger", "examples/ledger_week1_hardrock.csv"],
    [
        "rank",
        "--lines",
        "examples/hardrock_lines.csv",
        "--distributions",
        "examples/distributions.csv",
        "--platform",
        "hardrock",
        "--mode",
        "power",
        "--no-strict",
    ],
    ["devig", "--over", "-110", "--under", "-110"],
    [
        "compose",
        "--lines",
        "examples/sunday_lines.csv",
        "--auto",
        "--platform",
        "hardrock",
        "--allow-rec-line",
        "--n-tickets",
        "5",
        "--out-dir",
        "runs/baseline",
    ],
]


def _environment() -> dict[str, str]:
    env = {
        "PYTHONPATH": "src",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    }
    return env


def fingerprint(command: list[str]) -> str:
    """Hash of stdout and the exit code for one command."""

    result = subprocess.run(
        [sys.executable, "-m", "ceminiparlays", *command],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=_environment(),
        check=False,
    )
    payload = result.stdout + "\n--exit--\n" + str(result.returncode)
    return hashlib.sha256(payload.encode()).hexdigest()


def measure() -> dict[str, str]:
    return {" ".join(command): fingerprint(command) for command in COMMANDS}


def load() -> dict[str, str]:
    if not SNAPSHOT.exists():
        return {}
    return json.loads(SNAPSHOT.read_text(encoding="utf-8")).get("fingerprints", {})


def save(fingerprints: dict[str, str]) -> None:
    payload = {"version": 1, "fingerprints": fingerprints}
    SNAPSHOT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="code_health.baseline",
        description="Freeze and check the printed scoring output.",
    )
    parser.add_argument("mode", choices=["check", "update", "show"])
    args = parser.parse_args(argv)

    current = measure()
    if args.mode == "show":
        for name, value in sorted(current.items()):
            print(f"{value[:16]}  {name}")
        return 0

    if args.mode == "update":
        save(current)
        print(f"baseline: wrote {len(current)} fingerprints to {SNAPSHOT.name}")
        return 0

    stored = load()
    if not stored:
        print("baseline: no snapshot. Run with `update` first.")
        return 2

    drift = 0
    for name, value in sorted(current.items()):
        expected = stored.get(name)
        if expected is None:
            print(f"baseline: new command, not in the snapshot: {name}")
            drift += 1
        elif expected != value:
            print(f"baseline: OUTPUT CHANGED: {name}")
            drift += 1
    for name in sorted(set(stored) - set(current)):
        print(f"baseline: command removed from the harness: {name}")
        drift += 1

    if drift:
        print(f"baseline: {drift} difference(s). The printed numbers moved.")
        return 1
    print(f"baseline: identical across {len(current)} commands")
    return 0


if __name__ == "__main__":
    sys.exit(main())
