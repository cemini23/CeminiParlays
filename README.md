# CeminiParlays

Local CLI for NFL **sportsbook parlays**. Pick'em (Underdog / PrizePicks) is a second profile.

You type posted lines and the **displayed American parlay / SGP price**. The tool ranks EV with a copula. **You type the ticket in Hard Rock (or FanDuel / DraftKings).**

This is not a bot. It does not scrape Hard Rock, FanDuel, DraftKings, PrizePicks, or Underdog. It does not submit slips.

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

# Rank 2-leg Hard Rock parlays / SGPs (default --platform hardrock)
ceminiparlays run --lines examples/hardrock_lines.csv \
  --distributions examples/distributions.csv \
  --slate-id 2026-w02-sun --slip-size 2

# Same math on FanDuel or DraftKings
ceminiparlays run --lines examples/sportsbook_lines.csv \
  --distributions examples/distributions.csv \
  --slate-id 2026-w02-sun --platform fanduel --slip-size 2

# After you build the ticket in-app, re-price with the displayed American.
# --displayed-odds prices ONE ticket: the CSV must have exactly slip-size live legs.
ceminiparlays rank --lines examples/hardrock_ticket.csv \
  --distributions examples/distributions.csv \
  --displayed-odds +260 --out runs/edges.csv

# Rank 2-leg Underdog Standard slips (pick'em profile)
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

Default `--platform` is **hardrock**. Choices: `hardrock`, `fanduel`, `draftkings`, `underdog`, `prizepicks`. A blank CSV `platform` column matches any book.

`--displayed-odds` is the in-app American parlay / SGP price for **one ticket**. `--displayed-multiplier` is the decimal form. On a sportsbook platform the CLI quote is legal only when `live == slip-size`; a 4-row slate with `--slip-size 2` is six parlays, not one ticket. Per combo the price is: agreeing row `slip_multiplier` → agreeing all-leg `slip_odds` → CLI displayed (single-ticket only) → `leg_odds` product. A row quote wins over the CLI flag.

If you only type per-leg `leg_odds`, the tool multiplies those decimals as an **unconfirmed screen** (`leg_odds_naive`, Kelly = 0) until you pass `--displayed-odds` or type the same `slip_odds` on every combo leg. That product **overstates** same-game SGP payout. Rebuild the ticket in-app and pass the displayed price before you size.

`book_over` / `book_under` must be **two-way market** quotes (the posted over/under), never SGP-builder screen prices. The copula already adds correlation; feeding SGP-screen odds double-counts it.

In the example lines, **James Cook is a no-book row**: he has no typed book odds
but he *does* have a projected distribution, so he ranks. A no-book row with no
distribution is dropped. **Isiah Pacheco stays `out`** and is always listed as a
scratch.

## Injury / OUT

Scratch tokens (never priced; they never enter a combo):

- `out`, `ir`, `inactive`, `doubtful`, `nfi`, `pup`, `suspended`

Flag tokens (priced, warned; you decide):

- `q`, `questionable`, `gtd`, `game-time`, `limited`, `dnp`

The card prints `scratched <name>`. `--strict` still applies to **drops**, not scratches.

## Fail-closed rules (strict by default)

Every `rank` / `run` prints `lines=N live=N dropped=N scratched=N` and names the
players behind `dropped` and `scratched`. With `--strict` (the default) any
dropped leg aborts with exit code 2; `--no-strict` ranks anyway after the banner.
Scratches are always listed but never enter a combo.

A leg is dropped, never silently skipped, when:

- `team` or `opp` is blank (strict CSV reads abort; no `unknown:` teams are minted)
- only one of `book_over` / `book_under` is typed
- a `book_line` disagrees with the lounge `line`
- the line is an integer and `--allow-integer-lines` is off (push mass is voided, not folded into Under). Sportsbook integer lines stay excluded even with the flag (push / reduced-ticket payout is not modeled). Pick'em still honors `--allow-integer-lines`.
- there is no distribution and no both-sided book odds

Same-game and same-player multi-stat are legal on sportsbooks. Duplicate
`(player, stat)` is not. Pick'em still rejects same-player multi-stat and same-team
2-legs. Alt / demon / goblin `line_type` rows need a row or CLI multiplier or they
are excluded (`alt-needs-m`).

## What it computes

1. **Fair P** — `P(stat > line)` from a distribution, or from de-vigged book odds if you type both sides. Sharp `book_over` / `book_under` stay the fair-P input. Ticket book is `--platform`.
2. **Implied P** — reverse of the displayed American (sportsbook) or lounge payout table (pick'em).
3. **Slip EV** — joint hit rate from a Gaussian copula, not the independent product.
4. **Quarter Kelly** on the **whole ticket**, then a 5% cap.

**Hard Rock** is the operator primary book (`--platform hardrock`, the default). FanDuel and DraftKings use the same sportsbook path: displayed American, `leg_odds` product as a screen, same-game allowed, no lounge table. Flex Parlay is not modeled.

Pick'em stays a second profile: `--platform underdog` or `prizepicks`. If neither a displayed multiplier nor a row M is set, the CLI prints `UNCONFIRMED TABLE MULTIPLIER — confirm in-app` and marks those slips `table unconfirmed`; it still ranks so you can paper-trade.

Always confirm the American price or multiplier on the submit screen.

## What it will not do

- Scrape lounge or book boards
- Auto-fill or auto-submit slips
- Hit the network in tests or CI
- Treat FanDuel fantasy points as a prop fair value
- Size each leg with Kelly and then add the fractions

## Responsible use

Wager only where it is legal. Use a bankroll that is separate from DFS and best-ball. If gambling is a problem, call **1-800-GAMBLER**.

Output files always say **do not submit**. That line is the product contract. The operator types the ticket in-app.

## Research

See `RESEARCH.md` for the wiki, CeminiDFS lessons, Gemini math, and social scan that set this v1.

## Support

Thank you for your support — stars, issues, shares, and tips all help keep this CLI and the broader Cemini open-research stack alive.

If you’d like to tip, use the **donation-only** addresses below (not trading or production wallets). Prefer following the work? These are the best places to start:

| Project | Link |
|---------|------|
| **Outlier Weekly** (methodology newsletter) | [outlierweekly.substack.com](https://outlierweekly.substack.com) |
| **Atto** — organize Italian family documents on your computer | [youratto.com](https://youratto.com) |
| **GuruWatcher** — Discord alerts for your newsletter’s price levels | [guruwatcher.com](https://guruwatcher.com) |
| **YouTube** | [@Cemini23](https://www.youtube.com/@Cemini23) |

| Chain family | Address |
|--------------|---------|
| **X Money** (fiat, US) | Request [@Cemini23](https://x.com/Cemini23) in the X app — scan the Request QR |
| **EVM** (Ethereum, Polygon, Base, Arbitrum, …) | `0x444C5C2eC439E0382aa5a17F70313c536BcC5D58` |
| **Solana / SVM** | `J4zNn4hK9jTrKBFY8sbAGJHLoZvXvQf4B9pQSbSrocZE` |
| **Polymarket** (referral) | [polymarket.com/?r=Cemini23](https://polymarket.com/?r=Cemini23) |
| **Hyperliquid** (referral) | [app.hyperliquid.xyz/join/CEMINI23](https://app.hyperliquid.xyz/join/CEMINI23) |

Full wallet note: [SUPPORT.md](SUPPORT.md) · canon also in [CCC SUPPORT.md](https://github.com/cemini23/cemini-claude-code-CCC/blob/main/SUPPORT.md).

We’re grateful you’re here. Thank you for your support.

## License

MIT.
