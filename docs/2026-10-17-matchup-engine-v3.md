# Matchup engine v3, 2026-10-17

Do not type a ticket. Do not submit a bet. Do not commit this work unless you ask for a commit.

Seven tokens pass both keys. `rush_yds_q4` enters. Seven tokens fail. The passing tokens are in `LEGAL_MARKETS`. Canon C24 records the gate.

The 2026 week-6 slate is unplayed. Model EV is not realized EV. These rows are not a bet.

## Verdict

The score file is `data/cache/matchup_ev.csv`. The history file is `data/cache/matchup_hist.csv`. The regime file is `config/matchup_regime_rho.json`.

Promoted tokens: `rec_yds_q3`, `rec_yds_q4`, `receptions_q4`, `rush_yds_q4`, `pass_yds_q4`, `interceptions`, `total_q3`.

`rush_yds_q4` failed the v2 history key. The v3 lambda gives it a Brier gain. It now passes both keys. The v1 tokens `rec_longest` and `rush_longest` stay withdrawn. `receptions_q1` stays out. `spreads_q3` and `spreads_q4` stay unscored.

Measured checks:

1. Offense team equals book team on 601 of 601 scored legs. The v2 file already stored matching codes on 598 of 598. The compare now maps full names and old abbreviations (`Los Angeles Rams`, `LA`, `JAC`) to nflverse codes before the join.
2. The scanner read `feature_cache=ready` and priced the slate from `CeminiDFS/data/shared_cache/2026_w06`. Player volume, NGS, the matching defense rates, the week roof, and the referee z-scores enter the live price. The local CSV remains the fallback.
3. The scanner prints 238 qualified legs. `calibration_warning=1`. `warn_legs=8`. The v2 print had 15 legs above 0.45. The locked constants were not moved to force the count to 2.
4. A second calibration run matched the history file and the regime file byte for byte. After `rush_yds_q4` entered the promoted set, `python3 -m pytest -q -W error::RuntimeWarning` passed 526 tests. `ruff check src tests` passed.

## Two-key table

The floors stay locked. A multi-player skill market needs `N_slate >= 35`. A single-starter market needs `N_slate >= 16`. A game-level market needs `N_slate >= 10`.

The history key uses settled play-by-play from 2023 through 2026 week 5. 2022 play-by-play is absent. Each player-game is scored at a point in time. The synthetic lines are the prior median and, for a zero-inflated prop, a 0.5 line. The benchmark price is -114/-114. History does not read a book price and does not apply the live referee factor. `N_hist >= 250`, Brier skill above 0, bootstrap 95% CI lower bound above 0, and Benjamini-Hochberg q at or below 0.10 are all required.

| Market | Signal | N slate | Mean EV | CI low | CI high | q | N hist | Delta Brier | Hist CI low | Hist CI high | Hist q | Verdict | Reason |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| rec_yds_q3 | q3_script | 92 | 0.044833 | 0.025956 | 0.064827 | 0.000500 | 11199 | 0.019666 | 0.016892 | 0.022257 | 0.000857 | pass | pass |
| rec_yds_q4 | q4_separation | 93 | 0.078530 | 0.053138 | 0.103635 | 0.000500 | 11291 | 0.010220 | 0.007738 | 0.012804 | 0.000857 | pass | pass |
| receptions_q4 | q4_separation | 132 | 0.078608 | 0.056716 | 0.100617 | 0.000500 | 11538 | 0.020747 | 0.018116 | 0.023520 | 0.000857 | pass | pass |
| rush_yds_q4 | q4_rush | 33 | 0.212919 | 0.151940 | 0.271062 | 0.000500 | 5496 | 0.015266 | 0.011485 | 0.019333 | 0.000857 | pass | pass |
| pass_yds_q4 | q4_qb | 20 | 0.158132 | 0.084292 | 0.241327 | 0.000500 | 1689 | 0.068343 | 0.060074 | 0.076666 | 0.000857 | pass | pass |
| rec_longest | tail_rec | 89 | 0.198703 | 0.157822 | 0.241490 | 0.000500 | 6992 | -0.019479 | -0.023178 | -0.015926 | 1.000000 | fail | no_brier_skill |
| rush_longest | tail_rush | 41 | 0.285171 | 0.209305 | 0.358179 | 0.000500 | 3939 | -0.042786 | -0.049794 | -0.035357 | 1.000000 | fail | no_brier_skill |
| pass_longest | tail_pass | 20 | 0.372247 | 0.269891 | 0.472478 | 0.000500 | 1643 | -0.008656 | -0.018499 | 0.001074 | 1.000000 | fail | no_brier_skill |
| pass_attempts | funnel_volume | 22 | 0.341707 | 0.249626 | 0.430755 | 0.000500 | 1664 | -0.013399 | -0.024473 | -0.002057 | 1.000000 | fail | no_brier_skill |
| pass_completions | funnel_volume | 22 | 0.297623 | 0.191809 | 0.396495 | 0.000500 | 1664 | -0.010403 | -0.020474 | 0.000203 | 1.000000 | fail | no_brier_skill |
| interceptions | funnel_int | 21 | 0.071908 | 0.033356 | 0.112634 | 0.000500 | 1689 | 0.022747 | 0.018008 | 0.027686 | 0.000857 | pass | pass |
| field_goals | rz_stall | 3 | 0.045741 | -0.017159 | 0.162105 |  | 166 | 0.069267 | 0.048799 | 0.088222 |  | fail | too_few_hist |
| kicking_points | rz_stall | 0 |  |  |  |  | 166 | -0.007736 | -0.025699 | 0.010778 |  | fail | too_few_hist |
| total_q3 | q3_script_game | 13 | 0.123235 | 0.073871 | 0.179107 | 0.000500 | 824 | 0.014373 | 0.005832 | 0.023496 | 0.000857 | pass | pass |

