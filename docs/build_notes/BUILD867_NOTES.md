# Build 867: the law page read in one pass, every plot answers a mouse-over, one table of every value plotted, the curves a row a size, the sections lettered and the plots numbered

**Type: a page build, asked for by the operator on 2026-11-25 at 13:28, 13:34 and 14:11 (their words in
`docs/HISTORY.md`).** It may be applied to study 174's folder: only the law page and its test changed
(`graph_scale_dynamics/resources/ui/candidate.html`, `tests/ui/candidate_smoke.js`); no route, no reading, no score,
kind or decision moves (`tools/outputs_of_a_law.py --against` 865's record: 0 outputs changed).

## For the folders

**Study 174**: apply it and restart; open any law. Nothing the fleet runs changes.

## The page, top to bottom (13:28, 13:34)

"perhaps its time to number all the plot boxes ... the boxes/containers you can then label A->Z, then numbers can be
for within a zone". Every section heading carries a letter, A to Z in the page's order (`pgLabel`); every plot and
table in a section carries the letter and its number, top left to bottom right, on the plot's corner (the number's
mouse-over says what the plot draws) or before the table's first heading. The chains' section reads:

* **1 to 16, the 4x4 grid** as before: the graph counted, the four probes, geometry and energy, the run.
* **17, one table of every value the plots draw** ("we want the colums to be the rows basically, and show the highest
  N first ... an exact 1to1 copy of the above dataset"): a row a quantity and a start, a column a size, the largest
  first, so the page scrolls down, not across. Each value is the string the plot's mouse-over shows; the test checks
  every plotted point against its cell. No cell has a mouse-over. Its groups follow the grid (the graph counted, with
  the seeds' logarithmic-diameter flags; the four probes; geometry and energy; the run) and then the starts against
  each other and how far from a space.
* **18 on, each chain's curves, a row of four a size, the smallest first** ("not stack this one behind a filter by
  default show them as a grid starting from the msallest ... to the highest possible N Row"): every size's curves
  are asked for in turn, smallest first, and drawn as they come; the size buttons are gone.
* Then how far every two chains are apart (folded), one size in detail (folded; it now also lists each seed's meeting
  on that size, what the strip's mouse-over said), and the explanation (folded).

## Mouse-overs (13:28)

"our main 4x4 grid which is missing mouse overs so that when one hovers over a line, one can see the actual chain
start type+value at that point". Every plot of the chains' section and every curve answers the pointer with the
nearest point within 26 units of its drawing: a ring on the point and a card with the start, the size and the value
(the 4x4 grid: the mean, its standard error, the seeds it was read on and each seed's value; the curves: the start,
its seed, the size and the curve's value at that step or radius; the run: each seed's check, or the seeds' median).
The browser's own slow tooltips on the points are taken off once the card works (`tcHover`).

## What the strip, the stage cards and the starts' table became (13:34)

"the red circled area ... its too dense text, we want either clean tables or good plots". The strip "how the chains
ended, size by size" and the stage cards of "how far from a space" are gone; what they said is rows of the one table:
the chains' reading at each size and each chain's against the chain from empty, how the seeds ended, from when every
check held, the seeds lower in energy than from empty, the chains not moving, the chain that ended alone at the cap;
the stages in one line over the space's rows (passed, failed, not reached, the failed one's reason), each property a
row a chain with its integer d beside its name. The starts' table (a row a size) is turned the same way: what the
starts did, the groups that met, each lattice against its own start, its start's mean degree and its distance from
its start's own reading, the widest apart; its trend is the group's line. Nothing they held is dropped.

**The rungs' table** ("revisit whether all the other tables can be perhaps consolidated"): once every chain's reading
arrives it is one row a size, its jobs, compute, certificate and evidence, and the chains under the connectivity floor
there; what each chain read is in the chains' table, not repeated. Before the readings arrive, and when they cannot
be read, it shows what the size read, as before. The graph's tables, the census and the score's tables are as they
were: each holds what no other does.

## The two run plots (13:34)

"the 2 plots circled in yellow, they have the same shape, are not they not portraying the same thing". They are not:
the energy gap is how far apart the chains from different starts are, the checks are what the stopping rule reads
inside each chain (at zero temperature how much it still fell late in its run, else the split z). A law can pass the
second (every chain at rest) and fail the first (they rest apart). Both stay; the checks now draw the seeds' median a
line a size, smooth like the gap, each seed's check a faint dot under it, each answering the pointer.

## How much of its start each chain keeps (14:11)

"values between 0 and 1 made sense, but above 1? huh?". The kept share is a place on a log scale of reach,
log(R / R_random) / log(R_start / R_random) (`research/reach.kept`): 0 a random wiring of its degree, 1 its start; above
2 a stretched chain, reaching further than its start, of lower dimension; below 0 a chain denser than a random wiring.
As reach grows as N^(1/d), at large N it tends to d of the start over d of the chain: a ring from the tesseract towards
4, from the cubic lattices towards 3, from the square and triangular towards 2, which C2-G3187's chains approach. The
plot now draws 0 and 1 as dashed lines, "a random wiring" and "its start"; the number's mouse-over says the rest.

## Verification

4028 passed in 1306.48s (3 lanes at once)
