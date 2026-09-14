# HY3 audit — Hard Rock Week 1 (Sun 2026-09-13)

Auditor: OpenRouter `tencent/hy3`. OpenCode `opencode/hy3-free` returned `UnknownError` (sidecar down).

# CeminiParlays Week 1 Hard Rock Cash Parlays — Educational Audit

## 1. Verdict
The Week 1 paper‑cash exercise produced a net **+$26.07 on $40 risked** across five tickets, with **2 of 5 tickets settling as hits** (ticket B and ticket C). The positive result is attributable to two well‑structured legs (an anytime‑touchdown sequence and a moneyline/under combo). However, the audit identifies blocking product defects in the `ceminiparlays` CLI and process gaps in ticket construction and date handling. The CLI could not grade the supplied ledger, and a UTC‑based fetch window omitted a late‑starting game. The research CLI remains unsuitable for unattended grading until P0 fixes land. Overall verdict: **profitable on paper, but process and product maturity are below acceptable educational standard**.

## 2. What went right
- **Two tickets returned positive PnL as recorded**: ticket B returned **+$14.40 at +288** and ticket C returned **+$36.67 at +367** (figures supplied, not invented).
- **Anytime‑touchdown (ATD) logic succeeded where numeric props failed**: Chase Brown’s ATD leg hit even though his rushing‑yards line (56 vs 57.5) missed two other tickets by 1.5 yards.
- **SNF total and booked under both cleared**: the Sunday‑night total closed 48 vs a 47.5 line (hit), and the NYJ@TEN actual total of 33 beat a booked under‑39, supporting ticket C.
- **Game diversification inside tickets** was attempted by the compose step, reducing same‑game correlation within a single slip.
- **No prohibited activity**: the CLI performed no scraping and no auto‑submit, consistent with educational use.

## 3. What went wrong — betting process
- **Player concentration**: Chase Brown appeared as an anchor on A‑2leg, A‑4leg, and B. His rushing line (56 vs 57.5) caused the two $10 tickets to miss by 1.5 yards, showing correlated exposure that多元化 across tickets did not mitigate.
- **Date‑window misuse**: `--date 2026-09-13` was used, but DAL@NYG commenced 2026‑09‑14T00:20Z. Under the CLI’s UTC midnight‑to‑midnight window, the SNF data would be excluded, creating a blind spot if the operator trusted the fetch.
- **Card‑vs‑booked mismatch (TG‑06)**: ticket C was noted as $5 on under 38.5 on the card, but booked as $10 on under 39 at +367. TG‑01 requires the **booked ticket price before HIT PnL**; using card lines risks misstating stake and liability.
- **Manual board reliance**: ticket C was typed from a thin Hard Rock ML/spread board not represented in the CLI’s legal markets, increasing transcription risk.
- **No pre‑grade validation**: a ledger that crashes the grader was nonetheless used for PnL summary; process should treat a grade failure as blocking.

## 4. What went wrong — product
- **`grade` crash on string outcomes**: `_leg_outcomes` in `grade.py` calls `float()` on lines/actuals. The ledger contained `'yes'`, yielding `could not convert string to float: 'yes'`. This blocks all grading.
- **Void‑vs‑hit ambiguity for yes/no**: if `'yes'` were coerced to `1.0`, an ATD actual would equal a line of `1.0` and be treated as a push/void, destroying the Brown ATD hit. The product lacks discrete win/loss handling for propositional yes/no.
- **Market whitelist incomplete**: `markets.py LEGAL_MARKETS` omits h2h, spreads, and totals. Ticket C’s ML/under derivation is outside supported markets, forcing manual entry.
- **Fetch granularity**: `utc_day_window` ignores event start times and local slate boundaries; it cannot fetch a game that starts after UTC midnight but is part of the prior U.S. date.
- **No concentration guard**: compose pass‑2 may reuse an anchor player across tickets; no warning surfaces the Brown repetition.

## 5. Next‑week operator rules (max 6)
1. **Record booked stake, line, and price before any PnL** (TG‑01); never substitute card mock lines such as $5/u38.5 when $10/u39 was booked.
2. **Cap anchor‑player reuse** across simultaneous tickets; treat Chase Brown’s multi‑ticket appearance as a limit‑breach to avoid correlated misses.
3. **Fetch by event time, not UTC calendar date**; for U.S. slates use ET date or explicit game‑id to include SNF that starts after midnight UTC.
4. **Mark yes/no props as discrete outcomes** (hit/miss) in the ledger; never leave them as bare strings expecting numeric parsing.
5. **Validate thin‑board entries** against CLI‑supported markets; if unsupported, document divergence and do not rely on automated grade.
6. **Dry‑run grade in a sandbox**; treat any converter error as a stop‑ship condition for that ledger.

## 6. Product fixes P0/P1/P2
**P0 (blocking)**
- Patch `grade` to map `yes`/`no` (or equivalent) to discrete win/loss flags; remove `float()` from outcome parsing for propositional legs.
- Extend `LEGAL_MARKETS` to include h2h, spreads, and totals, or add a validated external‑board import path so ticket C is first‑class.
- Replace `utc_day_window` with an event‑start or ET‑slate window, or accept `--game-id`/`--kickoff` so DAL@NYG is fetched correctly.

**P1 (high value)**
- Add a concentration warning when compose reuses an anchor player across tickets (Brown on A‑2leg/A‑4leg/B).
- Enforce TG‑01 in code: require a `booked_price` field before computing HIT PnL; error clearly if missing.

**P2 (hardening)**
- Extend ledger schema to carry both `card_line` and `booked_line` (TG‑06) and surface diffs in audit output.
- Emit educational notes explaining why numeric pushes differ from yes/no hits to prevent void‑logic mistakes.

## 7. Disagreements with Cursor Grok (or none)
- **No fundamental disagreement**. The Cursor Grok thesis (ATD B and ML/under C were the wins; Brown concentration and UTC fetch were misses) matches this audit.
- **Minor extension**: Grok’s P0 list included “grade yes/ML/totals, ET slate window, fetch game markets.” This audit confirms those and adds that the **grade crash is not merely a missing feature but a hard blocker** for any yes/no ledger, warranting explicit unit tests.
- **Process emphasis**: Grok framed card‑vs‑booked (TG‑06) as a product note; we classify the $5/u38.5‑vs‑$10/u39 mismatch primarily as a **TG‑01 process violation** because PnL was derived from booked numbers while the card differed.
- **Nabers note**: consistent with Grok, the Nabers Q‑exclude‑then‑play event was *not* the SNF miss; no contradictory finding.
