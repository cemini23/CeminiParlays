# Matchup engine, 2026-10-17

Do not type a ticket. Do not submit a bet.

Four cells pass the locked rule. Ten cells fail. The passing tokens are now in `LEGAL_MARKETS`. Canon C24 records the rule.

The largest printed prices are 0.5-yard overs at plus money. A normal has no mass at zero. Model EV is not realized EV. The slate is unplayed. These rows are not a bet.

## Verdict

The score file is `data/cache/matchup_ev.csv`. Brier skill and log-loss are blank. The games have no outcome. `q_value` is blank when `N < 40`.

| Market | Signal | Family | N | Mean EV | CI low | CI high | boot p | q | Half-line share | One-leg CI low | Verdict | Reason | Dropped |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| rec_yds_q3 | q3_script | gaussian | 93 | 0.339351 | 0.278611 | 0.403640 | 0.000500 | 0.000500 | 0.451613 | 0.270352 | pass | pass | short_history:1 |
| rec_yds_q4 | q4_separation | gaussian | 75 | 0.239262 | 0.174322 | 0.309215 | 0.000500 | 0.000500 | 0.226667 | 0.164460 | pass | pass | missing_player:19, short_history:1 |
| receptions_q4 | q4_separation | gaussian | 98 | 0.123459 | 0.070021 | 0.181902 | 0.000500 | 0.000500 | 0.765306 | 0.062365 | fail | half_line_majority | missing_player:34, no_player:1, short_history:3 |
| rush_yds_q4 | q4_rush | gaussian | 21 | 0.167744 | 0.099268 | 0.237789 |  |  | 0.000000 | 0.089754 | fail | too_few_legs | missing_player:12, no_player:1 |
| pass_yds_q4 | q4_qb | gaussian | 20 | 0.108389 | 0.057099 | 0.173612 |  |  | 0.000000 | 0.046204 | fail | too_few_legs | no_player:4 |
| rec_longest | tail_rec | tail | 89 | 0.198703 | 0.157822 | 0.241490 | 0.000500 | 0.000500 | 0.000000 | 0.149619 | pass | pass | short_history:1, weibull:18 |
| rush_longest | tail_rush | tail | 41 | 0.285171 | 0.209305 | 0.358179 | 0.000500 | 0.000500 | 0.000000 | 0.205380 | pass | pass | no_player:3 |
| pass_longest | tail_pass | tail | 20 | 0.375868 | 0.274264 | 0.475379 |  |  | 0.000000 | 0.257737 | fail | too_few_legs | no_player:3 |
| pass_attempts | funnel_volume | poisson | 22 | 0.341083 | 0.249016 | 0.431478 |  |  | 0.000000 | 0.239537 | fail | too_few_legs | no_player:4 |
| pass_completions | funnel_volume | poisson | 22 | 0.299352 | 0.194935 | 0.398374 |  |  | 0.000000 | 0.173789 | fail | too_few_legs | no_player:4 |
| interceptions | funnel_int | poisson | 21 | 0.071908 | 0.033356 | 0.112634 |  |  | 1.000000 | 0.026669 | fail | too_few_legs | no_player:4 |
| field_goals | rz_stall | poisson | 1 | -0.017159 | -0.017159 | -0.017159 |  |  | 0.000000 |  | fail | too_few_legs | weather_unknown:22 |
| kicking_points | rz_stall | gaussian | 0 |  |  |  |  |  |  |  | fail | too_few_legs |  |
| total_q3 | q3_script_game | gaussian | 13 | 0.124407 | 0.074016 | 0.180113 |  |  | 0.000000 | 0.065123 | fail | too_few_legs |  |

`boot_p` 0.000500 means zero of 2000 bootstrap means were at or below 0. The formula is `(1 + count) / 2001`. The FDR family is the four cells with `N >= 40`. Those four p-values are equal, so the Benjamini-Hochberg step sets each q-value to 0.000500. `receptions_q4` is in that family and still fails. More than half of its lines are 0.5.

Promoted tokens: `rec_yds_q3`, `rec_yds_q4`, `rec_longest`, `rush_longest`.

`receptions_q1` stays out. That decision is in `docs/2026-10-17-uncovered-markets.md`. This pass does not reopen it.

## Executors

| Phase | Executor | What that executor wrote |
| --- | --- | --- |
| P0 capture markers and parse | primary | `hardrock_book.py` keep and stat markers. GLM did not write the parser. |
| P1 telemetry loader | primary | `matchup_features.py`. GLM did not write the loader. |
| P2 point-in-time join | primary | The same loader. Week 6 of 2026 is excluded, including the Thursday plays. |
| P3 signal math | primary | `matchup_math.py`. Formulas were locked before the score. |
| P4 EV and FDR verdict | primary | `matchup_score.py` and `data/cache/matchup_ev.csv`. |
| P5 tests | primary and `opencode/glm-5.3-flash-free` | Primary wrote `tests/test_matchup_engine.py`. GLM wrote only `tests/test_matchup_lag.py`. |
| `LEGAL_MARKETS` and canon | primary | `PROMOTED_MARKETS` in `markets.py`. Canon C24. |

`opencode models` lists `opencode/glm-5.3-flash-free`. No paid model was substituted. This continuation did not start a second GLM run.

## Surface

Capture stamp: `2026-10-17T16:20:43Z`. The file is `data/cache/hardrock_nfl_20261018_expanded.json`. It has 13 events and 295 market types. The Odds API was not called.

Command:

```text
python3 -m ceminiparlays.matchup_surface --capture data/cache/hardrock_nfl_20261018_expanded.json --out data/cache/matchup_surface.csv
```

Output:

```text
surface=36 live=27 partial=2 absent=7
```

Feed is `hardrock_getevents` when the census has the type. Feed is `none` when it does not.

