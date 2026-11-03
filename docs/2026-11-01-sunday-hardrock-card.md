# Week 8 Sunday Hard Rock card, 2026-11-01

Do not type a ticket until you check the laptop price. Do not submit a bet from this file.

The stake sum is $8.00. The ticket cap is $1.75. The game cap is $2.50.
The slate is unplayed. Model EV is not cash.

## Verdict

Tier 1 is four $1.00 Q4 RB legs. Tier 2 is two $1.25 quarter legs. Tier 3 is two $0.50 same-game slips and one $0.50 cross-game combo.
Priced pool: tier1 10, tier2 189, sgp_legs 245, sgps 1969, boost 16, quarter_players 487, blocked_grinders 2.
No scheme.md row is marked confirmed, so no full-game yard lean is on this card.
total_q3 is not priced. This build has no points model.
Pass overs for ATL, TB, IND, and JAX are off because of the wind fade.
Quarter shares use Empirical Bayes w_rec_q3_eb and w_rec_q4_eb from player target counts. Rush yards use w_rush_q4_eb.
The boost slip leaves displayed_boosted_payout blank. Apply the token on the laptop if it is live.
Q4 clock-grinder reception overs blocked: James Cook III, Kenneth Gainwell.

## Card

| Ticket | Tier | Game and kick | Legs | Book price | Model prob | Book implied | Tax-adj EV | Stake | Note |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| HR8-Q4-1 | 1 | IND @ JAX 1:00 PM ET | Bhayshul Tuten receptions_q4 under 0.5 (-200) | -200 | 0.8847 | 0.6667 | 32.7% | $1.00 | none |
| HR8-Q4-2 | 1 | CLE @ PIT 1:00 PM ET | Quinshon Judkins receptions_q4 over 0.5 (+130) | +130 | 0.6197 | 0.4348 | 42.5% | $1.00 | none |
| HR8-Q4-3 | 1 | TEN @ CIN 1:00 PM ET | Tony Pollard rec_yds_q4 over 0.5 (-105) | -105 | 0.7290 | 0.5122 | 42.3% | $1.00 | none |
| HR8-Q4-4 | 1 | MIN @ DET 1:00 PM ET | Aaron Jones Sr. rec_yds_q4 over 0.5 (+165) | +165 | 0.4974 | 0.3774 | 31.8% | $1.00 | none |
| HR8-CORE-1 | 2 | ARI @ DAL 1:00 PM ET | Dak Prescott rush_yds_q4 over 0.5 (+230) | +230 | 0.4119 | 0.3030 | 35.9% | $1.25 | roof TBD confirm at T-90 |
| HR8-CORE-2 | 2 | IND @ JAX 1:00 PM ET | Travis Hunter rec_yds_q3 over 0.5 (+200) | +200 | 0.4333 | 0.3333 | 30.0% | $1.25 | none |
| HR8-SGP-1 | 3 | ATL @ TB 1:00 PM ET | Austin Hooper receptions_q4 over 0.5 (+260); Bijan Robinson rush_yds_q4 over 14.5 (-120) | +260 + -120 | 0.3640 | 0.1515 | 140.3% | $0.50 | naive product; pair rho at or under 0.15 |
| HR8-SGP-2 | 3 | CLE @ PIT 1:00 PM ET | Aaron Rodgers pass_yds_q4 over 47.5 (-115); Jerry Jeudy receptions_q4 over 0.5 (+105) | -115 + +105 | 0.5575 | 0.2609 | 113.7% | $0.50 | naive product; pair rho at or under 0.15; QB CLAIMED not CONFIRMED |
| HR8-BOOST-1 | 3 | MIN @ DET 1:00 PM ET; CLE @ PIT 1:00 PM ET; LAC @ LAR 4:05 PM ET | Aaron Jones Sr. rec_yds_q4 over 0.5 (+165); Quinshon Judkins receptions_q4 over 0.5 (+130); Omarion Hampton receptions_q4 over 0.5 (+210) | +165 + +130 + +210 | 0.1165 | 0.0529 | 120.0% | $0.50 | designed for the profit-boost token; displayed payout left blank |

## Exposure

| Game | Exposure |
| --- | ---: |
| IND @ JAX | $2.25 |
| CLE @ PIT | $2.00 |
| MIN @ DET | $1.50 |
| ARI @ DAL | $1.25 |
| TEN @ CIN | $1.00 |
| ATL @ TB | $0.50 |
| LAC @ LAR | $0.50 |

## Book spread and total used for the script gate

| Game | Home spread | Total |
| --- | ---: | ---: |
| ARI @ DAL | -7.0 | 54.5 |
| ATL @ TB | -2.5 | 43.0 |
| BAL @ BUF | -3.0 | 54.5 |
| CLE @ PIT | -3.5 | 39.0 |
| IND @ JAX | -10.0 | 46.5 |
| KC @ DEN | 1.0 | 41.0 |
| LAC @ LAR | -6.5 | 45.5 |
| LV @ NYJ | -2.0 | 46.5 |
| MIN @ DET | -3.0 | 45.5 |
| NE @ MIA | 7.0 | 42.0 |
| TEN @ CIN | -12.5 | 46.5 |

Home spread is the home team's posted Hard Rock number. A negative number is a favorite.
A blank cell would fail a script-dependent Q4 leg closed. No blank cell was filled with a guess.
