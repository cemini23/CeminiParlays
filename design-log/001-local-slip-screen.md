# 001 — Local slip screen

## Decisions for the Implementer

- Build 200 annotated slips before any model call. The sample date is 2026-11-01.
- The screen describes a slip. The operator decides. Nothing in this system acts.
- No output path connects to a bet-submission surface.
- Do not wire LiquidAI/d1-2B into `slip-screen` until an accuracy file covers these 200 slips.
- Quote odds and lines by token index. The value is `text[start:end]`.
- Do not add a scoring weight or a cutoff. Do not edit `jev_gate.py`, `jev_sizing.py`, or `jev_client.py`.
- Do not depend on `jkrup/jeveryword`. Do not send slip text to a remote model.
- Do not send a slip image anywhere.

## Background

The v10.10 batch routes LiquidAI/d1-2B to a local slip screen and names that screen a "jev-gate". That name can be read as a decision to place a bet. The existing Jev gate marks a composed card. It is a different command. The new screen reads pasted slip text and returns facts.

d1-2B is a 1.92B single-pass decision model. The card documents Transformers `trust_remote_code=True` at version 5.19 or later. It is not a chat model. The published card has no benchmark on sportsbook slip text.

The numbered-token pattern comes from jeveryword. The upstream package calls a remote model with `TYPESAFE_API_KEY`. The repo had four stars. The pattern stays. The package does not.

The design-log methodology is the working method for this file. On 2026-11-01 the upstream `LICENSE` file is MIT, copyright 2026 Yoav Abrahami. The upstream README does not state a licence. No upstream rule file is copied into this repo.

The LFM Open License v1.0 allows commercial use below $10,000,000 annual revenue. A copy of that licence sits at `third_party/LiquidAI-d1-2B/LICENSE`. The model repo had no NOTICE file on 2026-11-01. Weights are not vendored.

## Problem

A generated odds token can turn `-110` into `-115` and still look plausible. A slip screen that emits a risk band with no measured accuracy looks like a decision. A remote extractor sends the slip off the machine.

## Prior Art

- `american_to_implied` in `src/ceminiparlays/odds.py` already turns one American integer into an implied probability. The screen parses a verbatim token with that function. It does not add a second price formula.
- `jev-gate` in `src/ceminiparlays/cli.py` marks a structured card. It does not read free slip text. Extending it would mix a marker with a text screen, so the null hypothesis fails for a new command and holds for the gate itself.
- `jev_sizing.py` already owns stake cutoffs. A new cutoff would decide a stake. Ban 1 forbids that. No new scoring parameter is added.
- `tests/test_no_network.py` allows HTTP only in `odds_api.py`, `jev_client.py`, and `hardrock_book.py`. The new modules stay off that list.
- `STANDARD_DISCLAIMER` in `src/ceminiparlays/__init__.py` already says the operator types the ticket. The screen repeats the boundary on its own output.

## Questions and Answers

Q: Can the live screen use the annotation rubric when the model is absent?
A: No. The rubric labels the frozen sample only. A live band without a measured rate is withheld.

Q: Does a measured rate of 0/200 still print the band?
A: Yes. The rate is printed on the same line. The band is a description. It does not block or permit a bet.

## Design

The metric is per-field exact match on the 200 slips.

| Field | Exact match means |
| --- | --- |
| `leg_count` | The choice label equals the gold label. |
| `markets` | The ordered market tuple equals the gold tuple. |
| `correlation` | The choice is `independent`, `same_game`, or `same_player`. |
| `risk_band` | The score legend equals the gold band. |
| `implied_probability` | `format(american_to_implied(parsed token), ".10f")` equals the gold string. |
| `quoted_odds` | Each odds span value equals the gold value and `text[start:end] == value`. |
| `quoted_lines` | Same invariant for each line span. |

The sample is 200 constructed slips dated 2026-11-01. There is no live-book date range. The risk rubric, first match wins, is: `long` when the leg count is 5 or more; else `same_player`; else `same_game`; else `short_stack` when the leg count is 3 or 4; else `plain`. That rubric is the annotation definition. It is not a runtime weight.

Parameters that may change in this campaign: none.
Files that may not change: `jev_gate.py`, `jev_sizing.py`, `jev_client.py`, and the body of `american_to_implied`.

`slip-screen` without a valid accuracy file prints the boundary, prints `risk_band withheld`, and does not load the model.
`slip-screen-measure` is the only command that loads LiquidAI/d1-2B. It writes the accuracy file. It does not place a bet.

## Implementation Plan

1. Freeze this log.
2. Add the 200-slip annotation and the numbered-token extractor.
3. Add the screen with an injected evaluator.
4. Keep the model unwired until a real d1 accuracy file exists.
5. Append results. Do not edit the frozen section above.

## Examples

A returned price is accepted only when `text[start:end]` is that price.
A risk line is `risk_band same_game exact_match=140/200` or `risk_band withheld`.

## Trade-offs

The 200 slips are constructed text with hand-set labels. They prove the metric and the slice invariant. They are not a sportsbook benchmark. The model card still has no slip-text number until `slip-screen-measure` is run on this machine.

## Verification

- The annotation file has 200 slips, and every gold span satisfies the slice invariant.
- A scripted evaluator scores 100% and still cannot unlock the risk band, because its model id is not `LiquidAI/d1-2B`.
- A choice that is not an index raises.
- An index that points at `board -110` returns `-110`, not the gold parlay price.
- `slip-screen` without accuracy exits 2 and does not load the model.

<!-- FROZEN 2026-11-01. Do not edit the section above this line. -->

## Implementation Results

2026-11-01. No deviation from the frozen section.

The annotated sample is `tests/fixtures/slip_screen/annotated.json`. It holds 200 slips. The builder and the file match. Every gold span satisfies `text[start:end] == value`.

`span_from_indices` in `src/ceminiparlays/numbered_span.py` builds the slice. `extract_span` asks two choice questions. A choice that is not an index raises. An index that points at the board token `-110` returns `-110`.

`slip-screen` prints the boundary and `risk_band withheld` when the accuracy file is missing or the model id is not `LiquidAI/d1-2B`. That path does not load the model.

`slip-screen-measure` is the loader. This environment has no `torch` and no `transformers`, so the d1-2B exact-match rates are not measured. The risk band stays withheld. A scripted evaluator scores every field exact on the 200 slips. Its model id is `gold-script`, so it cannot unlock the band.

No scoring parameter was added. `jev_gate.py`, `jev_sizing.py`, and `jev_client.py` were not edited.

The LFM licence is copied at `third_party/LiquidAI-d1-2B/LICENSE`. The model repo had no NOTICE file. Weights are not in the tree.

Local `pytest -q`: 605 passed. `ruff check src tests`: clean.
