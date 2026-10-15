# Sunday in 20 minutes

The operator path for one afternoon slate. Licensed Odds API fetch is allowed.
Book-site scrapers and auto-submit are not. You type the ticket in the app; this
CLI only fetches two-way lines, picks, and prices.

**Grok Bot desks:** Parlays Slate Desk and Parlays Recap Desk already exist in
Grok Bot.app. Charters live in OSINT WORKSPACE
(`briefs/2026-09-01_grok-bot-charters.md` §17 / §19). Product copy:
[`GROK-BOTS.md`](GROK-BOTS.md). Before lock, open Slate Desk → `environment.csv`.
After the games, open Recap Desk → ledger for step 8. Do not create new Bots.
The Bot does not fetch or submit. Slate Desk defaults to Sunday afternoon only,
so name **SNF DET@CAR** if you open it this Sunday; ATL@NO is Monday.

> **Sunday cash rules**
>
> 1. Run `ceminiparlays bankroll` before you type.
> 2. One cash ticket per player + family. Yards + a smaller ATD is allowed.
> 3. Do not type the published 4-leg and its 2-leg subset.
> 4. Type the booked displayed American (the in-app price).
> 5. Run `ceminiparlays diff --card --booked` before the ledger.
> 6. Never backfill a naive product of legs as the booked American.

**Rule for every step:** if a command exits `2`, read the named `dropped` /
`no-line` rows and fix the CSV. Do not pass `--no-strict` on a money slate.

This Sunday card is **2026-10-04** (Week 4). SNF DET@CAR is on this slate.
ATL@NO is Monday — wait. The London game IND@WAS kicks at 09:30 ET.

## 0. Install (once)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## 1. Build the fill-in slate (optional, 2 min)

```bash
ceminiparlays slate --games examples/games_2026_w04_sun.csv \
  --environment examples/2026-w04-sun-environment.csv
# writes runs/slate/lines_fill_in.csv from the Week 4 Sunday games file
# + the packaged roster. Team comes from the roster (DJ Moore = BUF).
# Missing env rows print ENVIRONMENT_MISSING_GAME: {AWAY}@{HOME} and exit 0.
```

Default `--games` stays `examples/games_sunday_afternoon.csv` (Week 1). Pass
`--games` for the current week's file. Use this only when you want a blank
roster sheet. Prefer `fetch` for posted two-way prices.

## 2. Fetch two-way lines (2 min)

`THE_ODDS_API_KEY` must already be in the environment. This CLI reads
`os.environ` only. It never prints the key.

```bash
ceminiparlays fetch --date 2026-10-04 --out runs/slate/lines.csv
# defaults: --books hardrock,fanduel,draftkings
#           --markets pass_yds,rush_yds,rec_yds,first_td,anytime_td
# --date is the America/New_York slate day (midnight ET → next midnight ET,
# converted to UTC; DST from zoneinfo). Sunday includes SNF.
# --utc-date YYYY-MM-DD keeps the old UTC calendar window.
# Game markets: add --markets h2h,spreads,totals if you want ML/spread/total rows.
# writes SLATE_FIELDS CSV: line + book_over/book_under for yard props;
# moneyline and spread rows are paired two-way (book_over/book_under);
# TD rows leave line blank and set leg_odds + a de-vigged pool ref_p.
# A raw implied probability is never written as fair_p.
# --reference-book R stamps R's de-vigged quote as ref_* on every other book's
# rows (auto-picked from draftkings/fanduel/betmgm). A rostered player who is on
# neither team in the event is dropped with roster-event-mismatch.
# prints x-requests-remaining / x-requests-used, then
# do not submit — type the ticket in-app

# Narrower card (overwrites only with --force)
ceminiparlays fetch --date 2026-10-04 --books hardrock --markets first_td \
  --out runs/slate/ftd.csv
```

Offline check (no network, no key):

```bash
ceminiparlays fetch --fixture tests/fixtures/odds_api_nfl.json --out /tmp/lines.csv
```