| Catalog key | Status | Odds API | Book markets | Note |
| --- | --- | --- | ---: | --- |
| player_pass_attempts | live | absent | 26 | |
| player_pass_completions | live | absent | 26 | |
| player_pass_interceptions | live | absent | 25 | |
| player_rush_attempts | live | not_fetched | 37 | Client key exists. This pass did not fetch it. |
| player_rush_reception_yds | live | absent | 31 | Census type `FT:PROPRSPRCYDS`. The keep list does not store those selections. The priced CSV has no rush-plus-reception rows. |
| player_rush_reception_tds | absent | absent | 0 | No `PROPRSPRCTD` type. |
| player_sacks | live | absent | 2 | |
| player_solo_tackles | partial | absent | 7 | Combined tackles. Not solo versus assists. |
| player_tackles_assists | partial | absent | 7 | Same combined market. |
| player_reception_longest | live | absent | 108 | Count includes ladders. |
| player_rush_longest | live | absent | 44 | Count includes ladders. |
| player_pass_longest_completion | live | absent | 23 | |
| player_kicking_points | live | absent | 23 | Census is live. Each kept market is Over only. Example: Cam Little, Over 7.5. The parser writes a row only when Over and Under both exist. The priced CSV has 0 `kicking_points` rows. |
| player_field_goals | live | absent | 23 | Priced CSV has 23 standard rows. |
| player_pats | live | absent | 21 | Priced CSV has 21 `extra_points` standard rows. |
| h2h_q1 | absent | absent | 0 | |
| h2h_q2 | absent | absent | 0 | |
| h2h_q3 | absent | absent | 0 | |
| h2h_q4 | absent | absent | 0 | |
| h2h_h1 | absent | absent | 0 | |
| h2h_h2 | absent | absent | 0 | |
| spreads_q1 | live | absent | 186 | Count includes alt ladders. `spread_q3` is captured and not scored. The spread sign was not locked. |
| spreads_q2 | live | absent | 195 | |
| spreads_q3 | live | absent | 187 | Not scored. |
| spreads_q4 | live | absent | 195 | |
| spreads_h1 | live | absent | 297 | |
| spreads_h2 | live | absent | 278 | |
| totals_q1 | live | absent | 339 | |
| totals_q2 | live | absent | 370 | |
| totals_q3 | live | absent | 352 | |
| totals_q4 | live | absent | 376 | |
| totals_h1 | live | absent | 684 | |
| totals_h2 | live | absent | 716 | |
| team_totals | live | absent | 2833 | The count includes alternate total ladders. Status live is the game total, not 2833 independent prices. |
| player_1st_td | live | not_fetched | 245 | Not in the locked 14 cells. |
| player_last_td | live | absent | 248 | Not in the locked 14 cells. |

Quarter and half moneylines are absent. The only moneyline type in the census is full-game `AMERICAN_FOOTBALL:FTOT:ML` (13).

## Features

The snapshot is as of 2026 week 6. A row enters only when `(season, week)` is strictly before `(2026, 6)`. Regular season weeks are 1 through 18. 2022 play-by-play and 2022 FTN charting are absent on disk. They were not invented.

FTN joins play-by-play when `nflverse_game_id` equals `game_id` and both play ids are integers. The join rate is 1.0 for 2023, 2024, 2025, and 2026. NGS is weekly. It has no `play_id`. The join key is `(season, week, player_id)`.

Command:

```text
python3 -m ceminiparlays.matchup_features --players /tmp/matchup_players_b.csv --teams /tmp/matchup_teams_b.csv
```

Output:

```text
target=2026-w6 players=1037 teams=32 ftn_join={'2023': 1.0, '2024': 1.0, '2025': 1.0, '2026': 1.0} missing=[] absent_2022=yes
```

Then:

```text
cmp -s data/cache/matchup_players_2026w06.csv /tmp/matchup_players_b.csv
cmp -s data/cache/matchup_teams_2026w06.csv /tmp/matchup_teams_b.csv
```

Output:

```text
FEATURES_IDENTICAL
```

## Score

Command:

```text
python3 -m ceminiparlays.matchup_score \
  --lines data/cache/hardrock_nfl_20261018_expanded.csv \
  --players data/cache/matchup_players_2026w06.csv \
  --teams data/cache/matchup_teams_2026w06.csv \
  --out /tmp/matchup_ev_b.csv \
  --legs /tmp/matchup_legs_b.csv
```

Output:

```text
market signal n mean_ev ci_low ci_high q verdict reason
rec_yds_q3 q3_script 93 0.339351 0.278611 0.403640 0.000500 pass pass
rec_yds_q4 q4_separation 75 0.239262 0.174322 0.309215 0.000500 pass pass
receptions_q4 q4_separation 98 0.123459 0.070021 0.181902 0.000500 fail half_line_majority
rush_yds_q4 q4_rush 21 0.167744 0.099268 0.237789  fail too_few_legs
pass_yds_q4 q4_qb 20 0.108389 0.057099 0.173612  fail too_few_legs
rec_longest tail_rec 89 0.198703 0.157822 0.241490 0.000500 pass pass
rush_longest tail_rush 41 0.285171 0.209305 0.358179 0.000500 pass pass
pass_longest tail_pass 20 0.375868 0.274264 0.475379  fail too_few_legs
pass_attempts funnel_volume 22 0.341083 0.249016 0.431478  fail too_few_legs
pass_completions funnel_volume 22 0.299352 0.194935 0.398374  fail too_few_legs
interceptions funnel_int 21 0.071908 0.033356 0.112634  fail too_few_legs
field_goals rz_stall 1 -0.017159 -0.017159 -0.017159  fail too_few_legs
kicking_points rz_stall 0     fail too_few_legs
total_q3 q3_script_game 13 0.124407 0.074016 0.180113  fail too_few_legs
promoted=rec_yds_q3,rec_yds_q4,rec_longest,rush_longest
```

Then `cmp` against `data/cache/matchup_ev.csv` and `data/cache/matchup_legs.csv`.

Output:

```text
EV_IDENTICAL
```

## Scanner

One command. It scores again and prints. It does not call Jev. It does not place a bet. `jev=fail_closed` means the process stopped before the Jev client.

```text
python3 -m ceminiparlays.matchup_scanner \
  --lines data/cache/hardrock_nfl_20261018_expanded.csv \
  --players data/cache/matchup_players_2026w06.csv \
  --teams data/cache/matchup_teams_2026w06.csv \
  --out data/cache/matchup_ev.csv \
  --legs data/cache/matchup_legs.csv
```

The rewrite matched `/tmp/matchup_ev_b.csv` and `/tmp/matchup_legs_b.csv`. The check printed `SCANNER_REWRITE_IDENTICAL`. Exit code 0. The print has 317 lines.

The print lists every leg on a passing market. It sorts by EV. It does not drop a negative leg. 298 legs are on the four passing markets. 50 of those 298 have EV at or below 0.

The first rows are 0.5-yard overs:

