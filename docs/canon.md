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
