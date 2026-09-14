# DeepSeek V4.1 Flash — Week 1 audit (Hard Rock cash, Sun 2026-09-13)

Auditor: DeepSeek V4.1 Flash. Evidence base: `docs/week1/2026-09-13-grade-recap.md`, `docs/week1/2026-09-13-tool-gaps.md`, `docs/week1/2026-09-14-cursor-grok-audit.md`, `examples/ledger_week1_hardrock.csv`, and a live `ceminiparlays grade` run plus a source read of `src/ceminiparlays/{grade,odds_api,markets,cli,compose}.py`. No Python edited. No `.env` read.

---

## 1. Verdict

**+$26.07 on $40 risked (ROI ≈ +65.2%), 2/5 tickets hit** — a winning session whose headline is carried entirely by two tickets and whose risk was badly concentrated. Ticket B (+$14.40 at booked +288) and Ticket C (+$36.67 at booked +367) covered the three losers ($10 + $10 + $5). The uncomfortable fact is *how* the losers lost: Chase Brown's **56 vs 57.5** — a 1.5-yard shortfall — zeroed **$20 of the $40** risked because he sat on both $10 rush tickets, while the same player's ATD leg kept Ticket B alive. That is not a strategy result; it is a single-player bet wearing two ticket numbers. Meanwhile the product could not grade a single one of the three discrete/ML tickets: `ceminiparlays grade --ledger examples/ledger_week1_hardrock.csv` exits 2 with `could not convert string to float: 'yes'`, so the recap PnL is hand-derived, not reproducible. Treat Week 1 as a **product-correctness fire and a process-discipline warning**, not as evidence the +65% repeats.

---

## 2. What went right (cite tickets)

- **Ticket B — the ATD composer contract held exactly.** All three named RBs scored (Gibbs 2 rush TD, Brown 1 rush TD, Hampton 1 rush TD); the naive product of typed prices (+288) matched the booked Hard Rock Total Odds (+288) and paid $19.40 on $5. We captured the **ticket** American, not an invented same-game price. This is the one place the product's "type it as listed" rule was validated end-to-end.
- **Ticket C — favorite-script + lowest-total under was the right construction.** CHI ML (-175) won 59–37, BAL ML (-180) won 41–23, and NYJ@TEN under 39 landed on **33** (23–10). The under was the correct game, and the total came in well clear, not on a knife edge.
- **Booked ticket used as source of truth on C (TG-06).** The card said $5 / Under 38.5 (-105); the booked ticket `4721458766464287025` was $10 / Under 39 (-110) / +367. Settling the Won-tab rather than the compose card is the right rule, and the delta was *flagged* rather than silently overwritten.
- **The rush-yard theses on the hits were real, not noise.** Gibbs 156 vs 85.5, Derrick Henry 144 vs 78.5, and D'Andre Swift 124 vs 60.5 all cleared their lines by a wide margin. The "lead RB on a high implied total" prior produced genuine separation on 3 of 4 rush legs.
- **Ticket 3's non-pass legs were correctly read.** Jaxson Dart 54 vs 31.5, Skattebo ATD **yes** (3-yd rush TD), and the SNF total **48 vs 47.5** all hit. The ticket died on the two pass-game legs, not on a broken read of the game.
- **No invented reduced-SGP on misses.** A-2leg, A-4leg, and ticket 3 carry a blank multiplier. That is the sportsbook contract and it was respected — the tool-gaps rows are all marked `do_not_auto_apply`.
- **Nabers exclusion did not cause the SNF loss.** He was excluded as Q with no Lamb, then played 6/69. Ticket 3 still died on Dak 175 vs 262.5 and Ferguson 6 vs 29.5. Conservative Q handling is defensible; keep it.

---

## 3. What went wrong — betting process

1. **Single-player concentration across tickets.** Chase Brown appeared on **A-2leg, A-4leg, and B**. Two of those are the *same market family* (rush_yds) at the same stake ($10 each), so Brown's 56-yard day was effectively one $20 bet on one player's rushing volume, not two independent tickets. The ATD leg hedged nothing — it needed a TD, which he scored, so the "hedge" only proves the two exposure types were correlated on the same game script.
2. **Both $10 rush tickets stayed live.** A-2leg and A-4leg were distinct cards, but they shared Brown, and A-4leg was built as a Gibbs-less variant. Running both means double Brown *and* double lead-RB-rush exposure for one 1 p.m. window. Whichever one was meant to replace the other, two $10 tickets on the same thesis is over-sizing.
3. **Correlated legs inside A-4leg.** All four legs are `rush_yds` overs on lead backs on favored scripts (Henry, Brown, Cook, Swift). Brown (56 vs 74.5-adjacent family) and Cook (57 vs 74.5) both missed; Henry and Swift crushed. Four legs of one stat family means one league-wide game-script shift can take down multiple legs at once; the legs were cross-game but not independent.
4. **Card-vs-booked drift on C went unnoticed until settle.** $5 / u38.5 (-105) on the card became $10 / u39 (-110) on the book. The PnL is right because the book was graded, but any research note quoting the card line is wrong unless it states the delta.
5. **Ticket 3's weak link was identified only after the fact.** A 5-leg SNF card at $5 is lottery size and fine, but Dak over 262.5 and Ferguson over 29.5 were the two legs that carried the least evidence; the three "good" legs (Dart, Skattebo, total) were not enough to save it.

