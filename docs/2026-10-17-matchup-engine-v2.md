# Matchup engine v2, 2026-10-17

Do not type a ticket. Do not submit a bet. Do not commit this work unless you ask for a commit.

Six tokens pass both keys. Eight tokens fail. The passing tokens are in `LEGAL_MARKETS`. Canon C24 records the two-key gate.

The 2026 week-6 slate is unplayed. Model EV is not realized EV. These rows are not a bet.

## Verdict

The score file is `data/cache/matchup_ev.csv`. The history file is `data/cache/matchup_hist.csv`. The regime file is `config/matchup_regime_rho.json`.

Promoted tokens: `rec_yds_q3`, `rec_yds_q4`, `receptions_q4`, `pass_yds_q4`, `interceptions`, `total_q3`.

Withdrawn v1 tokens: `rec_longest`, `rush_longest`. The history key failed. `receptions_q1` stays out. `spreads_q3` and `spreads_q4` stay unscored. The spread sign is not locked.

Measured checks:

1. On `rec_yds_q3` and `rec_yds_q4`, a 0.5 line uses the compound Poisson-gamma hurdle. `P(Y = 0) = exp(-λ)`. The mean EV on 0.5 lines is below the mean EV on the other lines.
2. Every scored market has a history row and a live row.
3. Offense team equals book team on 0 of 598 scored legs. The prior run had 11 mismatches on 93 `rec_yds_q3` legs.
4. The scanner prints 256 qualified legs. Zero of those legs have `ev_after_vig <= 0`. The prior run printed 50 such legs out of 298.
5. Every stored regime rho is finite. `python3 -m pytest -q -W error::RuntimeWarning` passed 521 tests. A RuntimeWarning fails that command, so the copula matmul warning count is 0.

`calibration_warning=1`. Fifteen printed legs have EV above 0.45. The flag does not drop the leg. The thresholds stay locked.

## Two-key table

Live floors replace the old `N > 40` rule. A multi-player skill market needs `N_slate >= 35`. A single-starter market needs `N_slate >= 16`. A game-level market needs `N_slate >= 10`.

The history key uses settled play-by-play from 2023 through 2026 week 5. 2022 play-by-play is absent. Each player-game is scored at a point in time. The synthetic lines are the prior median and, for a zero-inflated prop, a 0.5 line. The benchmark price is -114/-114. `N_hist` is unique player-games, or games for `total_q3`. The two line scores are averaged inside the player-game. A pass needs `N_hist >= 250`, a Brier skill gain above 0, a bootstrap 95% CI lower bound above 0, and a Benjamini-Hochberg q-value at or below 0.10.

A cell below the live floor has a blank live q and reason `cardinality`. `q = 0.000500` means zero of 2000 bootstrap means were at or below 0. The formula is `(1 + count) / 2001`.

