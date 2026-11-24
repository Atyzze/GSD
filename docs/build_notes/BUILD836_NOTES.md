# Build 836: study 172's reading made ready while it runs: every chain's peak degree in the bundle, a reader of what a lower mean degree cap would cut, and 172's predictions in one command. Not for study 172's folder while its laws run; after its last law, only to make its bundle.

**Type: the study bundle and two readers; nothing the fleet runs or decides (the operator, 2026-11-21 04:23: "Sounds
like we should? But no rush as it only needs to change the bundling code?").**
Changed: `reporting/study_tables.py` (`chain_rows`, `CHAIN_FIELDS`; `tables(..., blobs=)` writes
`chains.ndjson.gz`), `reporting/study_bundle.py` (passes the folder's `var/blobs`). New: `tools/cap_reading.py`,
`tools/study_172_reading.py`, `tests/integration/test_the_bundle_carries_every_chain_s_peak_postgres.py`,
`tests/unit/test_the_cap_reading.py`, `tests/unit/test_the_study_172_reading.py`; `tests/unit/test_report_audit.py` lists no
report unread (report 23, the hang autopsy, is read now, by R2). `resources/readings/studies.json`:
171 stopped, 172 running. The schema did not change; no frozen source moved; against 835's record
(`tools/outputs_of_a_law.py --against`) 0 outputs moved; the table's lock prints `analysis-5.3.0 e639334808716378
89f4fed82d9adc27`.

## What the operator asked

At 03:54, whether the mean degree cap of 32 is worth what it costs in memory and how many interesting laws go above 16
(answered in the conversation from 171's progress bundle; the reader below makes that answer one command). At 04:23,
the chain peaks in the bundle, and: 171 stopped for 172, which runs on 835 to the end. At 04:29, study A's full run as
ten batches of 10,000 rather than five of 20,000, and the builds that wait on no data in this order: what reads the
whole study, the small items that touch nothing a study decides, stable last.

## Every chain's peak, in the bundle

The database keeps one chain's peak edge count a run, the empty start's (`attempts.peak_edge_count`), and report 28
each chain's final degree, the mean over its seeds. Every chain's peak is in the run's compact evidence, kept in the
folder's blob store (`artifact_retention.compact_artifact`; its chain records' `final.peak_edge_count`), kept after the
run's raw body is evicted.
A real seed on each engine was checked here: both write every chain's final and peak edge count. The bundle's tables
now carry `chains.ndjson.gz`: a row per finished simulation and chain, its final and peak edges and mean degree
(2 x edges / N), its largest degree, whether it ended at the cap and why it ended, its multiplier and whether it was an
audit, and the seed's peak memory as report 28 reads it (the last finished attempt not interrupted). A run whose
evidence cannot be read is one row saying why; the table failing is written in `tables/README.json` and leaves the
other tables whole. A bundle made where there is no blob store (a test's) has no chains table.

## tools/cap_reading.py

For each lower cap, the chains and laws that reach it at each size, the laws the too dense gate would hold back under it
(every chain still going at the cap on every seed at the design's sizes in a row, before the let-through; a law goes on
while one chain does, `every_chain`), the scoring laws it touches and the memory a seed takes by its densest chain,
with the top size's memory scaled to 262,144 and 1,048,576. Without a chains table it reads report 28's finals and
says that what a cap would touch is at least that. On 171's progress bundle (finals), at a cap of 16: 220 of 1,000 laws
have a chain at or above it at 1,024 and 52 of 133 at 65,536; the too dense gate would have held back 7 laws at 1,024,
7 at 4,096 and 2 at 16,384, 2 of them among the 16 scoring laws (scores 18 and 10, both at 1,024: their chains sit
near 32 at 64 to 1,024 and settle to a lattice's degree from 4,096); a third (score 3) had its scoring chain at the cap
three sizes in a row but another chain going. At a cap of 24: 4, 5 and 1, one scoring law. Memory a seed at 65,536:
median 1.14 GB with every chain at 8 or below, 4.45 GB (max 6.42) with a chain between 16 and the cap, 1.95 GB at the
cap; the top size scaled to 1,048,576, median 24 GB, a tenth above 83 GB, the heaviest 103 GB. A chain that reaches a
lower cap would have ended there, so its readings at that size would differ too; the reader does not count that.

## tools/study_172_reading.py

R1 to R7 of `study_172_criterion.json` read in one command, exit 1 if one fails. R4 replays each decision at 1,024 with
each fact gate acting alone, so a law's gates are known, and on a design with `one_die` holds every law against its
pick. Dry run on 171's progress bundle (12 s): R1 holds (4,722 replay, 0 of 2,687 learned decisions differ), R2 holds
(no zero-temperature seed unresolved after the ceiling among report 23's 100 ranked laws), R3 holds, R4 fails as
separate dice should (24 of 252 laws held by one gate went on, 2 of 359 held by two or more), R5 holds (594 of 995,
59.7%), R6 holds (21 of 1,000), R7 fails (164.5 core-hours: 1,000 laws, unfinished).

## For the operator

Nothing to apply now: 172 stays on 835. When its batch reads **done**, if you want every chain's peak in its bundle:
untick auto extend (so no law is added on 836), stop, apply 836, start, and make the study bundle; nothing 836 changes
is read by the fleet. Made on 835, the bundle is read the same way, the cap reader on finals.

## Verification

3726 passed in 1151.43s (3 lanes at once)