Fetch is **not** an SGP quote. Do not type a product of legs into `slip_odds`.
The displayed American is still one in-app price per ticket (`--displayed-odds`
in step 5). Existing `--out` is refused unless you pass `--force`.

Roster still wins team codes: DJ Moore is BUF, never invented CHI. Unknown Odds
API markets are skipped with a `no-odds-api-market` note.

## 3. Compose the card (4 min)

```bash
ceminiparlays compose --auto \
  --lines runs/slate/lines.csv \
  --environment examples/2026-w04-sun-environment.csv \
  --card-md --max-exposure-per-player 1 \
  --out-dir runs/2026-w04-sun/compose
# --card-md writes a redacted card.md (no stake) next to card.txt
# --max-exposure-per-player 1 exits 2 on same-player same-stat concentration
```

`--auto` with no knobs uses: `--markets pass_yds,rush_yds,rec_yds`, `--legs 2`,
`--min-odds +150`, `--max-odds +400`, `--n-tickets 5`. Any knob you pass
overrides that one default. A single odds bound keeps the other default unless
that would empty the window: `--max-odds +250` keeps the `+150` floor;
`--min-odds +800` drops the `+400` cap for a first-TD longshot.

`--auto` caps each ticket at 2 legs of the same `stat_type`. Override with
`--max-legs-per-market N`. `--max-legs-per-market 0` turns the cap off. When
`--environment` is set, wind of 10 mph or more on a `first_td` or `pass_yds`
leg prints `WEATHER_MARKET_REVIEW` and the leg stays on the ticket.

**Pick'em gap report** (`ceminiparlays compare`): prints the de-juiced fair decimal versus the fixed pick'em all-hit multiplier. The operator's typed `displayed_multiplier` is echoed but does not replace the table in the gap. The typed ticket price stays the in-app price.

**Weather discount.** `apply_weather_discount` is wired into `evaluate_legs` when `--environment` is present. It moves the **model** marginal of a weather-sensitive stat (`pass_yds`, `pass_tds`, `rec_yds`, `receptions`, `anytime_td`, ...) only when `weather_exposed=true` and wind or precip was typed. Gates: indoor (dome/indoor/closed) = no discount; retractable-closed = no discount; not exposed = no discount; a non-weather stat = no discount; exposed but both fields blank = no discount + `WEATHER_FIELDS_BLANK` note; otherwise the magnitude is wind `min(0.04, max(0, wind-10)*0.002)` + precip `min(0.04, (precip/25)*0.01)`, cap 0.08. The sign is side-aware: the haircut lands on an **Over** and the boost on the matching **Under**. A market-only marginal is left alone. `compose` still prints `WEATHER_MARKET_REVIEW` and keeps the leg. An explicitly passed `--environment` path that does not exist raises, and a non-numeric cell (`20mph`) raises.

It writes `ticket-001.csv` … `ticket-005.csv` plus `card.txt` and `card.json`,
and prints `do not submit`. Tickets diversify games and prefer higher implied
team totals when `--environment` is present. `--environment` also writes
`compose_itt.json` (bet-time ITT snapshot). Do not rewrite that file from box
scores. Omit `--environment` to skip the snapshot.

`compose` writes a card on **every** run. A run with no qualifying leg writes a
**null card** with the reason and exits 2. Run it every slate week. A skipped
week is a process gap, not a missing file.

**Modeled edge and the fair marginal.** Every leg is gated on
`model P - market implied P`. The model P is a typed `fair_p` or a
`--distributions` projection. A leg below `--min-edge` (default `+0.01`) sets
`edge_gate: fail` and exits 2. A leg with no model P is flagged `no-edge` on the
card. Pass `--distributions` or type `fair_p` so the gate can work. Record the
edge on the card: `card.json` carries it per leg.

