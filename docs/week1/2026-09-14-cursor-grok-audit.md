# Cursor Grok audit — Hard Rock Week 1 (Sun 2026-09-13)

Auditor: Cursor Grok (this session). Graded from `docs/week1/2026-09-13-grade-recap.md`, `examples/ledger_week1_hardrock.csv`, `docs/week1/2026-09-13-tool-gaps.md`, and a live `ceminiparlays grade` run on that ledger.

**CLI evidence:** `ceminiparlays grade --ledger examples/ledger_week1_hardrock.csv` exits 2: `could not convert string to float: 'yes'`. The recap PnL is the source of truth until grade can parse ATD / ML rows.

**Session result (paper, Hard Rock cash):** **+$26.07** on **$40** risked (ROI about +65%). Hits **2/5** tickets. Won-tab locked B +288 and C +367. Misses have no booked American.

This is an operator + product postmortem, not a claim that +65% repeats.

---

## How we did

| ticket_id | Stake | Thesis | Result | Net |
|-----------|------:|--------|--------|----:|
| A-2leg | $10 | Cross-game 1 p.m. lead-RB rush (Gibbs 85.5 + Brown 57.5) | MISS (Brown 56) | −$10 |
| A-4leg | $10 | Four-RB rush without Gibbs (Henry / Brown / Cook / Swift) | MISS (Brown 56, Cook 57) | −$10 |
| B | $5 | Composer ATD: Gibbs −300 / Brown −130 / Hampton −155 | HIT at booked **+288** | **+$14.40** |
| C | $10 booked | CHI ML / BAL ML / NYJ@TEN under | HIT at booked **+367** | **+$36.67** |
| 3 | $5 | SNF 5-leg lottery (no Lamb / no Nabers) | MISS (Dak 175, Ferguson 6) | −$5 |

Two of five tickets paid. The two hits more than covered the three misses. Chase Brown yards missed by **1.5** and still scored a TD — that one miss killed **$20** of rush risk while the same player helped ticket B.

---

## What went right

1. **Anytime-TD composer (ticket B) was the cleanest product win.** Naive product +288 matched Hard Rock in-app Total Odds +288. All three named RBs scored. That is the contract we shipped: type two-way or listed ATD prices, capture the **ticket** American, do not invent SGP.
2. **Favorite-script + ITT on sides (ticket C) worked.** CHI 59–37 and BAL 41–23 were blowouts in the direction of the MLs. Lowest-total under (NYJ@TEN 33 vs booked 39) was the right game, not the wrong number.
3. **Rush ITT on the hits was real.** Gibbs 156, Henry 144, Swift 124 all crushed overs. The thesis “lead RB on a high implied total” was not random.
4. **Injury skips before lock were correct.** Chase (Fri DNP), Odunze Q, Kamara Q, Bowers Out, Pacheco IR — none of those names hit the booked tickets. DJ Moore stayed BUF.
5. **Nabers exclusion on SNF was conservative, not the loss.** He played (6/69). Ticket 3 still died on Dak 175 vs 262.5 and Ferguson 6 vs 29.5. Excluding a Q/GTD WR did not cause the miss.
6. **Booked ticket as source of truth on C.** Card said $5 / u38.5 (−105). Booked $10 / u39 (−110) / +367. Settling the Won-tab, not the compose card, is the right rule (TG-06).
7. **No invented reduced-SGP on misses.** A-2leg, A-4leg, and ticket 3 stay blank on multiplier. That is the sportsbook contract.

---

## What went wrong (betting)

1. **Player concentration.** Chase Brown was on A-2leg, A-4leg, **and** B. One 56-yard day zeroed two $10 rush tickets. ATD still hit. The composer diversifies **games inside a ticket** and allows an anchor reuse **across** tickets. That reuse is how Brown landed on both rush cards.
2. **A-2leg was not cancelled when A-4leg replaced it.** Operator intent was “drop Gibbs from the $10.” Both $10s stayed live. Double Gibbs/Brown rush exposure was a process miss, not a CLI miss.
3. **Cook 57 vs 74.5** killed A-4leg even if Brown had cleared. Two independent RB unders on the same four-leg is a thin margin.
4. **SNF 5-leg was a lottery that lost on the two pass/rec legs.** Dart rush, Skattebo ATD, and total 48 vs 47.5 all hit. Dak 175 and Ferguson 6 were the actuals. Weather at kick (72°F, dry, light wind) did not support a pass fade; the fade still happened on the field.
5. **Card vs booked drift on C** (stake and total line). PnL is correct because we graded the book. Research notes that quote the card line are wrong unless they note the delta.

---

## What went wrong (product)

Confirmed in this repo on 2026-09-14:

| Gap | Evidence | Impact Week 1 |
|-----|----------|----------------|
| `grade` is numeric-only | `float('yes')` on ATD/ML ledger | Cannot reproduce recap PnL with the CLI |
| `actual == line` is a void | If ATD `yes`/`yes` were coerced to 1.0, **hits would void** | Must treat yes/no as discrete, not a push |
| Fetch `--date` is UTC midnight→midnight | DAL@NYG `2026-09-14T00:20:00Z` missed on `--date 2026-09-13` | SNF lines were an ad-hoc window |
| Fetch has no `h2h` / `spreads` / `totals` | Ticket C built from a thin HR board | Game markets were pasted, not fetched |
| No cross-ticket player warning | Compose pass-2 reuses an anchor | Brown on three tickets |
| Incomplete packaged roster | Sunday compose `no-team` flood | Many fetch rows dropped |
| Env weather / thin-catalog not at bet time | TG-04 | Charlotte heat and MetLife SNF weather arrived after lock |
| HIT without booked American | TG-01 | B and C were saved by Won-tab screenshots; misses still blank (correct) |

---

## Improve next week (operator)

1. One player, one cash ticket unless the second ticket is a **different market family** and a **smaller** stake (B-style ATD vs A-style yards).
2. When you “replace” a $10, void or do not type the first $10.
3. Capture **in-app Total Odds + stake + ticket id** before kick. Do not finalize a HIT from a naive product.
4. Fetch with an **ET slate day**, not UTC calendar day, so SNF is in the dump.
5. Keep Nabers-style Q excludes. Do not auto-reprice when they later play.
6. SNF 5-legs stay lottery size ($5), not $10.

---

## Improve next week (product — for the implement plan)

P0 (this ship):

1. Grade yes/no ATD, ML win/loss, and totals on the Week 1 ledger. `yes` vs `yes` is a **hit**, never a void. HIT with empty multiplier **fails closed** (no invented PnL). Miss with empty multiplier is 0× (already).
2. `fetch --date` = America/New_York slate day (00:00 ET → next 00:00 ET in UTC). Keep `--utc-date` as the old window.
3. `fetch --markets` accepts `h2h`, `spreads`, `totals` and writes game rows the composer can skip for player tickets but the operator can type.

P1:

4. Cross-ticket player-concentration warning on `compose` (same `player_key` on two tickets).
5. Card vs booked: ledger may keep compose columns, but settle columns (`booked_stake`, `booked_line`, `ticket_id`) win.
6. Thin-catalog note when `h2h`/`spreads` are missing for a requested book.

P2 (do not auto-apply; TG do_not_auto_apply):

7. Persist compose ITT snapshot at bet time (TG-02).
8. Late-active alert only (TG-03) — no auto-void.
9. Stadium prior attach (TG-05) — priors, not odds.

Never: invent reduced-SGP, scrape book sites, auto-submit, rewrite booked lines silently.
