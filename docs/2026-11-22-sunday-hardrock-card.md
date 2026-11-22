# Week 11 Hard Rock card, 2026-11-22

Do not submit a bet from this file. Type any ticket yourself.
HR11-1 is already placed for $5.00. Those three legs are not on this card.
Remaining bankroll: $18.00.
Allocated on this card: $18.00.
Unallocated: $0.00.
Each new ticket is $3.00 to $6.00. Three tickets are $6.00 each.
Four tickets are $6.00, $6.00, $3.00, and $3.00.
The card keeps the pack with the higher stake-weighted EV.
A ticket is +EV only when the copula joint beats the estimated Hard Rock price.
Same-line +EV legs: 0.
Line-shift +EV legs: 1.
Q4 Poisson +EV legs: 14.
Bucket A priced tickets: 478.
Bucket B priced tickets: 113.

Prices come from config/week11/live_lines_2026-11-22.csv.
SAME_LINE_DEVIG is a power de-vig when two other books post the Hard Rock line.
LINE_SHIFT_DEVIG moves an adjacent yard line with the normal tail in half_edge.py.
Q4_POISSON_MODEL uses the shrunk q4_rec_pg rate. The line is a live Hard Rock line.
The gate is games at least 6 and target-share rank 1. A missing row is not a leg.
Team offense and team defense totals are not a player mean.
Est. HR Parlay Odds is the product of the posted leg prices.
When pair rho is above 0.15, the repo SGP tax shortens that price.
That price is not a captured Hard Rock same-game quote.

Highest line-shift leg: Breece Hall rec_yds under 21.50 at 1.24% (LINE_SHIFT_DEVIG).
Ollie Gordon II q4_rec_pg raw is 0.00. Shrinkage pulls the rate toward the league mean. The under uses that shrunk Poisson and the live Hard Rock line. Reject the leg if you do not want a zero-catch sample on the card.
Jahmyr Gibbs receptions_q4 is not the booked rush_yds_q4 leg. HR11-1 already has the rush_yds_q4 leg.

## Tickets

Ticket | Stake | Exact HR Legs & Odds | Pricing Source | Est. HR Parlay Odds | Fair Parlay Odds | EV %
--- | --- | --- | --- | --- | --- | ---
HR11-2 | $6.00 | Ollie Gordon II receptions_q4 under 0.50 (HR +120); Braelon Allen receptions_q4 over 0.50 (HR +180); Justice Hill receptions_q4 under 0.50 (HR -110) | Q4_POISSON_MODEL | +1076 | +291 | 201.09%
HR11-3 | $6.00 | Cam Skattebo receptions_q4 under 0.50 (HR -120); Jahmyr Gibbs receptions_q4 under 0.50 (HR +130); Ashton Jeanty receptions_q4 under 1.50 (HR -195) | Q4_POISSON_MODEL | +538 | +290 | 63.43%
HR11-4 | $6.00 | Bucky Irving receptions_q4 under 0.50 (HR +100); Javonte Williams receptions_q4 over 0.50 (HR +155); Keaton Mitchell receptions_q4 over 0.50 (HR +155) | Q4_POISSON_MODEL | +1200 | +797 | 45.05%

## Legs

Player | Team | Market | Side | HR Line | HR Odds | Fair Odds | Edge % | Pricing Source
--- | --- | --- | --- | --- | --- | --- | --- | ---
Ollie Gordon II | MIA | receptions_q4 | under | 0.50 | +120 | -373 | 73.48% | Q4_POISSON_MODEL
Braelon Allen | NYJ | receptions_q4 | over | 0.50 | +180 | -100 | 40.22% | Q4_POISSON_MODEL
Justice Hill | BAL | receptions_q4 | under | 0.50 | -110 | -184 | 23.77% | Q4_POISSON_MODEL
Cam Skattebo | NYG | receptions_q4 | under | 0.50 | -120 | -196 | 21.32% | Q4_POISSON_MODEL
Jahmyr Gibbs | DET | receptions_q4 | under | 0.50 | +130 | -103 | 16.81% | Q4_POISSON_MODEL
Bucky Irving | TB | receptions_q4 | under | 0.50 | +100 | -137 | 15.67% | Q4_POISSON_MODEL
Ashton Jeanty | LV | receptions_q4 | under | 1.50 | -195 | -321 | 15.33% | Q4_POISSON_MODEL
Javonte Williams | DAL | receptions_q4 | over | 0.50 | +155 | +128 | 11.98% | Q4_POISSON_MODEL
Keaton Mitchell | LAC | receptions_q4 | over | 0.50 | +155 | +128 | 11.98% | Q4_POISSON_MODEL
Ty Johnson | BUF | receptions_q4 | over | 0.50 | +195 | +174 | 7.66% | Q4_POISSON_MODEL
Tyler Allgeier | ARI | receptions_q4 | over | 0.50 | +135 | +122 | 6.03% | Q4_POISSON_MODEL
Alvin Kamara | NO | receptions_q4 | under | 0.50 | +115 | +109 | 2.83% | Q4_POISSON_MODEL
Chuba Hubbard | CAR | receptions_q4 | under | 0.50 | +115 | +112 | 1.26% | Q4_POISSON_MODEL
Breece Hall | NYJ | rec_yds | under | 21.50 | -115 | -118 | 1.24% | LINE_SHIFT_DEVIG
Jaylen Warren | PIT | receptions_q4 | over | 0.50 | -105 | -105 | 0.21% | Q4_POISSON_MODEL
Bhayshul Tuten | JAX | receptions_q4 | under | 0.50 | -210 | -204 | -0.88% | Q4_POISSON_MODEL
Courtland Sutton |  | rec_yds | over | 30.50 | -120 | -117 | -1.13% | LINE_SHIFT_DEVIG
Fernando Mendoza | LV | interceptions | under | 0.50 | +120 | +123 | -1.52% | SAME_LINE_DEVIG
Kalif Raymond |  | receptions | under | 2.50 | -135 | -129 | -1.78% | SAME_LINE_DEVIG
Josh Johnson | ARI | interceptions | over | 0.50 | -200 | -189 | -1.90% | SAME_LINE_DEVIG

## Checks

QB check on every new pass leg must be FAIL_BACKUP_QB=0.
Josh Johnson pass_yds, James Cook III rush_yds, and Jahmyr Gibbs rush_yds_q4 are booked.
Other markets for those three players stay eligible.
Out, IR, and doubtful names are off. The Sunday T-90 list is off.
DAL pass and receiving yards stay off while the AT&T roof is retractable and exposed.
config/rosters/nfl.json was not rewritten.