The marginal that drives the copula, EV, and Kelly is the **model**, not the book
you bet. Precedence: typed `fair_p` → a `--distributions` projection → `ref_p` →
`ref_book_over`/`ref_book_under` → the ticket book's own two-way de-vig → TD
`leg_odds` → a `contract_price` mid. So a projection now **beats** the ticket
book. A leg whose only fair value is a market price is priced but marked
`no-edge`; pass `--require-model` to drop it instead. `rank` takes the same
`--min-edge` and fails closed (exit 2) on a weak edge when it is set.

A same-game pair with no entry in `config/correlation_priors.json` is skipped
(`skip unmodeled-corr`), never priced from a guessed fallback. Pass
`--allow-unmodeled-correlation` to restore the old guess.

**Staleness.** `fetch` records `commence_time`. A leg whose game has already
kicked off is dropped (`already-kicked`). Pass `--max-line-age MINUTES` to drop a
line older than that (`stale-line`).

**Stake.** Pass `--bankroll N`. Each ticket gets a quarter-Kelly stake, capped at
5% of the bankroll. `card.json` records the `stake` and the `stake_rule`.

## 4. Snapshot the closing lines (near kickoff)

```bash
ceminiparlays fetch --date 2026-10-11 --out runs/slate/lines_close.csv
ceminiparlays closings --lines runs/slate/lines_close.csv \
  --out runs/2026-w05-sun/closing_props.csv
```

`closings` writes one row per prop: `platform,player_key,stat_type,side,line,over,under,captured_at`.
Run it as close to kickoff as practical. It is the only per-prop closing source.
Run this snapshot every slate. CLV cannot exist when the snapshot is missing.
`grade --closings` fills a blank `close_*` ledger cell from it by
`(platform, player_key, stat_type, side)` and computes `clv_pp`.

**Weekly, read the CLV.** Once a week, aggregate the graded ledgers:

```bash
ceminiparlays clv --ledger runs/2026-w05-sun/ledger.csv
```

`clv` prints the leg count, the mean / median / stdev CLV in percentage points,
a one-sided t-statistic and p-value for mean > 0, a positive-CLV rate, a
breakdown by platform / stat_type / market, and a verdict. `--ledger` is
repeatable. `--min-legs` changes the leg target (default 100). `--json` prints
the report as JSON; `--out PATH` also writes it there. The verdict is
**PROVE** when the mean is at least +1.5 pp and the t-statistic is at least 2.0
at 100 legs, **KILL** when the mean is at or below 0.0 pp at 100 legs, and
**KEEP COLLECTING** in between. It labels the basis: `same_book` when the close
came from the book that was bet, `reference` when it came from another book.
No sharp-book fetch is built here; the report only labels what the data shows.

**CeminiDFS handoff** (optional, copy the file; this CLI only reads):

```bash
cp path/to/ceminidfs_handoff.csv runs/slate/ceminidfs_handoff.csv
ceminiparlays compose --auto \
  --lines runs/slate/lines.csv \
  --environment examples/2026-w04-sun-environment.csv \
  --from-ceminidfs runs/slate/ceminidfs_handoff.csv \
  --card-md --max-exposure-per-player 1 \
  --out-dir runs/2026-w04-sun/compose
```

Missing file: `CEMINIDFS_HANDOFF_MISSING: {path}` and compose continues.
A present file fills blank `implied_total` (does not overwrite roof/weather)
and prints `ceminidfs exposure:` notes. FanDuel FPPG `projection` is not a
prop fair. Both examples above pass `--card-md --max-exposure-per-player 1`:
the first writes a redacted `card.md` (no stake), the second exits 2 on
same-player same-stat concentration.

**Before you type** (four checks, every week):

- **Wind** (packaged env): after the weather fill, fade pass / lean rush on the
  ≥10 mph rows in this week's environment.csv. The rows are blank until the
  research step fills wind and precip.
- **Roof**: DAL@HOU is retractable and stays weather-exposed until an official
  roof call. No call means treat it as exposed; do not fade on a guess.
