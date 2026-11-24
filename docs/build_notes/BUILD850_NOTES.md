# Build 850: the catalogue of behaviours, every law of a bundle placed in it with how early its kind was known, and the still lattice scored lowest beside the score in force, its criterion committed first. It changes no decision and no score in force and may be applied to any folder.

**Type: a reading and a candidate, asked for by the operator on 2026-11-24 at 10:22 ("all behavior needs to have a
list of this is a kind of behavior, this is how to spot it early, and this is how we score it"; "lattices that don't
change shouldn't be scored as well. They should basically get the lowest possible score"; "I think we will naturally
feel whenever we need a consolidation build"; 10:43: "Any probe that settles from empty or random, I want to
know").** New: `graph_scale_dynamics/resources/catalogue/catalogue.json` (the
kinds, `gsd-catalogue-1`, packaged by `pyproject.toml` as `catalogue/*.json`, outside the frozen templates), `graph_scale_dynamics/observability/catalogue.py` (`kind`, `still`, `agreeing`, `alike`),
`tools/catalogue_reading.py` and its test `tests/unit/test_the_behaviour_catalogue.py`;
`graph_scale_dynamics/resources/readings/still_lattice_criterion_1.json`, committed at 09:41:48Z before any later
bundle, in `tests/fixtures/committed_readings.json` and `docs/readings/README.md`. Changed: the consolidation comes
when one is needed, on no schedule (`docs/ROADMAP.md`, "Build cadence", and `tests/unit/test_build_cadence.py`, which
now holds that no line plans the next one); the operator's words of 10:22 in `docs/HISTORY.md`; the last pointers to
the papers' folder in `docs/readings/README.md` and the handoff. Nothing under `decisions/`, `scaleflow/`,
`measurements/`, `engine/` or `engine_rs/` moved; no frozen source moved; the schema did not change. Against 849's
record (`tools/outputs_of_a_law.py --against`) 0 outputs moved.

## The catalogue

Each kind has what it is, how a law is placed in it at a size, and how it scores (`docs/ARCHITECTURE.md`, "The
catalogue of behaviours"). In order, the first that applies: `grown` (any probe on the empty or the random start steps
within the score's own margin at three sizes in a row from 4,096, by its value alone), `made` (two starts or more agree
on d and mean degree within a tenth, d at least 1.5), `ring` (the same, d below 1.5: rings, chains and trees, told from
made by the d they agree on and not by the mean degree), `empty`, `full` (every chain that grows ends at the cap),
`frozen` (a lattice chain at its own degree within 5% that accepted no move), `still` (the same with at most 0.05
accepted moves an edge, some), `rewired`, `moved`, `broken`, `apart`, `unread`. The stream (175's H15) and the tree of
long paths are listed with where they are read. `grown` and the split of `frozen` from `still` are the operator's of
10:43 ("Any probe that settles from empty or random, I want to know. And settles means at the 3 highest rungs, it shows
convergence behavior"; "we should make a difference between a still lattice, which has a small set of moves, versus
actually frozen"). The numbers were chosen on study 174's first bundle and 175's second; a changed number is a new
criterion.

## Study 174's first bundle (6,168 laws; the 5 of its control campaigns left out)

At their deepest size: grown 8, made 8, ring 224, empty 2,397, full 770, frozen 43, still 52, rewired 347, moved 2,221,
broken 27, unread 71. **The 8 grown** are one-dimensional, d 1.0 to 1.15 from the twin starts at 65,536, every probe or
nearly every one stepping within its margin from 4,096: `18856793523d` and `3a8569fc6094` grow from empty and from random
one connected piece holding every node at mean degree 2.00, a single loop with at most short branches; `63e1fee2ce13`,
`69e17ab3949e` and `cad1627c4aa3` many separate loops at mean degree 2.00; `559f8b6fd288` (H01) chains at 1.89;
`99e25674e37a` a one-dimensional piece with triangles and squares at mean degree 3 to 4; `61e41fb7b3cb` one loop from
empty. The score in force settles none of them: its reach rule reads their reach growing as about d 2 where the probes
read 1. A single loop is a known answer (d 1), so whether that rule wrongly refuses it is read first in 851. 20 more
laws settle a twin probe at two sizes, their third not read or not settled.

Of the 306 laws read from 16,384, called at 4,096 against their kind at the deepest size: frozen or still 21 of 21
right, 21 of the 48 frozen or still at depth already called; ring 19 of 32 right, 19 of 22 caught; made 1 of 2, the one
made at depth caught (H31); empty 8 of 8; full 38 of 45; moved 95 of 138. At 1,024: frozen or still 16 of 16 right, 16
of 48 caught. Grown cannot be called before 65,536, its third size. Lattice chains: 63 still or frozen at 1,024 with a
deeper size, all 63 still or frozen at every deeper one; 25 of 25 at 4,096; of 88 still or frozen from 16,384, 21 were
at 1,024 and 25 at 4,096. The score in force scores 58 drawn laws; 43 are still or frozen at the size they score at
and would score 1.

## Study 175's second bundle (595 laws, running)

At their deepest size so far: grown 1 (`559f8b6fd288`, H01, its run again), made 17, ring 17, full 29, frozen 3, still
257, rewired 28, moved 239, broken 2, apart 2. **The 17 made are H31 (`3931d03e8edf`) and all 16 of its variants**,
every radius to a tenth: at 4,096 their bcc and fcc starts agree at d 3.42 to 3.50 and mean degree 25 to 29, none read
at 16,384 yet. H31 read d 4.0 at 16,384 in 174, so its d still rises with the size: made, and a region at 4,096, but
not yet a settled dimension. Of the 300 laws read from 16,384, frozen or still called at 1,024: 146 of 146 right, 146
of 247 caught; at 4,096: 211 of 211, 211 of 247. A lattice frozen at 1,024 is often still, not frozen, deeper (13 of
14): the two are told apart at the deepest size, and both score lowest. Lattice chains: 233 of 235 still or frozen at
1,024 stayed so at every deeper size, 295 of 296 at 4,096; of 491 still or frozen from 16,384, 232 were at 1,024 and
296 at 4,096. 246 of the 264 scoring laws are still or frozen at the size they score at.

So the early call of a lattice left alone is right 99% of the time or better in both studies and never hid a made law
or a ring, but it catches a quarter to two thirds of them at 1,024 or 4,096: many lattices fill up or rewire at small
sizes and stop moving only at large ones. A law's own energy at the perfect lattice (whether any single move pays)
could call them before any chain runs; `tools/neutral_moves_check.py` is where that would start. A mean degree below 2
leaves fewer edges than nodes, so nothing beyond a loop can form; it is not a kind of its own (the operator, 10:43:
"maybe there is not much compute saved by scanning for this"), and the reader can count such laws at no cost if a gate
for them is ever wanted.

## The criterion

`still_lattice_criterion_1.json`: judged on the first bundle of 174 or 175 sent after it, S1 (at least 98% of the
lattice chains still at 1,024, and at 4,096, are still at every deeper size), S2 (no law made or a ring at its
deepest size from 16,384 was called still at 1,024 or 4,096), S3 (at least half the scoring laws are still, reported);
still there means still or frozen, as the criterion's rule has it (at most 0.05 accepted moves an edge, none included).
If S1 and S2 hold, the still lattice scores 1 in the score in force, as the operator asked, and stopping a law early by
the still call is offered to them with what it saves and what it risks.

## For the folders

Nothing a folder decides or scores changes; 850 may be given to 174's or 175's folder when it suits, each needing one
restart of its own command.

## Verification

3888 passed in 1392.44s (3 lanes at once)
