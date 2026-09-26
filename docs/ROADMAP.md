# CeminiParlays product plan

**Status:** Phase 1 composer shipped (v0.2). Odds API ingest shipped (v0.3). Grade + ET fetch + game markets shipped (v0.4). Week 1 report flags + ITT snapshot shipped (v0.5). CeminiDFS handoff reader shipped (v0.6). Phases 2–3 stay specified here so we do not invent scope mid-route.  
**Contract:** no book-site scrapers, no auto-submit, no book/PM API keys in this repo (Odds API key is env-only: `THE_ODDS_API_KEY`), no network in CI. The operator types the ticket. `fetch` writes a CSV; `compose --auto` **picks** tickets; neither places them. Reports never overwrite the card, auto-void, or invent an SGP.

Sources: CeminiDFS GPP/env stack (`docs/GPP-WORKFLOW.md`, weather/vegas/stadiums), Gambling wiki `@concepts/parlay-and-correlated-bets.md` (SGP tax, DKeX COMBOS = product of binaries), `@briefs/2026-09-12_ceminidfs-lessons-pickem-parlay-cli.md`, world-cup-bot (shadow-first, DRY_RUN, paper ledger — steal the **gates**, not the CLOB).

## What the user can choose

| Knob | Flag | Default if omitted (`--auto`) |
|------|------|-------------------------------|
| Venue | `--platform` | `hardrock` |
| Market family | `--markets` | `pass_yds,rush_yds,rec_yds` |
| Legs | `--legs` / `--slip-size` | `2` |
| Odds window | `--min-odds` `--max-odds` | `+150` … `+400` |
| Ticket count | `--n-tickets` | `5` |
| Bankroll / stake | `--bankroll` `--stake` | print flat vs ¼-Kelly; do not invent a sixth ticket |
| Control | omit knobs + `--auto` | composer fills the table above |

Legal `--markets` tokens: `pass_yds`, `rush_yds`, `rec_yds`, `receptions`, `rush_att`, `pass_tds`, `first_td`, `anytime_td`, plus game markets `h2h`/`spreads`/`totals` (aliases `moneyline`/`spread`/`total`). `compose --auto` still uses yards only.  
`--markets first_td --legs 4 --min-odds +800` is a first-TD longshot.  
`--markets rush_yds --legs 3 --max-odds +250` is a shorter rush card.

## Variables the card must see (CeminiDFS borrow)

Operator-typed CSV, local files, or `ceminiparlays fetch` (Odds API). Never scraped in CI.

| Variable | Why it changes a parlay | Ingest |
|----------|-------------------------|--------|
| Injury / OUT / Q / DNP | Scratch vs warn | `injury_status` + roster |
| Team / opp / game | Same-game vs cross-game; first-TD mutex | lines + `games.csv` |
| Vegas ITT + spread | Favorite rush / dog pass | `environment.csv` |
| Roof / weather_exposed | Dome skip; retractable outdoor until roof call; SoFi not wind-exposed | `environment.csv` |
| Wind ≥10 / ≥15, precip | Pass yards down, rush up | `environment.csv` |
| Pace / implied plays | Attempt props | optional env columns |
| Two-way book odds | Fair P (never SGP-screen quotes) | `fetch` → `book_over` / `book_under`, or typed |
| Displayed American | Ticket identity | `ticket_id` + `--displayed-odds` |
| Correlation | QB+WR, rush vs pass, first-TD same game = illegal | priors JSON |
| Stake kind | Cash vs $2 bonus | ledger `stake_kind` |
| Settlement / void | Reduced SGP | Phase 2 |

Prediction markets (Polymarket / Kalshi): **combo = product of independently settled binaries** (DKeX COMBOS). Correlated NFL legs paid at the product of mids are the same naive-SGP error. Paper only. No CLOB, no LP canary, no WC auto-exec.

## Phase 1 — compose product (shipped, v0.2)

