# CeminiParlays product plan

**Status:** Phase 1 composer shipped (v0.2). Odds API ingest shipped (v0.3). Phases 2–3 stay specified here so we do not invent scope mid-route.  
**Contract:** no book-site scrapers, no auto-submit, no book/PM API keys in this repo (Odds API key is env-only: `THE_ODDS_API_KEY`), no network in CI. The operator types the ticket. `fetch` writes a CSV; `compose --auto` **picks** tickets; neither places them.

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

Legal `--markets` tokens: `pass_yds`, `rush_yds`, `rec_yds`, `receptions`, `rush_att`, `pass_tds`, `first_td`, `anytime_td`.  
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

## Phase 2 — environment + settlement

- **Odds API ingest (shipped, v0.3):** `ceminiparlays fetch` pulls two-way player props from The Odds API (licensed REST, stdlib `urllib.request` only). Still no FanDuel / DraftKings / Hard Rock / BetMGM site clients, unofficial GitHub “book APIs”, or auto-submit. A fetched two-way price is not a confirmed SGP.
- Import a **local** CeminiDFS week cache / projection CSV (`--from-ceminidfs path`) if the file exists; otherwise skip with a named note.
- Model push / reduced sportsbook tickets only when the ledger has a **settled** multiplier (already required). Optional `--allow-integer-lines` on books stays off.
- Roster refresh script that reads a **local** nflverse players parquet (no download).

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
