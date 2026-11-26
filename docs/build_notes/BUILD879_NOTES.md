# Build 879: the phenotype, the shortest description of a law's quantities

**Type: a reading build beside 878's lexicon, the operator's 2026-11-25 12:12 (each of the law page's quantities over
N fitted by the fewest forms that describe it, a law's phenotype the set of those forms, a new law read against the
set already seen), made on their word of 23:25 to keep building to the roadmap's end.** No score, kind or decision
moves; `tools/outputs_of_a_law.py --against` 870's record: 0 outputs changed. No schema change.

## For the folders

* Nothing to press. On a bundle, `python3 tools/phenotype_reading.py <bundle> --json <file>` writes every law's
  phenotype, the categories it falls in and the calibration geometry whose phenotype it shares most.

## What changed

1. **The forms** (`resources/catalogue/phenotype.json`, `gsd-phenotype-1`, and `observability/phenotype.py`): a
   quantity's readings over N from 256 (at least three sizes) are a constant when they stay within 5% of their
   weighted mean; otherwise a power of N and a straight line in log N are each fitted, weighted by the readings at
   each size, and the one with the smaller relative residuals describes it. A phenotype is the form of every
   quantity on every start; its categories name them ("reach as N^(1/2), d near 2", "reach as log N, an expander or a
   tree", "d_s constant"), several to a law and overlapping; two phenotypes are as alike as the share of their
   categories they hold in common, and a new law is read against the phenotypes already seen (`nearest_seen`).
2. **The known answers, committed before any law was read**: 20 of the calibration table's families, the reach each
   geometry predicts: a lattice's as N to one over its dimension (the square, triangular and honeycomb lattices 1/2,
   the four cubic 1/3, the two 4D 1/4), the ring's as N, the Sierpinski gasket's and carpet's as one over their
   fractal dimensions (0.631, 0.528), a uniform random tree's as the square root of N, and log N for the balanced
   tree, the random regular graphs, three random graphs and the hyperbolic tiling. Every one holds, the exponents
   within 0.06.
3. **`tools/phenotype_reading.py`**: a bundle's laws from `tables/rungs` (mean degree, giant piece, the four d's and
   the reach over N, weighted by seeds), the geometries' phenotypes from the calibration table.

## Acceptance, line by line

| the acceptance (`docs/agent/NEXT_BUILD.md` at 878) | the test |
|---|---|
| judged first on the calibration table's families, committed before any law is read | `tests/unit/test_the_phenotype_fits_each_geometry_its_own_form.py`, the first: 20 families, each its predicted form and exponent |
| the fewest forms; a phenotype read against those seen | the same file's second and third: a constant where the readings stay flat, fewer than three sizes no form, a law grown like a 2D lattice read like one |
| no score, kind or decision moves | `outputs_of_a_law --against`: 0 changed |
| the full lane green | the Verification below |

## What it does not do

* **Every start apart**: a bundle's rung rows hold a law's quantities over its seeds, not start by start, so the tool
  reads "every start" as one; the law page's chains, start by start, are the next reader.
* **The other quantities** (curvature, energy, triangles and squares per node, the Einstein check, the kept share)
  are fitted where a reader hands them over; the bundle's tables do not carry them over N yet.
* **The null map** and the new terms (the Ricci curvature in two forms) wait on every term's load read on a study,
  which needs the operator's next bundle.

## Verification

4179 passed, 41 skipped in 1313.40s (3 lanes at once)
