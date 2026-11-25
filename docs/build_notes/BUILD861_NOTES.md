# Build 861: the focus, the study's best laws one at a time inside their own study and beside its blind draw, their neighbours, their seeds and their depth; the reports late, not offline; a reading one seed gave drawn faint

**Type: a feature build, asked for by the operator on 2026-11-25 between 07:33 and 08:07 (their words in
`docs/HISTORY.md`), with the readings their questions asked for.** No score, kind or decision of a law moves:
`tools/outputs_of_a_law.py --against` 860's record, written first on the untouched 860 tree with its calibration
table: 0 outputs changed. Nothing under `decisions/`, `scaleflow/`, `measurements/`, `engine/` or `engine_rs/`
changed. One reading's contract moves: the science hash (`gsd-science-contract-2`, below). The seeded study planned
for 861 moves after the gates are revisited (`docs/ROADMAP.md`).

## For the folders

**Study 174**: take 861, then once

    python3 main.py focus --study 174

It makes three campaigns in 174's own folder (the neighbours, the seeds, the depth), puts the study's best law by
the folder's score in focus, and, if no split is set, gives the blind draw half the work slots and the focus the other
half (`A=2,N=1,D=1`; with a split already set, `python3 main.py workload --split A=2,N=1,D=1`). From then on the
controller does the rest at the end of every pass, at most once a minute: nothing more to switch, the blind draw goes
on beside it (keep `auto_extend` on and it never runs dry), and when a law's focus ends the next begins by itself.
`python3 main.py focus --study 174 --show` reads where it is; `--law <id prefix>` puts another law in focus now, the
one in focus set aside as unconfirmed. The next bundle carries the whole state as `focus.json`.

**Study 175**: pause it (07:44); its bundle of 06:43Z on 860 reads the same science as 174's, and only 3 of its 35
holders score by today's rule.

## The focus (`operations/focus.py`, `resources/readings/focus_plan_1.json`)

Asked at 07:33 ("2 worker groups for our current best candidate, 1 pushing N as high as possible and the other doing
random pertubations of it") and 07:47 ("does both automatically + pushing that N on the top contenders as well").

**Which law.** The study's best by the folder's own score, ties by campaign and graph number as the Top 100 orders
them (860). On 174's bundle of 06:26Z, 59 laws score: four rings at 19 (campaigns 1, 2, 6 and 8, d 1.02 to 1.06) and
a lattice start at 18 in campaign 3 (d 3.34), then 9 and below; so C1-G6940 first. A law whose focus has ended is not
taken again, and a scoring law that lies **inside a region already mapped** is passed over and named (`inside` in
the state): of the same kind, and nearer a mapped law than half the largest radius at which every one of that law's
neighbours read its kind (08:07: "score matters as to what to prioritize exploration compute on"). When every scoring
law is mapped or inside a mapped region, the focus waits for the outliers' queue (862).

**Three campaigns, two groups**, made once per folder and kept from law to law, each of the study's own design and
gates, its laws chosen and not drawn (a hand search policy), and none of them in the let-through ledger
(`db/decision_store.let_through_campaigns`): a gate's let-through share is learned from blind draws only.

| part | group | its laws | its ladder |
|---|---|---|---|
| N, the neighbours | N | 44 a law: rings of 4 at 1e-9, 1e-6 and 1e-3, of 8 at 0.01, 0.1, 0.2 and 0.4 | to 16,384, 3 seeds |
| S, the seeds | N | the law itself | to 16,384, 6 seeds |
| D, the depth | D | the law in focus and the study's best five by score | to 262,144, 3 seeds, its learning gates recording only |

A ring moves every parameter at once by its radius times a draw between a half and one, at random signs
(`research/perturb.variants`, as 175's did); 16,384 is the first size every kind is read at.

**Its seeds and its digits** (07:47: "being able to tell the difference is I feel important"). A law's random
streams are drawn from its own fingerprint (`engine/engine.py`, `stream_context`), so any move, however small, also
runs it on new streams: a ring of 1e-9 alone cannot tell a law sensitive to its exact digits from one whose outcome
depends on its seeds. So each of the law's seeds is also read alone (its kind from that seed's chains, `seed_kinds`),
its own campaign's three and S's six. S's seeds 0 to 2 are its own campaign's streams again, so they also show the run
reproduces (`reproduced`); 3 to 5 are new. Then:

* its seeds disagree: **its seeds**, the outcome is drawn, not set;
* they agree, and a move of 1e-3 or less reads another kind: **its exact parameters**, a knife edge;
* both agree: **robust**.

The law the operator remembered is very likely 175's H12 (aba936bffa, 174's campaign 3): another outcome in 4 of 4
moves at 1e-9 and in 4 of 4 at 0.001, where 175's moves as a whole kept their holder's outcome in 92% and 96%. It is hot
(beta 0.19) and scores 0 now; `python3 main.py focus --study 174 --law aba936bffa` reads which of the two it is.

