# Week 10 Sunday Hard Rock card, 2026-11-15

Do not submit a bet from this file. The operator types every ticket.

The stake sum is $18.00. That is the research allocation for this card.
The ticket cap is $2.50. The game cap is $4.50. The player cap is $4.50.
Singles use $12.00. Multi-leg slips use $6.00.

The number -110 is the reference juice ladder (REF_LADDER_NOT_BOOK).
It is not a captured Hard Rock price. Do not type it as a book price.
Spreads and totals are CLAIMED from config/odds/environment_odds_2026-11-15.csv.
Full-game yard lines are the slate median of team rates (LEAGUE_SLATE_MEDIAN_NOT_BOOK).
The Q3 reference line is the slate median of the two-way estimates, not a book total.

Munich NE at DET (9:30 AM ET) is off unless you pass --include-munich.
Kenneth Walker III (KC, questionable, Friday DNP) is off unless you pass
--allow-questionable-dnp after the Sunday 11:30 AM ET inactives.
Drew Lock pass legs are off. SEA rush legs can stay while he is the starter.
Domes (CAR at NO, SEA at LV) have no wind fade. A missing wind is not a zero.
Open-air wind of at least 12 mph blocks pass_yds OVER for HOU, CLE, BUF, and NYJ.
A passing leg in HOU at CLE, BUF at NYJ, or SF at DAL carries [WIND_REVIEW_NOTE].
No first_td leg is on this card. The packet has no first_td lean.

Same-game slips report the Gaussian joint and the Student-t joint (df=5).
When a pair rho is negative, the ticket uses the lower of the two joints.
The grader scores Brier once per settled ticket, not once per leg.

## Card

| Ticket | Tier | Game and kick | Legs | Model prob | Tax-adj EV | Stake | Note |
| --- | --- | --- | --- | ---: | ---: | ---: | --- |
| HR10-Q4-1 | 1 | SEA @ LV 4:05 PM ET | Emanuel Wilson rush_yds_q4 over 14.50 (ref -110) | 0.6600 | 26.0% | $1.75 | Q4 rush rate times the script factor; line 14.5 is not a book line; REF_LADDER_NOT_BOOK; -110 is not a Hard Rock price |
| HR10-Q4-2 | 1 | MIA @ IND 1:00 PM ET | Jonathan Taylor rush_yds_q4 over 14.50 (ref -110) | 0.6600 | 26.0% | $1.75 | Q4 rush rate times the script factor; line 14.5 is not a book line; REF_LADDER_NOT_BOOK; -110 is not a Hard Rock price |
| HR10-Q4-3 | 1 | SF @ DAL 4:25 PM ET | Christian McCaffrey receptions_q4 over 0.50 (ref -110) | 0.6600 | 26.0% | $1.75 | Poisson Q4 reception rate; line 0.5 is not a book line; REF_LADDER_NOT_BOOK; -110 is not a Hard Rock price |
| HR10-Q4-4 | 1 | BUF @ NYJ 1:00 PM ET | Braelon Allen receptions_q4 over 0.50 (ref -110) | 0.5852 | 11.7% | $1.75 | Poisson Q4 reception rate; line 0.5 is not a book line; REF_LADDER_NOT_BOOK; -110 is not a Hard Rock price |
| HR10-CORE-1 | 2 | MIN @ GB 1:00 PM ET | Kirk Cousins pass_yds under 229.85 (ref -110) | 0.6600 | 26.0% | $1.25 | LEAGUE_SLATE_MEDIAN_NOT_BOOK; REF_LADDER_NOT_BOOK; -110 is not a Hard Rock price |
| HR10-CORE-2 | 2 | MIN @ GB 1:00 PM ET | Jordan Love pass_yds under 229.85 (ref -110) | 0.6600 | 26.0% | $1.25 | LEAGUE_SLATE_MEDIAN_NOT_BOOK; REF_LADDER_NOT_BOOK; -110 is not a Hard Rock price |
| HR10-CORE-3 | 2 | SF @ DAL 4:25 PM ET | Christian McCaffrey rush_yds over 105.60 (ref -110) | 0.6600 | 26.0% | $1.25 | LEAGUE_SLATE_MEDIAN_NOT_BOOK; CONFIRMED scheme lean; REF_LADDER_NOT_BOOK; -110 is not a Hard Rock price |
| HR10-CORE-4 | 2 | BUF @ NYJ 1:00 PM ET | James Cook III rush_yds over 105.60 (ref -110) | 0.6600 | 26.0% | $1.25 | LEAGUE_SLATE_MEDIAN_NOT_BOOK; REF_LADDER_NOT_BOOK; -110 is not a Hard Rock price |
| HR10-SGP-1 | 3 | SF @ DAL 4:25 PM ET | Christian McCaffrey receptions_q4 over 0.50 (ref -110); Christian McCaffrey rush_yds over 105.60 (ref -110) | 0.4356 | 58.8% | $1.25 | Poisson Q4 reception rate; line 0.5 is not a book line; LEAGUE_SLATE_MEDIAN_NOT_BOOK; CONFIRMED scheme lean; gaussian_joint_p=0.435600; t_copula_joint_p=0.438003; REF_LADDER_NOT_BOOK; -110 is not a Hard Rock price |
| HR10-SGP-2 | 3 | SEA @ LV 4:05 PM ET | Emanuel Wilson rush_yds_q4 over 14.50 (ref -110); Zach Charbonnet rush_yds over 105.60 (ref -110) | 0.4356 | 58.8% | $1.25 | Q4 rush rate times the script factor; line 14.5 is not a book line; LEAGUE_SLATE_MEDIAN_NOT_BOOK; gaussian_joint_p=0.435600; t_copula_joint_p=0.438003; REF_LADDER_NOT_BOOK; -110 is not a Hard Rock price |
| HR10-SGP-3 | 3 | HOU @ CLE 1:00 PM ET | HOU at CLE total_q3 under 9.57 (ref -110); C.J. Stroud pass_yds under 229.85 (ref -110) | 0.4356 | 58.8% | $1.25 | mean 7.39; reference line is the slate median, not a book total; [WIND_REVIEW_NOTE]; LEAGUE_SLATE_MEDIAN_NOT_BOOK; CONFIRMED scheme lean; gaussian_joint_p=0.435600; t_copula_joint_p=0.438003; REF_LADDER_NOT_BOOK; -110 is not a Hard Rock price |
| HR10-BOOST-1 | 3 | MIA @ IND 1:00 PM ET; BUF @ NYJ 1:00 PM ET; MIN @ GB 1:00 PM ET | Jonathan Taylor rush_yds_q4 over 14.50 (ref -110); James Cook III rush_yds over 105.60 (ref -110); Kirk Cousins pass_yds under 229.85 (ref -110) | 0.2875 | 100.0% | $1.25 | Q4 rush rate times the script factor; line 14.5 is not a book line; LEAGUE_SLATE_MEDIAN_NOT_BOOK; rho=0; one leg per game; REF_LADDER_NOT_BOOK; -110 is not a Hard Rock price |
| HR10-CROSS-1 | 3 | LAR @ ARI 4:05 PM ET; JAX @ TEN 1:00 PM ET; CAR @ NO 1:00 PM ET | Kyren Williams rush_yds over 105.60 (ref -110); Bhayshul Tuten rush_yds over 105.60 (ref -110); Chuba Hubbard rush_yds over 105.60 (ref -110) | 0.2630 | 83.0% | $1.00 | LEAGUE_SLATE_MEDIAN_NOT_BOOK; rho=0; one leg per game; REF_LADDER_NOT_BOOK; -110 is not a Hard Rock price |

