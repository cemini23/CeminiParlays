# Grok CLI audit — Hard Rock Week 1 (Sun 2026-09-13)

Auditor: Grok CLI (extra-high). Graded Mon 2026-09-14 from `docs/week1/2026-09-13-grade-recap.md`, `docs/week1/2026-09-13-tool-gaps.md`, `docs/week1/2026-09-14-cursor-grok-audit.md`, `examples/ledger_week1_hardrock.csv`, and source reads of `src/ceminiparlays/{grade,odds_api,markets,cli,compose,payouts,odds,fetch}.py`. Live run: `ceminiparlays grade --ledger examples/ledger_week1_hardrock.csv` → exit 2, `could not convert string to float: 'yes'`. Recap PnL is the source of truth. No Python edited. No `.env` read. No invented reduced-SGP.

---

## 1. Verdict

Paper cash finished **+$26.07 on $40** (2/5 hits): Ticket B **+$14.40** at booked **+288**, Ticket C **+$36.67** at booked **+367**, and three misses (A-2leg −$10, A-4leg −$10, ticket 3 −$5). That is a real session, not a model claim that +65% repeats. Two theses paid (listed ATD; favorite MLs + the lowest 1 p.m. under). The $20 of rush cash died on one player and one extra $10 card. The CLI cannot reproduce any of this: `grade` dies on `'yes'` before it scores a single slip, and even after that parse is fixed the ledger stores American `+288` / `+367` in a column that `grade.py` treats as a decimal multiplier. Treat Week 1 as **two winning tickets plus a grader that still cannot print them**.

---

## 2. What went right

- **Ticket B (ATD, $5, +288) is the product contract.** Gibbs (2 rush TD), Chase Brown (5-yd rush TD), Hampton (9-yd rush TD) all scored. Naive product of the typed two-way prices (**+288**) matched Hard Rock Total Odds **+288**. Paid **$19.40** (ticket `7416657534771134738`). Net **+$14.40**. This is the shipped rule: type listed ATD prices, capture the **ticket** American, do not invent SGP.
- **Ticket C (CHI ML / BAL ML / NYJ@TEN under, $10 booked, +367) is the biggest win.** CHI 59–37, BAL 41–23, Jets–Titans **33** vs booked under **39**. Paid **$46.67** (ticket `4721458766464287025`). Net **+$36.67**. The under was the right game, not a 0.5-point knife edge.
- **Won-tab beat the compose card on C (TG-06).** Card: $5 / under **38.5** (−105). Booked: $10 / under **39** (−110) / +367. Settling the book, and flagging the delta, is the right rule.
- **Rush overs that hit were not noise.** Gibbs **156** vs 85.5, Henry **144** vs 78.5, Swift **124** vs 60.5. Lead-RB + high ITT was a real prior on those three legs.
- **Ticket 3’s non-pass legs were read correctly.** Dart **54** vs 31.5, Skattebo ATD **yes**, SNF total **48** vs 47.5 (hit by 0.5, not a push). The ticket died on Dak **175** vs 262.5 and Ferguson **6** vs 29.5.
- **Nabers-as-Q was conservative, not the SNF miss.** He later played 6/69. Ticket 3 still lost on Prescott and Ferguson. Do not auto-void or reprice from a late active (TG-03, `do_not_auto_apply`).
- **Misses keep a blank multiplier (TG-01).** A-2leg, A-4leg, and ticket 3 stay empty. That is the sportsbook contract. Do not backfill naive ~+264 / ~+1120 / ~+1600 as the booked American.
- **No scrape, no auto-submit.** Operator typed tickets in-app.

---

## 3. What went wrong — betting process

