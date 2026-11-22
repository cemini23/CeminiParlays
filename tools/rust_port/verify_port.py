#!/usr/bin/env python3
"""Gate the Rust copula port on a real, non-empty pytest run.

The script runs ``tests/test_copula_rust_parity.py`` twice, each time writing a
JUnit XML report that it then parses:

1. the whole parity module (``parity_tests``);
2. the Kelly subset selected with ``-m kelly_invariant``
   (``kelly_invariant_tests``).

On success it prints exactly one line::

    PARITY_OK parity_tests=<n> kelly_invariant_tests=<m> total_passed=<n>

``total_passed`` is the number of passing tests in the parity run (the Kelly run
is a subset of it, so the two runs are not summed). The script exits 1 on any
failure, any error, any skip, a run that collected zero tests, a parse
inconsistency, a non-zero pytest exit status, or ``passed != collected``. An
exit code of 0 with an empty run is treated as a failure.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
PARITY_MODULE = "tests/test_copula_rust_parity.py"
KELLY_MARKER = "kelly_invariant"
KILL_SWITCH = "FAST_ANYTHING_DISABLE"


@dataclass(frozen=True)
class Report:
    label: str
    returncode: int
    reported: int
    collected: int
    passed: int
    failures: int
    errors: int
    skipped: int
    stdout: str


def _run_pytest(extra: list[str], report: Path) -> tuple[int, str]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        PARITY_MODULE,
        "-q",
        "-p",
        "no:cacheprovider",
        f"--junitxml={report}",
        *extra,
    ]
    process = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return process.returncode, (process.stdout or "") + (process.stderr or "")


def _parse(report: Path, label: str, returncode: int, output: str) -> Report:
    if not report.is_file():
        raise SystemExit(
            f"verify_port: {label}: pytest wrote no JUnit report\n{output[-2000:]}"
        )
    root = ElementTree.parse(report).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    if not suites:
        raise SystemExit(f"verify_port: {label}: JUnit report has no <testsuite>")

    reported = 0
    cases = []
    for suite in suites:
        reported += int(suite.get("tests", 0))
        cases.extend(suite.findall("testcase"))

    failures = sum(1 for case in cases if case.find("failure") is not None)
    errors = sum(1 for case in cases if case.find("error") is not None)
    skipped = sum(1 for case in cases if case.find("skipped") is not None)
    collected = len(cases)
    passed = collected - failures - errors - skipped
    return Report(
        label=label,
        returncode=returncode,
        reported=reported,
        collected=collected,
        passed=passed,
        failures=failures,
        errors=errors,
        skipped=skipped,
        stdout=output,
    )


def _collect(report: Path, label: str, extra: list[str]) -> Report:
    returncode, output = _run_pytest(extra, report)
    return _parse(report, label, returncode, output)


def _problems(report: Report) -> list[str]:
    found = []
    if report.returncode != 0:
        found.append(f"{report.label}: pytest exited {report.returncode}")
    if report.collected == 0:
        found.append(f"{report.label}: collected zero tests")
    if report.reported != report.collected:
        found.append(
            f"{report.label}: report says {report.reported} tests, parsed "
            f"{report.collected} cases"
        )
    if report.failures:
        found.append(f"{report.label}: {report.failures} failed")
    if report.errors:
        found.append(f"{report.label}: {report.errors} errored")
    if report.skipped:
        found.append(f"{report.label}: {report.skipped} skipped")
    if report.passed != report.collected:
        found.append(
            f"{report.label}: passed {report.passed} != collected {report.collected}"
        )
    return found


def main() -> int:
    if os.environ.get(KILL_SWITCH, "").strip() == "1":
        sys.stderr.write(
            f"verify_port: {KILL_SWITCH}=1 forces the python engine, so a parity "
            "run would compare python to python; unset it and re-run\n"
        )
        return 1

    with tempfile.TemporaryDirectory(prefix="rust_port_verify_") as tmp:
        parity = _collect(
            Path(tmp) / "parity.xml", "parity", []
        )
        kelly = _collect(
            Path(tmp) / "kelly.xml", f"parity-{KELLY_MARKER}", ["-m", KELLY_MARKER]
        )

    problems = _problems(parity) + _problems(kelly)
    if problems:
        sys.stderr.write("verify_port: FAILED\n")
        for problem in problems:
            sys.stderr.write(f"  - {problem}\n")
        for report in (parity, kelly):
            if report.stdout.strip():
                sys.stderr.write(f"\n--- {report.label} output ---\n")
                sys.stderr.write(report.stdout[-4000:])
        return 1

    print(
        f"PARITY_OK parity_tests={parity.passed} "
        f"kelly_invariant_tests={kelly.passed} "
        f"total_passed={parity.passed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
