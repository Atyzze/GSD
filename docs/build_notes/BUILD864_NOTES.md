# Build 864: the held laws run on, the law page as a 4x4 grid, and no law done

**Type: a feature build, asked for by the operator on 2026-11-25 at 09:42, 09:53, 10:03 and 11:06 (their words in
`docs/HISTORY.md`).** It may be applied to study 174's folder: no score, kind or decision of a law the run-on does
not name moves (`tools/outputs_of_a_law.py --against` 863's record, written first on the untouched tree: 0 outputs
changed; `tools/replay_bundle.py` on 174's bundle of 2026-11-25 09:59Z: 45,941 decisions, 0 differ). `decisions/`
changed (the run-on), and the science freeze was written again for `decisions/decider.py`, `let_through.py` and
`replay.py`, deliberately. Made from 863's archive in a session that could not reach the repository: the operator
opens the pull request.

## For the folders

**Study 174**: apply it, restart, open Map, and at the bottom "Held laws run on" press "run them on": 40 laws go on
from 16,384 to 65,536 (about 185 core-hours, half a day at 16 workers). Start the focus there too if it is not yet.
Watch in the next bundle: those 40 laws' decisions (`run_on` at 16,384, then their own at 65,536), and the gates'
ledger, which must not move for them.

## The held laws run on (09:42, option 3)

**The list first** (`tools/held_by_a_gate.py`, committed as `study_174_run_on.json`): on 174's newest bundle (09:59Z,
sent with today's message), 193 laws are held by `starts_alike` at 16,384 (165 at 06:26Z). Each is classed by the best
reading of any of its starts there, the rule written into the file: **40 read something, every one a line or a ring
(d under 1.3)**; none reads d 1.3 to 2.5 or above; 153 read nothing. So the list is 40, not 65. The 65 came from 860's
reading of 06:26Z's bundle, by a rule its notes did not record; on the accepted probe means of the newest bundle no
held law reads the middle band, and the chain from empty alone agrees (39 lines, 154 nothing). 17 laws more get a
nearest whole d of 2 from the space score with no probe reading at all (the two looked at are paths at mean degree
2.0 to 2.1); with no probe reading they are "nothing read".

**The action**: the Map page's last panel, "run them on" (`POST /api/focus`, `do: run_on`, behind the admin
capability) writes the folder flag `run_on`, each named law with its gate and size (`operations/run_on.py`); "name no
more" clears it. The decider offers a named law only while it is parked, idle, and its latest decision is that gate's
stop at that size (`DecisionStore.run_on_laws`), decides it again as any parked law, and `decisions/by_word.run_on`
turns that stop into `run_next` to the next size, rule `run_on`, its reason "run on by the operator's word past
starts_alike at N=16,384, to N=65,536 (the list)", the overridden stop in `facts.run_on`, the word in the decision's
inputs so it replays. The let-through ledger takes `run_on` as no verdict and skips the law's later decisions, so no
gate's counts or learning move (`docs/DECISIONS.md`, "A law run on by word"). The panel then lists each law as
waiting, running on, or settled again.

## No law is done (11:06)

"no law is ever 'done', its either waiting to be extended or settled by gate/score/condition/gg-type ... always mention
the highest N-reading". `observability/law_status.py` says a law's status from its state and latest decision:
**waiting to be extended** (read to the top of its ladder; the stored state `DONE` keeps its name, so every decision
replays), **settled at N=16,384** by a gate, its budget or a condition with the rule named (by a region GG#n where the
focus names one), **running**, **not started**. The law page's header chip and its first line, its engine-decision box,
the explorer's state column and Home's lines read it. C8-G2983 now reads "waiting to be extended: read to N=65,536,
the top of its ladder".

## The law page as a 4x4 grid (09:53, 10:03)

Sixteen charts, one size (360 by 236), four across, two across under 1,100 pixels and one on a phone (pinch-zoom kept):
row 1 the graph counted (mean degree, largest component, triangles and squares a node), row 2 the four probes, row 3
reach, curvature, energy a node and **the Einstein check** (d_s times d_w over twice d_V, each chain's own means, 1 on
a geometry), row 4 the run: sweeps until each chain was at rest or met the chain from empty, **redrawn as the classic
chart** (x = N, a mark a start in its colour, filled when every seed got there, hollow if not, each seed in its
mouse-over), the widest energy gap and how far each chain still fell (sweeps across, a line a size), and **how much of
its start each chain keeps** (the starts' reading's kept share, each lattice start at each size from 1,024). The table
below keeps its eleven columns.

## Tests

`tests/unit/test_a_held_law_runs_on_by_word.py` (the gate alone stops the law; the word runs it on to the next size,
reviving it from parked; a word for another gate or size changes nothing; every decision replays with the word and
without; the gate's ledger counts do not move; the flag's form); `tests/integration/test_a_held_law_runs_on_by_word_postgres.py`
(the page's action names only listed laws that read something and are in the folder, the store offers a law only
while its gate still holds it there and never twice, the panel's stages, "name no more"); `tests/unit/test_no_law_is_done.py`
(every state has words and none says done, the highest reading named); the law page's smoke checks the four rows, 16
charts of one size and the rest chart a mark a start.

## Left for the next builds

865: study 176 designed again, seeded from any bundle of the same science (its scoring laws and GG regions), its
blind batches and focus from its first law, and Home's top as one bar, blind against zoned (`docs/agent/NEXT_BUILD.md`).
The pages' build numbers in words (10:00) after it. The operator's two questions on 176 are in `docs/ROADMAP.md`.

## Verification

4017 passed in 1267.44s (3 lanes at once)
