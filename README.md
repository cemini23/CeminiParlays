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
  --platform underdog --slip-size 2 --displayed-multiplier 3.5 --out runs/edges.csv

# One slate folder: edges.csv + report.txt
ceminiparlays run --lines examples/manual_lines.csv \
  --distributions examples/distributions.csv \
  --slate-id 2025-w01-sun --platform underdog --displayed-multiplier 3.5

# Grade your own ledger
ceminiparlays grade --ledger examples/ledger.csv --out runs/grade.json
```

`prop-fair`, `prop-rank`, and `prop-grade` are aliases for the same commands.

`--displayed-multiplier` is the in-app all-hit multiplier. A per-row
`slip_multiplier` column in the lines CSV wins over the flag for that combo. If
neither is set, the CLI prints `UNCONFIRMED TABLE MULTIPLIER — confirm in-app`
and marks those slips `table unconfirmed`; it still ranks so you can paper-trade.

In the example lines, **James Cook is a no-book row**: he has no typed book odds
but he *does* have a projected distribution, so he ranks. A no-book row with no
distribution is dropped. **Isiah Pacheco stays `out`** and is always listed as a
scratch.

## Fail-closed rules (strict by default)

Every `rank` / `run` prints `lines=N live=N dropped=N scratched=N` and names the
players behind `dropped` and `scratched`. With `--strict` (the default) any
dropped leg aborts with exit code 2; `--no-strict` ranks anyway after the banner.
Scratches are always listed but never enter a combo.

A leg is dropped, never silently skipped, when:

- `team` or `opp` is blank (strict CSV reads abort; no `unknown:` teams are minted)
- only one of `book_over` / `book_under` is typed
- a `book_line` disagrees with the lounge `line`
- the line is an integer and `--allow-integer-lines` is off (push mass is voided, not folded into Under)
- there is no distribution and no both-sided book odds

Injury tokens: `out`, `ir`, `inactive`, `doubtful`, `nfi`, `pup`, `suspended`
scratch the leg. `q`, `questionable`, `gtd`, `game-time`, `limited`, `dnp` keep
the leg, print a `questionable` warning, and never haircut the fair P for you.

Same-player multi-stat slips are rejected for v1 (`same-player multi-stat not
supported`). Alt / demon / goblin `line_type` rows need a row or CLI multiplier
or they are excluded (`alt-needs-m`).

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