| Market | Signal | N slate | Mean EV | CI low | CI high | q | N hist | Delta Brier | Hist CI low | Hist CI high | Hist q | Verdict | Reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| rec_yds_q3 | q3_script | 92 | 0.098999 | 0.072883 | 0.125293 | 0.000500 | 11199 | 0.018150 | 0.016125 | 0.020227 | 0.001000 | pass | pass |
| rec_yds_q4 | q4_separation | 93 | 0.114101 | 0.088182 | 0.141813 | 0.000500 | 11291 | 0.010412 | 0.008843 | 0.011979 | 0.001000 | pass | pass |
| receptions_q4 | q4_separation | 131 | 0.152998 | 0.121251 | 0.185925 | 0.000500 | 11291 | 0.020942 | 0.019194 | 0.022684 | 0.001000 | pass | pass |
| rush_yds_q4 | q4_rush | 33 | 0.271919 | 0.195325 | 0.345608 | 0.000500 | 5496 | -0.005918 | -0.009013 | -0.002508 | 1.000000 | fail | no_brier_skill |
| pass_yds_q4 | q4_qb | 20 | 0.142791 | 0.076622 | 0.213756 | 0.000500 | 1689 | 0.068034 | 0.059872 | 0.076129 | 0.001000 | pass | pass |
| rec_longest | tail_rec | 89 | 0.198703 | 0.157822 | 0.241490 | 0.000500 | 6992 | -0.019479 | -0.023178 | -0.015926 | 1.000000 | fail | no_brier_skill |
| rush_longest | tail_rush | 41 | 0.285171 | 0.209305 | 0.358179 | 0.000500 | 3939 | -0.042786 | -0.049794 | -0.035357 | 1.000000 | fail | no_brier_skill |
| pass_longest | tail_pass | 20 | 0.375868 | 0.274264 | 0.475379 | 0.000500 | 1643 | -0.008656 | -0.018499 | 0.001074 | 1.000000 | fail | no_brier_skill |
| pass_attempts | funnel_volume | 22 | 0.341083 | 0.249016 | 0.431478 | 0.000500 | 1664 | -0.013399 | -0.024473 | -0.002057 | 1.000000 | fail | no_brier_skill |
| pass_completions | funnel_volume | 22 | 0.299352 | 0.194935 | 0.398374 | 0.000500 | 1664 | -0.010403 | -0.020474 | 0.000203 | 1.000000 | fail | no_brier_skill |
| interceptions | funnel_int | 21 | 0.071908 | 0.033356 | 0.112634 | 0.000500 | 1689 | 0.022747 | 0.018008 | 0.027686 | 0.001000 | pass | pass |
| field_goals | rz_stall | 1 | -0.017159 | -0.017159 | -0.017159 |  | 166 | 0.069267 | 0.048799 | 0.088222 |  | fail | too_few_hist |
| kicking_points | rz_stall | 0 |  |  |  |  | 166 | -0.007736 | -0.025699 | 0.010778 |  | fail | too_few_hist |
| total_q3 | q3_script_game | 13 | 0.124407 | 0.074016 | 0.180113 | 0.000500 | 824 | 0.014373 | 0.005832 | 0.023496 | 0.001000 | pass | pass |

`rush_yds_q4` clears the live floor and fails the history key. It stays out. `field_goals` and `kicking_points` have 166 history games. The floor is 250. The floor stays. The priced CSV has 0 `kicking_points` rows because the book posted Over only. The weather gate still drops outdoor kickers.

Live Brier columns stay blank. The games have no outcome. The history Brier is the calibration key.

## Hurdle

Quarter receiving yards (`rec_yds_q3`, `rec_yds_q4`) and quarter rushing and passing yards (`rush_yds_q4`, `pass_yds_q4`) use a compound Poisson-gamma hurdle. `receptions_q4` is a Poisson count on the same shrunk λ. A normal is not the price for those props.

`K_q` is Poisson with mean `λ_q`. The Empirical Bayes weight is `k = 12` opportunities. `n_opp` is the sum of quarter targets, carries, or dropbacks. A player with `n_opp` missing or at or below 0 is dropped. The old minimum of 4 prior games still applies.

Given `k >= 1`, positive yards are Gamma with shape `k · α` and rate `β`. The sum runs from `k = 1` to `k = 12`. Mass above 12 is omitted.

For a line at 0.5:

`P(Y > 0.5) = (1 - exp(-λ)) · P(Y >= 1 | K >= 1)`

`λ = 0` gives probability 0. The zero-yard share `p0` comes from prior play-by-play. It is not fit to the odds. It is not a second multiplier on λ.

The team table did not have a quarter completion rate. This run added `q3_completion_allowed`, `q4_completion_allowed`, and `q4_rush_ypc_allowed`. Yards-per-catch tilt runs only when both the NGS z-score and the defense z-score exist. Otherwise the tilt is 0 and the hurdle still prices the leg when λ exists.

| Market | N | N at 0.5 | Mean EV at 0.5 | N at other lines | Mean EV at other lines | 0.5 mean at or below the other mean |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| rec_yds_q3 | 92 | 41 | 0.068551 | 51 | 0.123478 | yes |
| rec_yds_q4 | 93 | 32 | 0.106075 | 61 | 0.118312 | yes |
| receptions_q4 | 131 | 108 | 0.153567 | 23 | 0.150331 | no, by 0.003236 |
| rush_yds_q4 | 33 | 6 | 0.323412 | 27 | 0.260477 | no |
| pass_yds_q4 | 20 | 0 |  | 20 | 0.142791 | no 0.5 line on the slate |

The named check is `rec_yds_q3` and `rec_yds_q4`. Both pass. `receptions_q4` still passes both keys. `half_line_majority` is not a blocker. `rush_yds_q4` fails history. The constants stay locked.

Colby Parkinson, Rams, `rec_yds_q4` Over 0.5 at +240:

