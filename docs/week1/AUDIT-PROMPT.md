# Week 1 postmortem — auditor prompt (no secrets)

You are auditing CeminiParlays Week 1 Hard Rock cash parlays (Sun 2026-09-13, graded Mon 2026-09-14). Educational research CLI. No scrapers. No auto-submit. Operator types tickets in-app.

Read (in this repo):

- `docs/week1/2026-09-13-grade-recap.md`
- `docs/week1/2026-09-13-tool-gaps.md`
- `docs/week1/2026-09-14-cursor-grok-audit.md`
- `examples/ledger_week1_hardrock.csv`
- `src/ceminiparlays/grade.py` (`_leg_outcomes` is numeric `float()`)
- `src/ceminiparlays/odds_api.py` (`utc_day_window` is UTC calendar day)
- `src/ceminiparlays/markets.py` (no h2h/spreads/totals)

## Facts (do not invent other PnL)

Paper cash: **+$26.07** on **$40** (A-2leg −$10, A-4leg −$10, B +$14.40 at +288, C +$36.67 at +367, ticket 3 −$5). Hits 2/5.

Brown rush 56 vs 57.5 missed **two** $10 tickets by 1.5 yards; Brown ATD still hit. Cook 57 vs 74.5. Dak 175 vs 262.5, Ferguson 6 vs 29.5. NYJ@TEN total 33 vs booked under 39. SNF total 48 vs 47.5 hit. Nabers was excluded as Q then **played** 6/69; that was not the SNF miss.

CLI: `ceminiparlays grade` on this ledger → `could not convert string to float: 'yes'`.

Fetch `--date 2026-09-13` missed DAL@NYG (`2026-09-14T00:20:00Z`).

TG-01…TG-06: do not auto-apply items marked `do_not_auto_apply`. Never invent reduced-SGP. Never backfill naive product as the booked American.

## Write

Write **only** the file named in the operator message. Markdown with these sections:

1. Verdict (one paragraph: how we did)
2. What went right (bullets, cite tickets)
3. What went wrong — betting process
4. What went wrong — product (cite files)
5. Next-week operator rules (max 6)
6. Product fixes ranked P0/P1/P2 (must include: grade yes/ML/totals without voiding ATD hits; ET slate fetch window; game markets; concentration warning)
7. Disagreements with the Cursor Grok audit (or “none”)

Do not edit Python. Do not commit. Do not read `.env`. Stay in this repo.