- **Jev**: run the mandatory gate in *Run the Jev gate* below. It writes
  `jev_gate_report.csv`. Do not type a `do_not_type` row or a
  `thesis_unsupported` row.
- **Flags**: `--enforce-market-depth` only after a fetch that includes
  `h2h,spreads` — a yards-only fetch will halt (exit 2). `--alert-late-active`
  only if an inactives file exists — a missing file exits 2. A `status` of
  `out` / `inactive` / `ir` / `doubtful` **scratches** that player before pricing.

Report-only compose flags (default off):

```bash
# TG-04 thin catalog: halt when a game lacks moneyline/h2h or spread/spreads
# Use only after a fetch that includes h2h,spreads. A yards-only fetch halts.
ceminiparlays compose --auto --enforce-market-depth \
  --lines runs/slate/lines.csv --out-dir runs/slate
# CATALOG_THIN_MANUAL_INPUT_REQUIRED then exit 2
# --allow-thin-catalog prints the same note and continues
# compose --auto without the flag (yards only) does not halt

# TG-03 late status: scratch a player marked out/inactive/ir/doubtful in this CSV
# Use only when the inactives file exists. Missing file exits 2.
ceminiparlays compose --auto --alert-late-active inactives.csv \
  --lines runs/slate/lines.csv --out-dir runs/slate
# scratch (late status): {player}   — the leg is scratched before pricing
# A missing file exits 2. No void, no reprice, no haircut of a live leg.
# (An in-game `exit` / `left` token on a row still prints IN_GAME_EXIT and keeps
# the leg live.)
```

Want a different card?

```bash
# A first-TD longshot
ceminiparlays compose --auto --markets first_td --legs 4 --min-odds +800 \
  --lines runs/slate/lines.csv --out-dir runs/ftd

# A shorter rush card
ceminiparlays compose --auto --markets rush_yds --legs 3 --max-odds +250 \
  --lines runs/slate/lines.csv --out-dir runs/rush

# FanDuel / DraftKings / BetMGM use the same displayed-American path
ceminiparlays compose --auto --platform betmgm --lines runs/slate/lines.csv
```

### Run the Jev gate (after compose, before you type)

Run `ceminiparlays jev-gate` on the composed card. This step is mandatory every
week. It is one of the four checks above.

```bash
ceminiparlays jev-gate \
  --card runs/2026-w05-sun/compose/card.json \
  --lines runs/2026-w05-sun/lines.csv \
  --environment examples/environment.csv \
  --late-active runs/2026-w05-sun/inactives.csv \
  --promo-terms 'Up to $10 back as a Bonus Bet if your 2+ leg NFL bets lose' \
  --out-dir runs/2026-w05-sun/jev
```

The gate writes `jev_gate_report.csv` in `--out-dir`. The report has one row per
check per leg or card. The `action` cell tells you what to do.

- `pass`: type the leg.
- `do_not_type`: do not type the leg. The lines file contradicts it.
- `thesis_unsupported`: do not type the leg. The environment contradicts the
  thesis.
- `review`: an operator reads the row. Jev is not confident enough to mark it.
- `block`: the gate had no evidence or no server. The run exits 2.

The gate marks each row. It does not reprice, void, rewrite, or submit a ticket.
It **fails closed**: a `block`, a `do_not_type`, or a `thesis_unsupported` row
exits 2. `review` does not fail. Pass `--allow-flagged` to let a contradiction
through on purpose. A `pass_yds` thesis is side-aware — an Over asks for high
passing volume and an Under asks for low — and a leg whose team is absent from
`environment.csv` blocks. The verdict line goes on `card.md` only when that file
already exists. Read the report before you type.

## 5. Price one ticket before you build it (2 min)

Once you have the in-app American on one ticket:

```bash
ceminiparlays run --lines runs/2026-w04-sun/compose/ticket-001.csv \
  --distributions examples/distributions.csv \
  --platform hardrock --displayed-odds +264 \
  --out-dir runs/2026-w04-sun/ticket-001
```

