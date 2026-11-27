# Build 888: a dex read again to N=4,096, law by law, from the start, with its progress, and written anew on a find

**Type: an operations build, on the operator's words of 2026-11-27 01:35, watching study 178 read 177's dex on 887**
("ideally, the import folder is there from the start and so that if its pre seeded with a dex, the first thing it does
is indeed verify all its listed laws/zones"; "if we could prioritize the work grouped by all sims needed for 1 law, so
that we can see a progress bar per zone/candidate"; "N64, N256, N1024 and N4096 as base level of verification it
defaults to, unless its internal dex-lvl is set at a higher N"; "whenever a new zone/candidate is found that isnt in
the dex yet [...] also export new copy of the dex to the export folder"). `docs/ROADMAP.md`, "From 887's run". No
score, kind, gate or decision of any law moves, no frozen source and no schema; the science is 887's.
`tools/outputs_of_a_law.py --against` 887's record: 0 outputs changed.

## For the folders

* **Study 178, on 887 now**: apply 888 and restart the fleet. Its dex campaign is judged at N=4,096: each law's verdict
  comes once its 12 runs at 64 to 4,096 are done, and the fleet takes the Dex work law by law, every law to 4,096 before
  any law's deeper sizes. The campaign was made on 887 with a ladder to 65,536, so its laws still go deeper once every
  law has read to 4,096; a campaign's ladder is never changed under it.
* **Or study 178 afresh**, if those deeper runs are not wanted: unpack 888 into a new folder; its `import/` is there.
  Put `dex_177_2026-11-26T19-33-48Z.tar.zst` into it, then `uv run python main.py run --allow-host <host> --study 178`.
  The dex is read in as the study starts, before the fleet takes any work: the dex campaign is made with a ladder of
  64 to 4,096, and its laws are read term set by term set, the largest first (G79's family of 45, then G37's 34, then
  S176-C11-G4's 31).
* **What to watch**: "Working now" lists one row per law: its runs done of the 12 it is planned to read, what runs now,
  a bar; the per-seed rows are folded beneath. The Seeds panel's bar counts the dex's laws read again. The last dex line
  says why each copy was written.

## What changed

1. **The import folder from the start**: `import/` ships in the tree (its `README.md`; `.gitignore` keeps the rest out)
   and the controller makes it as it starts, the study's start too (`study.make_import_folder`). A dex in it when a
   study starts is read in by the start itself (`study.read_in_at_start`), before the fleet's first pass.
2. **A dex read again to N=4,096 by default** (`study_design.verify_level`, `study_design.ladder_to`): the dex campaign's
   ladder stops at the ladder's base, unless the design's `dex` entry or the dex itself asks for more (`verify_to` in the
   dex, written by `tools/dex.py make --verify-to N`), never past the design's top. A law is judged once it has read to
   that level on every seed, or once decided (`dex_check.read_to_level`), so a dex campaign made earlier with a deeper
   ladder is judged at 4,096 too.
3. **The Dex work law by law**: the fleet's Dex step claims `by_law` (`work_groups.claim_bounds`, `repo_jobs.claim_job`):
   the laws in the order they were read in, each law's runs by size, every law's sizes to 4,096 before any deeper size.
   In a study that verifies its dex first, the laws are read in term set by term set, the largest first
   (`study_seed.reading_order`), so a zone's laws finish together. The zone, depth and blind steps are unchanged.
4. **"Working now" by law** (`zone_live.law_rows`): one row per law under way, with its runs done of those planned (its
   seeds at every size of its ladder, to its level for a Dex law), the sizes and seeds running now, how long, and a
   bar (done, and the runs under way by their typical time). The per-seed table is folded beneath.
5. **A new copy of the dex on a find** (`dex.keep`, `dex.news`): besides the hourly copy, a new one is written when a law
   scoring here is not in the last dex, when a zone is mapped since, or when more of the dex's laws are verified here;
   looked at once a minute, never two within ten minutes. The last dex line says why.
6. **The Map page while the dex is verified**: the focus panel says no law is taken before every law has read, not that
   every law is mapped.

## Acceptance, line by line

| the acceptance | the test |
|---|---|
| the import folder from the start; a dex in it read in at the study's start, its campaign to N=4,096, its laws by term set | `tests/integration/test_a_dex_is_read_again_law_by_law_to_its_level_postgres.py`, the first |
| the Dex work claimed law by law, every law to 4,096 before a deeper size, through the worker's own claim | the same |
| a dex asking for 16,384 is read to 16,384; a law read to its level is judged without its decision | the second |
| a new dex on a new law, a new zone, more verified; never twice in ten minutes; hourly as before | the third |
| "Working now" one row per law with its runs and progress | the fourth; `tests/ui/dashboard_smoke.js` |
| the Dex step's claim bounds | `tests/unit/test_the_work_groups_share_the_fleet.py` |
| no output of a law moves | `tools/outputs_of_a_law.py --against` 887's record: 0 outputs changed |
| the full lane green | the Verification below |

## What it does not do

* The zone's search (889, `docs/ROADMAP.md`, "From 886", item 4) and zones one after another (890).
* A dex campaign's ladder is not cut under a running study: 178's laws on 887 still read past 4,096 once every law has
  read to it.
* The zone and blind steps keep their order of claims; only the Dex step is taken law by law.

## The pull requests

Push access was given at 01:42 ("Try again, worked last time"). `main` holds 880 (#18 to #27 merged 871 to 880). #28
holds 881 to 886 (886's archive on `main`), #29 887 on it, and 888's on 887. Merge them in order.

## Verification

4227 passed, 41 skipped in 1403.53s (3 lanes at once)
