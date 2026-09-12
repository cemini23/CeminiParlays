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

## 2026-09-12 super-audit

Verdict was **REWORK**; the P0 patch set landed as v0.1.1. Issue catalog from
`briefs/2026-09-12_ceminiparlays-preslate-super-audit.md`:

| ID | Status | Note |
|----|--------|------|
| I-01 | fixed | per-row `slip_multiplier` now prices the combo (`row` source beats CLI) |
| I-02 | fixed | correlation prior matches an exact unordered stat pair, not a set |
| I-03 | fixed | every skip is named in the exclusion block |
| I-04 | fixed | blank team/opp is invalid; no `unknown:` teams are minted |
| I-05 | fixed | exact Gaussian joint for Power 2–3 legs; `p_joint_se` from MC only |
| I-06 | fixed | OUT tokens scratch; FLAG tokens warn without a haircut |
| I-07 | fixed | table-only multipliers print `UNCONFIRMED TABLE MULTIPLIER` |
| I-08 | fixed | one-sided book odds drop the leg instead of falling through |
| I-09 | fixed | integer Poisson push is void mass; grader voids `actual == line` |
| I-10 | fixed | same-player multi-stat slips rejected in v1 |
| I-11 | fixed | Flex Kelly suppressed (`na (flex proxy suppressed)`) |
| I-12 | fixed | missing payout rows raise an operator-readable sentence |
| I-13 | fixed | alt `line_type` without an M is excluded (`alt-needs-m`) |
| I-14 | fixed | per-combo row M overrides the global CLI M; conflicts skip |
| I-15 | fixed | Flex partials stay July tables and say `flex_partials=table` |
| I-16 | fixed | Poisson with `sigma > 0` prints `poisson_sigma_ignored` |
| I-17 | fixed | `--max-slips` exposed; >20k combos abort unless `--allow-large-enum` |
| I-18 | fixed | `config/` copied to `ceminiparlays/data/`; loads off-repo |
| I-19 | fixed | `displayed_multiplier is not None`; `<= 0` rejected |
| I-20 | fixed | scratch/`questionable` warnings render on the card |
| I-21 | fixed | power de-vig retries `[0.05, 32]`, then says it could not bracket k |
| I-22 | open | same-team 2-legs still excluded by the two-team rule |
| I-23 | fixed | `corr_repaired=yes` plus the repaired matrix row is printed |
| I-24 | fixed | optional `book_line` column; a mismatch drops the leg |
| I-25 | fixed | card prints EV and `EV_lo`; rank sorts by lower bound then EV |
| I-26 | fixed | `lines= / live= / dropped= / scratched=` summary, strict exit 2 |
| I-27 | fixed | `questionable` / `limited` are flagged for a human decision |
| I-28 | fixed | `devig` prints all three methods and `UNSTABLE_DEVIG` over 1.5pp |
| I-29 | noted | lognormal CV still uses the median as a v1 proxy (no formula change) |
| I-30 | fixed | `--shade-pp` subtracts from every fair P before the copula |
| I-31 | fixed | `p_over_at_median` diagnostic on fair cards and slip rows |
| I-32 | fixed | README documents the strict workflow; example ranks Cook, lists Pacheco |
| I-33 | fixed | grader voids pushes and steps down to the smaller payout row |
| I-34 | noted | taxes, finite-horizon Kelly, and promos are out of model |
| I-35 | **rejected** | HY3's "Kelly net vs gross" finding is false; `kelly.py` is correct |

**Integer-line void.** A lounge integer line is a three-way event
(over / push / under). v1 keeps `p_push` separate, never folds it into Under, and
excludes integer lines unless `--allow-integer-lines` is passed. The grader
treats `actual == line` as a void: it drops the leg, pays the smaller table row
when one exists, and otherwise refunds the stake.

**Out-of-model.** The printed quarter Kelly is an upper bound. It ignores taxes,
promotions / profit boosts, and the finite horizon of a real bankroll. Do not
treat the printed fraction as a sizing instruction; the operator sets stakes.

**Lognormal CV.** `sigma / median` is used as if the median were the mean (I-29).
Changing it would shift every yard probability, so it is documented rather than
silently repriced this pass.