## Exposure

| Game | Exposure |
| --- | ---: |
| BUF @ NYJ | $4.25 |
| SF @ DAL | $4.25 |
| MIN @ GB | $3.75 |
| MIA @ IND | $3.00 |
| SEA @ LV | $3.00 |
| HOU @ CLE | $1.25 |
| CAR @ NO | $1.00 |
| JAX @ TEN | $1.00 |
| LAR @ ARI | $1.00 |

## Packet spread and total

Home spread is the home team's CLAIMED number. A negative number is a favorite.
NE at DET is listed and is not on the default card.

| Game | Spread | Total | On default card |
| --- | ---: | ---: | --- |
| NE @ DET 9:30 AM ET | -2.5 | 49.5 | no |
| KC @ ATL 1:00 PM ET | 3.0 | 47.5 | yes |
| HOU @ CLE 1:00 PM ET | 4.5 | 40.5 | yes |
| MIN @ GB 1:00 PM ET | -2.5 | 42.5 | yes |
| JAX @ TEN 1:00 PM ET | 10.5 | 46.5 | yes |
| MIA @ IND 1:00 PM ET | -3.5 | 38.5 | yes |
| CAR @ NO 1:00 PM ET | -2.5 | 48.5 | yes |
| BUF @ NYJ 1:00 PM ET | 8.5 | 50.5 | yes |
| SEA @ LV 4:05 PM ET | 6.5 | 40.5 | yes |
| LAR @ ARI 4:05 PM ET | 9.5 | 39.5 | yes |
| SF @ DAL 4:25 PM ET | 4.5 | 55.5 | yes |

Q4 rush reference line is 14.5 with sigma 8. The mean is the packet Q4 rate
times the script factor. A bench-blowout RB1 rush_yds_q4 OVER is blocked
(James Cook III, Kyren Williams, Bhayshul Tuten). Use the full-game rush over.
