# Build 892: the push list holds the host, in the operator's order, to the last size one seed fits

**Type: an operations build, on the operator's words of 2026-11-27** with study 178's bundle of 07:30:37Z and its dex of
07:26:24Z. 08:36: "The top list is basically the only queue the operator can directly steer [...] as soon as theres
any of them in there ... do that work first, and honor the prio set, when a zone confirmation is pushing its highest N,
it is simply added to that queue as a work item, currently, I am not seeing any depth-work being done at all". 08:54:
"the one it's doing currently should be in there as well and at the top. And the moment we remove it from the top, it
should abort the current one and start with the second one in that list", "I'm lacking the worker being visible in the
homepage at the bottom", "I also still don't see its memory usage". 09:09: "not 1 worker on it, but all other workers
paused and all resources going to just the depth work, until we find the memory limit and need to reduce worker count
to 1 [...] we try to predict as best as possible to guess when that will be". 09:19: "continue as needed until not a
single worker fits anymore [...] We stick to the general worker limit set". No score, kind, gate or decision of any law
moves, no frozen source and no schema. `tools/outputs_of_a_law.py --against` 891's record: 0 outputs changed.

## What 178's bundle showed

* **The depth worker was a share inside the fleet, not a worker of its own.** 889 gave the depth campaign a target of
  one worker inside the worker count, second in the fleet's order after the zone. A slot freed every few minutes on a
  fleet of 16 busy with runs up to an hour long, and the depth campaign's runs from 16,384 up yielded to base runs
  while many long runs held slots. At 07:30 its next run (G2302 at 16,384) sat queued with nothing leased, so Home
  showed no depth run.
