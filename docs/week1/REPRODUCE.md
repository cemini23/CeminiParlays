# Week 1 grade — reproduce

This page reprints the Week 1 Hard Rock ledger totals. It is a winning session, not a repeatable edge.

## Command

From the repo root, with the package installed:

```bash
ceminiparlays grade --ledger examples/ledger_week1_hardrock.csv --out docs/week1/grade.json
```

## Expected totals

| Field | Value |
|-------|-------|
| slips (`n_slips`) | 5 |
| hits | 2 |
| stake | 40 |
| pnl (2 decimals) | +26.07 |

Committed JSON: [`docs/week1/grade.json`](grade.json). Source ledger: [`examples/ledger_week1_hardrock.csv`](../../examples/ledger_week1_hardrock.csv).

Do not invent `paid` or `multiplier` values. If a live `grade` does not match these totals, stop.

This is one winning session. It is not a claim of edge.
