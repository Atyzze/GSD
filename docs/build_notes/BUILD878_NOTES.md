# Build 878: the lexicon, every law against every known type

**Type: a reading build on the catalogue's side and Home, the operator's 2026-11-25 12:03 ("all laws should instead
carry multiple scores/probabilities vs all known phenotypes and how similar they are to the other phenotypes, a giant
matrix 2d"), made on their word of 23:25 to keep building to the roadmap's end.** No score, kind or decision moves:
the lexicon reads what the laws already measured; `tools/outputs_of_a_law.py --against` 870's record: 0 outputs
changed. No schema change. It may be applied to a running folder.

## For the folders

* Home's Top 100 says, after each law's mean degree, the known type it reads nearest at its deepest size ("a cubic
  lattice"), or "near no known type", its mouse-over how many of that type's spreads away; the filters gain "known
  type". Nothing to press.
* On a bundle, `python3 tools/lexicon_reading.py <bundle> --md <page> --json <file>` writes the matrix: every law
  against every type, the count by type, and the best-scoring laws with their nearest two types.

## What changed

1. **The lexicon** (`resources/catalogue/lexicon.json`, `gsd-lexicon-1`): the known types are the calibration table's
   geometries, 24 of them from its 27 families; two families that build one geometry two ways are one type (the
   cubic lattice and its quotient, the 4D hypercubic lattice and the tesseract quotient, the two trees), because the
   readings cannot tell them apart. The readings compared are the four probes' d (or their refusal), the mean degree
   and the giant piece's share.
2. **The matrix** (`observability/lexicon.py`): each family's profile at each size from the table's cells (each
   reading's mean and spread over the seeds, a probe refused where most seeds refuse it); a law's distance to a type
   is the root mean square, over the readings both have, of how many of the type's own spreads apart they are (the
   spread floored, a refusal against a value 3 apart, no reading more than 10), at the type's size nearest the law's;
   a law further than 3 from every type is near none of them, the sign of a new zone. The same reading from a
   folder's rung summary (`features_of_summary`) and from a bundle's `tables/rungs` row (`features_of_rung_row`).
3. **Home** (`services/api/landscape_worker.known_type_of`, `resources/ui/app.js`): every landscape entry carries
   its known type at its deepest size, the Top 100 shows it, and the filters choose by it.
4. **`tools/lexicon_reading.py`**: the matrix of a bundle, on the bundle's own calibration table or this tree's.

## Acceptance, line by line

| the acceptance (`docs/agent/NEXT_BUILD.md` at 877) | the test |
|---|---|
| the known answers first: every family of the table nearest its own type | `tests/unit/test_the_lexicon_reads_every_family_as_its_own_type.py`, the first: profiles from seeds 0 to 6, every held-out reading of seeds 7 to 9 from 1,000 nodes (564 of them, 27 families) nearest its own type |
| the matrix from a bundle's table and from the live folder, the same | the same file's second: a bundle's row and a folder's summary read alike, a law near none a new zone |
| no score, kind or decision moves | `outputs_of_a_law --against`: 0 changed |
| the full lane green | the Verification below |

Before the families were grouped, 33 of the 564 held-out readings went to the other family of their own geometry and
none elsewhere: that is what made those three types two families each.

## What it does not do

* **Curvature and the reach's growth** are not in the readings yet: the table's cells do not carry a curvature, and
  the reach's growth needs two sizes of a law; the six readings are what both sides have.
* **The survey's kinds** (empty, full, a start remembered) stay the catalogue's; the lexicon places a law among
  geometries, the catalogue among behaviours, and Home shows both.
* No bundle is in the tree, so the matrix of 174's or 176's laws waits on the operator's next one.

## Verification

4176 passed, 41 skipped in 1319.37s (3 lanes at once)
