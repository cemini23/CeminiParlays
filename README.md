# CeminiParlays

Local CLI for NFL **pick'em** and **parlay** research.

You enter posted lines. The tool ranks slips. **You type the ticket in the app.**

This is not a bot. It does not scrape PrizePicks, Underdog, or any sportsbook. It does not submit slips.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Python 3.11 or 3.12.

## Commands

```bash
# One prop from a projected median + sigma
ceminiparlays fair --player "Patrick Mahomes" --stat pass_yds --line 275.5 \
  --median 268 --sd 55

# De-vig a two-way book market (operator-typed American odds)
ceminiparlays devig --over -155 --under 120 --method power

# Rank 2-leg Underdog Standard slips
ceminiparlays rank --lines examples/manual_lines.csv \
  --distributions examples/distributions.csv \
  --platform underdog --slip-size 2 --out runs/edges.csv

# One slate folder: edges.csv + report.txt
ceminiparlays run --lines examples/manual_lines.csv \
  --distributions examples/distributions.csv \
  --slate-id 2025-w01-sun --platform underdog

# Grade your own ledger
ceminiparlays grade --ledger examples/ledger.csv --out runs/grade.json
```

`prop-fair`, `prop-rank`, and `prop-grade` are aliases for the same commands.

## What it computes

1. **Fair P** — `P(stat > line)` from a distribution, or from de-vigged book odds if you type both sides.
2. **Implied P** — reverse of the lounge payout table.
3. **Slip EV** — joint hit rate from a Gaussian copula, not the independent product.
4. **Quarter Kelly** on the **whole slip**.

Default platform is **Underdog**. PrizePicks is the second payout profile. Always confirm the multiplier on the submit screen. Underdog and PrizePicks can shift payouts on correlated or alt-line legs. Pass `--displayed-multiplier` when the app shows a different number.

## What it will not do

- Scrape lounge or book boards
- Auto-fill or auto-submit slips
- Hit the network in tests or CI
- Treat FanDuel fantasy points as a prop fair value
- Size each leg with Kelly and then add the fractions

## Responsible use

Wager only where it is legal. Use a bankroll that is separate from DFS and best-ball. If gambling is a problem, call **1-800-GAMBLER**.

Output files always say **do not submit**. That line is the product contract.

## Research

See `RESEARCH.md` for the wiki, CeminiDFS lessons, Gemini math, and social scan that set this v1.

License: MIT.