1. **`slate`** — write fill-in `lines.csv` from `games.csv` + roster + optional injury file. Team comes from roster (DJ Moore = BUF). Blank `line` / odds until typed. `rank` refuses a blank line.
2. **`first_td` / `anytime_td`** — discrete markets. Two `first_td` legs in the **same game** skip (`same-game-first-td`). Cross-game first TD uses ρ = 0 in v1. Anytime TD same-game gets a prior row. Fair P from operator `leg_odds` or a typed `fair_p` column; no fake Gaussian median.
3. **Local roster + dists** — `--roster`, `--dists` already exist. Add `--environment` CSV. Document CeminiDFS export path. No live nflverse fetch in this repo.
4. **`bankroll`** — `--bankroll 25 --n-tickets 5` prints $5 flat vs ¼-Kelly 5% cap ($1.25). Card says which one you used.
5. **`ticket_id`** — a displayed American from `slip_odds` applies only to rows that share that id. CLI `--displayed-odds` requires `live == slip-size` (the rows *are* the ticket). A shared `ticket_id` does not relax the size match.
6. **`grade` ledger** — columns `ticket_id`, `market`, `stake_kind` (`cash`/`bonus`). Sportsbook void+miss = 0× (already).
7. **Reduced SGP / push** — keep integer-line exclusion on sportsbooks. Document as Phase 2. Do not invent a reduced-SGP table.
8. **Correlation** — add `first_td`/`first_td` same-game skip (harder than rho). Add `rush_yds`/`rush_yds` same-team and `anytime_td`/`anytime_td` same-team priors. Keep existing pass/rec 0.45.
9. **`docs/SUNDAY.md`** — 20-minute operator path.

Also in Phase 1:

- **`compose`** (`--auto`) — if the user does not specify markets/legs/odds, use the defaults table. Diversify games across tickets. Roster + scratch gates. Prefer higher ITT when `environment.csv` is present. Write `runs/{slate}/ticket-NNN.csv` + one card. Print `do not submit`.
- **Platforms:** keep `hardrock` `fanduel` `draftkings`. Add `betmgm` as another sportsbook (same displayed-American path). Add `polymarket` `kalshi` as prediction venues: each leg is a 0–1 contract price (`contract_price`); combo M = 1 / product of prices if they type `--displayed-odds`, else **unconfirmed product** (Kelly 0), same as `leg_odds_naive`.
- **Steal from WC bot / PM canary:** shadow banner, paper ledger fields, DRY_RUN language. Do **not** copy API clients, keys, or auto-exec.

## v0.4 — grade Week 1 + ET fetch + game markets (shipped)

- `grade` parses ATD `yes`/`no` and ML `win`/`loss` without voiding discrete matches. Numeric `actual == line` still voids on yardage/totals/spreads.
- Ledger `multiplier` `+288` is American via `american_to_decimal`. Optional `paid` (Won-tab) is `paid - stake` when present. HIT with an empty multiplier still fails closed.
- `fetch --date` is the America/New_York slate day (DST from `zoneinfo`). `--utc-date` keeps the old UTC window. Sunday includes SNF.
- `fetch --markets` accepts `h2h`, `spreads`, `totals`. `compose --auto` still skips game rows.
- `compose` warns when the same `player_key` appears on two tickets in the same `stat_type`. Warning only (exit 0). Yards + ATD on the same player does not warn.

## v0.5 — Week 1 report flags + ITT snapshot (shipped)

Reports only. No silent overwrite, no auto-void, no invented SGP. Displayed American stays ticket identity. House-rule quotes stay out of Python (no reduced-SGP table). SoFi remains `semi_open` (not `dome`); this wave does not edit `examples/environment.csv` ARI@LAC rows.

| Flag / file | Maps to | Behavior |
|-------------|---------|----------|
| `ceminiparlays diff --card --booked` | TG-06 `--diff-card-booked` | Per-`ticket_id` stake / lines / multiplier (string, so `+367` stays American). Exit 2 when any delta exists. `--accept-booked` prints the same table and exits 0. Never writes the card. Booked is display-only; the operator types the ledger. |
| `compose --enforce-market-depth` | TG-04 | Exit 2 with `CATALOG_THIN_MANUAL_INPUT_REQUIRED` when a game on the lines file lacks moneyline/h2h **or** spread/spreads. `--allow-thin-catalog` prints the same note and continues. Default off. `compose --auto` (yards only, flag off) does not halt. |
| `compose --alert-late-active FILE` | TG-03 | Print `OPERATOR_ACTION_REQUIRED` when a FLAG/OUT player is later `ACTIVE`. Exit 0 (alert only). Missing file exits 2. No void, no reprice, no haircut. |
| `compose --environment` → `compose_itt.json` | TG-02 | One object per env row used on composed tickets (`team`, `opp`, `game_id`, `implied_total`, `spread`, `roof`, `weather_exposed`, `wind_mph`, `precip_pop`) plus `captured_at` UTC `...Z`. Empty implied_total stays null. Omit `--environment` skips the file. Never rewrite from box scores. |

## v0.6 — CeminiDFS handoff reader (shipped)

This repo **reads** a copied `ceminidfs_handoff.csv`. CeminiDFS owns the writer. CLIs stay split. No live pipe. FanDuel FPPG `projection` is not a prop fair and is never written to `distributions.csv`.

