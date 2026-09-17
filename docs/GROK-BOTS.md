# Grok Bots for CeminiParlays

**This week / before next lock:** paste both desks (Parlays Slate Desk and Parlays Recap Desk) into Grok Bot.app. Cursor cannot create the Bots. CLI `grade` still wins if the Bot paper PnL disagrees. No Bot scrape. No Bot submit. No Odds API key on the Bot VM.

Operator paste for Grok Bot.app. Canon lives in OSINT `briefs/2026-09-01_grok-bot-charters.md` (§17 Parlays Slate Desk, §19 Parlays Recap Desk). Cursor cannot create the Bots — paste the Description, then send the First skill.

These Bots **research and recap**. They do not fetch Odds API, they do not scrape books, and they do not submit. Laptop path stays [`docs/SUNDAY.md`](SUNDAY.md): `fetch` → `compose` → type the ticket → `grade`.

## 1. Parlays Slate Desk (before lock)

**Name:** Parlays Slate Desk  
**Title:** Weather, roster, scheme edges

Use when you want a whole-slate packet: weather, injury/roster, and how each offense’s style meets each defense’s style. Output is context for `--environment` and scratches — not a displayed American.

Paste the **Description** and **Sunday parlay packet** skill from OSINT charters §17. Optional second skill: **Scheme matchup card**.

Default slate: NFL Sunday afternoon **1 p.m. ET + 4 p.m. ET** (4:05 / 4:25). Not SNF/MNF unless you name them.

After a clean run, copy files off the Bot VM:

| Bot file | Laptop use |
|----------|------------|
| `environment.csv` | `ceminiparlays compose --auto --environment …` |
| `scratches.md` | type `injury_status` on live rows |
| `scheme.md` | human filter before you compose a rush vs pass card |

Roof rules match `CeminiDFS` stadiums + this repo’s ROADMAP: dome skip; SoFi **not** wind-exposed; retractable stays exposed until a roof call; wind ≥10 / ≥15 mph and precip lean pass down / rush up.

Never two `first_td` legs from one game.

## 2. Parlays Recap Desk (after the games)

**Name:** Parlays Recap Desk  
**Title:** Ticket results → tool gaps

Drop the tickets you actually typed (`ticket-00N.csv`, the Hard Rock card, or a paste). The Bot fills actuals from official boxes and writes a ledger. Then on the Mac:

```bash
ceminiparlays grade --ledger path/to/ledger.csv --out runs/grade.json
```

CLI JSON wins if the Bot’s paper PnL disagrees. The Bot must not invent a reduced-SGP American after a void.

Paste Description + **Grade entered tickets** from OSINT charters §19.

`tool-gaps.md` is HITL: weather miss, SoFi outdoor tag, missed OUT, scheme lean, compose ITT preference, naive product vs copula. Do not auto-edit this repo from the Bot.

## Ledger shape

See `examples/ledger.csv` (pick'em) and `examples/recap_sportsbook_ledger.csv` (Hard Rock-shaped). Optional columns `ticket_id`, `market`, `stake_kind` (`cash` / `bonus`) are already accepted by `grade`. The sportsbook example `multiplier` values are **typed displayed decimals**, not a product of legs. Anytime-TD recap uses line `0.5` with actual `1` (hit) or `0` (miss) so a push cannot fake a void.

## Never

- Sportsbook login or Bet/Submit on the Bot VM
- Odds API key on the Bot VM
- FanDuel FPPG as a prop fair
- Independent product sold as confirmed SGP EV
