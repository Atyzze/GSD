# Build 868: every plot of the law page says in plain words what it shows, and a line between two readings names both

**Type: a page build, asked for by the operator on 2026-11-25 at 14:17 to 14:22 (their words in `docs/HISTORY.md`).**
It may be applied to study 174's folder: only the law page and its test changed
(`graph_scale_dynamics/resources/ui/candidate.html`, `tests/ui/candidate_smoke.js`); no route, no reading, no score,
kind or decision moves (`tools/outputs_of_a_law.py --against` 865's record: 0 outputs changed).

## For the folders

**Study 174**: apply it and restart; open any law. Nothing the fleet runs changes.

## Plain words behind every title (14:17, 14:20, 14:22)

"each of the 4x4 plots/charts deserve their mouse over description, or also made visible when tapped/clicked and
hidden again on another click, a 'speach bubble' box ... a small paragraph an eli5 as compressed as possible ... the box
is arguably currently not explaining what negative and above 1 values are to be interpreted". Every plot of the 4x4
grid and every curve has a short paragraph behind its title (`TC_ELI5`, `tcInfo`): pointing at the title shows it,
clicking the title keeps it open until the next click. Each says what the plot measures, what a line, a plane and
space read, and how to read every range it can show: the kept share's 1 (its start's dimension kept), above 1 (a lower
dimension, tending to d of the start over d now), between 0 and 1 (melting towards random) and below 0 (denser than a
random wiring); the Einstein check's 1; d_w's 2; curvature's 0; the reach's slope.

## A line between two readings (14:22)

"mousing over a line in the color of a start should tell you which start it is and between which two data points
you're hovering ... but also when clicked in between". On the 4x4 grid, the run's rest plot and the curves, the
pointer near a line between two readings names the line's start (and seed, on a curve) and both readings at its ends,
each the table's own text (`tcSegments`, `tcPick`: a reading within 12 units first, else a line within 8, else a
reading within 26). A click pins the card where it is, a second click lets it go; on a touch screen the tap does
the same.

## Verification

4028 passed in 1252.35s (3 lanes at once)
