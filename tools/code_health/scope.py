"""Scope tiers for the code-health queue.

Three tiers keep this tool off the evaluation path and off the action boundary.

- FREE: may change with no extra gate.
- EVALUATION: feeds a price, a stake, or a grade. A change here can move a
  metric while every test still passes. The queue records the finding, and the
  loop refuses it until the operator allows a baseline rerun.
- PROTECTED: holds the action boundary or a frozen design-log decision. The
  scanner never queues a finding here.

Ban that no tier relaxes: no finding may add a path from analysis to a
bet-submission surface, and none may add a dependency that could.
"""

from __future__ import annotations

from dataclasses import dataclass

FREE = "free"
EVALUATION = "evaluation"
PROTECTED = "protected"

#: The action boundary, the licensed HTTP paths, and the files frozen by
#: design-log 001. The scanner skips these as targets.
PROTECTED_MODULES: frozenset[str] = frozenset(
    {
        "cli.py",  # dispatch surface; one wrong branch reaches an action
        "hardrock_book.py",  # public sportsbook read
        "odds_api.py",  # licensed HTTP
        "jev_client.py",  # licensed HTTP
        "jev_gate.py",  # frozen by design-log 001
        "jev_sizing.py",  # frozen by design-log 001
        "odds.py",  # the body of american_to_implied is frozen
        "slip_screen.py",  # screen output must not trigger an action
        "slip_annotations.py",
        "numbered_span.py",
        "d1_local.py",
    }
)

#: Modules whose numbers reach a card or a ledger. Renaming a step, changing a
#: default, or reordering a normalisation here can move a metric.
EVALUATION_MODULES: frozenset[str] = frozenset(
    {
        "bankroll.py",
        "book_team.py",
        "ceminidfs.py",
        "closings.py",
        "clv.py",
        "compose.py",
        "copula.py",
        "correlation.py",
        "delta_rho.py",
        "environment.py",
        "fair.py",
        "feature_cache.py",
        "fetch.py",
        "grade.py",
        "grade_card.py",
        "half_edge.py",
        "inactive_gate.py",
        "io.py",
        "kelly.py",
        "lag_scanner.py",
        "late_active.py",
        "markets.py",
        "matchup_calibrate.py",
        "matchup_features.py",
        "matchup_math.py",
        "matchup_scanner.py",
        "matchup_score.py",
        "matchup_surface.py",
        "names.py",
        "payouts.py",
        "proppricing.py",
        "q4_checkdown.py",
        "quarter_usage.py",
        "roster.py",
        "season_ledger.py",
        "slips.py",
        "sunday_card.py",
        "weather.py",
        "week7_card.py",
        "week8_card.py",
    }
)

#: Import roots the package must never gain. Mirrors ``tests/test_no_network.py``.
BANNED_IMPORT_ROOTS: frozenset[str] = frozenset(
    {
        "requests",
        "httpx",
        "aiohttp",
        "selenium",
        "playwright",
        "websocket",
        "urllib.request",
    }
)

#: The only modules allowed to open an HTTP connection, per ``test_no_network``.
#: All three are also protected, so this tool never proposes a change to one.
LICENSED_HTTP: frozenset[str] = frozenset(
    {"odds_api.py", "jev_client.py", "hardrock_book.py"}
)


def tier(module_name: str) -> str:
    """Return the tier for one module file name."""

    if module_name in PROTECTED_MODULES:
        return PROTECTED
    if module_name in EVALUATION_MODULES:
        return EVALUATION
    return FREE


def is_scannable(module_name: str) -> bool:
    """True when the scanner may queue a finding for this module."""

    return tier(module_name) != PROTECTED


def requires_rebaseline(module_name: str) -> bool:
    """True when a change to this module needs a baseline rerun."""

    return tier(module_name) == EVALUATION


def evaluation_guard(module_name: str) -> str:
    """The guard a finding carries. ``rebaseline`` blocks the loop by default."""

    return "rebaseline" if requires_rebaseline(module_name) else "none"


#: Findings that add a test or drop an import no code uses. Neither can move a
#: metric, so neither needs a baseline rerun.
ADDITIVE_KINDS: frozenset[str] = frozenset({"test_gap", "unused_import"})


def finding_guard(module_name: str, kind: str) -> str:
    """The guard for one finding. A structural change on the scoring path is gated."""

    if tier(module_name) != EVALUATION:
        return "none"
    if kind in ADDITIVE_KINDS:
        return "none"
    return "rebaseline"


@dataclass(frozen=True)
class ScopeReport:
    """The tier lists, for the ``scope`` subcommand."""

    free: tuple[str, ...]
    evaluation: tuple[str, ...]
    protected: tuple[str, ...]

    def as_lines(self) -> list[str]:
        lines = [f"protected ({len(self.protected)}): never queued"]
        lines.extend(f"  {name}" for name in self.protected)
        lines.append(f"evaluation ({len(self.evaluation)}): queued, loop guards")
        lines.extend(f"  {name}" for name in self.evaluation)
        lines.append(f"free ({len(self.free)}): in scope")
        lines.extend(f"  {name}" for name in self.free)
        return lines


def report(module_names: list[str]) -> ScopeReport:
    """Split known module names into the three tiers."""

    buckets: dict[str, list[str]] = {FREE: [], EVALUATION: [], PROTECTED: []}
    for name in sorted(module_names):
        buckets[tier(name)].append(name)
    return ScopeReport(
        free=tuple(buckets[FREE]),
        evaluation=tuple(buckets[EVALUATION]),
        protected=tuple(buckets[PROTECTED]),
    )