Live Brier columns stay blank. The games have no outcome.

`field_goals` has 3 live legs because the week roof from the game-context file marks the dome. The history count is still 166. The 250-game floor stays. `kicking_points` still has no two-way price.

## Volume

Quarter lambda is full-game volume times the shrunk quarter share times a defense multiplier.

`w = (Opps_q + 15 * 0.25) / (Opps_total + 15)`.

The defense multiplier is clipped to `[0.80, 1.25]`. A live referee factor applies only to receiving markets and `pass_yds_q4`. It is `1 + 0.02 * (dpi_z + holding_z)`, clipped to `[0.95, 1.05]`. History does not use it. That is a train-and-serve gap. The weight stays locked.

Full-game volume uses the vig-stripped book count when a main line exists. Else it uses book yards divided by the player's own yards per event. Else it uses the unshrunk trailing mean. A sample shorter than 3 games can move down toward 1.2 catches per game. It cannot move up. The live gate still requires 4 prior games, so that 1.2 prior is tested and is not the production eligibility rule.

`vacated_target_boost` is extra targets per game. It is present for 990 players and non-zero for 155. The player's own catch rate turns those targets into receptions. The receptions are added to the full-game receiving volume. The column is not a multiplier and it is not applied to rush or pass volume.

The player-by-defense z product does not enter lambda. Yards-per-event tilt is unchanged.

| Market | N | N at 0.5 | Mean EV at 0.5 | N at other lines | Mean EV at other lines |
| --- | ---: | ---: | ---: | ---: | ---: |
| rec_yds_q3 | 92 | 41 | 0.050417 | 51 | 0.040344 |
| rec_yds_q4 | 93 | 32 | 0.072897 | 61 | 0.081485 |
| receptions_q4 | 132 | 109 | 0.075530 | 23 | 0.093194 |
| rush_yds_q4 | 33 | 6 | 0.301839 | 27 | 0.193159 |
| pass_yds_q4 | 20 | 0 |  | 20 | 0.158132 |

### Named backups

v2 pulled a small quarter sample toward the league quarter mean. v3 does not.

| Player | Market | v3 side | Line | Price | Model P | v3 EV | v2 note |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Colby Parkinson | receptions_q4 | over | 0.5 | 230 | 0.469995 | 0.550985 | was about 0.79 |
| Colby Parkinson | rec_yds_q4 | over | 0.5 | 240 | 0.447706 | 0.522202 | was 0.761389 |
| Davis Allen | receptions_q4 | over | 0.5 | 375 | 0.245612 | 0.166659 | was 0.538856 |
| KaVontae Turpin | receptions_q4 | over | 0.5 | 325 | 0.263236 | 0.118753 | was 0.821717 |
| Blake Corum | receptions_q4 | under | 0.5 | -500 | 0.812296 | -0.025245 | was over, EV 0.519732 |

Parkinson stays above 0.45. His book receptions line implies about 1.64 catches per game. His own Q4 target share is 0.3214. The product is about 0.64 expected Q4 catches. The +230 price, not a pull toward a starter mean, makes the EV. Davis Allen, Turpin, and Corum are no longer priced like starters. Corum's side flipped to under.

### Line 0.5, top 15 qualified legs

