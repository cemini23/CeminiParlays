# Week 1 consensus — auditor matrix (Mon 2026-09-14)

Paper cash: **+$26.07 on $40**, hits **2/5**. `ceminiparlays grade` reproduces this ledger: [`docs/week1/grade.json`](grade.json). Command and expected totals: [`REPRODUCE.md`](REPRODUCE.md).

| Auditor | Model | Outcome |
|---------|--------|---------|
| Cursor Grok | this session | `docs/week1/2026-09-14-cursor-grok-audit.md` |
| Grok CLI | `--reasoning-effort xhigh` (`extra-high` is not a legal enum) | `docs/week1/audit-grok-cli.md` |
| HY3 | OpenCode `opencode/hy3-free` → **UnknownError**; OpenRouter `tencent/hy3` | `docs/week1/audit-hy3.md` |
| Qwen | OpenRouter `qwen/qwen3-coder` (cheap coding Qwen) | `docs/week1/audit-qwen.md` |
| DeepSeek V4.1 Flash | `claude-ds` / `deepseek-flash` API | `docs/week1/audit-deepseek-flash.md` |
| OpenCode Zen | `hy3-free`, `deepseek-v4-flash-free`, `x-preview-f-free` all **UnknownError**; fallback OpenRouter `z-ai/glm-5.2` | `docs/week1/audit-opencode.md` |

OpenCode Zen sidecar is down (same UnknownError as Sunday). Audits still landed via OpenRouter + Flash + Grok CLI.

---

## How we did

Winning session on paper, not a repeatable edge. Ticket B (+$14.40 at booked +288) and Ticket C (+$36.67 at booked +367) covered three misses. Chase Brown **56 vs 57.5** zeroed **$20** of rush cash while the same player’s ATD helped B. The CLI prints this ledger: [`grade.json`](grade.json) (`hits` 2, `stake` 40, `pnl` 26.07).

---

## Consensus: what went right

- ATD B: listed prices, booked American **+288** matched naive product, all three RBs scored.
- ML/under C: CHI and BAL blowouts; NYJ@TEN **33** vs booked under **39**. Won-tab ($10 / u39 / +367) is the settle, not the compose card.
- Rush overs that hit (Gibbs 156, Henry 144, Swift 124) were real ITT/favorite-script separations.
- Ticket 3 non-pass legs (Dart, Skattebo ATD, total 48 vs 47.5) were read correctly; Dak/Ferguson killed it.
- Misses keep a blank multiplier. No invented reduced-SGP. No scrape, no auto-submit.
- Nabers Q-exclude then 6/69 was **not** the SNF miss (all auditors).

---

## Consensus: what went wrong

**Betting process**

1. Two $10 `rush_yds` tickets both needed Brown over 57.5. That is same-family stacking, not two independent bets.
2. A-2leg was extra cash versus the published $20 card (Grok CLI: the published card already *is* the 4-leg without Gibbs). Do not type both.
3. Card vs booked drift on C (stake and total line). PnL is right because the book won.
4. Four-leg all-rush A-4leg also died on Cook 57 vs 74.5.

**Product (reproduced in code)**

1. `grade._leg_outcomes` `float()` crashes on `'yes'` / `'win'`.
2. `actual == line` would **void** ATD/ML hits if those tokens were coerced to equal numbers.
3. Ledger `+288` / `+367` would become **288× / 367×** if parsed as decimal (`float("+288")`). Recap sportsbook example already uses `3.88`. **P0 landmine** (Grok CLI; Cursor Grok missed it).
4. `fetch --date` is UTC midnight→midnight; DAL@NYG `2026-09-14T00:20:00Z` missed.
5. No `h2h` / `spreads` / `totals` in fetch/LEGAL_MARKETS.
6. Compose has no same-player same-family concentration warning. Pass-2 menu reuse is not the same bug as two live $10 rush tickets (Grok CLI / Flash).

---

## Rejected recommendations

- **Qwen P0 “reject tickets with h2h/spreads/totals.”** Ticket C is the session’s biggest win. Add those markets; do not ban them.
- **Blunt “max 1 ticket per player.”** A-yards + smaller B-ATD is the card that paid. Warn on **same player + same family / stacked cash**, do not block yards+ATD.
- **Auto-void / reprice late actives, invent reduced-SGP, rewrite booked lines.** All `do_not_auto_apply`.

---

## Product ranking (this ship)

**P0 (must reproduce Week 1)**

1. Grade yes/no, ML win/loss, totals. Discrete match = hit, never void. Numeric `actual == line` stays a void.
2. Parse ledger `multiplier` `+288` as American via `american_to_decimal`. Optional `paid` column wins when present (B $19.40, C $46.67 → session **+$26.07** exact).
3. HIT with empty multiplier stays fail-closed. Miss with empty multiplier stays 0×.
4. `fetch --date` = America/New_York slate day. Keep `--utc-date` for the old window.

**P1 (same route if tests stay green)**

5. Fetch `h2h`, `spreads`, `totals` into slate rows. Compose `--auto` still skips them.
6. Compose warning when the same `player_key` appears on two tickets in the **same market family**.

**P2 (docs only this week)**

7. TG-02 ITT snapshot, TG-03 late-active alert, TG-05 stadium prior. Do not auto-apply.

**Never:** invent reduced-SGP, scrape book sites, auto-submit, “fix” Power Kelly, rewrite Verify.
