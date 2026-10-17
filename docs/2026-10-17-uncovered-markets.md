# Uncovered markets, 2026-10-17

Do not type a ticket. Do not submit a bet. No market enters `LEGAL_MARKETS`.

`receptions_q1` is the only market that clears the locked numeric rule. The other nine fail. The token stays out of `LEGAL_MARKETS`. One leg moves the CI lower bound to or below zero. 21 of the 25 legs are a line of 0.5. The scorer uses a normal. `fair.py` prices a low count as Poisson.

## Verdict

| Market | Legs | Mean EV | 95% CI low | 95% CI high | Cluster CI low | Cluster CI high | Verdict | Reason |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| pass_yds_h1 | 6 | 0.104931 |  |  |  |  | fail | too_few_legs |
| rush_yds_h1 | 8 | 0.080041 |  |  |  |  | fail | too_few_legs |
| rec_yds_h1 | 9 | 0.178619 |  |  |  |  | fail | too_few_legs |
| receptions_h1 | 15 | 0.088102 |  |  |  |  | fail | too_few_legs |
| pass_yds_q1 | 5 | 0.079198 |  |  |  |  | fail | too_few_legs |
| rush_yds_q1 | 8 | 0.153399 |  |  |  |  | fail | too_few_legs |
| rec_yds_q1 | 14 | 0.235427 |  |  |  |  | fail | too_few_legs |
| receptions_q1 | 25 | 0.078857 | 0.007329 | 0.153857 | 0.013678 | 0.135743 | pass |  |
| team_total_h1 | 6 | 0.093983 |  |  |  |  | fail | too_few_legs |
| total_h1 | 1 | -0.039802 |  |  |  |  | fail | too_few_legs |

The reproduce command is below. A blank CI cell means the market had fewer than 20 legs, so the CI was not used.

## Reproduce

```text
python3 -m ceminiparlays.half_edge score \
  --lines data/cache/hardrock_nfl_20261018.csv \
  --shares data/cache/half_shares.csv \
  --out data/cache/half_edge_ev.csv
```

Output:

```text
ngs_player_rows=1185
ngs_attached=620
dropped_unmatched=28
dropped_no_split=491
dropped_no_full_line=0
dropped_tie=0
dropped_no_price=0
market,n_legs,mean_ev,ci_low,ci_high,cluster_ci_low,cluster_ci_high,verdict,reason
pass_yds_h1,6,0.104931,,,,,fail,too_few_legs
rush_yds_h1,8,0.080041,,,,,fail,too_few_legs
rec_yds_h1,9,0.178619,,,,,fail,too_few_legs
receptions_h1,15,0.088102,,,,,fail,too_few_legs
pass_yds_q1,5,0.079198,,,,,fail,too_few_legs
rush_yds_q1,8,0.153399,,,,,fail,too_few_legs
rec_yds_q1,14,0.235427,,,,,fail,too_few_legs
receptions_q1,25,0.078857,0.007329,0.153857,0.013678,0.135743,pass,
team_total_h1,6,0.093983,,,,,fail,too_few_legs
total_h1,1,-0.039802,,,,,fail,too_few_legs
```

The same command a second time writes the same stdout and the same CSV.

Parse the same capture twice:

```text
python3 -m ceminiparlays.hardrock_book parse \
  --capture data/cache/hardrock_nfl_20261018.json \
  --rows data/cache/hardrock_nfl_20261018.csv \
  --inventory data/cache/market_inventory.csv
```

A second parse of that JSON writes the same CSV bytes. `cmp` matched on 2026-10-17.

Pytest:

```text
python3 -m pytest -q
```

```text
488 passed, 9 warnings in 2.89s
```

The nine warnings are the existing copula matrix warnings in `src/ceminiparlays/copula.py`. `ruff check src tests` passed.

## What was scored

The rule was locked in `src/ceminiparlays/half_edge.py` before the score.

Train on nflverse regular-season plays with `game_date` before 2026-10-18. That includes 2025 and 2026 through the Thursday game on 2026-10-15. It does not include the Sunday slate. Half is `qtr` in {1, 2}. Quarter 1 is `qtr == 1`. A game counts only when the full stat clears the floor: pass yards 50, rush yards 15, receiving yards 15, receptions 2, team points 1. The share is the unweighted mean of game shares. Shrink uses k = 8 toward the unweighted league mean of those game shares. A split is real when `n >= 8` and the shrunk share is farther from the league share than the standard error. The side is the sign of `model mean - posted line`. EV is `p_side * decimal(posted American) - 1`. The leg bootstrap uses `random.Random(20261017)`. The game-cluster bootstrap uses `random.Random(20261018)`. Each uses 2000 draws. A market needs 20 legs, a positive mean, a leg CI lower bound above 0, and a cluster CI lower bound above 0.

Only the ten markets in the table were scored. Half 2, quarters 2 to 4, spreads, moneylines, and alternate ladders were captured and not scored.

NGS weekly means are on the share file. 620 of 1185 player rows have one. The scorer does not read them. There is no rushing NGS file. Jev was not called. `half_edge.py` does not import `jev_client`. `jev_gate` is unchanged and still fails closed.