| Player | Market | Side | Line | Price | EV | Model P |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Colby Parkinson | receptions_q4 | over | 0.5 | 230 | 0.550985 | 0.469995 |
| Colby Parkinson | rec_yds_q4 | over | 0.5 | 240 | 0.522202 | 0.447706 |
| Cam Ward | rush_yds_q4 | over | 0.5 | 110 | 0.450604 | 0.690764 |
| Romeo Doubs | receptions_q4 | over | 0.5 | 120 | 0.449843 | 0.659020 |
| Hunter Henry | receptions_q4 | over | 0.5 | 100 | 0.445770 | 0.722885 |
| DeMario Douglas | receptions_q4 | over | 0.5 | 145 | 0.433650 | 0.585163 |
| Dameon Pierce | rec_yds_q3 | over | 0.5 | 170 | 0.431534 | 0.530198 |
| Kyren Williams | receptions_q4 | over | 0.5 | 135 | 0.429912 | 0.608473 |
| Tyler Shough | rush_yds_q4 | over | 0.5 | 125 | 0.412926 | 0.627967 |
| Dak Prescott | rush_yds_q4 | over | 0.5 | 140 | 0.401330 | 0.583887 |
| Kyren Williams | rec_yds_q4 | over | 0.5 | 140 | 0.391081 | 0.579617 |
| Rhamondre Stevenson | receptions_q4 | over | 0.5 | 115 | 0.381965 | 0.642775 |
| Rhamondre Stevenson | rec_yds_q4 | over | 0.5 | 125 | 0.377656 | 0.612292 |
| Patrick Mahomes | rush_yds_q4 | over | 0.5 | 115 | 0.346313 | 0.626192 |
| Rhamondre Stevenson | rec_yds_q3 | over | 0.5 | 100 | 0.325440 | 0.662720 |

### Line 1.5 and higher, top 15 qualified legs

Qualified legs at 1.5 or higher: 95 overs and 29 unders. The v2 list was mostly unders on high-volume receivers. The v3 list is mixed. The three named receivers are not all unders.

| Player | Market | v3 side | Line | Price | EV |
| --- | --- | --- | ---: | ---: | ---: |
| Brock Bowers | rec_yds_q3 | under | 14.5 | -115 | -0.039416 |
| Brock Bowers | rec_yds_q4 | over | 19.5 | -110 | 0.178798 |
| Brock Bowers | receptions_q4 | over | 1.5 | -145 | 0.256021 |
| Drake London | rec_yds_q3 | under | 16.5 | -115 | 0.049621 |
| Drake London | rec_yds_q4 | under | 21.5 | -120 | 0.033363 |
| Drake London | receptions_q4 | over | 1.5 | -120 | 0.106746 |
| Trey McBride | rec_yds_q3 | over | 11.5 | -115 | 0.201594 |
| Trey McBride | rec_yds_q4 | over | 16.5 | -115 | -0.042807 |
| Trey McBride | receptions_q4 | under | 2.5 | -170 | 0.084061 |

Top 15 by EV:

| Player | Market | Side | Line | Price | EV | Model P |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Justin Herbert | rush_yds_q4 | over | 2.5 | -110 | 0.559172 | 0.816709 |
| Matthew Stafford | pass_yds_q4 | over | 52.5 | -115 | 0.517877 | 0.811888 |
| Jonathan Taylor | rush_yds_q4 | under | 19.5 | -115 | 0.475478 | 0.789209 |
| James Cook III | rush_yds_q4 | under | 19.5 | -115 | 0.466538 | 0.784427 |
| Tyler Huntley | pass_yds_q4 | over | 36.5 | -115 | 0.465594 | 0.783922 |
| MarShawn Lloyd | rush_yds_q4 | under | 7.5 | -110 | 0.434424 | 0.751365 |
| Tyler Shough | pass_yds_q4 | over | 58.5 | -115 | 0.430390 | 0.765092 |
| Harold Fannin Jr. | rec_yds_q4 | over | 6.5 | -110 | 0.425958 | 0.746931 |
| Caleb Williams | rush_yds_q4 | over | 1.5 | -120 | 0.413366 | 0.770927 |
| Trevor Lawrence | pass_yds_q4 | under | 55.5 | -115 | 0.381165 | 0.738763 |
| Rhamondre Stevenson | rush_yds_q4 | under | 15.5 | -120 | 0.373599 | 0.749236 |
| Tanner McKee | pass_yds_q4 | over | 54.5 | -115 | 0.352078 | 0.723204 |
| PHI vs CAR total | total_q3 | over | 7.5 | 105 | 0.327633 | 0.647626 |
| Keenan Allen | rec_yds_q4 | over | 5.5 | -115 | 0.324276 | 0.708334 |
| Puka Nacua | receptions_q4 | over | 1.5 | 110 | 0.306509 | 0.622147 |

The eight legs above 0.45 are Herbert, both Parkinson 0.5 lines, Stafford, Taylor, Cook, Huntley, and Ward. Six of the eight are rush or pass. They are not the backup receiving shrink. The count stays at 8.

## Same-game joints

These tickets are research prints. Do not type these tickets. Do not submit a bet. There is no new stake weight.

Compose skips one player's `receptions_qX` and `rec_yds_qX` in the same quarter. Distinct players stay eligible. A different quarter stays eligible. A rush or pass stat in that quarter stays eligible. The priced set has zero `(same player, receptions_q4, rec_yds_q4)` pairs.

