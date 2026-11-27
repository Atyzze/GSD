# Build 897: every seed the N-push buys is read, its forecast priced as the admission holds a seed, and the push stops at N=1,048,576

**Type: an operations build, on the operator's words of 2026-11-27 15:29 and 15:47**, made on 896, with study 178's
bundle of 14:28:41Z and three screenshots (the Top page, the System page's memory ledger, G73's law page). 15:29: "how
come only 4 workers currently active? Meanwhile since some seeds at 1M seem to have finished already, why arent they
showing up at its candidate page?". 15:47, on G73's forecast holding the fleet to about Dec 5: "Thats probably good
reason to keep the push to 1million as the current default fleet max then? letting go of 4m all together unless
operator specifically pushed 1 law even higher, but makes more sense to not auto extend beyond 1M and to stop there".
No score, kind, gate or decision of any law moves, no frozen source and no schema. `tools/outputs_of_a_law.py
--against` 896's record: 0 outputs changed.

## What the bundle showed

**Memory, not the push, held the fleet to 4 seeds at N=1,048,576, and no seed of that size had finished; what G73's
law page lacked was half of 262,144, whose probes the restart for 896 had cancelled.** The bundle is a progress
reading: no campaign is done or at its law budget.

* **262,144: 16 runs done, 8 read.** Campaign 17's analysis queue held 76 done and 8 cancelled, no probe waiting; the
  rung summary had 8 seeds (0 to 7). The start of 14:15Z queued every finished run's probe again and then cancelled
  those it takes for a crash's leftovers ("Build 896 recovery compacted 8"): a rung keeps at most the seed attempts
  its campaign's spec allows, and the push campaign's spec, a copy of the focus's depth spec, allows 8. The N-push buys
  16. Seeds 8 to 15 had finished before that start and their probes were waiting, so all 8 were cancelled; every later start queues them again and cancels them again. 16,384 and 65,536 kept their 16 because their
  probes had ended before any start.
* **1,048,576: none finished.** 8 seeds bought, 4 running (2, 3, 5 and 1 in the screenshot); 7 of the 8 had been
  stopped, 1 to 3 times each, 12 stops in all: by the fleet's stops (`preempted_fleet_shutdown`, the last the restart
  for 896 at 14:14Z) and by the quiet bundle of 14:27Z (4, `preempted_campaign_paused`). A run there is forecast at about 8 h 54 min.
* **Why 4 at once.** The admission asked 10,800,739,966 bytes (10.1 GiB) to start each seed of 1,048,576 (1,858
  refusals for the memory floor in the bundle's record); the 4 running held 47.1 GiB of reservations, a running seed being held
  at 1.5 times what it has used; with 31.7 GiB available, the 10 GiB floor and 15.4 GiB still to be taken by the
  running children, 6.3 GiB was left. The host's reach for GSD was 54.0 GiB of 92.0: 15.6 to 16.8 GiB is the desktop
  and other programs, 8.2 GiB the RAM scratch, 4.3 GiB the kernel's slab.
* **Why the forecast said 7.** It priced a seed of 1,048,576 at 6.8 GiB: the largest peak of that size's attempts, all
  of them runs cut short by the restart, not a whole run. 54.0 / 6.8 is 7. The admission's 10.1 GiB is 48% more, its
  hold of a running seed (about 11.8 GiB each) 73% more: a miss of more than half, the first thing 896's page said to
  fix.
* **A resumed seed takes about twice the memory.** At 262,144 the 14 seeds that ran through peaked at 1.47 to 1.53
  GiB; seeds 6 and 7, each stopped once and resumed, at 3.05 and 3.19 GiB. Memory is linear in edges, about 190 to
  200 bytes an edge (summed over the 8 chains) at both 65,536 and 262,144, so a fresh seed of 1,048,576 should be near 6 GiB;
  the 4 running, all resumed, were at 9.0 to 9.4 GiB. The admission's ask grows from the largest peak below, the
  doubled one. This is 898.
* **Study 178's criterion** (`study_178_criterion.json`), read on this bundle, the first after the first zone was
  chosen: **P2, P3 and P4 hold; P1 holds but for its minute.** P1: one dex campaign (C15, kind seed, 193 laws), nothing
  else seeded, none before it; but read in at 00:23:52Z, 3 minutes after the folder's first campaign (00:20:49Z), not
  within one, and from 177's dex of 23:34:43Z, the copy written after the 19:33:48Z one the criterion names (both 193
  laws). P2: the dex's last law read again at 07:18:31Z, the focus and the depth worker's first law at 07:19:30Z. P3:
  192 confirmed, 0 denied, 1 unmatched (S176-C15-G7); 26,584 chains read again, 24,936 identical to the bit, none
  different, 232 of another length. P4: the zone of S176-C12-G100, 29 verified laws within 0.1 of its 45, ahead of 28
  within 0.1 of S177-C12-G1015, its centre in focus at the next step, chosen by zone. P5: the dex read in 00:23:52Z, its
  last law read again 6 h 55 min later.

