# Qwen audit — Hard Rock Week 1 (Sun 2026-09-13)

Auditor: OpenRouter `qwen/qwen3-coder` (cheap coding Qwen, similarly priced to HY3). No tools; prompt-only.

# CeminiParlays Week 1 Audit (Hard Rock Cash Parlays)

## 1. Verdict

Mixed outcome: **+26.07 on 40**, with **2/5 hits**. Wins came from correct judgment on **ATD B** and **ML/under C**, but the ledger suffered from **process and product gaps** that obscured actual performance. Product issues masked true outcomes, while betting process missed concentration risks and game window alignment.

---

## 2. What went right

- **Correctly identified key outcomes**: ATD B and ML/under C were solid plays that hit, contributing +$51.07 to PnL before deductions.
- **Diversified within tickets**: Ticket A used multiple legs to spread risk, and Ticket C included both ML and total action.
- **Legitimate use of player ATD logic**: Chase Brown’s all-touchdown logic held on ATD B, despite missing yards props.
- **Clear ticket structure**: Ledger showed leg types and outcomes, allowing for traceable grading post-close.

---

## 3. What went wrong — betting process

- **Player concentration risk**: Chase Brown appeared on **three tickets (A-2leg, A-4leg, B)**, increasing exposure to a single player’s performance.
- **Ticket sizing without variance control**: Two $10 misses (Brown yards vs 57.5, Cook vs 74.5) were avoidable with tighter unit management or diversification.
- **No pre-ticket concentration warnings**: CLI lacks alerting on repeated player usage across tickets.
- **Date window misalignment**: `--date 2026-09-13` missed SNF game (DAL@NYG) which started after UTC midnight, delaying SNF total grading.

---

## 4. What went wrong — product

- **Grading logic error**: `grade.py` failed on `'yes'` strings due to `float()` coercion. This blocked automated grading of ATD and yes/no props.
- **No legal market validation**: markets.py does not include h2h/spreads/totals, yet Ticket C was accepted with ML and total lines.
- **No ticket price validation**: Ticket C was booked at **$10/u39/+367**, but card had **$5/u38.5**, creating mismatched context.
- **No prop market standardization**: ATD "yes/no" should be treated as discrete outcomes, not continuous floats, to avoid void logic on line matches.

---

## 5. Next-week operator rules (max 6)

1. **Limit player reuse**: Max 1 ticket per player per card to reduce concentration risk.
2. **Validate ticket prices**: Require booked prices match card pricing before ticket acceptance.
3. **Use ET game window**: Fetch games based on ET start times, not UTC date rollover.
4. **Block non-standard markets**: Reject tickets with unsupported markets (e.g., no h2h/spreads/totals in LEGAL_MARKETS).
5. **Enforce discrete prop types**: Treat yes/no as enum, not float, in grading logic.
6. **Manual override for edge cases**: Allow manual lock of outcomes when auto-grade fails.

---

## 6. Product fixes P0/P1/P2

### P0 — Immediate

- **Fix grade.py float cast**: Handle `'yes'/'no'` as discrete outcomes; do not coerce to float.
- **Adjust fetch window**: Use ET game times, not UTC date rollover, for game alignment.
- **Reject unsupported markets**: Block tickets with h2h/spreads/totals until supported.

### P1 — Short-term

- **Add LEGAL_MARKETS support**: Include h2h, spreads, and totals for standard prop validation.
- **Add ticket price validation**: Compare card vs booked prices; warn or block mismatches.
- **Implement player reuse warnings**: Warn when same player appears on multiple tickets.

### P2 — Future

- **Add prop enum types**: Standardize discrete props (ATD, FG, etc.) as enums in schema.
- **Add concentration risk alerts**: Flag tickets that reuse players or teams across parlays.

---

## 7. Disagreements with Cursor Grok (or none)

None. Cursor Grok’s thesis aligns: **ATD B and ML/under C were the wins**, and **Brown concentration + UTC fetch** were core issues. Product/process gaps were accurately identified.