`price_source=leg_odds_naive`. `unconfirmed=yes`. The naive decimal is the product of the single-leg prices. When the largest pair rho is above 0.15, the book haircut is:

`P_book = P_indep_vigged + 0.55 * (P_copula_vigged - P_indep_vigged)`

`Decimal_sgp = 1 / P_book`

The vigged marginal is `1 / decimal` of each American price. The copula is the exact Gaussian joint. The regime is neutral. The printed table keeps a ticket only when that haircut applies and the tax-adjusted EV is above 0. A same-game book does not pay either decimal. Use the in-app price before any decision.

### Top 10 two-leg tickets

| Legs | Joint Prob | Indep Prob | Alpha | Naive joint EV | Tax-adjusted SGP EV |
| --- | ---: | ---: | ---: | ---: | ---: |
| Parkinson receptions_q4 over 0.5 + Kyren Williams rec_yds_q4 over 0.5 | 0.429389 | 0.272417 | 0.156972 | 2.400761 | 1.101364 |
| Parkinson rec_yds_q4 over 0.5 + Kyren Williams receptions_q4 over 0.5 | 0.420758 | 0.272417 | 0.148341 | 2.361855 | 1.086899 |
| Parkinson rec_yds_q4 over 0.5 + Puka Nacua receptions_q4 over 1.5 | 0.423831 | 0.278539 | 0.145292 | 2.026154 | 0.982438 |
| Parkinson receptions_q4 over 0.5 + Puka Nacua rec_yds_q4 over 14.5 | 0.450298 | 0.311444 | 0.138854 | 1.836876 | 0.956987 |
| Parkinson rec_yds_q4 over 0.5 + Jalen Brooks receptions_q4 over 0.5 | 0.409244 | 0.252922 | 0.156322 | 1.991577 | 0.937053 |
| Parkinson receptions_q4 over 0.5 + Jalen Brooks rec_yds_q4 over 0.5 | 0.415083 | 0.252922 | 0.162161 | 2.013504 | 0.937015 |
| Parkinson receptions_q4 over 0.5 + Davante Adams rec_yds_q4 over 5.5 | 0.447632 | 0.305281 | 0.142351 | 1.761698 | 0.926284 |
| DeMario Douglas receptions_q4 over 0.5 + Rhamondre Stevenson rec_yds_q4 over 0.5 | 0.515942 | 0.358291 | 0.157651 | 1.844131 | 0.913561 |
| Rhamondre Stevenson rec_yds_q4 over 0.5 + Romeo Doubs receptions_q4 over 0.5 | 0.553851 | 0.403513 | 0.150338 | 1.741561 | 0.897771 |
| Parkinson rec_yds_q4 over 0.5 + Michael Wilson receptions_q4 over 1.5 | 0.421319 | 0.273498 | 0.147821 | 1.678122 | 0.863972 |

Each row is two different players. The haircut cuts the naive EV by about half on these pairs.

### Three-leg tickets

Three-leg tickets stay same-player. Two tickets keep a positive tax-adjusted EV. The other same-player triples include a banned quarter pair, have pair rho at or below 0.15, or have tax-adjusted EV at or below 0.

| Legs | Joint Prob | Indep Prob | Naive joint EV | Tax-adjusted SGP EV |
| --- | ---: | ---: | ---: | ---: |
| Tuten rec_yds_q3 over 0.5 + receptions_q4 under 0.5 + rush_yds_q4 under 11.5 | 0.198262 | 0.186202 | 0.620338 | 0.534151 |
| Tuten rec_yds_q3 over 0.5 + rec_yds_q4 under 0.5 + rush_yds_q4 under 11.5 | 0.200155 | 0.188891 | 0.589924 | 0.512795 |

## Commands

History, first run and the byte-identical repeat:

`absent_2022=yes rec_yds_q3=11199:hist_pass rec_yds_q4=11291:hist_pass receptions_q4=11538:hist_pass rush_yds_q4=5496:hist_pass pass_yds_q4=1689:hist_pass rec_longest=6992:no_brier_skill rush_longest=3939:no_brier_skill pass_longest=1643:no_brier_skill pass_attempts=1664:no_brier_skill pass_completions=1664:no_brier_skill interceptions=1689:hist_pass field_goals=166:too_few_hist kicking_points=166:too_few_hist total_q3=824:hist_pass hist_pass=rec_yds_q3,rec_yds_q4,receptions_q4,rush_yds_q4,pass_yds_q4,interceptions,total_q3`

Scanner header:

`feature_cache=ready`

`qualified=238`

`promoted=rec_yds_q3,rec_yds_q4,receptions_q4,rush_yds_q4,pass_yds_q4,interceptions,total_q3`

`jev=fail_closed`

`calibration_warning=1`

`warn_legs=8`

`team_mismatch=0`
