# Build 893: the fleet in one of three modes, and the N-push its own ladder again from 64 on every worker

**Type: an operations build, on the operator's words of 2026-11-27**, made on 892 (its pull request, #34, still open).
10:32: "an-N push should have its own logic, since we're already intending to commit all resources to 1 law, might as
well turn it into a mini SMT test, where we re-do the entire ladder again from the lowest to the highest, and this
time, we take x seeds per start based on the available core/worker count [...] we only reduce the worker count as soon
as we hit the memory constraints we reduce the seed count back to base min 3 again", "we need absolute solid
predictions plotted out in advance", "now a rung needs two passess, thats the first break-point to mark visually
somewhere, and then another when we are forced to go from 2 workers to 1 and the time in between", "this single
thread blocking all compute [...] is only something I want tosee once its N has gotten so big all the memory is soaked
up by a single worker"; and of Home: the study-now panel "is now obsolete", "Which laws" under the landscape, the
selection and the fleet's work "1 box" like the older fleet ladder, "drop the 'all batches' from the box-titles", the
gates collapsed. 10:35: "the candidate page doesnt even show the data from N64k", "we definitely want 3 'modes' of
compute, the blind ladder with its gates, the zoned-search, and the N-pusher, always doing 1 of the three, never
combining any of them though the N-push is the natural end-station of the zoned-searched". 10:42: "the fleet ladder
should be showing the values of these 24 graphs there too [...] even if there are no averages yet, it should still
show the current value like there is for max time (1h20m+)". 11:37, of the zone search's idle slots: "those free
slots should be used to speed up the zoning mapping instead then, blind draw is only for when both other queues are
empty". No score, kind, gate or decision of any law moves, no
frozen source and no schema. `tools/outputs_of_a_law.py --against` 892's record: 0 outputs changed.

## What the operator saw

* **G2302 on three workers at N=262,144.** 892's push held the host, but the decision engine in the depth campaign
  bought 262,144 with the three seeds its policy asks, so three slots ran it and thirteen stood idle for hours: "this
  single thread blocking all compute" long before memory forced it.
* **The law page stopped at 16,384.** It read only the campaign it was opened in (the Dex campaign, C15); G2302's
  65,536 and 262,144 runs were in the depth campaign (C13).
* **Home showed a pushed law's run as "seeded"**: its origin, not what the fleet was doing.
* **The fleet ladder showed dashes for a rung under way** but its longest time ("1h20m+").

## What changed

1. **Three modes, never mixed** (`operations/modes.py`, the flag `fleet_mode`). The N-push while the Top page's push
   list holds a law; else the zone search while a zone has work (the dex read in being checked, a law in focus, a
   zone chosen and waiting); else the blind ladder with its gates. Each mode names its campaigns (`modes.kind_of`, by
   each campaign's design): the push campaign; the focus's parts N, S and E and the Dex campaign; every other active
   campaign. A run or a probe is claimed only from the mode's campaigns (`worker.in_mode`,
   `analyzer.claim_analysis_for_owner`, `repo.claim_analysis_job(campaigns=)`), and a run under way of another mode is
   stopped within two seconds, its seed saved, and given back (`lane_yield.mode_yield_reason`, class
   `preempted_fleet_mode`, 892's `preempted_depth_order` folded in), to go on when its mode comes back. Within a mode
   the fleet's order (885) is unchanged. The mode is written at every focus step, every ladder tick and every change
   of the push list (`modes.keep`), with why and since when; Home names it beside Now researching, the Top page above
   the list.
2. **The N-push redoes the law's whole ladder from 64, in a campaign of its own** (`operations/push_ladder.py`, part P,
   a copy of the focus's depth spec, its ladder to 4,194,304). The controller's decision engine leaves it alone
   (`push_ladder.is_push`): the ladder buys its own rungs (`push_ladder.step`, every 5 seconds in the controller and at
   every focus step). A rung is bought once the rung below has a finished run, priced from the law's own peaks below
   (`depth_reach.price`) against the host's reach, by `push_ladder.plan`: **as many seeds as workers** (the worker
   count; 16 in 178) all at once while they fit; **when memory binds**, as many at once as fit, the rung taking that
   many seeds but never fewer than 3, then in passes (3 seeds on 2 workers is two passes, on 1 three). When not one
   seed of the next size fits, the law is done (`push.ended`, rule `memory`, or `ladder` at its top) and the next law
   on the list is pushed. Every slot claims its runs, smallest first (`worker.claim_depth_for_owner`); they are probed
   as any run and their rung summaries written by the evidence rebuild. The gates do not stop a pushed law: the
   operator pushed it.
