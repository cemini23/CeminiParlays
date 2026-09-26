# CeminiParlays

Local CLI for NFL **sportsbook parlays**. Pick'em (Underdog / PrizePicks) is a second profile.

`fetch` pulls two-way player-prop lines from [The Odds API](https://the-odds-api.com). You still type the ticket in Hard Rock / FanDuel / DraftKings / BetMGM and pass the **displayed American parlay / SGP price**. The tool ranks EV with a copula. It does not submit slips and it does not scrape book sites.

## Why this is safe to run

The Never list is the product, not a buried limit.

- Displayed American is ticket identity. You type the in-app price. The CLI does not invent an SGP from the product of legs.
- No book-site scrape. Licensed Odds API ingest is the only HTTP path.
- No auto-submit. Output files say **do not submit**. You type the ticket in-app.
- No invented reduced-SGP table. HIT with an empty multiplier fails closed.
- Tests and CI do not hit the network.
- Wager only where it is legal. If gambling is a problem, call **1-800-GAMBLER**.

Numbered rules: [`docs/canon.md`](docs/canon.md). Machine index: [`llms.txt`](llms.txt).

**Start here:** [`docs/SUNDAY.md`](docs/SUNDAY.md) is the 20-minute path (fetch → compose → type the ticket price → size → grade). [`docs/canon.md`](docs/canon.md) is the citable rules. [`llms.txt`](llms.txt) lists the public docs. [`docs/ROADMAP.md`](docs/ROADMAP.md) is the phase plan (composer = v0.2; Odds API fetch = v0.3; grade + ET fetch + game markets = v0.4; Week 1 report flags + ITT snapshot = v0.5; CeminiDFS handoff reader = v0.6).

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Python 3.11 or 3.12.

No Odds API key for the offline fixture path:

```bash
ceminiparlays fetch --fixture tests/fixtures/odds_api_nfl.json --out /tmp/lines.csv
```

## Commands

```bash
# One prop from a projected median + sigma
ceminiparlays fair --player "Patrick Mahomes" --stat pass_yds --line 275.5 \
  --median 268 --sd 55

# De-vig a two-way book market (operator-typed American odds)
ceminiparlays devig --over -155 --under 120 --method power

# Compare de-juiced fair price vs fixed pick'em multiplier (gap report)
ceminiparlays compare --over -110 --under -110 --platform prizepicks --legs 2
ceminiparlays compare --over -110 --under -110 --platform underdog --legs 2 --mode standard

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

# Optional: only 4-leg tickets between +150 and +400
ceminiparlays rank --lines examples/hardrock_lines.csv \
  --distributions examples/distributions.csv \
  --legs 4 --min-odds +150 --max-odds +400 --out runs/edges.csv

# Rank 2-leg and 3-leg cards in one pass
ceminiparlays rank --lines examples/hardrock_lines.csv \
  --distributions examples/distributions.csv \
  --legs 2-3 --out runs/edges.csv

# Fill-in slate from the games file + packaged roster (blank line until typed)
ceminiparlays slate
# -> runs/slate/lines_fill_in.csv (DJ Moore is BUF, per the roster)

# Pull two-way player props (licensed Odds API; no book-site scrape).
# Key: THE_ODDS_API_KEY in the environment. This CLI only reads os.environ.
# --date is America/New_York midnight→midnight (UTC converted; includes SNF).
# --utc-date keeps the old UTC calendar window.
# Defaults: --books hardrock,fanduel,draftkings
#           --markets pass_yds,rush_yds,rec_yds,first_td,anytime_td
# Game markets: --markets h2h,spreads,totals (aliases moneyline,spread,total)
ceminiparlays fetch --out runs/slate/lines.csv
ceminiparlays fetch --date 2026-09-13 --books hardrock --markets first_td,anytime_td \
  --out runs/slate/ftd.csv --force
# Offline / CI: --fixture skips HTTP and does not need a key
ceminiparlays fetch --fixture tests/fixtures/odds_api_nfl.json --out /tmp/lines.csv
# Fetch fills line + book_over/book_under (or TD / h2h leg_odds / fair_p).
# The displayed SGP American is still typed once per ticket (--displayed-odds).

# Compose 5 tickets with the auto defaults (2-leg, +150..+400, yards markets)
ceminiparlays compose --auto --lines runs/slate/lines.csv \
  --environment examples/2026-w02-sun-environment.csv --out-dir runs/2026-w02-sun
# -> ticket-001.csv .. ticket-005.csv + card.txt + compose_itt.json
# compose_itt.json is the bet-time ITT snapshot. Do not rewrite it from box scores.
# Omit --environment to skip the file.

# Optional: copy a CeminiDFS handoff, then compose. FPPG is not a prop fair.
# Missing file prints CEMINIDFS_HANDOFF_MISSING and continues.
ceminiparlays compose --auto --lines runs/slate/lines.csv \
  --environment examples/environment.csv \
  --from-ceminidfs examples/ceminidfs_handoff.csv \
  --card-md --out-dir runs/2026-w01-sun
# fills blank implied_total; prints ceminidfs exposure notes; writes card.md
# --max-exposure-per-player 1 exits 2 on same-player same-stat concentration

# Thin catalog (TG-04). Default off; compose --auto (yards only) does not halt.
ceminiparlays compose --auto --enforce-market-depth \
  --lines runs/slate/lines.csv --out-dir runs/slate
# missing moneyline/h2h or spread/spreads → CATALOG_THIN_MANUAL_INPUT_REQUIRED, exit 2
# --allow-thin-catalog prints the same note and continues

# Late-active alert (TG-03). Exit 0 (alert only). Missing file exits 2.
ceminiparlays compose --auto --alert-late-active inactives.csv \
  --lines runs/slate/lines.csv --out-dir runs/slate

# Card vs booked (TG-06 `--diff-card-booked`). Never writes the card.
ceminiparlays diff --card examples/card_ticket_c.csv \
  --booked examples/booked_ticket_c.csv
# exit 2 when stake / lines / multiplier differ. --accept-booked prints the
# same table and exits 0. Type the booked ticket into the ledger.
# --accept-booked --emit-ledger PATH writes booked rows (not the card).

# A first-TD longshot card (needs 4+ first_td rows — use a fetched slate)
ceminiparlays compose --auto --markets first_td --legs 4 --min-odds +800 \
  --lines runs/slate/lines.csv --out-dir runs/ftd

# Flat vs quarter-Kelly stake for a 5-ticket card
ceminiparlays bankroll --bankroll 25 --n-tickets 5
# flat $5.00 each; quarter-Kelly cap $1.25 per ticket
```

`prop-fair`, `prop-rank`, and `prop-grade` are aliases for the same commands.

Default `--platform` is **hardrock**. Choices: `hardrock`, `fanduel`, `draftkings`, `betmgm`, `polymarket`, `kalshi`, `underdog`, `prizepicks`. A blank CSV `platform` column matches any book.

**Auto defaults** (`compose --auto`, any omitted knob): `--markets pass_yds,rush_yds,rec_yds`, `--legs 2`, `--min-odds +150`, `--max-odds +400`, `--n-tickets 5`. Pass any of those flags to override just that knob. A single odds bound keeps the other default unless that would make the window empty: `--max-odds +250` keeps the `+150` floor, while `--min-odds +800` drops the `+400` cap so a first-TD longshot still composes. Compose diversifies games, skips same-game `first_td`, prefers higher implied team totals when `--environment` is present, and only writes files — it never submits.

`--legs` sets how many legs to rank (`4`, `2,3,4`, or `2-4`). It overrides `--slip-size` when present. `--min-odds` / `--max-odds` keep slips in an American window after pricing (minimum = at least this long; maximum = no longer than this). `--displayed-odds` still prices **one** ticket and needs a single leg count.

`rank` / `run` load a packaged NFL roster (`config/rosters/nfl.json`, 2026-09-13). A **known** player on the wrong team is dropped as `wrong-team` (DJ Moore is BUF, not CHI). Unknown names pass. Pass `--roster path.json` to replace the file, or `--no-roster` to skip the check. Edit the JSON when someone is traded.

The v0.5 flags are **reports**. They do not void, reprice, invent an SGP, or overwrite the card. `--from-ceminidfs` is built (v0.6): copy `ceminidfs_handoff.csv`; this CLI only reads. FanDuel FPPG is not a prop fair. House-rule quotes stay out of Python (no reduced-SGP table). SoFi remains `semi_open` (not a dome).

`--displayed-odds` is the in-app American parlay / SGP price for **one ticket**. `--displayed-multiplier` is the decimal form. On a sportsbook (or prediction) platform the CLI quote is legal only when `live == slip-size` — a 4-row ticket needs `--legs 4`. A shared `ticket_id` does **not** let one American paint every 2-leg subset. Per combo the price is: agreeing row `slip_multiplier` → agreeing all-leg `slip_odds` → CLI displayed (size match only) → `leg_odds` product. A row quote wins over the CLI flag.

`ticket_id` groups rows: when any row carries one, a combo only combines rows that share that id (or all-blank rows). Type the in-app American in `slip_odds` on those rows. `--ticket-id <id>` filters the CSV to one ticket; then pass `--legs` matching that ticket before `--displayed-odds`.

`--markets` keeps only the named market families (`pass_yds`, `rush_yds`, `rec_yds`, `receptions`, `rush_att`, `pass_tds`, `first_td`, `anytime_td`, plus game markets `h2h`/`spreads`/`totals`). `compose --auto` still uses yards only and skips game rows. `first_td` and `anytime_td` are discrete: fair P comes from a typed `fair_p` or from `leg_odds` implied, never from a fake Gaussian. Two `first_td` legs in the same game never rank (`same-game-first-td`). Cross-game first TD uses ρ = 0; `anytime_td` same-team carries a 0.15 prior. Compose prints a warning (exit 0) when the same player appears on two tickets in the same `stat_type`; yards + ATD on one player does not warn.

If you only type per-leg `leg_odds`, the tool multiplies those decimals as an **unconfirmed screen** (`leg_odds_naive`, Kelly = 0) until you pass `--displayed-odds` or type the same `slip_odds` on every combo leg. That product **overstates** same-game SGP payout. Rebuild the ticket in-app and pass the displayed price before you size.

`book_over` / `book_under` must be **two-way market** quotes (the posted over/under), never SGP-builder screen prices. The copula already adds correlation; feeding SGP-screen odds double-counts it.

## Prediction markets (paper COMBOS)

`--platform polymarket` or `--platform kalshi` treats each leg as a 0–1 contract: type `contract_price` (e.g. `0.42`). With no displayed price the combo decimal is `1 / Π contract_price`, labelled `contract_product`, marked **unconfirmed**, and Kelly is forced to 0. Pass `--displayed-odds` (or type agreeing `slip_odds`) to mark it confirmed.

A COMBOS ticket is the product of **independently settled binaries**. Correlated NFL legs paid at the product of mids overstate EV — that is the same naive-SGP error as a same-game parlay. Paper only: no CLOB, no orders, no HTTP.

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
- `line` is blank or non-numeric (`no-line`) — a fill-in slate refuses to rank
- only one of `book_over` / `book_under` is typed
- a `book_line` disagrees with the lounge `line`
- the line is an integer and `--allow-integer-lines` is off (push mass is voided, not folded into Under). Sportsbook integer lines stay excluded even with the flag (push / reduced-ticket payout is not modeled). Pick'em still honors `--allow-integer-lines`.
- there is no distribution and no both-sided book odds (TD markets may instead carry `fair_p` or `leg_odds`; prediction legs may carry `contract_price`)

Same-game and same-player multi-stat are legal on sportsbooks. Duplicate
`(player, stat)` is not. Pick'em still rejects same-player multi-stat and same-team
2-legs. Alt / demon / goblin `line_type` rows need a row or CLI multiplier or they
are excluded (`alt-needs-m`).

## What it computes

1. **Fair P** — typed `fair_p`, de-vigged book odds, TD `leg_odds` implied, a projected distribution, or a prediction `contract_price` mid. Sharp `book_over` / `book_under` stay the fair-P input. Ticket book is `--platform`.
2. **Implied P** — reverse of the displayed American (sportsbook / prediction) or lounge payout table (pick'em).
3. **Slip EV** — joint hit rate from a Gaussian copula, not the independent product.
4. **Quarter Kelly** on the **whole ticket**, then a 5% cap.

**Hard Rock** is the operator primary book (`--platform hardrock`, the default). FanDuel, DraftKings, and BetMGM use the same sportsbook path: displayed American, `leg_odds` product as a screen, same-game allowed, no lounge table. Flex Parlay is not modeled.

Pick'em stays a second profile: `--platform underdog` or `prizepicks`. If neither a displayed multiplier nor a row M is set, the CLI prints `UNCONFIRMED TABLE MULTIPLIER — confirm in-app` and marks those slips `table unconfirmed`; it still ranks so you can paper-trade.

Always confirm the American price or multiplier on the submit screen.

## What it will not do

- Scrape lounge, book, Polymarket, or Kalshi boards (licensed Odds API ingest is the only HTTP path)
- Auto-fill or auto-submit slips or prediction COMBOS
- Hit the network in tests or CI
- Treat FanDuel fantasy points as a prop fair value
- Invent reduced-SGP step-down tables
- Size each leg with Kelly and then add the fractions
- Invent a displayed parlay / SGP price from the product of fetched legs

## Responsible use

Wager only where it is legal. Use a bankroll that is separate from DFS and best-ball. If gambling is a problem, call **1-800-GAMBLER**.

Output files always say **do not submit**. That line is the product contract. The operator types the ticket in-app.

## Research

See `RESEARCH.md` for the wiki, CeminiDFS lessons, Gemini math, and social scan that set v1.

- [`docs/SUNDAY.md`](docs/SUNDAY.md) — the 20-minute Sunday operator path.
- [`docs/canon.md`](docs/canon.md) — numbered citable rules.
- [`llms.txt`](llms.txt) — public-doc index for search and LLMs.
- [`docs/GROK-BOTS.md`](docs/GROK-BOTS.md) — Parlays Slate Desk + Recap Desk (already live in Grok Bot.app).
- [`docs/week1/REPRODUCE.md`](docs/week1/REPRODUCE.md) — Week 1 `grade` artifact (2/5, +$26.07).
- [`docs/2026-09-13-hardrock-card.md`](docs/2026-09-13-hardrock-card.md) — Week 1 $20 Hard Rock card.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — Phase 1 composer (v0.2), Odds API fetch (v0.3), grade + ET fetch + game markets (v0.4), Week 1 report flags + ITT snapshot (v0.5), CeminiDFS handoff reader (v0.6), Phase 2 stadium prior / nflverse parquet, Phase 3 more books.

`grade` accepts optional ledger columns `ticket_id`, `market`, `stake_kind` (`cash` / `bonus`), and `paid` (Won-tab cash; that row is `paid - stake`). Discrete ATD `yes`/`yes` and ML `win`/`win` are hits, never voids. Numeric `actual == line` still voids on yardage/totals/spreads. Ledger `multiplier` `+288` is American, not 288×. Unknown extra columns are ignored. Sportsbook void + miss still settles at `0×`. HIT with an empty multiplier still fails closed.

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
