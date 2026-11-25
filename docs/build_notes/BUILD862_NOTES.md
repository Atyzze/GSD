# Build 862: the Map page, where the focus is started, steered, stopped and watched, and every mapped region named GG#1, GG#2 and so on

**Type: a feature build, asked for by the operator on 2026-11-25 between 08:10 and 09:02 (their words in
`docs/HISTORY.md`).** No score, kind, gate or decision of a law moves: `tools/outputs_of_a_law.py --against` 861's
record, written first on the untouched 861 tree with its calibration table: 0 outputs changed. Nothing under
`decisions/`, `scaleflow/`, `measurements/`, `engine/` or `engine_rs/` changed, and nothing in `main.py`.

## For the folders

Any folder may take it. With no focus started it changes nothing a fleet runs: the Map page says "no focus in this
folder" and offers to start one. **Study 174**: open Map (beside Home), choose the study and "start the focus" with
the admin link; or, if 861's `python3 main.py focus --study 174` already started it, the page shows it as it stands.

## The Map page

Asked at 08:10 ("Calls for a dedicated page, titled phase map? Or just map rather") and 08:55 ("add the set focus
group functionality to the map page so it can be adjusted and observed from there as the data set grows"). One page,
read from the focus's own state (`GET /api/focus`, one flag, so it costs the API nothing), every change through
`POST /api/focus` behind the admin capability (`services/api/focus_route.py`, served beside the gate's route):

* **Start, stop, start again.** Stop pauses the focus's three campaigns (their running chains save and resume, as a
  campaign's pause does) and the controller's step reads nothing more; the blind draw goes on. Start again resumes
  them where they stood.
* **The split**: the shares of A (the blind draw), N (neighbours and seeds) and D (depth), the same setting as
  `main.py workload --split` and the System page.
* **Focus a law now** by its label (C1-G6940) or the start of its id: the law in focus is set aside as unconfirmed.
* **The settings of the next law**: its rings (radius:laws, 1 to 12 rings, at most 200 neighbours, the ring at 0.1
  kept since it confirms), the share that confirms, how many of the best laws go deep, the widest ring outward, and
  how near a mapped law a scoring law must be to be passed over. They apply from the next law that begins, so a
  reading under way never changes under its feet; the page shows what the next law takes until then.
* **In focus**: the law, its score, kind and stage; each ring's laws as alike, other and waiting, drawn as a bar; its
  own campaign's seeds and the seeds campaign's, each read alone, and whether its own reproduced; its sensitivity
  (its seeds, its exact parameters, or robust); how far its region reaches; its depth; each boundary line and where
  it stands; and "skip this law".
* **Regions**: every mapped region as GG#n with its kind, the laws it came from, how many laws read its kind, how far
  every ring read alike, its boundaries, and the range of every axis over its laws. Two regions of other kinds whose
  ranges overlap on every axis are said to touch: a boundary lies between them.
* **Depth**: each law taken deeper, how deep, to where it holds its kind, and where it was invalidated if it was.
* **The queue**: the study's scoring laws in the focus's order with where each stands (waiting, in focus, mapped,
  unconfirmed, invalidated, skipped, inside a region), "focus now" and "skip" on a waiting law, "put back" on one that
  ended or was skipped, so it can be taken again.
* **Ended**: each law whose focus ended, how, why, its region and its sensitivity.

The page polls every 4 s while it is open, as Home does. `main.py focus` stays as 861 left it, for a folder without a
browser (09:02: the pipeline otherwise as it was).

## GG numbers (`operations/focus_regions.py`)

Asked at 08:04 ("if new and no existing name, just create a new GG, G-group for it GG#391 or whatever number") and
08:29 (a term at coupling 0 is the term absent). A law is a point with one axis for each term it can hold, its
coupling, a term it lacks at 0, and the dynamics' axes: beta, locality, the swap share and zero temperature (1 or 0).
A term with a parameter is an axis of its own for each value (`degree_anchor k=4`). When a law's focus ends mapped,
its region is the law and every neighbour and line point that read its kind; its ranges are each axis's least and
greatest over them. It takes the next number, unless a region of the same kind already overlaps it on every axis: then
it joins that one, the lower number kept and the joining law named (`joined`). The numbers are new names, never graph
G codes; they live in the focus's state, so they survive restarts and go into the bundle (`focus.json`, and their
names in `study.json`'s `focus`). An unconfirmed or invalidated law gets no number. 176's map (`study_map`) keeps its
own regions; giving them GG numbers too waits for a folder that runs both.

## Smaller

* The focus reads the study's score boards once a step, not three times (the contenders, the next law, the queue).
* A law put in focus by hand leaves the skipped list.
* `main.py focus --show` names the regions with their spans, and says when the focus is stopped.
* **The box probe's time on the fleet ladder** (09:12: "these d_b Initial 0ms readout are concerning, and the
  suddenly in shoots up to ~8s?"): read, not changed. The probe answers in under a millisecond on a graph with no
  window of box sizes and takes seconds on one that has a window; up to 4,096 nearly every graph in 174 has none, so
  the median reads 0 ms, and by 65,536 the gates have left mostly laws with structure, so it reads 7 to 9 s. The full
  cost grows smoothly in the 95th percentile (campaign 1: 0 ms, 30 ms, 0.2 s, 1.1 s, 6.4 s, 29 s from 64 to 65,536).
  The ladder's headers keep to one short line (787), so the explanation is in `docs/ARCHITECTURE.md`; a split of the
  time into read and refused needs a schema change and comes with the fleet ladder under the filters.

## Tests

`tests/unit/test_the_map_names_its_regions_and_takes_the_operator_s_hand.py` (axes with absent terms at 0, ranges,
overlap, numbering and joining, touching, a region from the laws of the law's kind only, naming a law by label or id,
skip, put back, settings refused when they would break a reading, the next law taking the settings, an unknown action
refused by name, the command's words); the Postgres test starts, steers, stops and starts the focus again through the
page's own actions and checks that a stop pauses the focus's campaigns and never the blind draw's; the guard test
holds `POST /api/focus` to the admin capability; the smoke draws every panel of the page from a focus in its
boundaries stage, a folder with no focus, the rings' parsing, and a button's action and a refusal said on the page.

## Left for later

863, the 65 laws `starts_alike` holds at 16,384 that read something run on in 174 (the operator's choice at 09:42);
then study 176 designed again with A, N and D from its first law and the outliers' queue; then the engine's diet,
proven by replaying 176's seeds (`docs/ROADMAP.md`).

## What did not move

No score, kind, gate or decision: `tools/outputs_of_a_law.py --against` 861's record, 0 outputs changed.

## Verification

4005 passed in 1061.32s (3 lanes at once)
