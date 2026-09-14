# OpenCode-fallback audit — Hard Rock Week 1 (Sun 2026-09-13)

Auditor: OpenRouter `z-ai/glm-5.2`. OpenCode Zen (`opencode/hy3-free`, `opencode/deepseek-v4-flash-free`, `opencode/x-preview-f-free`) all returned `UnknownError`.

# CeminiParlays Week 1 Audit — Hard Rock Cash Parlays

**Slate:** Sun 2026-09-13 (graded Mon 2026-09-14) | **Paper cash only** | Educational CLI, no scrapers, no auto-submit

---

## 1. Verdict

**Week 1 was a net-positive research result undermined by two orthogonal failures: a betting-process concentration lapse and a product-side fetch/grading boundary condition.** The headline paper PnL is **+$26.07 on $40 staked (2/5 hits)**, but that number is fragile — it is carried entirely by Ticket C (+$36.67 at +367) and Ticket B (+$14.40 at +288), which together outweigh three losers (A-2leg -$10, A-4leg -$10, ticket 3 -$5). Two of the three losing legs lost by margins the model flagged as real exposure (Brown rush 56 vs 57.5; Cook 57 vs 74.5), and the SNF total was effectively a non-bet due to a UTC fetch miss. The product-grade result — a `float('yes')` crash in `grade.py` — means the CLI could not even reproduce this ledger at audit time. **P0 is blocked until `grade` runs clean on this exact ledger.**

---

## 2. What went right

- **ATD B hit clean.** Brown anytime touchdown materialized even though the rush yards leg (56 vs 57.5) missed by 1.5 yards on two $10 tickets. The ATD market and the rush-yards market are discrete exposures; the model's decision to treat them as independent legs rather than correlated pushes was validated.
- **ML/under C hit.** Ticket C — typed from a thin Hard Rock moneyline/spread board and booked at $10/u39/+367 — converted. The card's $5/u38.5 line was different from the booked $10/u39, and the booked price is what the model correctly relied on for HIT PnL (per TG-01).
- **SNF total hit (48 vs 47.5).** The under/over threshold was crossed by 0.5 — a legitimate half-point cover on the booked line. The miss was not a losing bet; it was a fetch-induced non-inclusion.
- **Discrete-leg logic on yes/no.** The `_leg_outcomes` failure surfaced a useful invariant: if `yes/yes` had been silently coerced to `1.0`, then `actual == line` would have VOIDed the ATD hits. The fact that yes/no must remain discrete (hit/miss, not push) is a correct modeling assumption that the product accidentally violated, not a process insight.
- **Diversification within a ticket held.** Compose's intra-ticket game-diversification rule did its job; the reuse problem was cross-ticket, not within-ticket.

---

## 3. What went wrong — betting process

1. **Brown concentration.** Chase Brown anchored three tickets (A-2leg, A-4leg, and B) with rush yards. Two of those missed at 56 vs 57.5 — a 1.5-yard shortfall — and the third leg's ATD hit was the only Brown win. When a single player carries 60% of staked exposure and the rush line misses by a thin margin, the ticket set is effectively a single correlated bet wearing three hats. Pass-2's cross-ticket anchor reuse produced a concentration that no intra-ticket diversification rule could catch.
2. **Thin-board typing on C.** Ticket C was typed from a sparse Hard Rock ML/spread board. It won, so the outcome was fine, but the process — building a +367 ticket from a board that lacks the h2h/spreads/totals markets the model would prefer — is a known-fit mismatch. `markets.py` `LEGAL_MARKETS` has no h2h/spreads/totals, so the model was operating outside its native market vocabulary.
3. **Two $10 tickets decided by 1.5 yards.** A-2leg and A-4leg each lost $10 on Brown 56 vs 57.5. That is not a product failure; it is a process outcome where the line was set just enough above the median that a single modest under cost the whole ticket set.
4. **Nabers exclusion-then-play was not the SNF miss.** Nabers was excluded as Q, then played 6/69. The SNF miss was the UTC-fetch non-inclusion of the DAL@NYG leg, not the Nabers decision. Conflating the two would misdiagnose the slate.

---

## 4. What went wrong — product

