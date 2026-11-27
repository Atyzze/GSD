# Build 896: in the N-push the probes get the slots the push's own work asks for, and the law page says what is still being read

**Type: an operations build, on the operator's words of 2026-11-27 14:36**, made on 895 (#37, on 894's #36), with
two screenshots of 894: "clearly, there is multiple data points from N265 already read, otherwise 1M workers wouldnt
have started already, so why are they not showing up on the candidate page? pls fix, or does build 895 adres this?".
895 did not (it is pages only). No score, kind, gate or decision of any law moves, no frozen source and no schema.
`tools/outputs_of_a_law.py --against` 895's record: 0 outputs changed.

## What the screenshots showed

* **A run done is not a reading.** The N-push buys a rung once one run of the rung below has finished (893): its peak
  memory and its time price the next. A run's readings come only when its graphs have been read by the four probes,
  about 16 minutes a seed at 262,144 (the fleet ladder's probe medians), and the law page draws a size once a reading
  of it exists. At 13:36Z G73 had 14 of its 16 runs at 262,144 done, four of them being probed (2 to 5 minutes in),
  and no reading yet: the page was right, and said nothing of why.
* **The probes had fewer slots than the push's work asked for.** The executor splits its slots between runs and
  probes by the first step of the fleet's order with work (`repo.refresh_scheduler_state`, `allocation.first_work`).
  In the N-push the zone's runs wait in step 0 (they are another mode's), so the split was taken from the waiting
  zone's runs and its probes, not from the push's: a push with probes queued could be given no probe slot, its probes
  run only on run slots that found no run (893's fault).

## What changed

1. **The split reads the mode's own work** (`repo.mode_campaigns`; `simulation_work_counts` and
   `analysis_backlog_tiers` take the mode's campaigns): in the N-push, the push's queued runs against its queued
   probes; in the zone search, the zone's; in the blind ladder, the blind draw's. With no mode set, as before.
2. **The law page says what is still being read** (`law_elsewhere.being_read`, the payload's `being_read`): for each
   size of the law, in any campaign, with probes queued or under way: its runs done of its runs, how many read, how
   many being probed and waiting for a probe, the time a probe takes at that size (the mean of the probes done there)
   and about when the next reading is due. The page reloads itself when it lands (894).

## For the folders

* **Study 178**: merge 894, 895 and this, apply 896 and restart the fleet's services (the executors read the new
  split; the runs under way are saved and go on). G73's probes at 262,144 then share the slots by the push's own
  work, and its law page says "being read" until each size lands.

## Acceptance, line by line

| the acceptance | the test |
|---|---|
| in the N-push the split is the push's own: its probes against its runs, not the waiting zone's | `tests/integration/test_the_push_list_is_the_operator_s_queue_postgres.py` |
| a size with runs done and probes under way is said, with how many read, probed and waiting | the same; `tests/ui/candidate_smoke.js` |
| no output of a law moves | `tools/outputs_of_a_law.py --against` 895's record: 0 outputs changed |
| the full lane green | the Verification below |

## What it does not do

* **A probe is not made faster**: at 262,144 the four probes of a seed take about 16 minutes; the curves gain the size
  as each seed's probes end.
* **The next rung still starts on the first run done**, not the first reading: the operator wants the push as fast as
  memory allows (09:19), and the reading follows.

## Verification

4256 passed, 41 skipped in 1260.43s (3 lanes at once)
