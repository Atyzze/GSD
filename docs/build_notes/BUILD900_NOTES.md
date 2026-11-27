# Build 900: the N-push runs 3 seeds a rung, and a rung done says how it ran

**Type: an operations build, on the operator's words of 2026-11-27 19:52**, made on 899, with a screenshot of study
178's Top page on 897: "these values seem to be missing? and well, perhaps we can homonize/simplify seed count
instead of these seemingly random values, ... might as well stick to the usual 3? we didnt need 16 or8 anyway and
just sticking to our usual 3 lets us queue all the work for the entire push much faster Im betting [...] a standard
N-push doesnt need them and effectively just completes the ladder to 1M as the old ladder would have done
automatically anyway". It needs a restart of the fleet, as 899 does: apply both with one. No score, kind, gate or
decision of any law moves, no frozen source, no schema.

## What the screenshot showed

G73's 1,048,576 had 8 seeds bought (896's plan, as many as fit then), 3 running at about 10.6 GiB each, the admission
holding 48.8 GiB for them of the host's 48.1: 3 at once, 3 passes, the rung 33 h 10 min, ending near 03:56Z on 11-29.
Its rungs done read "-" for at once, passes, the rung's time and its from and to: 897's forecast carried those for a
rung under way or ahead only.

## What changed

1. **3 seeds a rung** (`push_ladder.SEEDS`, `plan`): the push buys 3 seeds a size, as every law's ladder runs, all at
   once while memory holds them, else as many at once as fit, in passes. 893 to 899 bought as many as there were
   workers (16), fewer as memory bound. The next size is still bought once a run below it finishes, so with 3 seeds the
   climb overlaps: the two other seeds below still run while the next size starts.
2. **A rung holding more keeps 3** (`push_ladder.trim`, at every step for the law being pushed): its done and running
   seeds first, then queued ones by seed, up to 3; the other queued seeds are let go (status `cancelled`, so the
   scratch's repair frees their saved states), and the focus's events say how many. In 178 G73's 1,048,576 keeps its 3
   running seeds (2, 3 and 4) and lets go of 5 queued: one pass, about 11 h, where 3 passes read 33 h.
3. **A rung done says how it ran** (`rungs`' `began_utc`, `ended_utc`, `most_at_once`; the forecast's done rows): the
   most of its seeds that ran at once, its passes, the time from its first start to its last finish, and when. The Top
   page fills those columns; their headers say so.
4. **The break-points read against a rung's seeds**: "fewer than its seeds at once", "two passes", "one at a time",
   where they read against the workers.

## For the folders

* **Study 178**: `main` holds 898 and 899 (#40, #41); merge this pull request, apply 900 and restart the fleet's
  services once. G73's three
  seeds of 1,048,576 resume; the 5 queued are let go at the push's next step; the Top page reads 3 seeds, 1 pass at
  1,048,576 and fills its rungs done. G73 ends when those 3 finish, then G133 climbs from 64 with 3 seeds a rung.

## Acceptance, line by line

| the acceptance | the test |
|---|---|
| the push buys 3 seeds a rung, at once while memory holds them, else in passes | `tests/integration/test_the_fleet_runs_one_mode_at_a_time_and_the_push_its_own_ladder_postgres.py`; `tests/integration/test_the_push_list_is_the_operator_s_queue_postgres.py` |
| a rung of 8 seeds, 3 running, keeps those 3 and lets the 5 queued go | `tests/integration/test_the_n_push_reads_every_seed_and_stops_at_a_million_postgres.py`, "the forecast prices a seed as the admission asks" |
| a rung done says its at once, passes, time and from and to | the same two integration files; `tests/ui/dashboard_smoke.js`, the Top page's check |
| the full lane green | the Verification below |

## What it does not do

* **Every size of a push queued at once**, before a run below it has finished (`docs/ROADMAP.md`, "Still open from
  884 to 896", item 4): those seeds would be priced with no measured size below them; left for the operator to ask.
* **G73's 16 seeds at 64 to 262,144** stay as they were read; only seeds not yet run are let go.

## Verification

4267 passed, 41 skipped in 1415.42s (3 lanes at once)