| Flag / file | Behavior |
|-------------|---------|
| `compose --from-ceminidfs PATH` | Missing file prints `CEMINIDFS_HANDOFF_MISSING: {path}` and continues. Present file fills **blank** `implied_total` on the compose environment (`game` like `CIN@TB` → team/opp). Does not overwrite roof / weather / wind / precip. Prints `ceminidfs exposure:` notes. |
| `compose --max-exposure-per-player N` | Default unset (warning only, exit 0). When set, same `player` + `stat_type` on more than N tickets prints the concentration warning and exits 2. Yards + ATD on one player does not trip. |
| `compose --card-md` | Writes `out_dir/card.md` (or `--card-md PATH`). Redacted: legs + do not submit. No stake dollars, wallets, or Odds API key. `card.txt` still writes. |
| `diff --emit-ledger PATH` | Writes a ledger CSV from **booked** rows. Requires `--accept-booked`. Without it, do not write and keep exit 2 on deltas. Never overwrites the card. |

## v0.7 — pick'em gap + SGP weather discount (shipped)

- **`compare`** — print the gap between a de-juiced two-way fair price and the fixed pick'em all-hit multiplier. Uses `devig_two_way` for fair P, then `fair_decimal = 1 / (p ** legs)`. Compares against `resolve_payout` table value. The operator's typed `displayed_multiplier` is echoed but does not replace the table in the gap. Works for PrizePicks (power) and Underdog (standard/flex).
- **`weather.py`** — `apply_weather_discount` applies a numeric haircut to a marginal when `weather_exposed=true` and wind/precip were typed. Gates: indoor (dome/indoor/closed) = no discount; retractable-closed = no discount; not exposed = no discount; exposed but both fields blank = no discount + `WEATHER_FIELDS_BLANK` note; otherwise wind `min(0.04, max(0, wind-10)*0.002)` + precip `min(0.04, (precip/25)*0.01)`, cap 0.08. `sgp_from_score_marginals` feeds discounted marginals into the existing `exact_joint` copula. No forecast invention; uses only operator-typed fields.
- Hard Rock / FanDuel remain manual entry. No book login, no submit, no scraper.

## Operator process + GEO (docs, not a math bump)

Docs only. No math change.

- Sunday cash rules: [`docs/SUNDAY.md`](SUNDAY.md) (run `bankroll` first; one cash ticket per player+family; type the booked American; `diff --card --booked` before the ledger).
- Citable canon: [`docs/canon.md`](canon.md). Machine index: [`llms.txt`](../llms.txt).
- Week 1 `grade` artifact: [`docs/week1/grade.json`](week1/grade.json) (hits 2, stake 40, pnl 26.07). Reproduce: [`docs/week1/REPRODUCE.md`](week1/REPRODUCE.md).

`--from-ceminidfs` is built (v0.6). Copy the file; this CLI only reads.

## Phase 2 — environment + settlement

- **Odds API ingest (shipped, v0.3):** `ceminiparlays fetch` pulls two-way player props from The Odds API (licensed REST, stdlib `urllib.request` only). Still no FanDuel / DraftKings / Hard Rock / BetMGM site clients, unofficial GitHub “book APIs”, or auto-submit. A fetched two-way price is not a confirmed SGP. Game markets (`h2h`/`spreads`/`totals`) shipped in v0.4.
- **P2 leftover:** TG-05 stadium prior. Roster refresh from a **local** nflverse players parquet (no download). Do not rewrite historical ITT from box scores. Do not auto-apply Shin, reduced-SGP, or book-site clients.
- Model push / reduced sportsbook tickets only when the ledger has a **settled** multiplier (already required). Optional `--allow-integer-lines` on books stays off.
- **Grok Bot desks (operator, not CLI):** Parlays Slate Desk and Recap Desk already exist in Grok Bot.app. Slate writes `environment.csv` + scheme notes; Recap fills `ledger.csv` for `grade`. Copy: [`docs/GROK-BOTS.md`](GROK-BOTS.md). Do not create a second pair. No book scrape, no submit, no Odds API key on the Bot VM.

## Phase 3 — more sports / more books

- Extra sportsbook aliases only (Caesars, Fanatics) — same sportsbook math, no new scrape.
- WC / soccer COMBOS stay in world-cup-bot. CeminiParlays may **compare** a typed PM combo to a typed sportsbook parlay on the same binary events. No live orders.

## Never

- Scrape Hard Rock, FanDuel, DraftKings, Kalshi, or Polymarket (Odds API ingest is not a book-site scrape).
- Auto-submit, Chrome fill, or WC-bot live POST.
- Treat FanDuel FPPG as a prop fair.
- Two first-TD legs from one game.
- Independent product sold as confirmed SGP EV.
- Secrets in handoffs or free models.
- Rewrite `## Verify` to match a failing run.