1. **`grade.py` crash: `could not convert string to float: 'yes'`.** `_leg_outcomes` calls `float()` on lines/actuals. ATD markets serialize as `'yes'`/`'no'`; the grader has no branch for categorical legs. The CLI could not grade this ledger without manual coercion. This is the single most severe product defect because it blocks the audit loop entirely.
2. **UTC fetch window missed SNF.** `--date 2026-09-13` uses `utc_day_window` (UTC 00:00–00:00). DAL@NYG commenced at 2026-09-14T00:20:00Z — 20 minutes past the UTC day boundary. The fetch returned a slate without SNF, so the model never saw the leg that would have been the cleanest hit on the card (48 vs 47.5).
3. **No h2h/spreads/totals in `LEGAL_MARKETS`.** `markets.py` cannot express the markets Ticket C was typed from. The model built a +367 ticket using a board vocabulary it is not configured to read; the win is not evidence the product is healthy.
4. **Booked vs card price divergence unflagged.** TG-06: C was $5/u38.5 on the card but $10/u39/+367 booked. The model used the booked price for HIT PnL (correct under TG-01), but the product did not surface the divergence as a warning. A mismatch of $5 stake and 0.5-point line between card and booked should be an explicit flag, not a silent assumption.
5. **Cross-ticket anchor reuse undetected.** Pass-2 may reuse an anchor player across tickets; Brown on 3/5 tickets was not flagged. The product has no concentration guard across the ticket set, only within a ticket.

---

## 5. Next-week operator rules (max 6)

1. **No single player may anchor more than two tickets in a slate.** If pass-2 proposes a third reuse, downweight or reject the weakest of the three.
2. **Booked price is the only price.** Before grading any HIT, confirm the booked stake, line, and SGP price from the ticket; never carry card price into PnL (TG-01). If card ≠ booked, log the delta.
3. **SNF and MNF legs require an ET-aware slate window, not `--date` UTC midnight.** If the operator must use UTC, extend the window to capture the next-day kickoff or pass an explicit `--slate` flag.
4. **Do not type tickets from markets absent from `LEGAL_MARKETS`.** Until h2h/spreads/totals are added, ML/under tickets built from thin Hard Rock boards are flagged as out-of-vocabulary.
5. **Grade before staking.** Run `ceminiparlays grade` on the ledger as a dry run; if it cannot convert a leg type, do not submit paper cash until the grader is patched or the leg is manually coerced with a recorded reason.
6. **yes/no legs are discrete hits, not pushes.** Never coerce `yes`→`1.0` for grading; treat ATD as binary hit/miss. `actual == line` on a coerced float is a false VOID.

---

## 6. Product fixes P0/P1/P2

### P0 (block audit)
- **Grade categorical legs.** Add a branch in `_leg_outcomes` for `yes`/`no` (and any other non-numeric ATD-style markets) so `float()` is not called on them. Binary hit/miss, no push semantics.
- **ET slate window for fetch.** Replace or augment `utc_day_window` with an Eastern-time-aware window (or a kickoff-time-based window) so SNF/MNF games starting after UTC midnight are included under `--date`.
- **Fetch game markets.** Ensure `fetch` pulls the full game-market set (h2h, spreads, totals) for each contest, not just player props, so the model is not forced to type from thin boards.

### P1 (quality)
- **Concentration warning.** When a single player appears as an anchor on ≥3 tickets in a slate, emit a warning (not a block) with the aggregate exposure in dollars.
- **Card vs booked divergence flag.** When the card stake/line differs from the booked stake/line, surface the delta in the grade output and require an explicit acknowledgement.

### P2 (hygiene)
- **`LEGAL_MARKETS` expansion.** Add h2h, spreads, and totals to `markets.py` so the model's vocabulary matches the boards it is reading.
- **Coercion audit log.** If any manual coercion (yes→hit, etc.) is applied at grade time, record the reason and the operator who applied it so the ledger remains reproducible.

---

## 7. Disagreements with Cursor Grok

**None of substance.** The Cursor Grok thesis — ATD B and ML/under C were the wins; Brown concentration and UTC fetch were the product/process misses; P0 = grade yes/ML/totals, ET slate window, fetch game markets; P1 = concentration warning — matches this audit's findings precisely. The only nuance worth recording:

- The Cursor Grok P0 framing "grade yes/ML/totals" conflates two distinct fixes: the `float('yes')` crash (categorical-leg grading) and the `LEGAL_MARKETS` absence of ML/spreads/totals (fetch vocabulary). They are separate code paths and should be ticketed separately so that patching one does not silently assume the other. This is a scoping refinement, not a disagreement with the thesis.
