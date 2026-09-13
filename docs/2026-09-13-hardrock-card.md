# Hard Rock card — Sun 13 Sep 2026

Operator card for a **$20** Hard Rock bankroll. Fetched two-way prices
`2026-09-13T13:18:45Z`. Confirm every line and the **displayed American**
in-app. This CLI does not submit.

**Stakes:** $10 + $5 + $5. That is the whole $20.

**Skip:** Ja'Marr Chase (Fri DNP), Rome Odunze (Q), Alvin Kamara (Q),
Brock Bowers (Out), Isiah Pacheco (IR). Re-check inactives before lock.

## Ticket A — $10 — 4-leg rush (1 p.m.)

No Gibbs (he is on ticket B). Four games.

| Leg | Market | Line | Game | Two-way |
|-----|--------|------|------|---------|
| Derrick Henry | rush over | 78.5 | BAL @ IND | −115 / −115 |
| Chase Brown | rush over | 57.5 | TB @ CIN | −115 / −115 |
| James Cook | rush over | 74.5 | BUF @ HOU | −115 / −115 |
| D'Andre Swift | rush over | 60.5 | CHI @ CAR | −115 / −115 |

CSV: `examples/2026-w01-sun-ticket-a-rush.csv`. Naive product ≈ +1120.
Pass `--legs 4` with the in-app American.

```bash
ceminiparlays run --lines examples/2026-w01-sun-ticket-a-rush.csv \
  --distributions examples/distributions.csv --platform hardrock \
  --displayed-odds +XXX --legs 4 --out-dir runs/2026-w01-sun/ticket-A
```

## Ticket B — $5 — 3-leg anytime TD

| Leg | Market | Hard Rock | Game |
|-----|--------|-----------|------|
| Jahmyr Gibbs | anytime TD | −300 | NO @ DET |
| Chase Brown | anytime TD | −130 | TB @ CIN |
| Omarion Hampton | anytime TD | −155 | ARI @ LAC 4:25 |

CSV: `examples/2026-w01-sun-ticket-b-atd.csv`. Naive product ≈ +288.
Pass `--legs 3`. Hard Rock did not return anytime-TD prices for Henry or Cook.

```bash
ceminiparlays run --lines examples/2026-w01-sun-ticket-b-atd.csv \
  --distributions examples/distributions.csv --platform hardrock \
  --displayed-odds +XXX --legs 3 --out-dir runs/2026-w01-sun/ticket-B
```

## Ticket C — $5 — 1 p.m. slate (ML + total)

Typed in-app only. The Odds API Hard Rock board was missing most 1 p.m.
moneylines and spreads.

| Leg | Market | Price |
|-----|--------|-------|
| CHI moneyline | ML | −175 |
| BAL moneyline | ML | −180 |
| NYJ @ TEN Under 38.5 | total | −105 |

Naive product ≈ +377. Confirm all three still exist in Hard Rock.