| Player | Market | Side | Line | Price | EV | Player pct | Def pct | Signal |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Colby Parkinson | rec_yds_q4 | over | 0.5 | +240 | 1.597567 | 71.39 | 96.77 | q4_separation |
| Colby Parkinson | rec_yds_q3 | over | 0.5 | +195 | 1.210667 | 71.39 | 77.42 | q3_script |
| Josh Cameron | rec_yds_q3 | over | 0.5 | +195 | 1.140568 | 83.97 | 74.19 | q3_script |
| Brian Thomas Jr. | rec_yds_q3 | over | 0.5 | +175 | 1.117314 | 95.44 | 74.19 | q3_script |
| Darnell Mooney | rec_yds_q3 | over | 0.5 | +185 | 1.107108 | 85.08 | 35.48 | q3_script |

`rec_yds_q3` has 42 of 93 lines at 0.5. Mean EV on those lines is 0.600365. Mean EV on the other 51 lines is 0.124398. `rec_yds_q4` has 17 of 75 lines at 0.5. Mean EV is 0.667180 on those lines and 0.113838 on the other 58. The count-stat half-line rule does not cover yards. This report does not add that rule after the score.

The full scanner stdout is below.

```text
market signal n mean_ev ci_low ci_high q verdict reason
rec_yds_q3 q3_script 93 0.339351 0.278611 0.403640 0.000500 pass pass
rec_yds_q4 q4_separation 75 0.239262 0.174322 0.309215 0.000500 pass pass
receptions_q4 q4_separation 98 0.123459 0.070021 0.181902 0.000500 fail half_line_majority
rush_yds_q4 q4_rush 21 0.167744 0.099268 0.237789  fail too_few_legs
pass_yds_q4 q4_qb 20 0.108389 0.057099 0.173612  fail too_few_legs
rec_longest tail_rec 89 0.198703 0.157822 0.241490 0.000500 pass pass
rush_longest tail_rush 41 0.285171 0.209305 0.358179 0.000500 pass pass
pass_longest tail_pass 20 0.375868 0.274264 0.475379  fail too_few_legs
pass_attempts funnel_volume 22 0.341083 0.249016 0.431478  fail too_few_legs
pass_completions funnel_volume 22 0.299352 0.194935 0.398374  fail too_few_legs
interceptions funnel_int 21 0.071908 0.033356 0.112634  fail too_few_legs
field_goals rz_stall 1 -0.017159 -0.017159 -0.017159  fail too_few_legs
kicking_points rz_stall 0     fail too_few_legs
total_q3 q3_script_game 13 0.124407 0.074016 0.180113  fail too_few_legs
qualified=298
promoted=rec_yds_q3,rec_yds_q4,rec_longest,rush_longest
jev=fail_closed
player market side line price ev player_pct def_pct signal
Colby Parkinson rec_yds_q4 over 0.500000 240 1.597567 71.385542 96.774194 q4_separation
Colby Parkinson rec_yds_q3 over 0.500000 195 1.210667 71.393342 77.419355 q3_script
Josh Cameron rec_yds_q3 over 0.500000 195 1.140568 83.970407 74.193548 q3_script
Brian Thomas Jr. rec_yds_q3 over 0.500000 175 1.117314 95.437731 74.193548 q3_script
Darnell Mooney rec_yds_q3 over 0.500000 185 1.107108 85.080148 35.483871 q3_script
Bhayshul Tuten rec_yds_q3 over 0.500000 190 1.064670 49.691739 74.193548 q3_script
Josh Cameron rec_yds_q4 over 0.500000 175 0.960832 9.939759 0.000000 q4_separation
Brian Thomas Jr. rec_yds_q4 over 0.500000 150 0.958273 38.855422 0.000000 q4_separation
Justice Hill rec_yds_q3 over 0.500000 190 0.954678 64.488286 3.225806 q3_script
Bucky Irving rec_yds_q3 over 0.500000 190 0.926758 76.448829 6.451613 q3_script
Cam Skattebo rec_yds_q3 over 0.500000 175 0.902484 81.504316 35.483871 q3_script
Marvin Harrison Jr. rec_yds_q3 over 0.500000 160 0.893383 89.519112 29.032258 q3_script
MarShawn Lloyd rush_longest under 12.500000 -120 0.821953 0.000000 93.548387 tail_rush
Darnell Mooney rec_yds_q4 over 0.500000 155 0.793559 60.542169 32.258065 q4_separation
Kayshon Boutte rec_yds_q3 over 0.500000 140 0.778755 80.271270 29.032258 q3_script
Noah Fant rec_longest over 8.500000 -105 0.755980 49.938348 35.483871 tail_rec
Cole Kmet rec_longest over 7.500000 -115 0.746973 63.501850 29.032258 tail_rec
Dameon Pierce rec_yds_q3 over 0.500000 170 0.743091 67.570900 61.290323 q3_script
Jalen Brooks rec_yds_q4 over 0.500000 120 0.732349 5.421687 29.032258 q4_separation
Rico Dowdle rush_longest over 8.500000 -110 0.723105 65.551839 38.709677 tail_rush
Malachi Fields rec_yds_q4 over 0.500000 125 0.716085 1.807229 32.258065 q4_separation
Daniel Jones rush_longest over 5.500000 -110 0.711508 67.892977 19.354839 tail_rush
Tyler Higbee rec_yds_q4 over 0.500000 115 0.705408 72.590361 96.774194 q4_separation
Jahan Dotson rec_yds_q3 over 0.500000 150 0.703966 70.653514 12.903226 q3_script
Rashod Bateman rec_yds_q3 over 0.500000 155 0.702802 76.572133 3.225806 q3_script
Keaton Mitchell rush_longest over 6.500000 -120 0.685718 89.464883 6.451613 tail_rush
Brian Thomas Jr. rec_longest over 12.500000 -125 0.672693 86.683107 70.967742 tail_rec
Kenneth Gainwell rush_longest over 6.500000 -110 0.667689 67.725753 48.387097 tail_rush
Gunnar Helm rec_yds_q4 over 0.500000 100 0.664961 67.168675 90.322581 q4_separation
Malachi Fields rec_yds_q3 over 0.500000 145 0.658572 66.954377 35.483871 q3_script
Marvin Harrison Jr. rec_yds_q4 over 0.500000 135 0.651027 12.048193 87.096774 q4_separation
Marvin Harrison Jr. rec_longest over 14.500000 -110 0.638782 87.792848 58.064516 tail_rec
Omarion Hampton rush_longest over 9.500000 -120 0.610436 73.913043 6.451613 tail_rush
Rashod Bateman rec_yds_q4 over 0.500000 135 0.599460 56.626506 51.612903 q4_separation
Kayshon Boutte rec_yds_q4 over 0.500000 120 0.596301 17.771084 87.096774 q4_separation
Makai Lemon rec_yds_q3 over 0.500000 150 0.594561 85.819975 61.290323 q3_script
Kenyon Sadiq rec_yds_q3 over 0.500000 135 0.590449 56.720099 19.354839 q3_script
Makai Lemon rec_yds_q4 over 0.500000 120 0.585501 9.638554 74.193548 q4_separation
Oronde Gadsden rec_longest over 10.500000 -120 0.580855 67.570900 22.580645 tail_rec
D'Andre Swift rec_yds_q3 over 0.500000 130 0.574716 68.927250 45.161290 q3_script
Najee Harris rush_longest over 9.500000 -120 0.573329 69.397993 58.064516 tail_rush
Jalen Brooks rec_yds_q3 over 0.500000 160 0.572077 24.907522 38.709677 q3_script
Bucky Irving rec_longest over 7.500000 -120 0.568733 41.676942 77.419355 tail_rec
Chris Rodriguez Jr. rush_longest over 8.500000 100 0.567613 72.240803 16.129032 tail_rush
Cam Skattebo rec_longest over 7.500000 -125 0.562168 45.499383 51.612903 tail_rec
MarShawn Lloyd rec_yds_q3 over 0.500000 160 0.561803 19.358816 87.096774 q3_script
Gunnar Helm rec_yds_q3 over 0.500000 145 0.557556 40.813810 32.258065 q3_script
Jakobi Meyers rec_yds_q3 over 0.500000 -115 0.549483 92.355117 74.193548 q3_script
Jahan Dotson rec_yds_q4 over 0.500000 120 0.537724 37.349398 93.548387 q4_separation
Darnell Mooney rec_longest over 14.500000 -115 0.535039 87.546239 51.612903 tail_rec
Jonathan Taylor rec_yds_q3 over 0.500000 110 0.527634 73.859433 100.000000 q3_script
Bhayshul Tuten rush_longest under 13.500000 -105 0.515196 56.856187 16.129032 tail_rush
Kenneth Gainwell rec_yds_q3 over 0.500000 145 0.498286 54.623921 6.451613 q3_script
Bryce Young rush_longest over 7.500000 -115 0.490237 81.605351 54.838710 tail_rush
Justice Hill rush_longest over 6.500000 -140 0.488313 78.595318 96.774194 tail_rush
Tyler Shough rush_longest over 7.500000 -115 0.487966 71.906355 100.000000 tail_rush
Dontayvion Wicks rec_yds_q3 over 0.500000 105 0.481266 75.832306 61.290323 q3_script
Ty Johnson rec_longest over 10.500000 -110 0.479886 57.336621 6.451613 tail_rec
Braelon Allen rec_yds_q3 over 0.500000 125 0.463182 38.717633 19.354839 q3_script
Chris Godwin Jr. rec_longest over 14.500000 -115 0.462308 57.706535 77.419355 tail_rec
Elic Ayomanor rec_longest over 12.500000 -120 0.459366 82.737361 61.290323 tail_rec
Chris Godwin Jr. rec_yds_q3 over 0.500000 100 0.458648 92.601726 6.451613 q3_script
Rashod Bateman rec_longest over 12.500000 -120 0.458183 84.586930 48.387097 tail_rec
Jameis Winston rush_longest over 5.500000 -110 0.454605 68.561873 58.064516 tail_rush
Jake Ferguson rec_yds_q3 over 0.500000 -115 0.453123 88.162762 64.516129 q3_script
DK Metcalf rec_longest over 21.500000 -115 0.446903 89.889026 80.645161 tail_rec
Kalif Raymond rec_yds_q3 over 0.500000 110 0.440798 64.611591 45.161290 q3_script
Jakobi Meyers rec_yds_q4 over 3.500000 -115 0.437611 36.445783 0.000000 q4_separation
Mark Andrews rec_longest over 12.500000 -110 0.431820 55.610358 48.387097 tail_rec
Justice Hill rec_longest over 7.500000 -135 0.423405 46.115906 48.387097 tail_rec
Darnell Washington rec_yds_q3 over 0.500000 120 0.420572 62.145499 51.612903 q3_script
Kayshon Boutte rec_longest over 15.500000 -110 0.413931 91.615290 58.064516 tail_rec
Bo Melton rec_longest over 11.500000 -110 0.412831 89.272503 87.096774 tail_rec
Emeka Egbuka rec_longest over 16.500000 -125 0.411389 82.860666 77.419355 tail_rec
Darren Waller rec_yds_q4 over 0.500000 -110 0.400568 44.578313 54.838710 q4_separation
Kyle Pitts Sr. rec_yds_q3 over 0.500000 -105 0.399262 86.559803 12.903226 q3_script
Javonte Williams rec_yds_q3 over 0.500000 120 0.393405 68.557337 64.516129 q3_script
Quentin Johnston rec_yds_q3 over 0.500000 -110 0.390066 83.353884 58.064516 q3_script
Xavier Hutchinson rec_longest over 10.500000 -125 0.388651 74.352651 58.064516 tail_rec
Kyren Williams rec_yds_q3 over 0.500000 105 0.384389 73.242910 77.419355 q3_script
Tyler Higbee rec_yds_q3 over 0.500000 -115 0.383168 83.107275 77.419355 q3_script
Darren Waller rec_yds_q3 over 0.500000 -105 0.381311 72.626387 16.129032 q3_script
Ashton Jeanty rec_longest over 11.500000 -115 0.378773 41.923551 16.129032 tail_rec
Keenan Allen rec_yds_q3 over 5.500000 -120 0.378525 97.287300 100.000000 q3_script
Rhamondre Stevenson rec_yds_q3 over 0.500000 100 0.373779 82.737361 54.838710 q3_script
Cam Skattebo rush_longest under 13.500000 -120 0.362077 58.361204 58.064516 tail_rush
Darnell Washington rec_yds_q4 over 0.500000 105 0.360599 71.686747 22.580645 q4_separation
Dak Prescott rush_longest over 7.500000 -110 0.355894 60.367893 29.032258 tail_rush
Ladd McConkey rec_yds_q3 over 4.500000 -115 0.355216 93.588163 58.064516 q3_script
Ryan Flournoy rec_yds_q3 over 0.500000 -105 0.351518 79.408138 64.516129 q3_script
D'Andre Swift rec_longest over 9.500000 -110 0.348689 44.019729 29.032258 tail_rec
Javonte Williams rec_longest over 8.500000 -110 0.347839 0.000000 32.258065 tail_rec
Chris Godwin Jr. rec_yds_q4 over 3.500000 -115 0.343512 51.204819 3.225806 q4_separation
C.J. Stroud rush_longest over 7.500000 -115 0.329043 69.732441 61.290323 tail_rush
Bijan Robinson rush_longest under 20.500000 -115 0.326204 72.742475 70.967742 tail_rush
Dallas Goedert rec_yds_q3 over 3.500000 -110 0.324520 90.258940 61.290323 q3_script
Rome Odunze rec_yds_q3 over 1.500000 -115 0.322088 85.696671 45.161290 q3_script
Kyle Pitts Sr. rec_yds_q4 over 3.500000 -115 0.320114 52.409639 93.548387 q4_separation
Kenneth Walker III rec_yds_q3 over 0.500000 -110 0.317057 77.435265 25.806452 q3_script
Nico Collins rec_longest over 24.500000 -115 0.316112 80.271270 58.064516 tail_rec
Woody Marks rec_yds_q3 over 0.500000 120 0.316014 25.647349 29.032258 q3_script
Keenan Allen rec_yds_q4 over 5.500000 -115 0.315966 39.759036 67.741935 q4_separation
Pat Freiermuth rec_yds_q3 over 2.500000 -115 0.311878 80.641184 51.612903 q3_script
Michael Mayer rec_yds_q3 over 0.500000 -110 0.309421 70.160296 0.000000 q3_script
Chuba Hubbard rec_longest over 9.500000 105 0.303376 0.000000 12.903226 tail_rec
Drake London rec_yds_q3 under 16.500000 -115 0.301925 95.067818 12.903226 q3_script
DJ Moore rec_yds_q3 over 6.500000 -110 0.301354 95.314427 70.967742 q3_script
Jake Ferguson rec_longest over 13.500000 -110 0.301014 51.418002 32.258065 tail_rec
Chuba Hubbard rec_yds_q3 over 0.500000 105 0.300544 66.214550 16.129032 q3_script
Tyler Huntley rush_longest over 11.500000 -130 0.295669 85.117057 96.774194 tail_rush
Jakobi Meyers rec_longest over 16.500000 -120 0.295576 64.611591 70.967742 tail_rec
Zay Flowers rec_longest over 21.500000 -115 0.290416 79.408138 48.387097 tail_rec
Jake Ferguson rec_yds_q4 over 3.500000 -115 0.289623 68.373494 80.645161 q4_separation
Denzel Boston rec_yds_q4 over 9.500000 -110 0.288963 6.325301 38.709677 q4_separation
Christian McCaffrey rec_longest under 16.500000 -115 0.288274 43.526510 83.870968 tail_rec
Dalton Schultz rec_yds_q4 over 4.500000 -115 0.287564 75.903614 87.096774 q4_separation
Wan'Dale Robinson rec_yds_q4 over 7.500000 -115 0.284132 76.506024 90.322581 q4_separation
Ryan Flournoy rec_yds_q4 over 2.500000 -115 0.280714 75.602410 80.645161 q4_separation
Rome Odunze rec_yds_q4 over 5.500000 -115 0.278584 43.373494 12.903226 q4_separation
Kalif Raymond rec_yds_q4 over 0.500000 -110 0.278297 91.867470 12.903226 q4_separation
Dallas Goedert rec_longest over 15.500000 -115 0.276914 51.911221 38.709677 tail_rec
Kendrick Bourne rec_yds_q4 over 6.500000 -110 0.274538 24.397590 29.032258 q4_separation
Javonte Williams rush_longest under 15.500000 -125 0.272266 71.739130 29.032258 tail_rush
A.J. Brown rec_yds_q4 over 5.500000 -115 0.271176 13.253012 83.870968 q4_separation
Tyler Warren rec_longest under 17.500000 -105 0.267682 47.472256 90.322581 tail_rec
Cade Otton rec_yds_q3 over 0.500000 -110 0.266413 80.517879 6.451613 q3_script
Emeka Egbuka rec_yds_q4 over 6.500000 -110 0.261210 31.626506 3.225806 q4_separation
Kendrick Bourne rec_yds_q3 over 1.500000 -115 0.260617 67.694205 38.709677 q3_script
Mark Andrews rec_yds_q3 over 2.500000 -110 0.259163 90.012330 3.225806 q3_script
Wan'Dale Robinson rec_yds_q3 over 3.500000 -120 0.248305 96.054254 32.258065 q3_script
Juwan Johnson rec_yds_q3 over 5.500000 -115 0.243148 90.505549 93.548387 q3_script
Elijah Higgins rec_longest over 9.500000 -120 0.236529 45.499383 67.741935 tail_rec
Blake Corum rush_longest under 14.500000 -125 0.234592 73.076923 83.870968 tail_rush
Kyren Williams rush_longest under 15.500000 -115 0.234215 63.712375 83.870968 tail_rush
Dontayvion Wicks rec_yds_q4 over 2.500000 -120 0.233035 37.650602 74.193548 q4_separation
Dalton Kincaid rec_yds_q3 over 6.500000 -120 0.229256 87.299630 70.967742 q3_script
Tetairoa McMillan rec_longest under 22.500000 -110 0.227238 79.161529 12.903226 tail_rec
Derrick Henry rush_longest over 18.500000 -115 0.227121 79.598662 96.774194 tail_rush
Darren Waller rec_longest over 14.500000 -125 0.227099 63.008631 12.903226 tail_rec
Noah Gray rec_longest over 10.500000 -115 0.225407 60.172626 41.935484 tail_rec
George Pickens rec_yds_q3 over 11.500000 -115 0.221592 93.218249 64.516129 q3_script
Harold Fannin Jr. rec_yds_q4 over 6.500000 -110 0.221280 78.012048 38.709677 q4_separation
Mike Evans rec_longest over 24.500000 -115 0.219068 86.929716 83.870968 tail_rec
Chris Olave rec_longest under 24.500000 -110 0.218655 85.943280 35.483871 tail_rec
Harold Fannin Jr. rec_yds_q3 over 4.500000 -110 0.216173 90.628853 41.935484 q3_script
Kenneth Walker III rec_longest over 10.500000 -125 0.215299 41.183724 41.935484 tail_rec
Dameon Pierce rush_longest under 13.500000 -105 0.212928 56.521739 74.193548 tail_rush
Dalton Schultz rec_yds_q3 over 2.500000 -115 0.212570 88.902589 29.032258 q3_script
Tyler Higbee rec_longest under 17.500000 -115 0.208607 49.321825 74.193548 tail_rec
Colston Loveland rec_yds_q4 over 5.500000 -115 0.205749 65.662651 12.903226 q4_separation
Chuba Hubbard rush_longest under 14.500000 -110 0.205197 67.056856 54.838710 tail_rush
Kenyon Sadiq rec_yds_q4 over 0.500000 -105 0.203552 96.385542 45.161290 q4_separation
Colston Loveland rec_yds_q3 over 2.500000 -115 0.202533 86.066584 45.161290 q3_script
DK Metcalf rec_yds_q4 over 8.500000 -110 0.196676 20.481928 22.580645 q4_separation
Davante Adams rec_yds_q4 over 5.500000 -115 0.193371 25.301205 96.774194 q4_separation
Quentin Johnston rec_yds_q4 over 4.500000 -110 0.190995 33.734940 9.677419 q4_separation
Davante Adams rec_yds_q3 over 8.500000 -120 0.190199 97.533909 77.419355 q3_script
Brock Bowers rec_longest under 24.500000 -120 0.188504 59.926017 16.129032 tail_rec
Kyle Pitts Sr. rec_longest over 15.500000 -115 0.188277 61.898890 93.548387 tail_rec
Malik Nabers rec_yds_q4 over 14.500000 -115 0.186842 38.554217 32.258065 q4_separation
Jaylen Warren rec_yds_q3 over 3.500000 -110 0.184884 80.887793 51.612903 q3_script
Emeka Egbuka rec_yds_q3 over 2.500000 -115 0.180630 96.300863 6.451613 q3_script
Puka Nacua rec_yds_q3 over 17.500000 -115 0.177130 98.520345 77.419355 q3_script
Ashton Jeanty rush_longest over 11.500000 -120 0.176628 55.183946 87.096774 tail_rush
Garrett Wilson rec_longest under 22.500000 -110 0.174742 71.146732 25.806452 tail_rec
Colby Parkinson rec_longest over 10.500000 -115 0.173742 50.431566 74.193548 tail_rec
Cade Otton rec_yds_q4 over 4.500000 -115 0.170973 65.060241 3.225806 q4_separation
Christian Watson rec_yds_q3 over 11.500000 -115 0.166188 93.094945 87.096774 q3_script
Dalton Schultz rec_longest over 14.500000 -115 0.165658 56.596794 58.064516 tail_rec
Isaiah Likely rec_yds_q3 under 7.500000 -110 0.165061 74.229346 35.483871 q3_script
Pierre Strong Jr. rush_longest over 8.500000 -120 0.161740 68.060201 93.548387 tail_rush
Cam Ward rush_longest over 7.500000 -120 0.159423 64.715719 41.935484 tail_rush
Mark Andrews rec_yds_q4 over 3.500000 -115 0.158773 58.132530 51.612903 q4_separation
Trevor Lawrence rush_longest over 9.500000 100 0.158256 81.270903 16.129032 tail_rush
Tony Pollard rush_longest over 12.500000 -125 0.156907 68.729097 41.935484 tail_rush
Juwan Johnson rec_yds_q4 over 6.500000 -120 0.155639 62.349398 61.290323 q4_separation
Christian Watson rec_longest over 27.500000 -115 0.154510 92.231813 87.096774 tail_rec
Charlie Kolar rec_longest over 13.500000 -105 0.152184 46.239211 22.580645 tail_rec
Ladd McConkey rec_yds_q4 over 7.500000 -115 0.144835 60.240964 9.677419 q4_separation
Chris Olave rec_yds_q3 over 12.500000 -115 0.141608 96.547472 93.548387 q3_script
Jahan Dotson rec_longest over 15.500000 -110 0.140648 80.394575 93.548387 tail_rec
Devaughn Vele rec_longest under 18.500000 -115 0.140479 67.077682 35.483871 tail_rec
Rome Odunze rec_longest under 21.500000 -115 0.138659 89.025894 29.032258 tail_rec
Tre Tucker rec_yds_q4 over 7.500000 -110 0.137771 52.710843 19.354839 q4_separation
Bijan Robinson rec_yds_q3 over 2.500000 -120 0.131860 86.806412 12.903226 q3_script
Kendrick Bourne rec_longest over 16.500000 -115 0.126982 65.721332 67.741935 tail_rec
DJ Moore rec_yds_q4 over 7.500000 -120 0.124270 59.638554 77.419355 q4_separation
Pat Freiermuth rec_yds_q4 over 4.500000 -115 0.118746 56.927711 22.580645 q4_separation
Bucky Irving rush_longest over 14.500000 -120 0.117610 70.568562 48.387097 tail_rush
Ashton Jeanty rec_yds_q3 over 2.500000 -120 0.116163 91.738594 0.000000 q3_script
Dallas Goedert rec_yds_q4 over 5.500000 -120 0.114943 74.397590 74.193548 q4_separation
Tucker Kraft rec_yds_q3 over 6.500000 -115 0.114717 78.298397 87.096774 q3_script
Parker Washington rec_longest under 24.500000 -110 0.111309 81.997534 70.967742 tail_rec
Travis Kelce rec_yds_q4 over 6.500000 -115 0.110940 70.180723 58.064516 q4_separation
Drake London rec_longest under 28.500000 -115 0.110852 73.612824 93.548387 tail_rec
Isaiah Likely rec_longest under 19.500000 -120 0.108816 59.062885 51.612903 tail_rec
Keenan Allen rec_longest over 18.500000 -110 0.105409 67.200986 90.322581 tail_rec
Tetairoa McMillan rec_yds_q3 under 10.500000 -115 0.097397 89.149199 16.129032 q3_script
Rhamondre Stevenson rec_longest over 10.500000 -115 0.094530 44.389642 64.516129 tail_rec
Hunter Henry rec_longest over 15.500000 -120 0.092452 58.323058 64.516129 tail_rec
Woody Marks rush_longest over 10.500000 -125 0.087862 59.698997 61.290323 tail_rush
Luther Burden III rec_longest over 20.500000 -120 0.087849 65.104809 29.032258 tail_rec
Davante Adams rec_longest over 23.500000 -115 0.087329 76.202219 74.193548 tail_rec
Harold Fannin Jr. rec_longest over 15.500000 -115 0.085659 55.240444 45.161290 tail_rec
Xavier Worthy rec_longest under 19.500000 -115 0.085471 84.463625 41.935484 tail_rec
Chris Olave rec_yds_q4 over 15.500000 -115 0.081132 48.493976 61.290323 q4_separation
Matthew Golden rec_yds_q3 under 10.500000 -115 0.072282 80.764488 87.096774 q3_script
Devaughn Vele rec_yds_q3 over 5.500000 -120 0.068544 79.654747 93.548387 q3_script
Pat Freiermuth rec_longest under 16.500000 -120 0.068032 53.760789 80.645161 tail_rec
KC Concepcion rec_yds_q3 under 5.500000 -110 0.067471 97.040691 41.935484 q3_script
Brock Bowers rec_yds_q3 under 14.500000 -115 0.066349 96.670777 0.000000 q3_script
Jonathan Taylor rec_longest over 9.500000 -115 0.064774 41.430333 90.322581 tail_rec
DK Metcalf rec_yds_q3 over 6.500000 -115 0.064235 91.861899 51.612903 q3_script
Devaughn Vele rec_yds_q4 over 7.500000 -115 0.055956 21.385542 61.290323 q4_separation
Xavier Worthy rec_yds_q4 over 5.500000 -115 0.053935 83.433735 58.064516 q4_separation
Deshaun Watson rush_longest over 11.500000 -110 0.051651 74.247492 45.161290 tail_rush
Brenton Strange rec_longest under 16.500000 -110 0.051159 55.733662 70.967742 tail_rec
Tyler Warren rec_yds_q3 over 8.500000 -115 0.049782 92.848335 100.000000 q3_script
Luther Burden III rec_yds_q3 over 6.500000 -115 0.049556 87.422935 45.161290 q3_script
Isaiah Likely rec_yds_q4 under 9.500000 -115 0.048948 87.048193 32.258065 q4_separation
Jalen Coker rec_longest under 21.500000 -115 0.046752 70.406905 12.903226 tail_rec
Malik Nabers rec_longest under 24.500000 -110 0.044999 81.750925 51.612903 tail_rec
Drake London rec_yds_q4 under 21.500000 -120 0.041683 25.602410 93.548387 q4_separation
Zay Flowers rec_yds_q4 over 10.500000 -110 0.039925 80.120482 51.612903 q4_separation
Parker Washington rec_yds_q3 over 8.500000 -120 0.038723 89.025894 74.193548 q3_script
Juwan Johnson rec_longest over 17.500000 -120 0.037259 58.692972 35.483871 tail_rec
Dontayvion Wicks rec_longest over 16.500000 -110 0.035238 75.955610 38.709677 tail_rec
Christian Watson rec_yds_q4 under 14.500000 -115 0.034744 17.469880 48.387097 q4_separation
Puka Nacua rec_yds_q4 over 14.500000 -110 0.033349 43.975904 96.774194 q4_separation
Josh Downs rec_yds_q4 over 6.500000 -120 0.027307 50.301205 67.741935 q4_separation
Travis Kelce rec_yds_q3 over 8.500000 -115 0.026728 92.478422 25.806452 q3_script
Brenton Strange rec_yds_q3 over 4.500000 -115 0.026652 65.351418 74.193548 q3_script
Trey McBride rec_yds_q4 under 16.500000 -115 0.025177 58.734940 29.032258 q4_separation
George Pickens rec_longest over 24.500000 -115 0.023990 86.436498 32.258065 tail_rec
Dalton Kincaid rec_longest under 19.500000 -115 0.023678 66.954377 6.451613 tail_rec
Trey McBride rec_yds_q3 over 11.500000 -115 0.023351 98.643650 38.709677 q3_script
CeeDee Lamb rec_yds_q3 over 13.500000 -115 0.022769 97.410604 64.516129 q3_script
Travis Kelce rec_longest under 20.500000 -110 0.022604 58.446363 41.935484 tail_rec
Jonathan Taylor rush_longest over 17.500000 -125 0.022062 71.571906 19.354839 tail_rush
Zay Flowers rec_yds_q3 over 8.500000 -110 0.020004 96.177559 3.225806 q3_script
Malik Nabers rec_yds_q3 under 11.500000 -115 0.014299 95.930949 35.483871 q3_script
Germie Bernard rec_yds_q4 over 6.500000 -120 0.010435 10.240964 22.580645 q4_separation
Kalif Raymond rec_longest over 16.500000 -110 0.008694 65.598027 29.032258 tail_rec
Denzel Boston rec_yds_q3 over 5.500000 -115 0.007649 69.050555 41.935484 q3_script
CeeDee Lamb rec_longest over 25.500000 -120 0.006095 70.283600 32.258065 tail_rec
Tyler Allgeier rush_longest under 12.500000 -125 0.004633 64.046823 9.677419 tail_rush
Puka Nacua rec_longest over 26.500000 -115 0.000934 68.680641 74.193548 tail_rec
Luther Burden III rec_yds_q4 under 9.500000 -120 0.000835 82.530120 12.903226 q4_separation
Matthew Golden rec_longest over 24.500000 -115 -0.000007 91.245376 87.096774 tail_rec
Tetairoa McMillan rec_yds_q4 over 11.500000 -115 -0.003135 28.915663 54.838710 q4_separation
Michael Wilson rec_yds_q4 over 13.500000 -115 -0.003179 26.807229 29.032258 q4_separation
Michael Mayer rec_longest over 14.500000 -110 -0.005359 52.034525 16.129032 tail_rec
Tre Tucker rec_yds_q3 under 4.500000 -115 -0.005629 79.038224 0.000000 q3_script
Tyler Warren rec_yds_q4 over 7.500000 -120 -0.006450 68.975904 67.741935 q4_separation
KC Concepcion rec_yds_q4 under 7.500000 -115 -0.006547 71.084337 38.709677 q4_separation
Wan'Dale Robinson rec_longest over 16.500000 -115 -0.007141 60.665845 61.290323 tail_rec
Ryan Flournoy rec_longest over 16.500000 -120 -0.008446 62.762022 32.258065 tail_rec
Dalton Kincaid rec_yds_q4 under 8.500000 -115 -0.010149 77.710843 77.419355 q4_separation
Jaylen Warren rush_longest over 14.500000 -115 -0.010576 77.257525 38.709677 tail_rush
Trey McBride rec_longest under 18.500000 -125 -0.012916 53.637485 67.741935 tail_rec
Brenton Strange rec_yds_q4 over 6.500000 -110 -0.014161 72.289157 0.000000 q4_separation
Jaylen Warren rec_longest over 12.500000 -105 -0.014671 0.000000 80.645161 tail_rec
George Pickens rec_yds_q4 over 14.500000 -110 -0.014825 15.361446 80.645161 q4_separation
Darnell Washington rec_longest over 12.500000 -115 -0.015350 50.554871 80.645161 tail_rec
Bijan Robinson rec_longest over 13.500000 -120 -0.016781 46.609125 93.548387 tail_rec
Garrett Wilson rec_yds_q4 under 17.500000 -115 -0.018140 43.674699 45.161290 q4_separation
Rhamondre Stevenson rush_longest under 14.500000 -120 -0.021657 65.384615 12.903226 tail_rush
Gunnar Helm rec_longest over 10.500000 -115 -0.021837 48.212084 61.290323 tail_rec
Jalen Coker rec_yds_q4 over 8.500000 -120 -0.022333 31.325301 54.838710 q4_separation
Garrett Wilson rec_yds_q3 over 12.500000 -115 -0.022506 98.890259 19.354839 q3_script
Justin Herbert rush_longest over 12.500000 -105 -0.024632 88.963211 6.451613 tail_rush
Tucker Kraft rec_yds_q4 under 9.500000 -120 -0.025692 90.361446 48.387097 q4_separation
Brock Bowers rec_yds_q4 under 19.500000 -120 -0.030157 55.421687 19.354839 q4_separation
CeeDee Lamb rec_yds_q4 under 17.500000 -115 -0.030731 37.951807 80.645161 q4_separation
George Kittle rec_longest over 23.500000 -115 -0.031025 61.405672 83.870968 tail_rec
Josh Downs rec_yds_q3 over 7.500000 -115 -0.036204 89.642417 100.000000 q3_script
Carnell Tate rec_yds_q3 over 6.500000 -120 -0.036516 99.876695 32.258065 q3_script
Jalen Coker rec_yds_q3 under 8.500000 -120 -0.037971 85.573366 16.129032 q3_script
Xavier Worthy rec_yds_q3 over 6.500000 -120 -0.038784 89.765721 25.806452 q3_script
Nico Collins rec_yds_q4 under 14.500000 -115 -0.039956 30.120482 87.096774 q4_separation
Nico Collins rec_yds_q3 under 12.500000 -115 -0.040135 93.341554 29.032258 q3_script
Josh Downs rec_longest over 19.500000 -110 -0.041656 67.447596 90.322581 tail_rec
Michael Mayer rec_yds_q4 over 4.500000 -110 -0.044490 73.795181 19.354839 q4_separation
Brock Purdy rush_longest over 10.500000 -115 -0.044769 76.421405 64.516129 tail_rush
Kyren Williams rec_longest under 10.500000 -115 -0.046718 41.060419 74.193548 tail_rec
Michael Wilson rec_longest over 21.500000 -110 -0.047481 77.805179 67.741935 tail_rec
Josh Allen rush_longest under 13.500000 -125 -0.047857 87.290970 22.580645 tail_rush
D'Andre Swift rush_longest over 14.500000 -110 -0.049129 69.565217 77.419355 tail_rush
Germie Bernard rec_yds_q3 under 5.500000 -115 -0.052616 79.778052 51.612903 q3_script
Matthew Golden rec_yds_q4 over 12.500000 -120 -0.053439 46.084337 48.387097 q4_separation
Carnell Tate rec_yds_q4 over 11.500000 -120 -0.054028 31.927711 90.322581 q4_separation
Colston Loveland rec_longest under 18.500000 -120 -0.054914 60.789149 29.032258 tail_rec
Michael Wilson rec_yds_q3 over 9.500000 -115 -0.058430 81.997534 38.709677 q3_script
Drake Maye rush_longest over 12.500000 -115 -0.059021 90.468227 12.903226 tail_rush
Tre Tucker rec_longest under 17.500000 -120 -0.059527 91.122072 16.129032 tail_rec
Tucker Kraft rec_longest under 20.500000 -120 -0.059731 57.090012 87.096774 tail_rec
Cade Otton rec_longest under 14.500000 -110 -0.062587 51.541307 77.419355 tail_rec
Parker Washington rec_yds_q4 over 10.500000 -120 -0.071974 23.493976 0.000000 q4_separation
```