## What changed

1. **A start keeps every probe the N-push bought** (`scheduling/recovery.superseded_analysis_keys`): in a push
   campaign (`push_ladder.is_push`) a rung allows every seed it holds; elsewhere the ceiling is the spec's as before,
   and a seed's shorter run is still superseded by its longer one everywhere. On 897's start in 178 the 8 cancelled
   probes of 262,144 are queued again (`ensure_analysis_queue` already did that) and now stay queued.
2. **A seed is priced as the admission will hold it** (`push_ladder.price`, used by the plan and the forecast): peaks
   from whole runs only (`push_ladder.rungs`: `peak_bytes` the largest, `typical_bytes` the median of exit-0 attempts;
   a cut run's peak is kept apart as `cut_bytes`); a size grown from the sizes below by their typical peaks
   (`depth_reach.price`, which still alone decides whether a size is tried); priced at the larger of that and the
   admission's own ask for it (`push_ladder.asked`, the worker's `memory.predicted_claim_peak_bytes` on the law's last
   job spec); a running seed
   held at `SETTLED_RESERVATION_SLACK` (1.5) times its expected peak (its own typical where it has whole runs, else the
   largest of the grown price, its runs under way and its runs cut short). At once: `1 + (reach - price) // held`, at
   most the workers. The full lane's first run caught the case where the ask is the smaller (a law whose sizes below
   grow faster than the admission's model): the price is never below the law's own growth. A run's time is the mean over finished seeds of all their attempts' wall, so a resumed seed's
   time before its stop counts (896 took only the last attempt: 262,144's mean read 1 h 28 min where the 14 seeds that
   ran through took 1 h 37 min).
