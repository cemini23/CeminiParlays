# Sunday in 20 minutes

The operator path for one afternoon slate. Licensed Odds API fetch is allowed.
Book-site scrapers and auto-submit are not. You type the ticket in the app; this
CLI only fetches two-way lines, picks, and prices.

**Grok Bot desks:** before lock, Parlays Slate Desk can write `environment.csv` and
scheme notes. After the games, Parlays Recap Desk fills a ledger for step 7.
Paste: [`GROK-BOTS.md`](GROK-BOTS.md). The Bot does not fetch or submit.

**Rule for every step:** if a command exits `2`, read the named `dropped` /
`no-line` rows and fix the CSV. Do not pass `--no-strict` on a money slate.

## 0. Install (once)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## 1. Build the fill-in slate (optional, 2 min)

```bash
ceminiparlays slate
# writes runs/slate/lines_fill_in.csv from examples/games_sunday_afternoon.csv
# + the packaged roster. Team comes from the roster (DJ Moore = BUF).
```

Swap `--games` for the current week's game file. Use this only when you want a
blank roster sheet. Prefer `fetch` for posted two-way prices.

## 2. Fetch two-way lines (2 min)

`THE_ODDS_API_KEY` must already be in the environment. This CLI reads
`os.environ` only. It never prints the key.

```bash
ceminiparlays fetch --out runs/slate/lines.csv
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
ceminiparlays fetch --date 2026-09-13 --books hardrock --markets first_td \
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
  --environment examples/environment.csv \
  --out-dir runs/2026-w01-sun/compose
```

`--auto` with no knobs uses: `--markets pass_yds,rush_yds,rec_yds`, `--legs 2`,
`--min-odds +150`, `--max-odds +400`, `--n-tickets 5`. Any knob you pass
overrides that one default. A single odds bound keeps the other default unless
that would empty the window: `--max-odds +250` keeps the `+150` floor;
`--min-odds +800` drops the `+400` cap for a first-TD longshot.

It writes `ticket-001.csv` … `ticket-005.csv` plus `card.txt`, and prints
`do not submit`. Tickets diversify games and prefer higher implied team totals
when `--environment` is present.

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

## 4. Price one ticket before you build it (2 min)

Once you have the in-app American on one ticket:

```bash
ceminiparlays run --lines runs/2026-w01-sun/compose/ticket-001.csv \
  --distributions examples/distributions.csv \
  --platform hardrock --displayed-odds +264 \
  --out-dir runs/2026-w01-sun/ticket-001
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