**The stages.** *Neighbourhood*: the ring of 0.1 read whole; under two thirds of it reading the law's kind ends the
focus **unconfirmed** (175's rings kept their holder's outcome in 71% of moves at 0.1, 89% at 0.01). Else it waits for
every ring, for S and for D to hold the law's kind at 16,384 or deeper. If no neighbour from 0.01 out reads another
kind, a ring of 8 at twice the largest radius is added, until one differs or 0.8 (a relative move under 1 never flips a
coupling's sign); none differing to 0.8 ends it **mapped**. *Boundaries*: each neighbour of another kind from 0.01 out
is joined to the law by a line halved four times where the kind flips (`research/neighbourhood`, as 176's map does),
the boundary known to a sixteenth of its line; all lines done ends it **mapped**, with its boundaries. A ring under 0.01
that reads another kind is never a boundary: it is the law's seeds or its digits. *At any stage*, D reading another
kind than the law's own campaign at a size both read, or at 262,144 than its deepest, ends it **invalidated**, saying
where and what.

**The depth.** D's laws run 64 to 262,144 (the operator, 2026-11-14 19:58: one size at a time). Their first 65,536
are their own campaign's runs again on the same streams, about a quarter of D's work budget; D's gates that learn
record only (`let_through_from` above its top; the fact gates act as everywhere), so a law its own campaign let
through is not held in D by a gate still learning.
A seed's save at 262,144 is about 76 s by 65,536's 19 s, inside the 120 s a stop waits; 1,048,576 waits on the save (`docs/ROADMAP.md`).
C1-G6940's seed peaked at 1.46 GiB at 65,536, so about 7 GiB at 262,144, well inside one job's 60% of the host.

**What it carries.** The flag `study_focus`; `main.py focus --show`; the bundle's `focus.json` and `study.json`'s
`focus` (its campaigns, the law in focus, its stage, how many have ended). Each ended law keeps its kind, its rings'
tallies, its seeds read alone, its sensitivity, its depth, its boundaries and how far its region reaches (`alike_to`).
The controller logs `study_focus` when it adds laws, and `study_focus_failed` with the error, never stopping its pass,
if a step fails. An ungrouped campaign counts as the blind draw when the shares name A (174's batches were made before
groups), `scheduling/work_groups.in_shares`.

Tests: `tests/unit/test_a_focus_reads_its_law_by_seeds_moves_and_depth.py` runs the stages on a law's real rings
(unconfirmed, invalidated, outward to 0.8, a line halved to 0.25 to 0.3125, a tiny ring that is never a boundary, the
three sensitivities, a region's reach, a law inside one passed over);
`tests/integration/test_a_focus_runs_beside_the_blind_draw_postgres.py` starts 174's design in Postgres, focuses a law,
and checks the three campaigns, their ladders, seeds, groups and shares, the ledger without them, a second law in the
same campaigns, and that a law the study lacks makes nothing.

## The red box while a bundle is made

**What it was.** The reports page asks the API for its status every 4 s through the web process, which gives an API
answer 1.5 s unless the route is a slow one. While a study bundle is being made the API is busy, the status took
longer, the web process answered 503 or 504, and the page drew the red "reports status unavailable" box and "reports
offline", though nothing had failed. **Now** the reports' routes get 10 s like the other slow ones
(`services/web/main.SLOW_ROUTES`), and a 503 or 504 within a minute of the last answer shows a quiet line, "the reports'
status is late (last answer N s ago)", the badge "reports late", and the last answer stays on the page. A minute of
silence, or any other failure, is the red box as before. The smoke runs it: late on a 503, offline after a minute,
offline at once on a 500.

## A reading one seed gave, drawn faint

Asked at 07:51 ("extreme outliers for d_w, a value around ~8.6 ... another single data/probe at ~6.6 as well and 2 at
4 ... same for d_V, 3 outliers"). On 174's bundle of 06:26Z, of 641 laws with a d_w reading, 99% read under 2.87; of
982 with d_V, 99% under 2.24. The outliers:

| law | probe, value | from | the graph there | every seed at the larger sizes |
|---|---|---|---|---|
| f1307c3a2c (C1) | d_w 8.59 | 1 of 3 seeds at 256 | mean degree 22, its largest piece 55% | no scaling window at 1,024 and 4,096 |
| 5ec523ff7b (C5) | d_w 6.64, d_V 3.92 | 1 and 2 of 3 at 1,024 | mean degree 2.2, a quarter in its 2-core: a tree | growth undecided at 4,096, exponential at 16,384 |
| 3924efb6f0 (C10) | d_w 4.07 | 1 of 3 at 256 | mean degree 11 | no scaling window at 1,024, exponential at 4,096 |
| dae579fe73 (C9) | d_w 4.01 | 1 of 3 at 256 | mean degree 9, its largest piece 28% | exponential at 1,024 and 4,096 |
| 6bed81506e (C9) | d_V 4.64 | 2 of 3 at 4,096 | mean degree 3, half in its 2-core | growth undecided at 16,384 and 65,536 |
| cc3738844e (C8) | d_V 3.34 | 1 of 3 at 1,024 | mean degree 2.2: a tree | exponential at 4,096 |

None scores, and the probes were right at every larger size: a walk on a graph in pieces is held in its piece, so its
spread stalls and a fit over a short window reads a walk dimension far too high; a tree that grows exponentially reads
a volume dimension that climbs with N until the growth class says exponential. The landscape plots each law's latest
reading, whatever stood behind it. **Now** each point carries, for each probe, how many of its seeds gave the reading
and at which larger sizes every seed refused it, with the reason (`landscape_worker.reading_support`,
`readings_from`); a reading one seed of three gave is drawn faint and dashed, and its tooltip says "read on 1 of 3
seeds at N=256 ...; every seed refused it at 1,024 (no scaling window), 4,096 (exponential growth)". In 174, 146 d_w
readings of 641 and 178 d_V of 982 are one seed's.

## The science hash over the table's cells

`gsd-science-contract-2`: the calibration table enters the hash by its science (its analysis version, its estimator's
fingerprint and its cells), not by its file's bytes, which also carry the times it was adopted. 174's two bundles and
175's carry tables whose files differ only in those times; their cells' hash is the same (`f523d0baebe7e46c...`), so
their science hashes are now the same, as they should be. The file's own SHA-256 stays beside it, outside the hash.

## Left for a later build

862, the outliers' queue and the GG numbers (08:04 and 08:07); then the seeded study with the gates revisited, the
fleet ladder under the filters, the map's term axis and the depth past 262,144 (`docs/ROADMAP.md`).

## What did not move

No score, kind, gate or decision: `tools/outputs_of_a_law.py --against` 860's record, 0 outputs changed. 174's
batches decide as before: the focus's campaigns are outside their let-through ledger and their learning batches.

## Verification

3990 passed in 1076.32s (3 lanes at once)