* **It held the zone's centre.** The depth worker took S178-C15-G2302 (177's S176-C12-G100, the first zone's centre;
  S178-C13-G1 in its depth campaign) at 07:19:30, as the law in focus; the pushes of 07:32 and 07:33 waited for it to
  end (889's rule). Its depth campaign ran it again from 64: 14 runs by 07:30, one stopped by a pause.
* **The zone waited six hours for the dex.** From 01:00 to 07:18 the fleet ran almost nothing but the dex read in
  (C15): about 38 core-hours, of which 31 were 16,384 and 65,536 runs the decision engine bought on merit (187 laws at
  16,384, 93 at 65,536, 255 more queued). The check needed only 64 to 4,096 (about 7 core-hours), but those runs
  waited behind the long ones for free slots (median queue wait two to three hours from 02:00). The check ended at
  07:18:31 (192 confirmed, 1 unmatched) and the zone was chosen at once.
* **The zone search itself is under way.** Its 28 laws within 0.1 all read alike to the centre (28 of 28, 07:20:41);
  at 07:30 its 12 lines and 4 terms switched off were each reading their first step (10%).

## What changed

1. **While the push list holds a law, the host is its** (`push.holds_host`; `worker.claim_simulation_for_owner`,
   `analyzer.claim_analysis_for_owner`, `lane_yield.depth_yield_reason`). Every slot of the worker count takes only
   the first law's runs, smallest size first, all seeds of a size at once as far as the memory admission lets them in;
   every other run is stopped within two seconds with its seed saved, as a pause stops it, and given back to the queue
   (class `preempted_depth_order`); no other run starts, and the analyzers probe only the pushed law's runs. A memory
   hold kept for another campaign's run is ended. The decision engine buys each next size as before, once the size
   below is read; the law climbs until not one seed of the next size fits, then leaves the list for `pushed_done`
   (`push.ended`), and the next law has the host. With the list empty the fleet goes back to its order, each stopped
   run resuming from its saved seed.
2. **Its reach is the host's** (`depth_reach.room_for`): while the list holds the host the depth campaign's sizes are
   priced against all the memory the host admits for runs (`memory_hold.reach`: what is available and what our own
   runs hold, less the host's floor), not the depth worker's half (881's "no more than 50% of total system", made
   when the fleet ran beside it).
3. **The list is the operator's** (`push.toggle`, `push.move`, the focus action `push_move`). A law the operator
   pushes joins the end; a zone's central law joins the end when its zone is mapped (`zone_search._central`,
   `push.add`; 891's separate `central` list is folded in, `push.adopt_central`). The Top page has "first", "up" and
   "stop pushing" on each law and says who put it there. Taking the first law off, or moving another above it, stops
   its run under way at once; a law moved down waits with its runs and saved seed (`depth_waiting`) and goes on where
   it was when it is first again; a law taken off is let go (`let_go`), not taken again until it is pushed again. The
   depth campaign is kept throughout (882's `depth_restart`, which began a new one and paused the old, is gone).
4. **The law the depth worker held when 892 came in is put first on the list, once** (`push.adopt_now`, the state's
   `push_list_adopted`): in 178 that is G2302, by "the depth worker's own line". After that the depth worker's own
   pick (the law in focus, then its depth list) stays off the list, because on the list it would hold the host from
   the zone's work: it runs only while the list is empty, on the depth slot below.
5. **The depth slot** (`worker_count.tick`, `executor._depth_once`): one executor above the worker count, started once
   the focus has depth work and never stopped by a worker count or the ramp, runs the depth worker's own pick while
   the list is empty, its runs and their probes; it stands idle while the list holds the host, so a push keeps to the
   worker count. The fleet's own slots never take the depth campaign's work outside a push (`work_groups.ordered`
   leaves it out).
6. **The forecast says when the push ends** (`push.forecast`, `push.run_seconds`): for each size ahead the memory it
   needs (as since 889), how many of its seeds fit at once in the reach, the time a run takes priced from the law's
   own two deepest sizes (growth between N^1 and N^3), the hours for the size, the last size one seed fits, the size
   from which seeds run one at a time, and about when the push ends.
7. **The Top page shows the push at work**: the run under way with its size, seed, start and clock and the memory it
   holds now and at most so far beside the memory priced for that size (from the executor's heartbeat,
   `push._memory_of`); whether the list holds the host; the laws waiting with their runs kept and those done; the
   forecast's seeds at once, time and hours per size.
8. **Home names a pushed law's runs "pushed"** (the chip of group D), with their clock and bar as any run. 890's zone
   steps (part E) were drawn "seeded" by a clash of keys: they read "zone edges" now, the Dex laws "seeded".
9. **While a dex is checked its laws run only to the level they are verified at** (`dex_check.keep` marks the level,
   `work_groups.verifying`, `claim_bounds`): the decision engine still buys their deeper sizes, which run once the
   check is done, after the zone's work. 178's check is done, so this changes nothing in it now; it is for the next dex
   read in.

## For the folders

* **Study 178**: apply 892 and restart the fleet. The push list reads G2302 first (the law the depth worker held),
  then G73 and G133, and the list holds the host: every slot of the worker count runs G2302's seeds, the zone's search
  and the Dex runs stop with their seeds saved, and Home shows G2302's runs as "pushed". Take G2302 off, or move G73
  first, and its run stops, saved, and G73 has the host. The forecast for G2302 on the 46 GiB half priced 4,194,304
  past its reach; with the host's reach the Top page says which size is its last and about when it ends. When the list
  is empty the zone's search goes on where it stopped.

## Acceptance, line by line

| the acceptance | the test |
|---|---|
| the depth worker's own pick stays off the list and runs on the depth slot; its reach the depth share | `tests/integration/test_the_push_list_goes_first_on_a_depth_slot_of_its_own_postgres.py` |
| a law on the list holds the host at once: every other run stops, saved; every slot takes its runs, all seeds at once; probes its alone; its reach the host's | the same |
| taken off the top, its run stops at once and the next law has the host; not taken again until pushed again | the same |
| moved down, its large run stops and its small one may finish; moved first, it takes the depth worker | the same |
| the list empty, the host goes back and the own pick goes on where it was | the same |
| the law held when 892 came in is put first once, and not again once taken off | the same |
| a law that reaches its limit leaves the list; the run under way says its memory | the same |
| 891's central laws folded into the list's end; a zone's central law joins the end | the same; `tests/integration/test_the_first_zone_is_searched_by_stepping_and_halving_postgres.py` |
| the depth slot starts once there is depth work, above the worker count, no count stops it; its own role | `tests/unit/test_the_depth_worker_has_a_slot_above_the_worker_count.py` |
| the fleet's offers leave out the depth campaign, and the Dex past its level while it is checked | the same |
| the forecast: seeds at once per size, time a run, hours, the last size, one at a time from, the end | the same |
| an open check marks its level; a finished one clears it | 888's and 891's dex tests |
| the Top page: the push at work with its memory, the host, the order buttons, who pushed, waiting and done, the forecast | `tests/ui/dashboard_smoke.js` |
| Home names a pushed law's runs "pushed" and the zone's steps "zone edges" | the same |
| no output of a law moves | `tools/outputs_of_a_law.py --against` 891's record: 0 outputs changed |
| the full lane green | the Verification below |

## What it does not do, and what the operator decides

* **Sizes are climbed one after another.** The decision engine buys a size once the size below is read and priced
  from its peaks; starting several sizes at once (the operator, 09:19: 65,536, 262,144 and 1,048,576 "can all still
  start at the same time") would have the engine buy a size before the one below has run, in `decisions/` (frozen).
  **The operator decides** whether to open that: a speculative rung priced from the forecast, its seeds started beside
  the size below while the reach holds them, the price corrected as the size below reads.
* **The reach of a pushed law is the host's** (above). Say so to keep 881's half instead.
* **A stopped run resumes from its saved seed on the same host**, as a paused one does; a run below 16,384 of a law
  still on the list is not stopped when the list changes, it finishes in seconds to two minutes.
* **The depth campaign reads each law again from 64**, as since 861: the decision engine climbs its ladder in its own
  campaign (for G2302 15 runs, about five core-minutes, before 65,536).

## Verification

4243 passed, 41 skipped in 1261.97s (3 lanes at once)