## Gate and copula

C24 is the promotion rule. A micro or period token enters `LEGAL_MARKETS` only when N is at least 40, the bootstrap 95% CI lower bound is above 0, and the q-value is at or below 0.10.

The four passing tokens do not share one signal. `rec_yds_q4` uses `q4_separation`. `receptions_q4` uses the same signal and fails. No second promoted market uses `q4_separation`. No copula rho is set. No joint weight is set.

Jev was not called. The scanner does not import `jev_client`.

## Tests

```text
python3 -m ruff check src tests
```

Output:

```text
All checks passed!
```

```text
python3 -m pytest -q
```

Output ends:

```text
507 passed, 9 warnings in 3.40s
```

The nine warnings are the existing `copula.py:117` matmul warning. New tests cover the week cutoff, the Weibull and Poisson tail, the power de-vig of −115/−115, the Benjamini-Hochberg step, and the four promoted tokens. `receptions_q1` still raises in `parse_markets`.

## Residual risk

- One unplayed slate. There is no historical closing-line archive for these markets. `runs/2026-w05-sun/closing_props.csv` is not a backtest.
- Model EV is the gap versus this board. It is not settled profit.
- The normal used for quarter receiving yards has no mass at zero. The top EV rows are 0.5-yard overs.
- 11 of 93 `rec_yds_q3` legs have a feature-store team that differs from the slate team. The book posted the name inside the event. The defense z uses the slate opponent. The names are Darnell Mooney (slate NYG, feature ATL), Marvin Harrison Jr. (slate HOU, feature ARI), Jahan Dotson (slate ATL, feature PHI), Jakobi Meyers (slate JAX, feature LV), Kenneth Gainwell (slate TB, feature PHI), Dontayvion Wicks (slate PHI, feature GB), Darren Waller (slate CAR, feature MIA), Keenan Allen (slate IND, feature CHI), DJ Moore (slate BUF, feature CHI), Kendrick Bourne (slate ARI, feature NE), and George Pickens (slate DAL, feature PIT). Marvin Harrison Jr. Q3 receiving yards is inside the event "Jaguars vs Texans".
- Josh Cameron matches a feature row with that full name, team JAX, and 4 prior receiving games. Four games is the minimum. It is a short history, not a renamed player.
- 2022 pbp and 2022 FTN are absent.
- Kicking points never became two-way rows. Field goals lost 22 of 23 legs to `weather_unknown`. Both teams must have a modal home roof in {dome, indoor, closed}. There is no week-6 wind feed.
- Q3 points are 6 times a touchdown, plus 3 times a made field goal, plus 1 times a made extra point. Safeties and two-point conversions are omitted.
- Alternates are not extra samples. One main line is kept per player, stat, and kickoff.
- `spread_q3` is not scored. `anytime_td` and `player_last_td` are inventoried and not scored.
- No commit was made.
