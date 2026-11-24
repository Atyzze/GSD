# Build 859: the handover of the context that made 856 and 857. Home's landscape keeps its whole plot above the filters, the Top 100 lists every law of a small campaign, and a fresh context starts from the repository alone

**Type: a handover, asked for by the operator on 2026-11-24 at 23:00 ("create 1 more hand-over built so the next
context can make a fresh start from source alone"), with the fixes to Home they sent at 23:07 and 23:09
(`docs/HISTORY.md`).** No score, kind, gate or decision moves; nothing under `decisions/`, `scaleflow/`,
`measurements/`, `engine/` or `engine_rs/` changed.

## For the folders

Any folder may take it, 174's included: it changes Home and what the landscape carries, nothing a fleet runs. Each
campaign's landscape is built once more after the restart (its inputs' contract moved, `gsd-landscape-inputs-3`), so
the Top 100 and the filters fill in a few seconds later than usual the first time.

## What Home does now

**The landscape's plot is whole.** 857 put the Filters panel inside the landscape's row and left the row's height
alone, so the plot lost the panel's height at its bottom: the FLOWING band and its points were cut off in the
operator's screenshots of 23:07 and 23:09 (88 px at their 1,749 px width, 198 px at 1,280 with many kinds). The row
is now the landscape's own height (`--gsd-land-h`, the whole row's height before 857) plus the filters' height as the
page measures it (`--gsd-filter-h`, `measureFilterHeight`, watched as the panel resizes) plus the gap between them.
The Top 100 fills the row, so it grows by exactly what the filters add. Below 1,250 px, where the boxes stack, the
landscape keeps its own height. `tests/ui/hero_check.js` measures this in Chromium at 1,100 to 1,920 px: nothing of
the plot below its panel, the plot at its floor, the Top 100 as tall as the row. On 857's stylesheet it fails at
every width (`tests/unit/test_the_landscape_holds_its_plot.py`). The smoke's checks of the stylesheet's arithmetic
were right and did not see it: they never counted the filters in the row.

**The Top 100 lists every law of a small campaign.** The list took a law whose chain from empty read nothing only
when it scored above zero (`landscape_worker.top_candidates_of`, since 776). C11, the standing controls, has five laws
and none reads anything from empty. Three score: by their terms, P1 (9, a lattice kept), P2 (1, frozen) and C1 (1,
still) of `controls_criterion_2.json`. N1 and N2 are the negative controls, which must read nothing, and they score 0,
so the list left them out. Now the places the list leaves empty go to those laws, the deepest first, after every law
listed before. Nothing that was listed moves, and a batch with a hundred laws listed already is unchanged.

**A lattice start's point says its kind.** With "include lattice starts" ticked, a law is drawn at its scoring start's
readings, from a point that `landscape_worker.marked` never saw. It read "not read yet" and fell out of any group or
batch filter: 15 laws not read yet in the operator's screenshot, 17 with lattice starts ticked. Each start's point is
now marked as its law's (`build_landscape`); `tests/integration/test_the_landscape_s_inputs_postgres.py` holds every
point the landscape draws to its kind, group, batch and region.

## The handover

**What the context of 856 and 857 learned, and where each piece now lives:**

| what | where it lives now |
|---|---|
| A simulation on every hardware thread starves the API: 32 of 32 slots, the round trip 463 s, the page stale and answering 503 (18:26); a faster refresh asks more of the starved process | `docs/LESSONS.md`, "Host state"; the Workload panel (856) |
| 857's filters shortened the plot, and the stylesheet's checks could not see it | `docs/LESSONS.md`, "Pages, controls and settings"; `tests/ui/hero_check.js` |
| A short list's rule hid two of five laws; a field put on every point missed the points made elsewhere | `docs/LESSONS.md`, "Pages, controls and settings" |
| A change to what a landscape carries needs its inputs' contract moved, or a finished campaign keeps the old one | `docs/LESSONS.md`, "Releases" |
| Every page is read for a gendered pronoun, of anyone; 856's gate failed on one | `docs/LESSONS.md`, "Releases" |
| A number said before where it was measured: SMT was credited to the work unit's fit, which never read it | `docs/LESSONS.md`, "Evidence" |
| Two builds made in between (858, 859) each moved the plan's numbers on five pages | `docs/LESSONS.md`, "Documents"; the plan now names its builds by what they make |
| `gh pr create` is refused in this sandbox; the REST call opens the pull request | `docs/agent/ENVIRONMENT.md`, section 9 and step 14 |
| The opt-in for a device's CPU model and timings (18:28); the two kinds of scouts (18:32); the 23:00 handover; Home at 23:07 and 23:09 | `docs/HISTORY.md`, the standing decisions |
| Is the Rust engine as lean as it can be (18:28) | `docs/ROADMAP.md`, "Unscheduled" |
| Home's refresh every 0.5 s, and a control for it behind the admin link (18:26), held back while the API is starved | `docs/ROADMAP.md`, "Questions for the operator" |
| A table of devices by their throughput, a high score among peers who opted in (18:32) | `docs/ROADMAP.md`, "Planned builds", after the paper |
| The Filters panel counts the landscape's points only: C11 reads "1 of 1 laws shown" for five laws | `docs/ROADMAP.md`, "Planned builds", item 1, for a later build |
| 858's leftover, the notes of 823 to 845 into `docs/HISTORY.md`'s eras | `docs/ROADMAP.md`, the consolidation |
| `main.py` stands 604 bytes under its ratchet, where the seeded study's flag will press | `docs/agent/NEXT_BUILD.md`, 860 |

**A fresh start from the repository alone, made and used.** This build was made on a clone of `main` as merged at
858 (`git clone https://github.com/Atyzze/GSD`), brought up by `tools/prepare_environment.sh` with `GSD_TREE` and
`GSD_PREFIX` pointing at it: every step found or made what it needs (the table seeded from
`calibration/seed_table.json`, as from an archive), and the quick check passed, 216 tests in 171 s. The same clone ran
the gate and is the checkout the pull request was pushed from. `docs/agent/ENVIRONMENT.md`, section 10, now opens with
this route and step 14 says how the pull request is opened from the sandbox; `docs/agent/HANDOFF.md`, "Start here",
names it first.

**The plan names its builds by what they make.** The seeded study, group D and the consolidation are the next three
builds, in that order, each given its number when it is made (`docs/ROADMAP.md`, "Planned builds"); the archive the
consolidation sends is named for its build then.

## Left for a later build

The Filters panel counts the laws the landscape draws, and a law that reads nothing from empty is drawn nowhere, so it
is in no kind's count: with the Top 100 now listing all five of C11's laws, the panel still says "1 of 1 laws shown".
Counting every law needs each law's kind from the score board beside the landscape's points, the same server change
as the ladder's live counts by kind (857).

## What did not move

No score, kind, gate or decision: `tools/outputs_of_a_law.py --against` 858's record (written on 858 as merged), 0 outputs changed. The order of
the Top 100 is the same for every law it listed before; only its empty places fill.

## Verification

3956 passed in 1266.45s (3 lanes at once)
