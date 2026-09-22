# Sunday in 20 minutes

The operator path for one afternoon slate. Licensed Odds API fetch is allowed.
Book-site scrapers and auto-submit are not. You type the ticket in the app; this
CLI only fetches two-way lines, picks, and prices.

**Grok Bot desks:** Parlays Slate Desk and Parlays Recap Desk already exist in
Grok Bot.app. Charters live in OSINT WORKSPACE
(`briefs/2026-09-01_grok-bot-charters.md` §17 / §19). Product copy:
[`GROK-BOTS.md`](GROK-BOTS.md). Before lock, open Slate Desk → `environment.csv`.
After the games, open Recap Desk → ledger for step 7. Do not create new Bots.
The Bot does not fetch or submit. Slate Desk defaults to Sunday afternoon only,
so name **SNF IND@KC** if you open it this Sunday; NYG@LAR is Monday.

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

This Sunday card is **2026-09-20**. SNF IND@KC is on this slate. NYG@LAR is
Monday — wait.

## 0. Install (once)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## 1. Build the fill-in slate (optional, 2 min)

```bash
ceminiparlays slate --games examples/games_2026_w02_sun.csv \
  --environment examples/2026-w02-sun-environment.csv
# writes runs/slate/lines_fill_in.csv from the Week 2 Sunday games file
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
ceminiparlays fetch --date 2026-09-20 --out runs/slate/lines.csv
# defaults: --books hardrock,fanduel,draftkings
#           --markets pass_yds,rush_yds,rec_yds,first_td,anytime_td
# --date is the America/New_York slate day (midnight ET → next midnight ET,
# converted to UTC; DST from zoneinfo). Sunday includes SNF.
# --utc-date YYYY-MM-DD keeps the old UTC calendar window.
# Game markets: add --markets h2h,spreads,totals if you want ML/spread/total rows.
# writes SLATE_FIELDS CSV: line + book_over/book_under for yard props;
# TD / h2h rows leave line blank and set leg_odds + raw implied fair_p.
# prints x-requests-remaining / x-requests-used, then
# do not submit — type the ticket in-app

# Narrower card (overwrites only with --force)
ceminiparlays fetch --date 2026-09-20 --books hardrock --markets first_td \
  --out runs/slate/ftd.csv
```

Offline check (no network, no key):

```bash
ceminiparlays fetch --fixture tests/fixtures/odds_api_nfl.json --out /tmp/lines.csv
```

Fetch is **not** an SGP quote. Do not type a product of legs into `slip_odds`.
The displayed American is still one in-app price per ticket (`--displayed-odds`
in step 4). Existing `--out` is refused unless you pass `--force`.

Roster still wins team codes: DJ Moore is BUF, never invented CHI. Unknown Odds
API markets are skipped with a `no-odds-api-market` note.

## 3. Compose the card (4 min)

```bash
ceminiparlays compose --auto \
  --lines runs/slate/lines.csv \
  --environment examples/2026-w02-sun-environment.csv \
  --card-md --max-exposure-per-player 1 \
  --out-dir runs/2026-w02-sun/compose
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

It writes `ticket-001.csv` … `ticket-005.csv` plus `card.txt`, and prints
`do not submit`. Tickets diversify games and prefer higher implied team totals
when `--environment` is present. `--environment` also writes `compose_itt.json`
(bet-time ITT snapshot). Do not rewrite that file from box scores. Omit
`--environment` to skip the snapshot.

**CeminiDFS handoff** (optional, copy the file; this CLI only reads):

```bash
cp path/to/ceminidfs_handoff.csv runs/slate/ceminidfs_handoff.csv
ceminiparlays compose --auto \
  --lines runs/slate/lines.csv \
  --environment examples/2026-w02-sun-environment.csv \
  --from-ceminidfs runs/slate/ceminidfs_handoff.csv \
  --card-md --max-exposure-per-player 1 \
  --out-dir runs/2026-w02-sun/compose