1. **Chase Brown rush sat on two $10 tickets.** A-2leg and A-4leg both needed Brown over **57.5**. He ran **56** (miss by **1.5**) and still scored the TD that helped Ticket B. One volume miss zeroed **$20 of $40**. That is same-market stacking, not two independent bets.
2. **A-2leg was extra cash, not the published Ticket A.** `docs/2026-09-13-hardrock-card.md` already specified Ticket A as the **4-leg without Gibbs** ($10) plus B ($5 ATD) plus C ($5) — a **$20** card. Recap: two distinct Ticket A screenshots, kept as `A-2leg` and `A-4leg` (no merge). Both $10s stayed live. Planned bankroll **$20**; risked **$40** (extra A-2leg $10, C booked $10 not $5, ticket 3 $5).
3. **Brown on A (rush) and B (ATD) was the card design.** The published A-4leg already shares Brown with B at a **smaller** ATD stake. Do not treat that pair as the same error as two $10 rush cards. The ATD paid; the double rush did not.
4. **Cook 57 vs 74.5 independently killed A-4leg.** Even if Brown had cleared 57.5, the four-leg still dies. Four `rush_yds` overs on one slip is one script family with four names.
5. **Card vs booked drift on C.** Stake and total line moved in-app. PnL is correct because the Won-tab won. Any note that still quotes $5 / u38.5 is wrong unless it states the delta (TG-06).
6. **Ticket 3 stayed lottery size ($5) and still lost on the two pass/rec legs.** Keep that size. Do not grow SNF 5-legs to $10.

---

## 4. What went wrong — product (cite files)

Reproduced 2026-09-14. `ceminiparlays grade --ledger examples/ledger_week1_hardrock.csv` prints `error: could not convert string to float: 'yes'` and exits **2** (`cli.py` maps `ValueError` → 2).

| Gap | Evidence | Week 1 impact |
|-----|----------|----------------|
| `grade` is numeric-only | `grade.py` `_leg_outcomes` does `float()` on every `lines` / `actuals` token | Ticket B (`yes`), Ticket C (`win`), ticket 3 (`yes`) crash the run. A-2leg and A-4leg are numeric but never get a CLI total because the ledger is one pass. |
| `actual == line` is a void | `grade.py`: equal actual and line increments `voids` | If `yes`/`yes` were coerced to `1.0`, **Ticket B would void**, not hit. Same trap for `win`/`win` on ML. Discrete match is a **hit**. |
| `yes` / `ml` are not sides | `MORE_SIDES` / `LESS_SIDES` are over/under aliases only | After a naive float fix, side `yes` or `ml` still falls through to **miss**. ATD and ML need their own compare. |
| ML `lines` are American prices, not totals | Ledger C: `lines=-175\|-180\|39`, `actuals=win\|win\|33` | Do not compare `win` to **−175**. The −175 is the quoted ML. The 39 is the total line. |
| American ticket price stored as `multiplier` | Ledger B/C: `+288`, `+367`. `grade.py` does `float(raw["multiplier"])`. `payouts.resolve_payout` uses that as **decimal** `all_hit`. `examples/recap_sportsbook_ledger.csv` already uses `3.88`, not `+288`. | If yes/win parsed and `+288` were left as `288.0`, Ticket B PnL becomes **$5 × (288 − 1)** instead of **+$14.40**. Recap is then unrecoverable. Convert `+288` / `+367` with `odds.american_to_decimal` (`+288` → 3.88× → **+$14.40** exact; `+367` → 4.67× → **+$36.70**, three cents over the Won-tab **$46.67** / **+$36.67** — prefer booked paid when present). |
| HIT with empty multiplier already fails closed | `payouts.py` sportsbook branch raises if `displayed_multiplier is None`; `test_grade_blank_platform_sportsbook_hit_requires_price` | Keep this. Do not invent SGP. Miss with blank multiplier is already 0×. |
| Fetch `--date` is UTC calendar day | `odds_api.utc_day_window`: `00:00Z` → next `00:00Z`. `cli._cmd_fetch` always calls it. Help text: “UTC calendar day”. No `--utc-date` flag exists yet. | `--date 2026-09-13` is `2026-09-13T00:00:00Z` → `2026-09-14T00:00:00Z`. DAL@NYG `2026-09-14T00:20:00Z` (8:20 p.m. ET) is **20 minutes outside**. SNF lines were an ad-hoc window (`runs/2026-w01-snf/`). Ticket 3 was still typed; the fetch miss did not cause Dak/Ferguson to miss. |
| No game markets | `markets.LEGAL_MARKETS` is player props only (`pass_yds`, `rush_yds`, `rec_yds`, `receptions`, `rush_att`, `pass_tds`, `first_td`, `anytime_td`). `parse_markets` refuses anything else. `odds_api.MARKET_TO_STAT` / `STAT_TO_MARKET` have no `h2h` / `spreads` / `totals`. Fetch maps via `STAT_TO_MARKET[stat]`. | Ticket C could not be fetched. Operator typed a thin Hard Rock ML/total board (TG-04). Adding tokens to `LEGAL_MARKETS` alone is not enough — fetch mapping must move too. |
| Compose pass-2 reuses an anchor | `compose.py`: pass 1 blocks shared `_leg_key`; pass 2 fills the menu with a shared anchor. No cross-ticket `player_key` warning. | ATD compose card reuses Hampton/Gibbs across ticket-001/004/005. That is a **menu**. Operator picked one ATD ticket. **A-2leg + A-4leg Brown rush is not in `runs/2026-w01-sun/compose-yards/card.txt`.** Double rush cash is an operator process miss, not pass-2 output. |
| Booked American captured after settle | TG-01; B and C locked from Won-tab screenshots | Capture Total Odds + stake + ticket id **before kick**. Block HIT finalize if multiplier is empty. |
| Thin catalog / weather not at bet time | TG-04; `examples/environment.csv` has ITT (LAC 28.50, CHI 25.25, BAL 25.50) but empty `wind_mph` / `precip_pop` | Charlotte heat and MetLife kick weather arrived from recaps, not from the bet-time pack. |
| TG rows marked `do_not_auto_apply` | TG-01…TG-06 | Persist ITT (TG-02), late-active **alert only** (TG-03), stadium prior (TG-05). Do not rewrite ITT from box scores. Do not auto-void late actives. Do not invent odds from stadium priors. |

