"""Shared pytest hooks.

A run that collects nothing is a failure. Exit code 0 with zero tests is the
classic way a broken suite (bad path, an import error swallowed by a wrapper, a
deselected-only run) looks green; this turns it red. ``--collect-only`` is
exempt because collecting is its whole purpose.
"""

from __future__ import annotations

import pytest


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if getattr(session.config.option, "collectonly", False):
        return
    if session.testscollected == 0:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