```

Missing file: `CEMINIDFS_HANDOFF_MISSING: {path}` and compose continues.
A present file fills blank `implied_total` (does not overwrite roof/weather)
and prints `ceminidfs exposure:` notes. FanDuel FPPG `projection` is not a
prop fair. Both examples above pass `--card-md --max-exposure-per-player 1`:
the first writes a redacted `card.md` (no stake), the second exits 2 on
same-player same-stat concentration.

**Before you type** (four checks, every week):

- **Wind** (packaged env): fade pass / lean rush on **NO@BAL**, **MIN@CHI**,
  **WAS@DAL** (only if the roof is open), **IND@KC** — the ≥10 mph rows.
- **Roof**: WAS@DAL is retractable and stays weather-exposed until an official
  roof call. No call means treat it as exposed; do not fade on a guess.
- **Jev**: `jev_verify` each live leg against the lines file and the CeminiDFS
  handoff row. If Jev contradicts the row, do not type that ticket.
- **Flags**: `--enforce-market-depth` only after a fetch that includes
  `h2h,spreads` — a yards-only fetch will halt (exit 2). `--alert-late-active`
  only if an inactives file exists — a missing file exits 2.

Report-only compose flags (default off):

```bash
# TG-04 thin catalog: halt when a game lacks moneyline/h2h or spread/spreads
# Use only after a fetch that includes h2h,spreads. A yards-only fetch halts.
ceminiparlays compose --auto --enforce-market-depth \
  --lines runs/slate/lines.csv --out-dir runs/slate
# CATALOG_THIN_MANUAL_INPUT_REQUIRED then exit 2
# --allow-thin-catalog prints the same note and continues
# compose --auto without the flag (yards only) does not halt

# TG-03 late active: FLAG/OUT on the lines file, later ACTIVE in this CSV
# Use only when the inactives file exists. Missing file exits 2.
ceminiparlays compose --auto --alert-late-active inactives.csv \
  --lines runs/slate/lines.csv --out-dir runs/slate
# OPERATOR_ACTION_REQUIRED: {player} excluded as {status} later ACTIVE
# exit 0 (alert only). Missing file exits 2. No void, no reprice, no haircut.
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

**Optional jev HITL** (after compose, before you type): run `jev_verify` on each
live leg against the lines file and the CeminiDFS handoff row. If Jev contradicts
the row, do not type that ticket. Optional `jev_find` is a type/skip read and may
label a ticket `promo_hedge`, `real_hedge`, or `straight_bet`. Jev does not set
odds, Kelly, or ITT.

## 4. Price one ticket before you build it (2 min)

Once you have the in-app American on one ticket:

```bash
ceminiparlays run --lines runs/2026-w02-sun/compose/ticket-001.csv \
  --distributions examples/distributions.csv \
  --platform hardrock --displayed-odds +264 \
  --out-dir runs/2026-w02-sun/ticket-001
```

`--displayed-odds` is legal only when `live == slip-size`. A 2-leg compose file
matches the default; a 4-leg first-TD file needs `--legs 4`. A shared
`ticket_id` does not let one American price every subset.

## 5. Size the card (1 min)

```bash
ceminiparlays bankroll --bankroll 25 --n-tickets 5
# bankroll $25.00 over 5 tickets: flat $5.00 each
# quarter-Kelly cap (5% of bankroll): $1.25 per ticket
```

Pick flat **or** the cap for the whole ticket — never split Kelly across legs.

## 6. Type the tickets in-app (3 min)

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

## 7. Grade after the games

```bash
ceminiparlays grade --ledger my_ledger.csv --out runs/grade.json
```

Optional ledger columns `ticket_id`, `market`, `stake_kind` (`cash` / `bonus`),
and `paid` (Won-tab cash → that row is `paid - stake`) are accepted; unknown
extra columns are ignored. Discrete ATD `yes`/`yes` and ML `win`/`win` are hits,
never voids. Numeric `actual == line` still voids on yardage/totals/spreads.
`multiplier` `+288` is American (`american_to_decimal`), not 288×. Sportsbook
void + miss = `0×`. HIT with an empty multiplier still fails closed.

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
