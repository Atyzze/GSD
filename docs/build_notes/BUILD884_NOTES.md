# Build 884: the zone live on the Map page, and the zone's workers on the zone

**Type: a build that shows the work, with two fixes to where the zone's workers go, on the operator's words of
2026-11-26 17:22 ("I'm mainly missing insight to see whether or not it is actively mapping our first zone at all";
"I want to see the active workers showing up on this page as well, so I can see what it is actively doing"; "I'm
not seeing any timers").** No score, kind or decision of any law moves, no frozen source and no schema; the science
is 883's. It is applied to 177's running folder.

## For the folders

* **Study 177**: apply 884 and restart. The Map page opens on the law in focus, S177-C11-G37, and says under it how
  long it has been in focus, how many of its laws are read (and in the last hour, and when the last was), the work
  left, who runs now, and every law of its zone where it stands, each with a clock. Within a minute of the restart
  the share the slider gives the zone goes to the zone: the Dex laws read again count with the blind draw, and the
  neighbours the outlier set aside on 883 left queued wait behind G37's.

## What was hidden or wrong (the Map page of 17:22)

1. **"waiting" said nothing**: of G37's 44 neighbours, 42 were "waiting", whether running at 4,096, queued, their
   probes being read, held by the decider or not started. A neighbour is judged only at 16,384, so a neighbourhood
   read side by side shows nothing for most of its time and then nearly all of it at once.
2. **No worker on the Map page**: it said what the zone worker waits for, never who runs.
3. **No clock**: not how long the law had been in focus, nor how long any run had run.
4. **The zone's share was not the zone's**: study 177's design puts its seeded campaign (C11, the Dex laws read
   again, 130 laws) in the zone's work group N, and each campaign of a group with work takes an equal part, so the
   zone's neighbours shared their share with C11 (6 of the 16 workers at 17:10) and with the law's seeds.
5. **The outlier's neighbours ran beside G37's**: S177-C4-G10, set aside on 883, left its neighbours queued in the
   zone's campaign at the same rank (883's notes, "What it does not do").
6. **"each term switched off" ticked before any term was read**: at the law's first step it counted 0 of 0.

## What changed

1. **The zone now** (`operations/zone_live.py`, served with the Map page as `zone_now` and kept in a bundle's
   `focus.json`): every simulation running in the fleet, who runs it (zone, zone seeds, depth, Dex laws, blind), its
   law, its part (a ring, a term switched off, a boundary line, the law on more seeds, an earlier law's), its size,
   seed, how long it has run and the typical time of one seed at that size over the last six hours (the zone's own
   runs where it has them, else the fleet's). Every law of the zone where it stands: running (its seeds done, running,
   queued), queued, its probes being read, waiting for the decider, sent on, held (with its rule), decided, failed,
   not started, read; since when; and its kind at the largest size all its seeds have read, against the law in
   focus at that size. The work left: each waiting law's sizes up to 16,384 times their typical time, over the zone's
   workers now; at most that, since a law the decider stops needs less.
2. **The focus's step keeps its times** (`operations/focus.py`): when each law of the zone was read (`read_at`), its
   kinds so far (`so_far`, `kinds_so_far`), when each condition of "to map it" first held (`needs_at`, dropped if it
   stops holding), the typical times (`typical`, read every five minutes, `typical_of`).
3. **The Map page** (`resources/ui/map.js`, `index.html`): under the law in focus, one line of how long, how many
   read, the work left; one of who runs now against the zone's share; the rings table with running, queued, between
   sizes, held, not started and alike so far; how a neighbour is judged, in words; and every law of the zone in a
   fold, the running first. A new panel, **Working now**, lists every running simulation, the zone's first, with its
   clock and a bar against its typical time, amber past it. The clocks tick every second. The page opens on the law in
   focus; the Seeds panel (the dex and the bundles) moved below Depth.
4. **The Dex laws count with the blind draw** (`scheduling/work_groups.group_of`; `repo.worker_allocation` returns
   each campaign's `design_kind`): a campaign of kind `seed` is in group A whatever its design says, so the slider's
   zone share is the zone's neighbours' and seeds', and the Dex laws share the laws-coming-in side with the blind draw.
5. **The law in focus's zone first** (`focus.zone_first`, at every step): the queued runs of laws no longer in focus,
   in the zone's campaign and the seeds' campaign, wait behind the law in focus's (their priority raised by
   `focus.BEHIND`, ten thousand million); they still take a worker whenever the law in focus has none queued, and come
   forward again if their law is in focus again. The page says how many wait so.
6. **A condition holds only once it is read**: "each term switched off" needs every term switched off read.

## How a neighbour is judged (the operator's question, 17:22)

A neighbour is **alike** when its **kind** at N=16,384 is the law in focus's kind at 16,384; a neighbour the decider
stops by a rule before 16,384 reads another kind. The kind is one word from the probes of all eight starts
(`observability/catalogue.kind`): grown, made, ring, small_world, frozen, still, rewired, moved, broken, apart, empty,
full. The law's region stands when two thirds of its ring at 0.1 (8 laws whose every coupling moved by 5% to 10%) is
alike; then rings at twice the radius until one is not all alike or 0.8 is reached, or, where a neighbour at 0.01 or
beyond reads another kind, the line to it is halved four times to find where the kind flips. **The score does not
enter**: G37 reads "moved" at 16,384 (its lattice starts leave their degree), and a neighbour that scores 0 but also
reads "moved" counts alike. Whether alike should also ask the law's settled probes to settle in the neighbour within
the score's margins is the operator's to decide (`docs/ROADMAP.md`, "Questions for the operator").

## Acceptance, line by line

| the acceptance | the test |
|---|---|
| every law of the zone where it stands, with since when; who runs now, by role, with its clock and typical time; the work left; the Dex laws in group A; an earlier law's runs behind the law in focus's; the typical times kept every five minutes | `tests/integration/test_the_map_page_shows_where_each_law_of_the_zone_stands_postgres.py` |
| the Dex laws' campaign takes no worker the zone is owed | `tests/unit/test_the_work_groups_share_the_fleet.py`, the last |
| the Map page draws the line, the rings' columns, the fold, Working now and the clocks | `tests/ui/dashboard_smoke.js` |
| a bundle's `focus.json` carries the zone now | `tests/unit/test_one_bundle_for_the_whole_study.py` |
| no output of a law moves | `tools/outputs_of_a_law.py --against` 880's record: 0 outputs changed |
| the full lane green | the Verification below |

## What it does not do

* **A zone's best law**: a region is still named after the law it was mapped from; the law that best stands for it
  (its best scoring member read alike, the nearest the middle on a tie) and the regions carried in the dex, so a dex
  read in does not map a region again, are to come (`docs/ROADMAP.md`, "From 881").
* The depth worker still climbs a law from 64 in its own campaign (the plan's 887).
* Home's "Now researching" is unchanged; Working now is on the Map page only.

## Verification

4207 passed, 41 skipped in 1157.34s (3 lanes at once)
