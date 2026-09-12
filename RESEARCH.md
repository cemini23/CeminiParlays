# CeminiParlays research notes (2026-09-12)

v1 follows Fable verdict **C′**: K147 CLI surface + offline Gemini math. No live polling.

## Internal

| Source | Keep |
|--------|------|
| Gambling wiki K147 architecture + pipeline spec | `fair` / `rank` / `grade`; `edges.csv`; Underdog first |
| `briefs/2026-09-12_ceminidfs-lessons-pickem-parlay-cli.md` | Stages, CSV contract, operator submits, copula not product, injury as a human gate |
| Wiki payout pages | UD 2-leg Standard **3.5×**; PP Power **3×** |
| Wiki legal page | Local CLI **GO**. Scrapers and auto-submit **NO-GO** |
| Underdog entity page | Lounge **does** shift multipliers on correlated legs — prefer displayed M |
| OSINT Kalshi parlay pages | Different product (PM RFQ). Do not mix into this CLI |
| CCC license rules | MIT LICENSE file required. Reject no-LICENSE scrapers |
| Cyber wiki | No overlap |

## Gemini deep research (desktop docx)

Keep: power/additive/multiplicative de-vig, Gaussian copula + nearest PSD, Flex EV, quarter Kelly, void/push as later work.

Cut: 5–30s lounge polling, Textual live TUI, MILP solver, Polars/DuckDB/msgspec, clipboard-as-submit.

Gemini used PP 3× as the 2-leg example. That is PrizePicks, not Underdog.

## External

Paid market: Unabated, BettingPros, Upside, OddsJam, PickLabs, SmartStake. No quality MIT CLI.

GitHub hits are scrapers or salary-cap DFS (`draftfast`). Extract math ideas only. Do not vendor.

OpenCLI + Brave social scan:

- Reddit: +EV = de-vig sharp books vs lounge breakeven. 2-pick Power on PP is a hard price. Flex insurance is better near breakeven. QB+WR stacks are the common correlation story. Settlement disputes are common (void/DNP).
- YouTube: OddsJam / Unabated / "beat PrizePicks with math" funnels. Same math: line vs consensus, not locks.
- X: promo slips and +EV screenshots. No open CLI to copy.

## v1 product bar

Working tested public repo. Manual CSV in. `edges.csv` + report out. CI on 3.11 and 3.12. No network imports.