| Run | Model probability | EV |
| --- | ---: | ---: |
| v1 normal | 0.763990 | 1.597567 |
| v2 hurdle | 0.518056 | 0.761389 |

His Q3 Over 0.5 at +195 has model probability 0.401207 and EV 0.183560. The Q4 EV is above 0.45, so the scanner warning is on. He has a long history, so `k = 12` moves λ only a little. The leg stays in the qualified list.

## Book team

The offense team is the book team when the book team is present. Personal rolling stats stay on the matched player. A blank book team can fall back to the feature team. A book team that is missing from the team table drops the leg.

Offense team equals the leg team on 598 of 598 scored legs. The 11 players from the prior mismatch now carry the book team on every scored leg:

| Player | Book team on the scored legs |
| --- | --- |
| Darnell Mooney | NYG |
| Marvin Harrison Jr. | HOU |
| Jahan Dotson | ATL |
| Jakobi Meyers | JAX |
| Kenneth Gainwell | TB |
| Dontayvion Wicks | PHI |
| Darren Waller | CAR |
| Keenan Allen | IND |
| DJ Moore | BUF |
| Kendrick Bourne | ARI |
| George Pickens | DAL |

The book label is the join key. This report does not replace a book label with a memory roster.

## Scanner

`matchup_scanner.py` prints a qualified leg only when `ev_after_vig >= 0.02`. This run prints `qualified=256`, `ev <= 0` count 0, `team_mismatch=0`, `calibration_warning=1`, and `jev=fail_closed`.

The default command does not construct a Jev client and does not start the Jev process. `--with-jev` with no fixture stays fail-closed. Compose and rank accept the same flag and print the route only when the flag is set.

## Regime rho

Residuals are same-player and same-game, from 2023 through 2026 week 5. 2022 is absent. One regime is assigned per player-game, in this order: `q4_trailing_comeback` (score margin entering Q4 below -7), else `q3_opening_surge` (team Q3 EPA per play above 0), else `explosive_light_box`, else `neutral`. The explosive rule is a 15-yard play with a defensive box of 6 or fewer when FTN charting joins, else a 20-yard play. FTN joins at 1.0 for 2023 through 2026. Cross-player rho was not estimated. `total_q3` is keyed by game, so its pairs with player markets are `psd_fill` with `n = 0`.

The matrix is projected to the nearest correlation with eigenvalue floor `1e-6`. `nearest_psd` uses `np.dot`. The file has 700 pairs. 261 are empirical. 439 are `psd_fill`. Every rho is finite. Pairs with fewer than 40 co-occurring residuals are not given an invented pre-projection number. After the projection, a missing pair can be `psd_fill` so the promoted block is populated.

`correlation.py` reads the regime file only after the full-game prior misses, and only when a stat is a matchup token. Full-game priors in `config/correlation_priors.json` stay in place. Compose does not gain a new pricer. Do not add a separate joint weight to the ticket stake. The default regime for an unplayed game is `neutral`.

Empirical rho for pairs of promoted markets:

| Pair | Neutral | Q3 opening surge | Q4 trailing comeback | Explosive light box |
| --- | --- | --- | --- | --- |
| rec_yds_q4, receptions_q4 | 0.869537 (n=51) | 0.823395 (n=4794) | 0.812500 (n=3542) | 0.812488 (n=2904) |
| rec_yds_q3, receptions_q4 | -0.187608 (n=47) | 0.022101 (n=4698) | 0.053233 (n=3423) | 0.022149 (n=2814) |
| rec_yds_q3, rec_yds_q4 | -0.184266 (n=47) | 0.020419 (n=4698) | 0.056929 (n=3423) | 0.005854 (n=2814) |
| interceptions, pass_yds_q4 | 0, psd_fill, n=0 | 0.111773 (n=717) | 0.123773 (n=528) | 0.037605 (n=437) |

Neutral full-game examples, same player: `rec_yds` with `rec_yds_q3` is 0.519366 (n=49). `rec_yds` with `rec_yds_q4` is 0.381693 (n=50). Full-game residuals use a marginal point-in-time model with adjustment 0. They are not a second promotion gate.

## Same-player joint, neutral regime

These pairs are both qualified on the live slate (`ev >= 0.02`) and share a player. The joint is the exact Gaussian-copula probability of the two chosen sides under neutral rho. It is a report number. It is not a displayed ticket price. It is not a bet.

