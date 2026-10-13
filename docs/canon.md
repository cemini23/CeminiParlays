# CeminiParlays canon

Numbered rules a search engine or LLM can quote. This page has no live picks.

## C1. Displayed American is ticket identity

The in-app American parlay / SGP price is the ticket. Type that price (`--displayed-odds`, or ledger `multiplier` / `slip_odds`). Do not replace it with a product of fetched legs.

## C2. SGP is not the independent product of legs

A same-game parlay is not independent. The product of per-leg odds overstates payout and EV. Confirm the displayed price in-app before you size.

## C3. No scrape

This CLI does not scrape book, lounge, Polymarket, or Kalshi boards. Licensed Odds API ingest is the only HTTP path. Offline `fetch --fixture` needs no key.

## C4. No auto-submit

The CLI does not fill or submit slips. The operator types the ticket in the book app.

## C5. No invented reduced-SGP table

House-rule step-downs stay out of Python. A sportsbook void with remaining hits needs the settled in-app multiplier. Do not invent a reduced ticket.

## C6. HIT with an empty multiplier fails closed

A full hit with a blank `multiplier` is an error. It is not a silent refund and it is not a guessed payout. A miss with an empty multiplier settles at 0×.

## C7. SoFi is `semi_open`, not a dome

SoFi Stadium is not a dome. Tag it `semi_open`. Do not treat it as wind-exposed like an open bowl.

## C8. `do not submit` is the product contract

Every output that prices a ticket prints **do not submit**. That line is the contract. Research only.

## C9. Responsible use — 1-800-GAMBLER

Wager only where it is legal. Keep a bankroll separate from DFS and best-ball. If gambling is a problem, call **1-800-GAMBLER**.

Tips: [SUPPORT.md](../SUPPORT.md). This page does not list wallets.

## C10. Incomplete capture stays partial

Block finalize when the visible N-Bet does not match the captured legs. Block finalize when a book ticket id is not 18 or 19 digits. Mark that row `PARTIAL` plus the visible digits. Do not invent a leg, a stake, or the missing digits.

## C11. Off-card PnL stays apart

Tag a ticket `off_card` when its game is outside the slate window, or when its ticket id is not on the compose card. Report that PnL apart from the on-card PnL.

## C12. Cash and bonus stay apart

Report `cash_pnl`, `bonus_in`, and `bonus_out` as separate figures. A No Sweat bonus is not a cash win.

## C13. An in-game exit stays live

A player who leaves during the game does not void the leg and does not cash out. Grade the typed actual. No auto-cashout. No invented void.

## C14. Book actual and official actual both stay

Keep `book_actual` and `official_actual` on the ledger. Do not drop either column. The typed `actuals` column still grades the leg.

## C15. Every card writes an artifact, even a null card

`compose` always writes `card.json` plus `card.txt`. When no leg qualifies, or a strict run drops a leg, it writes a **null card** with the reason and exits 2. A skipped slate is a process gap, not a missing file. Never pad a card to a requested count.

## C16. A parlay leg needs a modeled edge

The edge is `model P - market implied P`. The model P is a typed `fair_p` or a projection. The market implied P is the de-vigged two-way book. `compose` writes the edge on every leg of `card.json`. A leg whose edge is below `--min-edge` (default `+0.01`) sets `edge_gate: fail` and exits 2. A leg with no model P is flagged `no-edge` on the card. A fair price is still −EV without an edge; the legs multiply the hold.

## C17. Capture the per-prop closing line and the CLV

`compose` writes the bet-time line and both prices on `card.json`. Run `closings` near kickoff to snapshot the per-prop closing lines. `grade --closings` joins the snapshot to the ledger and fills the `close_*` cells. CLV is the closing implied minus the bet implied. Positive beats the close. There is no other per-prop closing source.

## C18. Book the stake and the promo at value

`compose --bankroll` sizes each ticket with quarter-Kelly, capped at 5% of the bankroll, and records `stake` and `stake_rule` on `card.json`. A flat stake is not a Kelly stake. Record the promo terms and the settled result on the ledger. Carry the bonus's expected cash value in `promo_value`. `net_pnl` is `cash_pnl + promo_value`. An unsettled promo raises `PROMO_UNCONFIRMED` and is never counted.

## C19. The Jev gate is mandatory and marks only

Run `ceminiparlays jev-gate` after `compose` and before the operator types. It is mandatory every slate week. It writes `jev_gate_report.csv` and one verdict line on `card.md`. It **marks** a row `pass`, `do_not_type`, `thesis_unsupported`, `review`, or `block`. It never reprices, voids, rewrites, or submits a ticket. A missing key, a missing server, or a malformed answer fails closed: every pending row is `block` and the run exits 2. A `do_not_type` or `thesis_unsupported` row prints loud and exits 0. The gate answers questions only. It is not an optimizer and holds no card, stake, or payout. Player names and public status strings only — no PII.