`--displayed-odds` is legal only when `live == slip-size`. A 2-leg compose file
matches the default; a 4-leg first-TD file needs `--legs 4`. A shared
`ticket_id` does not let one American price every subset.

## 6. Size the card (1 min)

```bash
ceminiparlays bankroll --bankroll 25 --n-tickets 5
# bankroll $25.00 over 5 tickets: flat $5.00 each
# quarter-Kelly cap (5% of bankroll): $1.25 per ticket
```

Pick flat **or** the cap for the whole ticket — never split Kelly across legs.

## 7. Type the tickets in-app (3 min)

Open Hard Rock / FanDuel / DraftKings / BetMGM and enter the legs. Confirm every
line and the displayed American. The CLI never submits.

After the booked ticket exists, diff it against the compose card (TG-06). Booked
is display-only. You still type the ledger.

```bash
ceminiparlays diff --card examples/card_ticket_c.csv \
  --booked examples/booked_ticket_c.csv
# per-ticket_id stake / lines / multiplier deltas; exit 2 when any delta exists
# --accept-booked prints the same table and exits 0; never writes the card
# --accept-booked --emit-ledger PATH writes booked rows (not the card)
```

## 8. Grade after the games

```bash
ceminiparlays grade --ledger my_ledger.csv --out runs/grade.json
```

Optional ledger columns `ticket_id`, `market`, `stake_kind` (`cash` / `bonus`),
and `paid` (Won-tab cash → that row is `paid - stake`) are accepted; unknown
extra columns are ignored. Discrete ATD `yes`/`yes` and ML `win`/`win` are hits,
never voids. Numeric `actual == line` still voids on yardage/totals/spreads.
`multiplier` needs an explicit sign to read as American: `+288` and `-110` are
prices, but a bare integer is a decimal. `120` is **120×**, not +120 (2.2×) — an
8-leg Underdog slip pays `120`. Sportsbook void + miss = `0×`. A 3-leg Flex with
one void steps down to the 2-leg Standard payout (`3.5×`), not a refund. A HIT
with an empty multiplier still fails closed, and a **blank `stake` cell now fails
closed** instead of defaulting to `$1.00`.

`two_plus_td` and `pass_td` (alias of `pass_tds`) are legal ledger markets.
`To Score 2+ TDs` maps to `two_plus_td`. `Passing TDs` maps to `pass_tds`.

Capture guards (exit 2 when any row is partial):

- The visible N-Bet must equal the captured legs. If it does not, the row is `PARTIAL`. Do not invent the missing legs.
- A book ticket id must be 18 or 19 digits. A shorter digit string is clipped. The status is `PARTIAL-` plus the visible digits. Do not pad the id.
- Pass `--games` for the slate window and `--card` for the compose card. A game outside that window, or a ticket id that is not on the card, is `off_card`. Its PnL is `off_card_pnl`, apart from `on_card_pnl`.
- `cash_pnl`, `bonus_in`, and `bonus_out` stay separate. A No Sweat return is bonus. It is not a cash win.
- `injury_status` of `exit`, `left`, or `concussion` prints `IN_GAME_EXIT`. The leg stays live. Grade the typed actual. No auto-cashout. No invented void.
- `replay_reversal=yes` is a separate recap note. It does not change the grade.
- Keep `book_actual` and `official_actual`. The typed `actuals` column still grades the leg.

## Full auto example (one command)

```bash
ceminiparlays compose --auto \
  --lines examples/sunday_lines.csv \
  --environment examples/environment.csv \
  --out-dir /tmp/compose-demo
```

`first_td` example (cross-game, two tickets): `examples/first_td_ticket.csv`.

Week 1 Sunday $20 Hard Rock card (4-leg rush + anytime TD + 1 p.m. slate):
[`docs/2026-09-13-hardrock-card.md`](2026-09-13-hardrock-card.md).
