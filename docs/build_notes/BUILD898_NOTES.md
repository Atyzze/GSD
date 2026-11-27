# Build 898: the fleet ladder counts the graphs grown, and a seed's rough time is shared by the seeds its law ran

**Type: a pages build, on the operator's words of 2026-11-27 18:26**, made on 897 (#39), with two screenshots of study
178 on 897 (Home at about 17:26Z: the fleet ladder and Now researching; G73's law page): "we can see on the work left
that at least SOME of the 1million N seeds must have finished by now, not all of them, but some ..should shown up by
now, but they dont, ... how come? easy fix?". It applies with a restart of the dashboard alone: the fleet, and the
seeds of 1,048,576 under way, keep running. No score, kind, gate or decision of any law moves, no frozen source, no
schema, no worker or admission code.

## What the screenshots showed

**No seed of 1,048,576 had finished: two numbers on Home said otherwise.** The fleet ladder's own row at 1,048,576 read
"–/–/–/3h33m+" for the time per seed and "–/–/–/9.8 G+" for its memory: no finished seed (the dashes), the slowest
still under way (the +). Three seeds ran (2, 3 and 4, 3 h 17 min to 3 h 31 min in).

* **The graphs column read 64 at 1,048,576.** Its header says "graphs grown"; it counted every seed bought there, a
  graph a start (8 seeds by 8 starts), finished or not (`rung_distribution`'s `graphs` is a count of the rung's
  seeds whatever their jobs' status; `completed` is the count of those finished). With "+24 now" beside it, it read as
  8 seeds grown and 3 more under way.
* **Now researching read "~34h43m54s rough" a seed**, its progress bars at a tenth after 3 h 31 min. A size none of a
  law's seeds has finished is timed from the law's own size below, times the ratio of the sizes; the law's time there
  is the whole of its seeds' time, and it was divided by 3 seeds (`rung_eta.own_rung_seconds`'s default), where the
  N-push ran 16: G73's 262,144 took about 93,800 s in all, so 31,300 s a "seed" times 4. Over its 16 seeds it is about
  5,860 s, 6 h 31 min at 1,048,576. 897's forecast prices a run there at 8 h 54 min (the growth from 65,536 to
  262,144 was about 7 times for 4 times the nodes, so a run may take up to about 11 h): the first seed of 1,048,576
  should finish between about 20:30Z and 01:00Z.
* G73's law page read 262,144 from 16 seeds: 897's start had probed the 8 cancelled ones.

## What changed

1. **The fleet ladder's graphs are those grown** (`resources/ui/app.js`, the ladder's graphs cell and its total):
   finished seeds times their starts, "of" the graphs bought where more are bought than grown, then "+ now" for those
   under way. 1,048,576 reads "0 of 64 +24 now"; a size grown whole reads as before. The header line: "Graphs grown at
   this N, a start of every finished seed, of those bought here, with a + those being grown now."
2. **A seed's rough time is its law's time below shared by the seeds that ran there**
   (`Repo.dashboard_live_candidate_timing` counts each size's seeds with time, `rung_seeds`; the overview's rungs carry
   it; `rung_eta.own_rung_seconds` divides by it, by 3 where it is not known). 1,048,576 reads about 6 h 31 min rough,
   its bars past half.

## For the folders

* **Study 178**: merge this pull request (897 is on `main`, #39); apply 898 and restart the dashboard only. The seeds of
  1,048,576 keep running. On Home the ladder's 1,048,576 reads "0 of 64 +24 now" until a seed finishes, and Now
  researching reads about 6 h 31 min a seed.

## Acceptance, line by line

| the acceptance | the test |
|---|---|
| the ladder counts a size's graphs bought apart from those grown | `tests/integration/test_a_rung_under_way_reads_as_under_way_postgres.py`; `tests/ui/dashboard_smoke.js`, "a size whose seeds are bought and not grown" and the older ladder check, now "6 of 12" |
| a seed's rough time is its law's time below over the seeds that ran there | the integration file above; `tests/unit/test_a_law_s_rough_time_is_over_the_seeds_it_ran.py` |
| the full lane green | the Verification below |

## What it does not do

* **The two answers of 18:26** (a pushed seed held at 1.1 times its peak, a bundle beside the N-push) need a restart
  of the fleet: 899.
* **The rough time still grows as the nodes** (times 4 from 262,144); the N-push's forecast on the Top page grows it as
  the law's own two deepest sizes did.

## Verification

4265 passed, 41 skipped in 1463.62s (3 lanes at once)
