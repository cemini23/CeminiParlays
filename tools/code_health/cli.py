"""Command line for the code-health queue."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import PACKET_DIR, QUEUE_PATH, REPO_ROOT, SRC_DIR
from . import review, scan, scope
from .loop import guard_check, pick, work_order, working_diff
from .queue import STATUSES, Queue

EPILOG = """run from the repo root:
  PYTHONPATH=tools .venv/bin/python -m code_health scan
  PYTHONPATH=tools .venv/bin/python -m code_health top
  PYTHONPATH=tools .venv/bin/python -m code_health loop
"""


def _load() -> Queue:
    return Queue.load(QUEUE_PATH)


def _save(queue: Queue) -> None:
    queue.save(QUEUE_PATH)


def cmd_scan(args: argparse.Namespace) -> int:
    queue = _load()
    fresh = scan.scan(REPO_ROOT)
    added, updated, absent = queue.merge_scan(fresh)
    _save(queue)
    if args.json:
        print(json.dumps([finding.to_dict() for finding in fresh], indent=2))
        return 0
    print(f"scan: {len(fresh)} findings ({added} new, {updated} updated, {absent} absent)")
    by_kind: dict[str, int] = {}
    for finding in fresh:
        by_kind[finding.kind] = by_kind.get(finding.kind, 0) + 1
    for kind, count in sorted(by_kind.items(), key=lambda item: -item[1]):
        print(f"  {kind:<16} {count}")
    stats = queue.stats()
    print(
        f"queue: {stats['total']} total, {stats['eligible']} eligible, "
        f"{stats['guarded']} guarded"
    )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    queue = _load()
    rows = queue.sorted()
    if args.status:
        rows = [row for row in rows if row.status == args.status]
    if args.kind:
        rows = [row for row in rows if row.kind == args.kind]
    if args.eligible:
        rows = [row for row in rows if row.guard == "none" and row.status == "open"]
    for finding in rows[: args.n]:
        guard = "" if finding.guard == "none" else f" [{finding.guard}]"
        print(
            f"{finding.id}  {finding.score:>3}  {finding.status:<11} "
            f"{finding.kind:<14} {finding.path}:{finding.line}{guard}"
        )
    if len(rows) > args.n:
        print(f"... {len(rows) - args.n} more")
    return 0


def cmd_top(args: argparse.Namespace) -> int:
    queue = _load()
    for finding in queue.eligible(args.allow_rebaseline)[: args.n]:
        print(work_order(finding))
        print("-" * 60)
    return 0


def cmd_loop(args: argparse.Namespace) -> int:
    queue = _load()
    finding = pick(queue, args.allow_rebaseline)
    if finding is None:
        print("no eligible item. run `scan`, or allow a rebaseline.")
        return 0
    finding.status = "in_progress"
    _save(queue)
    print(work_order(finding))
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    queue = _load()
    targets = [f for f in queue.sorted() if f.status == "open" and f.present][: args.n]
    written = review.emit_packets(targets, PACKET_DIR)
    for path in written:
        print(path)
    print(f"review: {len(written)} packets in {PACKET_DIR}")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    queue = _load()
    verdicts = review.load_verdicts(Path(args.file))
    applied = review.apply_verdicts(queue.findings, verdicts)
    _save(queue)
    print(f"record: {applied} of {len(verdicts)} verdicts applied")
    return 0 if applied else 1


def cmd_mark(args: argparse.Namespace) -> int:
    queue = _load()
    finding = queue.get(args.id)
    if finding is None:
        print(f"no finding with id {args.id}")
        return 2
    finding.status = args.status
    if args.note:
        finding.notes.append(args.note)
    _save(queue)
    print(f"{finding.id} -> {finding.status}")
    return 0


def cmd_guard(args: argparse.Namespace) -> int:
    diff = Path(args.diff).read_text(encoding="utf-8") if args.diff else working_diff(REPO_ROOT)
    violations = guard_check(diff)
    if not violations:
        print("guard: clean")
        return 0
    for violation in violations:
        print(f"guard: {violation}")
    return 1


def cmd_stats(args: argparse.Namespace) -> int:
    queue = _load()
    for key, value in queue.stats().items():
        print(f"{key:<12} {value}")
    return 0


def cmd_scope(args: argparse.Namespace) -> int:
    names = sorted(path.name for path in SRC_DIR.glob("*.py"))
    for line in scope.report(names).as_lines():
        print(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code_health",
        description="A persisted code-health queue. Scan, review blind, work one item.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="refresh the queue from the mechanical checks")
    p_scan.add_argument("--json", action="store_true")
    p_scan.set_defaults(func=cmd_scan)

    p_list = sub.add_parser("list", help="list findings")
    p_list.add_argument("--status", choices=STATUSES)
    p_list.add_argument("--kind")
    p_list.add_argument("--eligible", action="store_true", help="open and unguarded only")
    p_list.add_argument("-n", type=int, default=20)
    p_list.set_defaults(func=cmd_list)

    p_top = sub.add_parser("top", help="print the work orders for the top items")
    p_top.add_argument("-n", type=int, default=3)
    p_top.add_argument("--allow-rebaseline", action="store_true")
    p_top.set_defaults(func=cmd_top)

    p_loop = sub.add_parser("loop", help="take the top item and print its work order")
    p_loop.add_argument("--allow-rebaseline", action="store_true")
    p_loop.set_defaults(func=cmd_loop)

    p_review = sub.add_parser("review", help="write blind review packets")
    p_review.add_argument("-n", type=int, default=10)
    p_review.set_defaults(func=cmd_review)

    p_record = sub.add_parser("record", help="merge reviewer verdicts into the queue")
    p_record.add_argument("file")
    p_record.set_defaults(func=cmd_record)

    p_mark = sub.add_parser("mark", help="set a finding status")
    p_mark.add_argument("id")
    p_mark.add_argument("status", choices=STATUSES)
    p_mark.add_argument("--note")
    p_mark.set_defaults(func=cmd_mark)

    p_guard = sub.add_parser("guard", help="refuse a diff that crosses the boundary")
    p_guard.add_argument("--diff", help="read a diff file instead of the worktree")
    p_guard.set_defaults(func=cmd_guard)

    p_stats = sub.add_parser("stats", help="counts by status")
    p_stats.set_defaults(func=cmd_stats)

    p_scope = sub.add_parser("scope", help="show the three tiers")
    p_scope.set_defaults(func=cmd_scope)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
