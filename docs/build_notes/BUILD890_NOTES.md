# Build 890: the first zone searched by stepping and halving, a neighbour alike by its curves, its central law pushed

**Type: an operations build, `docs/ROADMAP.md`, "From 886", item 4, on the operator's answers of 2026-11-27 01:55**
("B, and the rule": "Yes"; "keep going, make all the builds needed so that our roadmap document may shrink"): a law is
alike to the zone's centre when their kinds agree and every curve both have locked in takes the same form and value
(B), and the first zone is the rule's (887's `zone_choice`). No score, kind, gate or decision of any law moves, no
frozen source and no schema; the ring method stays for a law taken into focus by its score. `tools/outputs_of_a_law.py
--against` 889's record: 0 outputs changed.

## For the folders

* **Study 178**: apply 890 and restart the fleet. Once the dex is read again (887, 888), its first zone is taken into
  focus as before, but no ring is drawn around it: the Map page's "In focus" panel shows **the zone's search**, its
  laws judged, a table of every parameter's two ways with each step coloured by its verdict, the edge each line found,
  whether the edge held at 16,384, then its central law and what the search cost.
* **What to watch**: a new campaign "its zones' edges, each step read to N=4,096" (the focus's part E, the zone step of
  the fleet's order, laddered 64 to 4,096 only); one law per line in it at a time; then two laws per edge in the zone
  campaign read to 16,384; then the central law first in the depth worker's line after any law the operator pushed.

## What changed

1. **Likeness** (`observability/likeness.py`): a law's curves are fitted from its rungs up to the size read
   (`curves`, by the phenotype's own `fit`: constant, power or log, three sizes from 256), and two laws are **alike**
   (`alike`) when their kinds agree and no curve locked in by both differs, within the phenotype's margins (exponents
   within `exponent_within`, values and log slopes within `constant_within`, relative). A curve one of them has not
   locked in counts neither way; with none shared, the kind decides alone, as the operator's fallback asks.
2. **The zone's search** (`operations/zone_search.py`), begun by `focus.start_next` for a law taken in by the zone rule
   (887's `BY_ZONE`); its stages:
   * **members**: every law of the zone (`zone_chosen`'s members, the dex's laws of the centre's term set) judged
     against the centre at 4,096 from the runs the dex check already made: no new run. Two thirds of the laws within
     0.1 must read alike (the plan's `confirm_share` at its `confirm_radius`), else the law ends UNCONFIRMED as 887's
     rings would.
   * **edges**: each parameter (`perturb.parameters`: the couplings and the dynamics' own) stepped both ways from the
     centre by 10%, 20%, 40%, 80% and 160% of its value (down to 95% at most), one point a line at a time, until a step
     reads other; then the gap halved three times, the edge known to an eighth of its step. A share cannot leave 0 to 1:
     that way ends with no law. Each term switched off once (the knockouts). Every point runs in campaign E to 4,096
     only and is judged there by likeness.
   * **confirming**: the two points either side of each edge run in the zone campaign to 16,384 and are judged against
     the centre's own seeds at 16,384: an edge holds when the inside reads alike and the outside other.
   * **done**: the central law, the middle of each parameter's alike extent (`central_spec`), made in the zone
     campaign, put on the focus's `central` list and made a contender: the depth worker takes it after the operator's
     pushed laws (`push.front`, 889) and prices each size past 65,536 against half the host's memory (873). The law
     ends MAPPED, its region named as before (885), and its search kept with the ended law.
3. **The benchmark**, kept with the search (`zone_search.benchmark`): per line its points, runs, core-hours and hours
   and its edge; in all, the search's runs and core-hours from the attempts; how many edges called at 4,096 held at
   16,384; and the ring method's rings priced from the plan for the same law.
4. **The zone step** takes the E campaign (`work_groups.ZONE_PARTS`, its tier SQL); Working now names its laws "a step
   of the zone's search, read to N=4,096" (`zone_live`).
5. **The Map page** draws the search (`searchBlock` in `map.js`), live and after the law ends.

## The benchmark, priced before it runs

The ring method on this very zone, from 177's dex (`chains.ndjson.gz`, study 176's runs, `seconds` per chain): the 44
laws of S176-C11-G79's term set that 176's map drew around it (S176-C12, the centre S176-C12-G100 among them, 28 of them
within 0.1 of it) took **5,280 chains, 3.2 core-hours**, 78% of it at 16,384 (2.49 core-hours; 4,096 took 0.52, 1,024
0.14, 256 0.05). One law to 4,096 is about 0.016 core-hours, one to 16,384 about 0.073.

The search on the same centre: 6 parameters (four couplings, locality, swap), 12 lines. A line that changes at its
second step costs five points to 4,096 and two to 16,384, about 0.23 core-hours; one that runs out all five steps and
three halvings, eight and two, about 0.27. The 12 lines then cost **2.7 to 3.3 core-hours**, the four terms off 0.06,
the members nothing: about the ring method's cost, for what the ring method does not give, an edge on every axis
within an eighth of its step, each edge checked at 16,384, and a central law. Its hours are longer: a line's points
follow one another (each a ladder to 4,096), so a line takes up to eight such round trips where a ring's laws run
together. The real figures come with the run, in the search's `benchmark` and on the Map page; if a line's steps prove
the slow part, the next build may step every line's next two points at once.

## Acceptance, line by line

| the acceptance | the test |
|---|---|
| the zone's laws judged with no run; two thirds alike within 0.1 or UNCONFIRMED | `tests/integration/test_the_first_zone_is_searched_by_stepping_and_halving_postgres.py` |
| an edge found by stepping and halving on a law of known answer: up between 55% and 60%, down between 32.5% and 35% (the box rule at +57% and -33%) | the same |
| a share that would leave 0 to 1 ends its way with no law; the E campaign laddered to 4,096 in the zone step | the same |
| every edge read again at 16,384; the central law the middle of the extents, pushed first to the depth worker | the same |
| an unread law has no reading and no rungs | the same, before the reading is replaced |
| two laws alike by kind and locked-in curves within the phenotype's margins; the kind alone when none is shared | `tests/unit/test_two_laws_are_alike_by_kind_and_locked_in_curves.py` |
| the Map page draws the search: its laws, every line's steps, the edges, the central law, the cost | `tests/ui/dashboard_smoke.js` |
| no output of a law moves | `tools/outputs_of_a_law.py --against` 889's record: 0 outputs changed |
| the full lane green | the Verification below |

## What it does not do, and what the operator decides

* Its laws are judged at 4,096, not 16,384 as 886's plan wrote: 888 reads a dex again to 4,096 unless the dex asks for
  more, and 16,384 for every law of the zone would be new runs (2.49 of the ring method's 3.2 core-hours). The edges
  alone are read at 16,384.
* It searches one zone, the first; zones one after another, and the dex as a list of zones, are 891.
* A line moves one parameter at a time from the centre: a zone that bends (alike along each axis, other along a
  diagonal) is not seen; a diagonal line is the ring method's strength and stays in the tree.
* The central law waits for the law the depth worker is running, as a pushed law does (889).
* **The operator decides**: whether the central law should go before the operator's pushed laws (now after them).

## Verification

4234 passed, 41 skipped in 1449.53s (3 lanes at once)