| Player | Leg A | Leg B | Rho | Independent | Joint |
| --- | --- | --- | ---: | ---: | ---: |
| Keenan Allen | rec_yds_q4 over 5.5 at -115, EV 0.454813 | receptions_q4 over 0.5 at -170, EV 0.341983 | 0.869537 | 0.657504 | 0.750423 |
| Parker Washington | rec_yds_q4 under 10.5 at -110, EV 0.410927 | receptions_q4 under 1.5 at -210, EV 0.301697 | 0.869537 | 0.651697 | 0.729128 |
| Isaiah Likely | rec_yds_q4 under 9.5 at -115, EV 0.300849 | receptions_q4 under 1.5 at -150, EV 0.438757 | 0.869537 | 0.600655 | 0.686398 |
| KC Concepcion | rec_yds_q4 under 7.5 at -115, EV 0.284790 | receptions_q4 under 1.5 at -210, EV 0.287248 | 0.869537 | 0.599255 | 0.680028 |
| Davante Adams | rec_yds_q4 over 5.5 at -115, EV 0.304265 | receptions_q4 over 0.5 at -150, EV 0.306102 | 0.869537 | 0.546705 | 0.665854 |
| Michael Wilson | rec_yds_q4 under 13.5 at -115, EV 0.321694 | receptions_q4 under 1.5 at -115, EV 0.365256 | 0.869537 | 0.516254 | 0.648734 |
| Tetairoa McMillan | rec_yds_q4 under 11.5 at -115, EV 0.232232 | receptions_q4 under 1.5 at -200, EV 0.193307 | 0.869537 | 0.524340 | 0.639115 |
| Trey McBride | rec_yds_q4 under 16.5 at -115, EV 0.201197 | receptions_q4 under 2.5 at -170, EV 0.324291 | 0.869537 | 0.535725 | 0.632905 |

Leg EV, rho, and the joint come from `data/cache/matchup_legs.csv` and the neutral regime file. The joint is not a ticket price.

## Top qualified legs

The pool is promoted markets with `ev >= 0.02`. There are 132 legs at line 0.5 and 124 legs at line 1.5 or higher.

### Line 0.5

| Player | Team | Market | Side | Line | Price | Model p | EV |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| KaVontae Turpin | DAL | receptions_q4 | over | 0.5 | 325 | 0.428639 | 0.821717 |
| Colby Parkinson | LAR | receptions_q4 | over | 0.5 | 230 | 0.543847 | 0.794695 |
| Colby Parkinson | LAR | rec_yds_q4 | over | 0.5 | 240 | 0.518056 | 0.761389 |
| Jerry Jeudy | CLE | receptions_q4 | over | 0.5 | 170 | 0.623637 | 0.683820 |
| Cole Kmet | CHI | receptions_q4 | over | 0.5 | 210 | 0.527086 | 0.633965 |
| Omarion Hampton | LAC | receptions_q4 | over | 0.5 | 220 | 0.505842 | 0.618694 |
| Noah Fant | NO | receptions_q4 | over | 0.5 | 170 | 0.573099 | 0.547367 |
| Brian Thomas Jr. | JAX | rec_yds_q3 | over | 0.5 | 175 | 0.559624 | 0.538967 |
| Davis Allen | LAR | receptions_q4 | over | 0.5 | 375 | 0.323970 | 0.538856 |
| Blake Corum | LAR | receptions_q4 | over | 0.5 | 325 | 0.357584 | 0.519732 |
| Dalton Kincaid | BUF | receptions_q4 | under | 0.5 | 170 | 0.560155 | 0.512417 |
| Calvin Ridley | TEN | receptions_q4 | over | 0.5 | 165 | 0.566155 | 0.500310 |
| Ted Hurst III | TB | receptions_q4 | over | 0.5 | 180 | 0.500901 | 0.402524 |
| Antonio Williams | WAS | receptions_q4 | over | 0.5 | -110 | 0.731716 | 0.396913 |
| Luther Burden III | CHI | receptions_q4 | under | 0.5 | 160 | 0.535025 | 0.391065 |

### Line 1.5 or higher

