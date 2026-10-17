# CeminiParlays canon

Numbered rules a search engine or LLM can quote. This page has no live picks.

## C1. Displayed American is ticket identity

The in-app American parlay / SGP price is the ticket. Type that price (`--displayed-odds`, or ledger `multiplier` / `slip_odds`). Do not replace it with a product of fetched legs.

## C2. SGP is not the independent product of legs

A same-game parlay is not independent. The product of per-leg odds overstates payout and EV. Confirm the displayed price in-app before you size.

## C3. No HTML scrape. One public book read.

This CLI does not scrape book HTML. It does not scrape lounge, Polymarket, or Kalshi boards. It does not fill a slip and it does not submit a bet.

Two read paths are allowed. `odds_api.py` reads the licensed Odds API. `hardrock_book.py` reads Hard Rock's public odds API: `GET /java-graphql/operation/GetEvents` and `GET /sportsbook/v1/api/getRootLadder`. The operator approved that read on 2026-10-17. The Odds API feed does not carry half, quarter, or alternate lines, and the posted price has to be the book's own price. The read does not log in and does not call `placeBets`. Offline `fetch --fixture` needs no key.

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

The leg marginal that drives the copula, EV, and Kelly must be INDEPENDENT of the book being bet: a typed `fair_p` or a projection beats the ticket book's own de-vig. A market-only marginal is priced but marked `no-edge`; `--require-model` drops it instead. `rank` runs the same edge gate: with `--min-edge` set, a weak edge exits 2. A same-game pair with no entry in `config/correlation_priors.json` is skipped, never priced from a guessed fallback; `--allow-unmodeled-correlation` restores the guess.

## C17. Capture the per-prop closing line and the CLV

`compose` writes the bet-time line and both prices on `card.json`. Run `closings` near kickoff to snapshot the per-prop closing lines. `grade --closings` joins the snapshot to the ledger and fills the `close_*` cells. CLV is the closing implied minus the bet implied. Positive beats the close. There is no other per-prop closing source.

## C18. Book the stake and the promo at value

`compose --bankroll` sizes each ticket with quarter-Kelly, capped at 5% of the bankroll, and records `stake` and `stake_rule` on `card.json`. A flat stake is not a Kelly stake. Record the promo terms and the settled result on the ledger. Carry the bonus's expected cash value in `promo_value`. `net_pnl` is `cash_pnl + promo_value`. An unsettled promo raises `PROMO_UNCONFIRMED` and is never counted.

## C19. The Jev gate is mandatory and marks only

Run `ceminiparlays jev-gate` after `compose` and before the operator types. It is mandatory every slate week. It writes `jev_gate_report.csv` and one verdict line on `card.md`. It **marks** a row `pass`, `do_not_type`, `thesis_unsupported`, `review`, or `block`. It never reprices, voids, rewrites, or submits a ticket. A missing key, a missing server, or a malformed answer fails closed: every pending row is `block` and the run exits 2. A `do_not_type` or `thesis_unsupported` row is a contradiction and also exits 2, unless the operator passes `--allow-flagged`. A `pass_yds` thesis is side-aware: an Over needs high passing volume, an Under needs low volume, and a leg whose team is absent from `environment.csv` blocks. The verdict line goes on `card.md` only when that file exists; an absent `card.md` is never created to hold a verdict alone. The gate answers questions only. It is not an optimizer and holds no card, stake, or payout. Player names and public status strings only — no PII.

## C20. Jev routes; Python computes

Jev is a discrete epistemic router. It answers a typed question about a structured state and returns calibrated probabilities, a score, and a confidence. It NEVER performs power de-vigging, positive semi-definite projection, Monte Carlo copula draws, or Kelly math. Those stay in `numpy` / `scipy`. Every Jev answer is cached deterministically on disk under `data/cache/jev/<sha256>.json`, so a rerun is reproducible and a repeated question costs no network call.

Provider order is TypeSafe System One, then Jev MCP, then OpenRouter as a backup. `--jev-provider auto` fails over only when a provider is unconfigured or fails transiently. A permanent failure such as HTTP 401 stops the chain, so a bad key never silently bills the backup. When no provider answers, the caller blocks; it never substitutes a guess.

## C21. Size from confidence, then cap the slate

