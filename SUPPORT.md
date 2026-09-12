# Support

See the `## Support` block in [README.md](README.md). Canon: https://github.com/cemini23/cemini-claude-code-CCC/blob/main/SUPPORT.md

## Settlement and voids

CeminiParlays does not settle tickets. Voids, pushes, and SGP reprices happen in-app. `grade` needs the **settled** multiplier you see after the book drops a voided leg. A sportsbook miss after a void is 0× (the ticket lost). All-void refunds 1×. A missing sportsbook multiplier is never a silent 1× refund. Disputes go to the book, not this CLI.