| Player | Team | Market | Side | Line | Price | Model p | EV |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| Matthew Stafford | LAR | pass_yds_q4 | over | 52.5 | -115 | 0.802077 | 0.499535 |
| Isaiah Likely | NYG | rec_yds_q3 | under | 7.5 | -110 | 0.778182 | 0.485620 |
| Keenan Allen | IND | rec_yds_q4 | over | 5.5 | -115 | 0.778156 | 0.454813 |
| Isaiah Likely | NYG | receptions_q4 | under | 1.5 | -150 | 0.863254 | 0.438757 |
| Tyler Shough | NO | pass_yds_q4 | over | 58.5 | -115 | 0.755823 | 0.413061 |
| Parker Washington | JAX | rec_yds_q4 | under | 10.5 | -110 | 0.739057 | 0.410927 |
| Tre Tucker | LV | rec_yds_q3 | under | 4.5 | -115 | 0.738573 | 0.380811 |
| Matthew Golden | GB | rec_yds_q3 | under | 10.5 | -115 | 0.733036 | 0.370458 |
| Michael Wilson | ARI | receptions_q4 | under | 1.5 | -115 | 0.730253 | 0.365256 |
| Trevor Lawrence | JAX | pass_yds_q4 | under | 55.5 | -115 | 0.725823 | 0.356973 |
| Brock Bowers | LV | rec_yds_q3 | under | 14.5 | -115 | 0.717889 | 0.342140 |
| PHI vs CAR total | PHI | total_q3 | over | 7.5 | 105 | 0.648224 | 0.328858 |
| Drake London | ATL | rec_yds_q3 | under | 16.5 | -115 | 0.710139 | 0.327652 |
| Trey McBride | ARI | receptions_q4 | under | 2.5 | -170 | 0.833813 | 0.324291 |
| Michael Wilson | ARI | rec_yds_q4 | under | 13.5 | -115 | 0.706952 | 0.321694 |

## Shared cache

`--feature-cache` defaults to `/Users/claudiobarone/Projects/CeminiDFS/data/shared_cache/2026_w06` when that directory contains the three parquet files. This run resolved that directory. Status is `ready`. The scanner loads the frames read-only and does not write to CeminiDFS.

The score still uses the local point-in-time CSV. The parquet frames are not joined into λ or EV. The published player file has no injury-vacuum column. `game_context_pit.parquet` does contain `referee_dpi_z` and `referee_holding_z`. Those z-scores are not applied to the price. A later join would move the locked table, so this run does not add one.

Manifest: season 2026, week 6, max source week 5. Shapes: player 990 by 45, defense 32 by 14, game context 14 by 14.

## Lag scanner

Elasticity is locked. `rec_yds_q3` and `rec_yds_q4` use 0.25 of full-game receiving yards. `rec_longest` uses 0.20. `rush_longest` uses 0.20 of rushing yards. `pass_completions` uses 1/12 of passing yards. `total_q3` uses 0.25 of the full-game total. A flag needs an anchor move of at least 2.0 yards or points, or an implied-probability move of at least 0.04, while the derivative moves less than 35% of the theoretical move, and the current leg has EV of at least 0.02.

The two captures are the original priced CSV and the expanded priced CSV. Both runs wrote the same file. `flag_count=0`. The file is `data/cache/matchup_lag.csv` and it has a header only.

Of the derivative main lines present in both captures, 199 had a previous derivative and a previous anchor. Zero of those anchors moved by 2.0 or by 0.04 implied probability. 181 current derivative mains had no paired previous row. The expanded capture added markets. The shared main lines did not move enough to flag.

## Commands

Feature build, run twice. The two CSVs matched. Stdout:

```text
target=2026-w6 players=1037 teams=32 ftn_join={'2023': 1.0, '2024': 1.0, '2025': 1.0, '2026': 1.0} missing=[] absent_2022=yes
```

```text
python3 -m ceminiparlays.matchup_features --players /tmp/matchup_players_a.csv --teams /tmp/matchup_teams_a.csv
python3 -m ceminiparlays.matchup_features --players /tmp/matchup_players_b.csv --teams /tmp/matchup_teams_b.csv
```

Official copies: `data/cache/matchup_players_2026w06.csv`, `data/cache/matchup_teams_2026w06.csv`.

History and rho, each under `-W error::RuntimeWarning`, exit 0. History, rho, and stdout were byte-identical across the pair. Stderr prints one week label per week and is not part of the identity check.