---

## 5. Next-week operator rules (max 6)

1. **One player, one cash ticket** unless the second ticket is a **different market family** and a **smaller** stake (B-style ATD vs A-style yards). Two $10 `rush_yds` tickets on the same player are forbidden.
2. **Do not type a second $10 on the same thesis.** If the card already has the 4-leg, do not also type the 2-leg. Planned stake is the card total, not “both screenshots.”
3. **Capture in-app Total Odds + stake + ticket id before kick.** Never finalize a HIT from a naive product. Empty multiplier on a winner is a stop, not a guess (TG-01).
4. **Fetch the ET slate day, then confirm SNF/MNF is in the dump.** If DAL@NYG (or the 8:20 p.m. ET game) is missing, paste it and label the paste ad hoc.
5. **Keep Q/GTD excludes.** Do not auto-reprice when they later play (TG-03). Nabers 6/69 was not the Ticket 3 miss.
6. **SNF 5-legs stay $5.** Won-tab settle wins over the compose card; write the card-vs-booked delta (TG-06).

---

## 6. Product fixes ranked P0 / P1 / P2

### P0 — this ship (cannot reproduce Week 1 without these)

1. **Grade yes/no ATD, ML win/loss, and totals on `examples/ledger_week1_hardrock.csv` without voiding ATD hits.** Parse by market, not blanket `float()` (`grade.py` `_leg_outcomes`).
   - `yes` vs `yes` and `win` vs `win` are **hits**, never voids.
   - `actual == line` void stays for **numeric** markets only (yardage, totals, spreads). 48 vs 47.5 is a hit; 47.5 vs 47.5 is a void.
   - Side `yes` / `no` and `ml` (or `win`/`loss` actuals) need a discrete branch; `MORE_SIDES`/`LESS_SIDES` do not cover them.
   - Moneyline `lines` (`-175`) are quotes, not thresholds.
   - Ledger `multiplier` values `+288` and `+367` are **American ticket prices**. Convert with `american_to_decimal` before payout. Do not treat `+288` as 288× decimal.
   - HIT with empty multiplier **fails closed** (already true). Miss with empty multiplier is 0× (already true). Do not invent reduced-SGP.
   - Acceptance: `ceminiparlays grade` on this ledger exits 0, reports **2/5 hits**, and matches recap paper net **+$26.07** (allow the 3-cent +367 rounding, or store booked paid).

2. **`fetch --date` = America/New_York slate day** (00:00 ET → next 00:00 ET, expressed in UTC). For 2026-09-13 (EDT, UTC−4) that is `2026-09-13T04:00:00Z` → `2026-09-14T04:00:00Z`, which contains DAL@NYG `2026-09-14T00:20:00Z`. Use the DST tz database, not a hard-coded −4/−5. Keep the current UTC midnight window behind a new `--utc-date` (it does not exist today).

### P1 — next

