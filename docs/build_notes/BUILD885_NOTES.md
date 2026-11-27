# Build 885: one order for the fleet, a zone that stands at a smaller ring, and zones by name

**Type: a scheduling build, on the operator's words of 2026-11-26 19:06 to 19:21 ("only do blind draws when there are
no seeds/zones to confirm"; "we also dont need the allocation slider, the fleet naturally swaps between what work is
most required"; "our system never tries to map multiple zones at the same time. It always focuses on one zone at the
same time with all its available compute"; "'no regions mapped' arent it zones? too many different namings").** No
score, kind or decision of any law moves, no frozen source and no schema; the science is 884's. It is applied to 177's
running folder.

## For the folders

* **Study 177**: apply 885 and restart. The fleet then takes its work in one order, runs and probes alike: G37's zone,
  the depth worker, the Dex laws read again, the blind draw, and the neighbours earlier laws left last. G37's
  neighbours, whose runs at 16,384 were done and whose probes waited (884's page at 19:02: 31 laws "its probes being
  read", up to 27 minutes, 110 probes queued and 3 read at a time), are read first and on most of the slots. If ring
  0.1 is not two thirds "moved", the zone stands at ring 0.01 when that one is, instead of ending.

## What was wrong (884's Map page and Home of 19:02)

1. **The probes were starved by the blind draw's queue**: the slots are split between probes and runs by the probe
   backlog against every queued run (`scheduling/allocation.compute_allocation`); the blind draw's 1,091 queued runs
   left the probes 3 of 16 (16 times 220 over 220 plus about 1,470).
2. **Probes are read by size, small first**: a probe takes its run's priority, the base block's before the deep
   sizes', so the zone's readings at 16,384 waited behind every blind and Dex reading at 64 to 4,096.
3. **The fleet split itself by shares**: the slider gave the zone a share and the blind draw the rest, and with
   nothing of G37's to run, its share went to the neighbours earlier laws left (11 workers at 19:02).
4. **One ring decided**: a law whose ring at 0.1 was not two thirds alike ended "unconfirmed" whatever its ring at
   0.01 read; the two neighbours of G37's ring 0.1 read so far both read "made".
5. **"so far" was judged against the law's own campaign**: its three seeds, one of which reads "made", where each of
   its six seeds in its seeds' campaign reads "moved".
6. **Regions and zones**: one thing under two names; zones were named GG#n.

## What changed

1. **One order** (`scheduling/work_groups.ordered`, `TIER_NAMES`): in a folder with a focus, the work is taken in
   five steps: the zone of the law in focus (its neighbours, its seeds, each term switched off, its lines), the depth
   worker (below its one worker, offered with the first step), the Dex laws read again, the blind draw, earlier laws'
   leftovers (runs whose priority `zone_first` raised by `work_groups.BEHIND`). Each step takes a worker only when the
   steps before it have nothing queued; a run under way is never stopped. `services/worker.offers` hands each step
   to the claim in turn, the claim kept above `BEHIND` until the last (`claim_job(under=)`); a folder without a focus
   keeps its shares.
2. **The probes in the same order** (`repo.claim_analysis_job`): ordered by the step of their campaign before their
   priority; the analyzer first claims the zone's and the depth worker's (`tier_at_most`), then its two halves.
3. **The slots follow the first work** (`allocation.first_work`, `repo.analysis_backlog_tiers`,
   `simulation_work_counts(ordered=True)`): the split between probes and runs counts the probes and runs of the first
   step that has either, so the zone's probes are read on most of the slots while the zone has no run to make; the
   whole backlog is still published, and a slot with nothing of its kind takes the other.
4. **The slider is gone**: the Map page says the fleet's order, how much each step has queued and which step the
   fleet is on now (`zone_now.order`).
5. **A zone stands at a smaller ring** (`focus.confirmed_at`): when ring 0.1 is under two thirds alike, the largest
   ring from 0.01 below it that is two thirds alike holds the zone (`confirmed_at`, an event, the "to map it" line),
   its edge then sought on the lines to each neighbour of another kind; with none, the law ends unconfirmed, which the
   Map page calls **a lucky hit** (no zone found around it, its readings kept). A zone's reach for "inside" is its
   `alike_to`, else its `confirmed_at`.
6. **Zones**: new ones named Z1, Z2 (`focus_regions.PREFIX`), a seeded one renumbered so; the Map page says zone
   throughout.
7. **"so far" against the law on six seeds** (`current.law_kinds`: its seeds' campaign over its own); the line under
   the law says how many probe readings its zone waits for when no run is left.

## Acceptance, line by line

| the acceptance | the test |
|---|---|
| runs claimed zone, Dex, blind, leftovers, the zone's largest before a leftover's smallest | `tests/integration/test_the_fleet_takes_its_work_in_one_order_postgres.py`, the first |
| probes read in that order; the slots follow the first step with work | the same file, the second |
| a folder without a focus keeps its shares | the same file, the third |
| the depth worker below its one is offered with the first step; what each step has queued | `tests/unit/test_the_work_groups_share_the_fleet.py`, the last |
| the zone's and depth worker's probes before either half | `tests/unit/test_the_fleet_in_two_halves.py` |
| a zone at 0.01 when 0.1 fails, unconfirmed when both do, a ring still read holds the judgement | `tests/unit/test_a_focus_reads_its_law_by_seeds_moves_and_depth.py` |
| the order instead of the slider, the probes line, a smaller zone, a lucky hit | `tests/ui/dashboard_smoke.js` |
| no output of a law moves | `tools/outputs_of_a_law.py --against` 880's record: 0 outputs changed |
| the full lane green | the Verification below |

## What it does not do

* **The zone's last stage** (the operator, 19:06 and 19:21): its central law, the one in the middle of its boundaries,
  assembled from its members and pushed to the largest N, in place of the depth worker as a step of its own; each
  term set to 0 as well as switched off. Next build.
* **A smarter zone** (19:21: "I don't think every law should be done from N64"): a neighbour runs the whole ladder from
  64; the kind at 16,384 needs 16,384 and 4,096 (`catalogue.kind` reads N/4), so 64 to 1,024 (about 5% of a
  neighbour's compute, three of its five round trips) could be skipped. Next builds.
* **The dex as zones, an import as its own campaign verified first, lucky hits kept to revisit**: after 177's first
  two zones (19:21: "importing mechanics is for later").
* Home's study bar still splits blind and zoned.

## Verification

4214 passed, 41 skipped in 1154.37s (3 lanes at once)