3. **The rung under way says how many run and why** (`forecast`'s `under_way`): the seeds running, what the admission
   holds for them, the largest so far (the executor's heartbeat), the ask for one more and the headroom now
   (`memory.admission_headroom`), so how many more fit; its passes left counted from there. On the Top page: "N=1,048,576
   under way: 4 seeds run at once, the admission holding 47.1 GiB for them (the largest at 9.4 GiB so far); the next
   asks 10.1 GiB and 6.3 GiB is free above the host's floor, so it waits for one to finish". The rung table's memory
   cell carries the ask, the grown price, the hold and the runs' peaks in its mouse-over; a rung whose ask passes the
   host's reach is said ("its seeds wait until the ask falls").
4. **The N-push stops a law at N=1,048,576** (`push.CEILING`, `push.ceiling_of`): the push campaign's ladder still
   reaches 4,194,304, but `push_ladder.step` and the forecast stop at the law's ceiling, and a law that reaches it is
   done with rule `ceiling` ("its ceiling, N=1,048,576: a law goes higher only when pushed past it"). **"past"** on the
   Top page (`push_past`, `push.past`) sets the law's `to` one size of the ladder higher and puts it back at the end of
   the list if it had left; its sizes run stay, so it goes on from its last. The forecast says what the size past the
   ceiling would ask (`ceiling`). A zone's central law that joins the list stops at 1,048,576 too.
5. **The bundle carries the N-push** (`focus.json`'s `push_now`, `push.for_the_bundle`): the list with each law's
   ceiling, the runs under way with their memory, the law's forecast as the Top page shows it, the laws done; not the
   Top 100, which the bundle's tables hold. 896's page asked for `push_ladder.rungs` and `forecast` from a bundle that
   did not carry them.

The forecast's contract is `gsd-push-ladder-2` (new fields; `needs_bytes` now the price above).

## For the folders

* **Study 178**: apply 897 and restart the fleet's services. The 4 seeds of 1,048,576 stop, saved, and resume (a stop
  costs a resumed seed memory until 898). At the start the 8 unread probes of 262,144 are queued and stay queued; on the
  free slots each takes about 16 minutes (d_s about 10, the other three about 6 between them), so G73's law page shows
  16 seeds at 262,144 within about an hour. The Top page then says 4 run at 1,048,576 (perhaps 5 while the young seeds'
  reservations are low) and why; G73 ends at 1,048,576 once its 8 seeds are done, about 18 hours on in two passes, and
  G133 is pushed from 64. In btop: the probes beside the 4 big seeds for the first hour, then 4 children of about 9 to
  10 GiB each and 7 slots idle, which the host's memory limits, not the fleet.
* **What to watch in the next bundle**: `focus.json`'s `push_now.law.ladder` against what ran (each rung's
  `at_once`, `needs_bytes`, `hours`); campaign 17's analysis queue with no cancelled row of 262,144; its rung summary
  of 262,144 at 16 seeds; `pushed_done` with G73 at 1,048,576, rule `ceiling`.

## Acceptance, line by line

| the acceptance | the test |
|---|---|
| a start keeps every probe the N-push bought, queues again those 896's start cancelled, and still cancels a blind rung's excess | `tests/integration/test_the_n_push_reads_every_seed_and_stops_at_a_million_postgres.py`; `tests/unit/test_a_start_cancels_no_probe_the_n_push_bought.py` |
| a seed is priced as the admission asks and holds it, not by a run cut short, and the rung under way says how many run and how many more fit | the integration file above, on 178's numbers (10.06 GiB asked, 47.1 GiB held, 6.29 GiB free: 4 at once, 2 passes, 5 seeds bought where 8 were promised) |
| the push stops a law at 1,048,576 with rule `ceiling`, buys no seed above it, and goes on from its last size when pushed past | the integration file above |
| the Top page says it all | `tests/ui/dashboard_smoke.js`, "the Top page says how many seeds run now and why" |
| the bundle carries the N-push | the integration file above; `tests/unit/test_one_bundle_for_the_whole_study.py` |
| the ladder's climb as before where memory is the admission's own | `tests/integration/test_the_fleet_runs_one_mode_at_a_time_and_the_push_its_own_ladder_postgres.py`: 65,536 now 5 seeds, not 6, each running seed held at 1.5 times its peak |
| no output of a law moves | `tools/outputs_of_a_law.py --against` 896's record: 0 outputs changed |
| the full lane green | the Verification below |

## What it does not do

* **The admission is unchanged**: what it asks and holds is priced, not moved. Whether a pushed seed's hold may shrink
  is a question in `docs/ROADMAP.md` ("A pushed seed's hold").
* **A resumed seed still takes about twice the memory**: 898, measured first.
* **G73's 1,048,576 keeps its 8 seeds**, bought on 896's price; priced now it would have bought 5.
* **A bundle still stops the N-push's seeds**: a question in `docs/ROADMAP.md` ("A bundle beside the N-push").
* **The Map page's planned count for a pushed law** still lists its campaign's ladder to 4,194,304
  (`zone_live.planned_of`); the Top page is the push's own.

## Verification

4262 passed, 41 skipped in 1430.45s (3 lanes at once)