`jev-gate --size` turns the gate into a three-stage sizing controller. Stage 1 is the fail-closed hard gate: missing environment data, a `pre_game_inactive` player, an unavailable provider, or `p_jev * c_jev < 0.50` sets `BLOCKED` and a zero stake. Stage 2 shrinks quarter-Kelly by `clip((p_jev * c_jev - 0.50) / 0.35, 0.0, 1.0)` and caps one ticket at `--max-ticket-pct`. Stage 3 scales all passing tickets down together so the slate fits `--max-slate-pct`. The sizing report is written beside the gate report, and the gate report schema stays frozen. Sizing is off by default: without `--size` the gate marks only.

## C22. A fair value is never circular

The market side of a fair value comes from a book the operator did NOT bet. `fetch --reference-book` stamps a sharp book's de-vigged quotes as `ref_book_over` / `ref_book_under`, and `rank --dfs-pricing` de-vigs those. A de-vig of the ticket book's own price would report that book's margin as an edge.

A prop priced from the CeminiDFS handoff uses a split-normal built on `(median, p15, p85)`, never a symmetric normal: the handoff's asymmetry is the signal. The DFS and market probabilities blend as `(1 - w) * p_market + w * p_dfs` with `w = 0.35 * jev_regime_conf`, capped at 0.35 until 100 legs of closing-line calibration are proven. `disagreement_edge_bps` is recorded in `edges.csv` so the handoff's record against the close is measurable, not assumed.

## C23. The season ledger is the proof

Ticket P&L cannot prove an edge at a practical sample size; leg-level closing line value can. `fetch --closing-snapshot` freezes the close into `runs/<week>/closing_lines.csv`. `grade` computes `leg_clv_bps` per leg and `dfs_vs_close_brier_delta` when a handoff is supplied. `grade --season-ledger` appends one durable row per run. A run without `--season-ledger` appends nothing and writes no other file.

## C24. A period market enters only through two keys

A token enters `LEGAL_MARKETS` only when both keys pass. Do not promote on one key.

The history key uses settled play-by-play from 2023 through 2026 week 5. 2022 play-by-play is absent. Score each player-game at a point in time. The synthetic lines are the prior median and, for a zero-inflated prop, a 0.5 line. The benchmark price is -114/-114. Require at least 250 player-games (games for `total_q3`). Require a Brier skill gain above 0. Require a bootstrap 95% CI lower bound above 0. Require a Benjamini-Hochberg q-value at or below 0.10.

The live key uses one unplayed slate. A multi-player skill market needs at least 35 legs. A single-starter market needs at least 16 legs. A game-level market needs at least 10 legs. Require a mean EV above 0, a bootstrap 95% CI lower bound above 0, and a Benjamini-Hochberg q-value at or below 0.10.

On 2026-10-17 the v3 tokens that pass both keys are `rec_yds_q3`, `rec_yds_q4`, `receptions_q4`, `rush_yds_q4`, `pass_yds_q4`, `interceptions`, and `total_q3`. `rush_yds_q4` entered when quarter lambda stopped shrinking the level. The v1 tokens `rec_longest` and `rush_longest` stay withdrawn. Their history key failed. `receptions_q1` stays out. `spreads_q3` and `spreads_q4` stay unscored. The spread sign is not locked.

Quarter receiving yards and quarter rushing yards use a compound Poisson-gamma hurdle. A normal distribution is not used for those props or for a reception prop. `receptions_q4` is a Poisson count. V3 quarter lambda is full-game volume times a shrunk quarter share times a defense multiplier. Full-game volume is not shrunk toward a starter mean. The quarter share uses 15 plays and a 0.25 prior.

Regime correlations are stored in `config/matchup_regime_rho.json`. `correlation.py` reads that file only after the full-game prior is missing, and only when a stat is a matchup token. Compose can price a same-game research joint with the Gaussian copula. Compose does not pair one player's receptions and receiving yards in the same quarter. The naive decimal is the product of the single-leg prices. When the largest pair rho is above 0.15 and the price source is `leg_odds_naive`, the research decimal uses the book haircut: vigged independent probability plus 0.55 times the gap to the vigged copula. That decimal is not the displayed SGP price. The print stays unconfirmed. Do not add a stake weight.

The 2026 week-6 slate is unplayed. Model EV is not realized EV. The live Brier columns stay blank. The history Brier is the calibration key.