3. **The forecast, rung by rung** (`push_ladder.forecast`): done, under way (its seeds left) and ahead, each with its
   seeds, how many at once, its passes, the memory a seed needs (its peak, or priced; a priced rung chained into the
   next without its safety factor twice), the time a run takes (its mean, or priced from the law's two deepest sizes
   by `push.run_seconds`, growth between N^1 and N^3), the hours the rung takes and when it starts and ends from now.
   Its break-points (`marks`), each only where memory causes it: the first rung with fewer at once than workers, the
   first with two passes, the first on one worker; the first size past the host's reach (`limit`) and the end. It is
   read again at every poll of the Top page (every 4 seconds), so it moves with every finished run.
4. **The Top page plots it** (`GSD_TOP` in `map.js`): the mode and why; the runs under way, each with the memory it
   holds now and at most (the executor's heartbeat); the list and its order buttons; then the law being pushed: the
   last size it reaches and about when, the break-points in words with the time between the first two-pass rung and
   the first one-worker rung, a timeline of the rungs ahead from now to the end coloured by phase (all workers, fewer,
   one worker) with each break-point marked, the rung table, and the memory a seed needs over N against the reach.
5. **The depth worker's own pick is gone.** 892's depth slot (an executor above the worker count) and the depth
   worker's own line (the law in focus, then the depth list) are retired (`executor`, `worker_count` as at 891): a law
   goes deeper only on the push list. The focus's depth campaign (part D) takes no law; its readings are kept. A Dex
   law runs only to the level it is verified at, also after the check: deeper is the N-push's.
6. **The law page reads every campaign of its law** (`services/api/law_elsewhere.py`): a size this campaign has not
   read is taken from the law's other campaign with the most readings of it, its curves drawn with the rest (the
   chains, every chain's reading, the curves at a size) and its rung in the table marked with its campaign. The score
   on the page still reads this campaign's own sizes, as every list of the study does.
7. **Home**: "The study now" is gone; "Which laws" stands under the landscape and the Top 100; the selection's ladder
   and the fleet's work are one box, **Fleet ladder**, with the older build's groups: candidates (rung, laws, waiting,
   scoring, graphs), laws stopped by rule (one column a rule and their total, from the selection), evolving laws,
   probing laws, totals. A rung under way shows its live values marked + as its time already did: the graphs being
   grown (`running_graphs`) and the heaviest memory held so far (`running_peak_bytes`, from the executors' heartbeats,
   `rung_distribution.live_memory`). No box title says "all batches"; "The gates" opens on a click. A pushed law's
   runs are "pushed" (group P), the depth campaign's "depth".
8. **The zone search's free slots run its lines ahead** (`zone_search.ahead`, `_look_ahead`, `free_runs`; 11:37).
   While a line's step is being read, the two points it may need next (the next step out if the step reads alike,
   halfway back if it does not; in a halving, either half's midpoint) are made and run on the slots the zone search
   leaves free (the worker count less its queued and running runs, three runs a point), the lines with the fewest
   steps read first. When the line comes to a point already run ahead it reads it without a new law; the point it did
   not need is left unread, its runs kept. The Map page marks such a point with a +, and the search counts them
   (`ahead`). A line's last step out is counted by its steps read, not by its points made, so the edges found are
   those of 890's rule.

## For the folders

* **Study 178**: merge 892's pull request, apply 893 and restart the fleet. The push list still reads G2302 first
  (then G73 and G133), so the fleet goes into the N-push: the zone's search and the Dex runs stop with their seeds
  saved, a push campaign is made, and G2302's ladder runs again from 64 with 16 seeds a rung on the 16 workers. The Top
  page plots when memory binds, priced from the peaks of its new runs as they finish, and when it ends. Take G2302 off and G73 has the fleet; with the list empty the zone's search
  goes on where it stopped.

## Acceptance, line by line

| the acceptance | the test |
|---|---|
| one mode at a time: the blind ladder, the zone search, the N-push; another mode's runs and probes not claimed, its run under way stopped and saved; the mode back, its runs go on | `tests/integration/test_the_fleet_runs_one_mode_at_a_time_and_the_push_its_own_ladder_postgres.py` |
| the N-push redoes the ladder from 64, as many seeds as workers at once, fewer as memory binds down to 3, then passes, ends when not one seed fits | the same |
| the forecast: every rung's seeds, at once, passes, hours and end; the break-points where memory binds; the limit and the end | the same; `tests/integration/test_a_law_pushed_to_the_n_limit_is_pushed_at_once_postgres.py` |
| the list is the operator's: moved down or taken off, its runs stop at once; the next law has the fleet; pushed again it joins the end; the law held when 892 came in first once | `tests/integration/test_the_push_list_is_the_operator_s_queue_postgres.py` |
| a law done leaves the list and the next is pushed; the runs under way show their memory | the same |
| a pushed law needs no score; the Top 100 by N and the law's sizes | `tests/integration/test_a_law_pushed_to_the_n_limit_is_pushed_at_once_postgres.py` |
| the zone search's free slots run each line's two possible next points; the line takes the one it needs and reads it without a new law; only in the zone search, only the slots free | `tests/unit/test_the_zone_search_runs_its_lines_ahead_on_free_slots.py` |
| the law page draws every campaign's sizes, its score its own; the rung table marks where each was read | `tests/unit/test_the_law_page_reads_every_campaign_of_its_law.py` |
| a rung under way carries its graphs and the memory its workers hold, merged across batches | `tests/integration/test_the_ladder_shows_the_slowest_run_postgres.py` |
| Home: one fleet ladder with candidates, stops by rule and the live values marked +; no "all batches"; the mode named; the filters under the landscape | `tests/ui/dashboard_smoke.js`, `tests/ui/hero_check.js` |
| the Top page: the mode, the runs with their memory, the ladder's timeline with its break-points, the rung table, the end | `tests/ui/dashboard_smoke.js` |
| the depth worker takes no law of its own; the older focus tests read so | the focus's integration tests, updated |
| no output of a law moves | `tools/outputs_of_a_law.py --against` 892's record: 0 outputs changed |
| the full lane green | the Verification below |

## What it does not do, and what the operator decides

* **The zone search's free slots go to its own lines** (above), the blind ladder only when the push list is empty and
  the zone has no work (the operator, 11:37). Free slots in its other stages (its members' readings, its edges read
  again at 16,384) still wait for that work; 178's next bundle says how many slot-hours that is.
* **A rung is bought once the one below has a finished run**, not before: the first runs of a size price the next.
  Starting a size from the forecast alone is open (the same, item 4).
* **The N-push runs every rung again from 64**, as asked: for G2302 the sizes below 65,536 cost minutes on 16 workers;
  its earlier runs in C13 and C15 stay where they are and the law page shows them.
* **The blind ladder runs only when the focus has no law and no dex is being checked**: the zone search goes on from
  law to law while there are contenders.

## Verification

4247 passed, 41 skipped in 1262.47s (3 lanes at once)