3. **Game markets.** `fetch --markets` accepts `h2h`, `spreads`, `totals`. Extend `LEGAL_MARKETS`, `MARKET_TO_STAT` / `STAT_TO_MARKET`, and `rows_from_events` so game rows write. Composer skips them on player tickets unless asked. Operator can type Ticket C from the dump. Odds API only — no book-site scrape.
4. **Cross-ticket concentration warning on `compose`.** Warn when the same `player_key` **and** same market family (`rush_yds` with `rush_yds`) appear on two proposed tickets, or when one player’s cash stake stacks. Do **not** block A-yards + B-ATD at a smaller stake — that pair is the Week 1 card and it paid. Pass-2 may keep a menu; print the reuse.
5. **Card vs booked.** Ledger may keep compose columns. Settle columns (`booked_stake`, `booked_line`, `ticket_id`, booked American) win. Record the delta (TG-06). Thin-catalog note when `h2h`/`spreads` are missing for a requested book (TG-04).
6. **HIT-without-price guard at finalize.** Same fail-closed as grade; say “type the Won-tab American.” Misses stay 0× with a blank multiplier.

### P2 — `do_not_auto_apply` (manual only)

7. Persist compose ITT snapshot at bet time (TG-02). Never rewrite ITT from postgame boxes.
8. Late-active **alert only** (TG-03). No auto-void, no reprice.
9. Attach stadium prior (`stadium_id`, home rush EPA) to home rush/ATD legs (TG-05). Priors, not odds.

**Never:** invent reduced-SGP, scrape book sites, auto-submit, or silently rewrite booked lines.

---

## 7. Disagreements with the Cursor Grok audit

Agree on the session math, on B/C as the wins, on `float('yes')`, on `yes`/`yes` must not void, on the UTC SNF window, and on TG-01 (no invented SGP). Four disagreements:

1. **A-2leg was not an un-voided “replace Gibbs” ticket.** Cursor Grok states operator intent was “drop Gibbs from the $10” and that A-2leg stayed live by mistake. The recap only says two distinct screenshots, no merge. The published card (`docs/2026-09-13-hardrock-card.md`) **already is** the 4-leg without Gibbs. A-2leg is extra $10 on the same Brown rush line. The rule “do not type both” still holds; the replacement story is not in the audit pack.

2. **Double Brown rush is not compose pass-2.** Cursor Grok blames pass-2 anchor reuse for Brown on both rush cards. `runs/2026-w01-sun/compose-yards/card.txt` has no Gibbs 85.5 + Brown 57.5 ticket. Pass-2 did reuse Hampton/Gibbs on the **ATD menu**; the operator picked one. Same-player rush on A-2leg and A-4leg is operator sizing. A concentration warning still belongs in P1, but it must key on **same player + same family / stacked cash**, not “any `player_key` on two tickets.” The published card **intends** Brown rush (A) + Brown ATD (B). A blunt two-ticket warning would flag the structure that paid **+$14.40**.

3. **`+288` / `+367` as decimal is a P0 landmine Cursor Grok does not name.** Fixing `yes` without converting American ticket prices would print a fantasy PnL (288× / 367×). P0 grade is not done until the Week 1 ledger reproduces **+$26.07** (or booked paid), not merely “exits 0.” Also: ML `win`/`win` must not void, and ML `lines` (−175) are quotes. Cursor Grok’s P0 sentence covers ATD void; it does not cover these two.

4. **Game markets are P1, not P0. “Incomplete packaged roster / Sunday compose `no-team` flood” is not confirmed in the grade pack.** Ticket C was typed and paid from a thin board (TG-04). Missing `h2h`/`spreads`/`totals` did not corrupt PnL. Fetch mapping must still grow (P1). Cursor Grok lists a Sunday `no-team` flood as confirmed; this audit did not find that banner in the week-1 recap, tool-gaps, or ledger. `runs/2026-w01-snf/lines.csv` does show blank `team`/`opp` on many fetch rows (roster miss → `_team_opp` returns empty), which is a real fetch hygiene issue, not a confirmed compose flood. Injury-skip names on the published card (Chase Fri DNP, Odunze Q, Kamara Q, Bowers Out, Pacheco IR) and a 72°F MetLife claim are **not** in the recap/tool-gaps/ledger pack; this audit does not treat them as verified wins. TG-04 says SNF weather was **not** in the bet-time environment file.

One emphasis, not a disagreement: the session headline that generalizes is **$20 of rush cash on one Brown volume miss**, not 2/5 at +65%.