```text
python3 -W error::RuntimeWarning -m ceminiparlays.matchup_calibrate --hist /tmp/matchup_hist_b.csv --rho /tmp/matchup_rho_b.json
python3 -W error::RuntimeWarning -m ceminiparlays.matchup_calibrate --hist /tmp/matchup_hist_c.csv --rho /tmp/matchup_rho_c.json
```

Stdout:

```text
absent_2022=yes rec_yds_q3=11199:hist_pass rec_yds_q4=11291:hist_pass receptions_q4=11291:hist_pass rush_yds_q4=5496:no_brier_skill pass_yds_q4=1689:hist_pass rec_longest=6992:no_brier_skill rush_longest=3939:no_brier_skill pass_longest=1643:no_brier_skill pass_attempts=1664:no_brier_skill pass_completions=1664:no_brier_skill interceptions=1689:hist_pass field_goals=166:too_few_hist kicking_points=166:too_few_hist total_q3=824:hist_pass hist_pass=rec_yds_q3,rec_yds_q4,receptions_q4,pass_yds_q4,interceptions,total_q3
```

Live score, run twice. EV, legs, and stdout were byte-identical.

```text
python3 -m ceminiparlays.matchup_score --lines data/cache/hardrock_nfl_20261018_expanded.csv --players data/cache/matchup_players_2026w06.csv --teams data/cache/matchup_teams_2026w06.csv --hist data/cache/matchup_hist.csv --out /tmp/matchup_ev_a.csv --legs /tmp/matchup_legs_a.csv
python3 -m ceminiparlays.matchup_score --lines data/cache/hardrock_nfl_20261018_expanded.csv --players data/cache/matchup_players_2026w06.csv --teams data/cache/matchup_teams_2026w06.csv --hist data/cache/matchup_hist.csv --out /tmp/matchup_ev_b.csv --legs /tmp/matchup_legs_b.csv
```

The last stdout line is:

```text
promoted=rec_yds_q3,rec_yds_q4,receptions_q4,pass_yds_q4,interceptions,total_q3
```

Scanner, run twice. Stdout, EV, and legs were byte-identical. Scanner EV matched `data/cache/matchup_ev.csv`.

```text
python3 -m ceminiparlays.matchup_scanner --out /tmp/scan_ev_a.csv --legs /tmp/scan_legs_a.csv
python3 -m ceminiparlays.matchup_scanner --out /tmp/scan_ev_b.csv --legs /tmp/scan_legs_b.csv
```

```text
feature_cache=ready
qualified=256
promoted=rec_yds_q3,rec_yds_q4,receptions_q4,pass_yds_q4,interceptions,total_q3
jev=fail_closed
calibration_warning=1
team_mismatch=0
```

Lag scanner, run twice. The CSV and the stdout were byte-identical.

```text
python3 -m ceminiparlays.lag_scanner --prev-capture data/cache/hardrock_nfl_20261018.csv --curr-capture data/cache/hardrock_nfl_20261018_expanded.csv --legs data/cache/matchup_legs.csv --out /tmp/matchup_lag_a.csv
python3 -m ceminiparlays.lag_scanner --prev-capture data/cache/hardrock_nfl_20261018.csv --curr-capture data/cache/hardrock_nfl_20261018_expanded.csv --legs data/cache/matchup_legs.csv --out /tmp/matchup_lag_b.csv
```

```text
flag_count=0
```

This turn compared the official files to the stored run copies. History, rho, EV, legs, and scanner EV still match.

Checks this turn:

```text
python3 -m ruff check src tests
```

```text
All checks passed!
```

```text
python3 -m pytest -q -W error::RuntimeWarning
```

```text
521 passed in 3.17s
```

`opencode models` still lists `opencode/glm-5.3-flash-free`. No paid model was substituted. This continuation did not start a second GLM run. GLM already wrote `feature_cache.py`, `lag_scanner.py`, and the three unit modules `tests/test_feature_cache.py`, `tests/test_lag_scanner.py`, and `tests/test_book_team.py`.

## Executors

| Work | Executor |
| --- | --- |
| Hurdle, Empirical Bayes, history Brier gate, regime rho, PSD fix | primary |
| `LEGAL_MARKETS`, Canon C24, live score, scanner EV gate, `--with-jev` | primary |
| Book-team join, `--feature-cache` reader, `lag_scanner.py`, their unit tests | `opencode/glm-5.3-flash-free` |

The v1 report stays at `docs/2026-10-17-matchup-engine.md`. This file does not replace it.
