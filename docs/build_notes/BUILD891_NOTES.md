# Build 891: the zones one after another, the dex a list of zones, the lucky hits kept

**Type: an operations build, the zone map's sixth step (`docs/agent/ZONE_MAP.md`), on the operator's words of
2026-11-26 19:06 to 19:21** ("our system never tries to map multiple zones at the same time"; "the DEX should in the end just be a list of
zones") and of 2026-11-27 01:55 ("keep going, make all the builds needed so that our roadmap document may shrink").
No score, kind, gate or decision of any law moves, no frozen source and no schema. `tools/outputs_of_a_law.py
--against` 890's record: 0 outputs changed.

## For the folders

* **Study 178**: apply 891 and restart the fleet. When the first zone's search ends (890), the zone rule is asked
  again at once: the Map page's dex panel shows **the next zone** with how many laws were passed over, and above the
  term-set groups a table of **the zones searched**: each zone's region, its centre, how it ended, its laws alike, its
  edges and the size they held to, and its central law. G37's family is next by 887's reading of 177's dex. When no two
  laws of one term set are left within 0.1 of each other, the panel says "no zone left to choose" and the focus goes
  back to the best free scoring law, as before.
* **The dex**: every copy now carries, on each mapped region, its `zones` (below), each zone's central law among the
  dex's laws, and a `lucky` list. `python3 tools/dex.py zones <dex>` prints the zones it holds first, then the next zone
  the rule would choose with the laws those zones pass over.

## What changed

1. **A zone kept** (`zone_search.zone_of`, `zone_search.ended`, called by `focus._finish` when a searched law ends):
   its centre, kind and locked-in curves, its term set (`signature`), its laws alike and those near it, its **box**
   (each parameter's alike extent up and down, from the lines' `lo`), its edges with whether each held, the size they
   held to (16,384 when every edge held), its central law and its cost. Kept in the focus state's `zones` and, for a
   mapped zone, on its region's `zones`.
2. **The next zone** (`dex_check.next_zone`): the zone chosen goes to `zones_chosen`, and the rule (`zone_choice`) is
   asked again over the dex's verified laws without those `dex_check.searched` names: every centre searched before,
   the laws near an unconfirmed centre (not a zone at its radius), and the laws inside a mapped zone's box
   (`zone_search.within`: the same term set and every parameter within its extent). The first choice passes over the
   same laws, so a zone carried in by a dex is not searched again.
3. **The dex a list of zones** (`operations/dex.py`): a region's `zones` travel into the dex and back with the region
   (`study_seed` keeps them on a read-in region); each zone's central law is put among the dex's laws, so a study
   reading the dex runs it again to the dex's level with the rest; `lucky` lists the laws that ended with no zone
   around them (885's lucky hit: UNCONFIRMED), each with its spec and why, to revisit; `counts` gives `zones` and
   `lucky`; the dex's README says what each holds.
4. **The roadmap shrinks**: the planned builds made from 885 to 891 are one paragraph, the questions already answered
   (their answers in `docs/HISTORY.md`) and the slider's (gone at 885) are out: 877 lines to 790.

## Acceptance, line by line

| the acceptance | the test |
|---|---|
| a second zone searched after the first, the second term set's family; the first's laws passed over, inside its box or at its centre | `tests/integration/test_the_zones_are_searched_one_after_another_and_carried_in_the_dex_postgres.py` |
| no zone left: the choice says so and the focus goes back to the score | the same |
| the dex written with both zones on their regions and both central laws among its laws, read back with them | the same |
| a dex read in passes over every law its zones hold; `tools/dex.py zones` prints them and the next zone | the same |
| the Map page lists the zones searched, how each ended, its central law, the next zone and the laws passed over | `tests/ui/dashboard_smoke.js` |
| the first zone's search as at 890 | `tests/integration/test_the_first_zone_is_searched_by_stepping_and_halving_postgres.py` |
| no output of a law moves | `tools/outputs_of_a_law.py --against` 890's record: 0 outputs changed |
| the full lane green | the Verification below |

## What it does not do, and what the operator decides

* A zone read in from a dex is passed over by the rule, and its laws are read again with the dex's other laws; the
  region it rides on is placed by `study_seed` as before, `zones` kept. That path runs in the fleet, the copy is
  one key; the test reads the written dex back by `read_part` and by the dex tool, not through a second folder.
* An unconfirmed zone's near laws are passed over with its centre: a family that is not a zone at 0.1 around its
  most central law is not walked law by law. Say so if each of its laws should be tried as a centre.
* The lucky hits are listed, not searched or read again.
* **The operator decides**: 892 waits on study 178's first zones. Its search's benchmark says whether the lines'
  steps are the slow part (then each line's next two points at once), and whether a law taken by its score should
  be searched as a zone is in place of the rings (`docs/ROADMAP.md`, "Still open from 884 to 889").

## Verification

4235 passed, 41 skipped in 1425.50s (3 lanes at once)