## Capture

`data/cache/hardrock_nfl_20261018.json` is the board. The stamp argument was `--captured-at 2026-10-17T23:40:00Z`. The file has 13 NFL events and 295 market types. The priced slate is `data/cache/hardrock_nfl_20261018.csv` (34,231 rows). The row shape is `SLATE_FIELDS`.

The read that returned prices was:

- `GET https://api.hardrocksportsbook.com/sportsbook/v1/api/getRootLadder`
- `GET https://api.hardrocksportsbook.com/java-graphql/competitions/2295257447167426824/events`
- `GET https://api.hardrocksportsbook.com/java-graphql/operation/GetEvents`

Channel `FLORIDA_ONLINE`. Segment `FL`. No login. No `placeBets`.

## Inventory

`data/cache/market_inventory.csv` has one row per book type and period. Feed is `hardrock_getevents`. Feed status is `live` for every row, because this capture holds the market.

| repo_gate | Count | Meaning |
| --- | ---: | --- |
| covered | 1 | Full-game moneyline. One market per game. The token is already legal. |
| partial | 36 | A legal full-game token posted as a ladder. The Odds API client requests one line. |
| absent | 258 | A period market, or a type `LEGAL_MARKETS` does not name. |

`odds_api` is `absent` on 288 rows and `not_fetched` on 7. `not_fetched` means `MARKET_TO_STAT` has a full-game key and this capture did not call The Odds API. It does not mean that feed posted a half line or an alternate line.

## Book API wrappers

License is the GitHub license field read on 2026-10-17. It was null for each repo. That is "no license file". Endpoints are the URLs in the cited file. They are not guessed.

| Repo | License | Endpoint in the source | Used for this capture |
| --- | --- | --- | --- |
| [derekcnursey/codex_hoops-edge](https://github.com/derekcnursey/codex_hoops-edge) `src/hrb_odds.py` | no license file | `GET https://api.hardrocksportsbook.com/sportsbook/v1/api/getRootLadder` | Yes. Ladder. |
| same file | no license file | `GET https://api.hardrocksportsbook.com/sportsbook/v1/api/whatsMySegment` | No. |
| same file | no license file | `GET https://api.hardrocksportsbook.com/sportsbook/api/public/events/tree` | No. |
| same file | no license file | `POST https://api.hardrocksportsbook.com/java-graphql/graphql` | No. A trivial POST returned HTTP 400 on 2026-10-17. |
| [Hurteau101/DifferentOdds-API-V2](https://github.com/Hurteau101/DifferentOdds-API-V2) `Books/SGP/hardrock_sgp.py` | no license file | `wss://api.hardrocksportsbook.com/websocket` with `BetslipBuilderRequest` | No. A slip request is out of scope. |
| [super-phantom91/SpringBoot_MongoDB_MySQL_Chat](https://github.com/super-phantom91/SpringBoot_MongoDB_MySQL_Chat) `CustomWebSocketService.java` | no license file | `wss://api.hardrocksportsbook.com/graphql-ws` | No. The file also contains proxy credentials. They were not copied. |

The app bundle `https://app.hardrock.bet/dist/bundle.3.42.14235.js` returned HTTP 200 on 2026-10-17. It names `GET /java-graphql/operation/GetEvents`. That GET is the price path.

## Proposed gate change

Not applied.

```python
PERIOD_STATS = frozenset({"receptions_q1"})
LEGAL_MARKETS = frozenset(YARDS_STATS | TD_STATS | COUNT_STATS | GAME_STATS | PERIOD_STATS)
```

Do not apply it on this evidence. Drop the single highest leg (over 1.5 at +145, EV 0.443). The other 24 legs have mean EV 0.063685. The same leg bootstrap then has a lower bound of -0.002724. That check is not a second gate. It shows the pass is one leg. `tests/test_hardrock_book.py` keeps `receptions_q1` illegal.

## Executors

`opencode/glm-5.3-flash-free` is listed and is free. It was not used. No paid model was substituted. The price parser was already in the tree. The join thresholds are the signal. A second writer on the price path would fork the evidence.

| Phase | Executor |
| --- | --- |
| P0 inventory | This session. Census is in `hardrock_book.py`. |
| P1 parser and capture | This session. The module was already started. |
| P2 join | This session. `half_edge.py shares` writes `data/cache/half_shares.csv`. |
| P3 signal | This session. Rules are the module docstring. |
| P4 EV verdict | This session. |
| P5 tests and canon | This session. Canon C3 now allows the public read and still bans HTML scrape and submit. |
| P6 Jev | Not run. The rate model stays in Python. |

## Residual risk

The sample is one upcoming slate. It is not a multi-week closing-line backtest. The leg bootstrap treats legs as exchangeable. The cluster bootstrap groups legs by kickoff and the two teams. Eight failing markets have a positive point estimate and fewer than 20 legs. The rule does not let those means enter the gate. Team and game totals mostly fail the split test because a half of points sits near half of the game. 28 priced period rows did not match a player. 491 matched a player and failed the split test. No full-game main line was missing for a scored row.

Do not type a ticket from this file.