---

## 4. What went wrong — product (cite files)

| # | Gap | Code evidence | Week 1 impact |
|---|-----|---------------|---------------|
| 1 | **Discrete and ML actuals crash the grader** | `src/ceminiparlays/grade.py:42-43` does `float(part)` on every `actuals` and `lines` token. | `float('yes')` on ticket B and `float('win')` on ticket C both raise. Reproduced: `ceminiparlays grade --ledger examples/ledger_week1_hardrock.csv` → exit 2, `could not convert string to float: 'yes'`. **3 of 5 tickets (B, C, 3) are ungradeable by the CLI.** |
| 2 | **`actual == line` is a blind void** | `grade.py:48` voids whenever `actual == line`. | If `yes`/`yes` or `win`/`win` were ever coerced to matching numbers, **ATD and ML hits would void instead of pay**. Discrete markets must never reach the push comparison; totals/spreads must keep it. |
| 3 | **Fetch day window is UTC, not ET slate** | `src/ceminiparlays/odds_api.py:127-133` (`utc_day_window` builds 00:00Z→00:00Z); `src/ceminiparlays/cli.py:728,739` calls it. | `--date 2026-09-13` covers `2026-09-13T00:00Z → 2026-09-14T00:00Z`, so DAL@NYG at **`2026-09-14T00:20:00Z`** (8:20 p.m. ET) is 20 minutes outside the window. SNF was hand-pasted, and its lines were an ad-hoc window. |
| 4 | **No game markets in the legal set** | `src/ceminiparlays/markets.py:19` (`LEGAL_MARKETS` = player props only); `parse_markets` (`markets.py:51-60`) refuses unknown tokens; `odds_api.py:34-44` `MARKET_TO_STAT`/`STAT_TO_MARKET` have no `h2h`/`spreads`/`totals`; fetch default `cli.py:272-274`. | Ticket C (2 MLs + a total) could not have been fetched. It was built from a thin Hard Rock board (TG-04), i.e. pasted by hand. |
| 5 | **No cross-ticket concentration warning** | `src/ceminiparlays/compose.py:185-194` — pass 2 *deliberately* reuses a shared anchor leg across tickets; the module docstring (`compose.py:130-137`) frames this as "a menu of alternatives." | That is precisely the mechanism that let Chase Brown land on A-2leg and A-4leg. There is no warning keyed on `player_key` across tickets (only `_leg_key` dedup within pass 2's `chosen` set). |
| 6 | **Booked price not captured at submit** | TG-01; `payouts.resolve_payout` does raise when a sportsbook HIT has no displayed multiplier, so the failure mode is "fail closed," which is correct. | But B and C were only gradeable because Won-tab screenshots were taken afterward. Misses remain blank (correct — no invented reduced-SGP). The capture step is manual and unenforced. |
| 7 | **Deferred, correctly** | TG-02 (ITT snapshot), TG-03 (late-active alert), TG-05 (stadium prior) are all `do_not_auto_apply`. | Keep as manual. Notably, TG-03 was real: Nabers was excluded as Q and then played 6/69, and the tooling did not surface the late activation. |

---

## 5. Next-week operator rules (max 6)

1. **One player, one cash ticket per slate** unless the second ticket is a *different market family* AND a *smaller stake* (B-style ATD vs A-style yards). Brown on three tickets is the rule-breaker this rule exists for.
2. **When you replace a $10, void or don't type the original.** Never leave both the old and new card live — A-2leg and A-4leg both running is the failure this prevents.
3. **Capture in-app Total Odds + stake + ticket id before kick.** Never finalize a HIT from a naive product; if the multiplier is empty on a winner, stop and get the Won-tab (TG-01).
4. **Fetch the ET slate day, then eyeball the dump for the late game.** Confirm the 8:20 p.m. ET SNF game is present; if it isn't, paste it *and label it ad hoc* rather than pretending it was fetched.
5. **Cap same-stat-family stacking at two legs per ticket.** Four `rush_yds` overs on one card is one bet with four tickers; prefer independent stat families and game scripts.
6. **SNF / same-game-ish cards stay $5 lottery size, and the Won-tab settle wins over the compose card** (note any card-vs-booked delta explicitly, per TG-06).

---

## 6. Product fixes ranked P0 / P1 / P2

### P0 — correctness, this ship

1. **Grade `yes`/`no` ATD, ML win/loss, and totals without voiding ATD hits.** Parse actuals/lines by declared `market` instead of blanket `float()` (`grade.py:42-43`). Rules: `yes`/`no` and `win`/`loss` are **discrete** — matching values are a **HIT**, never a void; `actual == line` void logic (`grade.py:48`) must apply **only** to pushable numeric markets (totals, spreads), never to discrete ones. HIT with empty multiplier stays fail-closed (already true in `payouts.resolve_payout`). **Acceptance: `ceminiparlays grade` on `examples/ledger_week1_hardrock.csv` exits 0 and reproduces 2/5 hits and +$26.07 on $40.**
2. **ET slate fetch window.** `--date` becomes the **America/New_York slate day** (00:00 ET → next 00:00 ET, converted to UTC); keep `--utc-date` as the legacy window (`odds_api.py:127-133`, `cli.py:728,739`). For 2026-09-13 (EDT, UTC-4) that is **`2026-09-13T04:00:00Z → 2026-09-14T04:00:00Z`**, which contains DAL@NYG `2026-09-14T00:20:00Z`. Compute the offset from the actual DST rule, not a hard-coded -4/-5.

### P1 — next

3. **Game markets in fetch/compose/rank.** `--markets` accepts `h2h`, `spreads`, `totals`; `fetch` writes game rows the operator can type, `compose`/`rank` skip them for player tickets unless explicitly requested (`markets.py:19,51-60`; `odds_api.py:34-44`). No scrapers — Odds API only.
4. **Cross-ticket player-concentration warning on `compose`.** Warn when the same `player_key` appears on 2+ proposed tickets; escalate when it is the same `stat_type`/family at the same or larger stake (the Brown pattern). Make it a warning (with an explicit override flag), consistent with "compose is a menu, not an autopilot." Add a regression test over the Week 1 shape.
5. **Thin-catalog + card-vs-booked guard.** Emit a thin-catalog note when `h2h`/`spreads` are missing for a requested book (TG-04), and make settle columns (`booked_stake`, `booked_line`, `ticket_id`) authoritative over compose columns in the ledger (TG-06), recording the delta rather than overwriting.
6. **HIT-without-price guard at finalize.** Block PnL finalization for a sportsbook HIT whose multiplier is still empty, with a message pointing at the Won-tab (TG-01). Misses stay 0× with a blank multiplier.

### P2 — `do_not_auto_apply`, manual only

7. **Persist compose ITT snapshot at bet time** (team, window, ITT, timestamp) per ticket (TG-02). Never rewrite historical ITT from postgame box scores.
8. **Late-active alert only** for injury/Q excludes (TG-03). No auto-void and no reprice when an excluded player later plays.
9. **Attach stadium prior** (`stadium_id`, home rush EPA) to home rush/ATTD legs (TG-05). Priors, not odds.

**Never:** invent reduced-SGP step-downs, scrape book sites, auto-submit tickets, or silently rewrite booked lines.

---

## 7. Disagreements with the Cursor Grok audit

I agree with its two central calls — B/C were the wins, and Brown concentration + UTC fetch were the core defects — and I reproduced its CLI finding. Four disagreements, all about evidence weight or priority:

1. **Game markets should be P1, not P0.** Grok puts `h2h`/`spreads`/`totals` in P0 alongside grading and the ET window. Game markets are an *ingest convenience*; they corrupt no PnL. Ticket C is proof the operator can still type ML/total lines from a partial board (flagged as TG-04). Grading correctness and the slate window are the P0s because they block reproducing the session at all.
2. **The no-void rule must be stated for ML, not just ATD.** Grok's P0 #1 says "`yes` vs `yes` is a hit, never a void" but does not extend that to `win`/`win` on moneylines. The same `grade.py:48` branch would void a matching ML just as fast. I also want the converse made explicit: **totals/spreads keep the numeric push-void** — the fix is market-typed, not "stop voiding."
3. **Two "what went right" items are uncited in the audit pack.** Grok credits injury skips ("Chase (Fri DNP), Odunze Q, Kamara Q, Bowers Out, Pacheco IR") and a specific SNF kickoff weather ("72°F, dry, light wind"). Neither appears in `2026-09-13-grade-recap.md`, `2026-09-13-tool-gaps.md`, or the ledger; TG-04 says MetLife SNF weather was **not** in the bet-time environment pack. I do not credit those as verified wins, and I would not use the 72°F claim to argue the pass-fade was weather-justified.
4. **Two product-row claims are unverified by the provided files.** "Incomplete packaged roster — Sunday compose `no-team` flood" and the framing that "operator intent was 'drop Gibbs from the $10'" are presented as confirmed, but the recap only establishes that A-2leg and A-4leg were two distinct cards from screenshots. These may be true from a live compose run, but they are not evidenced in the audit pack; I treat them as plausible inference, not fact. The recommended rule (void the replaced $10) stands regardless.

One refinement rather than a disagreement: Grok notes Brown's 1.5-yard miss "killed $20 of rush risk." I would make that the headline finding of the session — the concentration, not the two-hit outcome, is what generalizes.
