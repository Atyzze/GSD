# Build 828: the fact gates read three sizes in a row, and study 171 carries it: start 171 on this build, not on 827, in a new folder. On study 169's laws replayed by the engine, the rule stops none of its 10 scoring laws, where one size stopped 4, for about 7% more work.

**Type: the operator's question of 2026-11-20 11:27 answered from study 169's bundle, and their choice of 11:39
carried: the empty, too dense and disconnected gates decide on three sizes in a row, then 171 on it.**
Changed: `decisions/engine.py` (`Policy.fact_sizes_in_a_row`, the three verdicts, `SET_FIELDS`), `decisions/gates.py`
(the three gates' descriptions), `resources/readings/study_171_design.json` and `study_171_criterion.json` (revised
before any start), `resources/readings/studies.json`, `tests/fixtures/committed_readings.json`,
`tests/fixtures/science_freeze.json`, `tests/unit/test_the_fact_gates_read_three_sizes_in_a_row.py` (new),
`tests/unit/test_the_baseline_study_stops_a_law_only_on_the_facts.py`, `docs/DECISIONS.md`, `docs/OPERATIONS.md`,
`docs/HISTORY.md`, `docs/ROADMAP.md`, `docs/WHERE_WE_ARE.md`, `docs/agent/HANDOFF.md`, `docs/agent/NEXT_BUILD.md`.

## The question

The operator, 11:27: "what happens if we reconsider that choice to instead always require a trend of 3 rungs in a row
looking the same, or at least showing the same trend? Because if it's empty, or at least basically if it's too sparse,
... maybe that's a fluke. Whereas if the 3rd gate would, for example, show a slight increase, suddenly it would make
less sense to abort it". And: "I think we have enough data to answer my question already."

**How the fact gates decided until now** (each of a law's eight chains alone; a law stops only when every chain does):
`empty`, mean degree at most 0.05 at every size so far, from 256, so on two sizes (64 and 256) there; `too_dense`,
mean degree at the cap of 32 at the size alone, from 256; `disconnected`, the largest component under half the graph
at the size and not grown since the size below, from 1,024.

## Read on study 169

169 recorded every verdict and stopped no law on one below 16,384, so every one of its 1,000 drawn laws ran to 4,096
at least. Each of its decisions replayed by the engine, with the fact gates acting and nothing let through, every
other gate recording:

| rule | laws stopped on a fact | at 256 / 1,024 / 4,096 / 16,384 | of its 10 scoring laws | laws with a start later out of every fact zone on seeds at rest |
|---|---:|---|---|---:|
| one size (until now) | 694 | 467 / 218 / 9 / 0 | 4 stopped: `a3821d783b1f` 23, `2ccc10742c72` 14, `719667adb61b` 7, `d3064b8bccee` 7 | 3 |
| three sizes in a row | 665 | 0 / 633 / 29 / 3 | none | the same 3 |

The four scoring laws had every start at the cap, or empty, at 256 or 1,024, and their scoring start lower later:
`2ccc10742c72`'s bcc start read a mean degree of 22.7, 25.6 and 32 at 64, 256 and 1,024, then 8.3 at 4,096 and 8.0
at 65,536 (the bcc lattice's own degree is 8). At 4,096 and 16,384 those seeds were cut by the budget and at 65,536
they reached the sweep ceiling, so whether they would have filled up at the larger sizes with more work is what 171's
larger budgets read. The 3 laws both rules lose had their random start empty at 64, 256 and 1,024 and connected at a
mean degree of about 4.5 at 4,096 on seeds at rest; no reading of the smaller sizes shows it, and none scores.

Chain by chain under the rule until now: of 551 chains too dense at 256, 76 later read under the cap (66 of them on
seeds not at rest there, cut by the budget or at the sweep ceiling); of 3,181 empty at 256, 102 later had edges (87 at rest); of 1,605 disconnected at 1,024, 42
later connected (12 at rest).

The trend part was read too (a script over the same decisions' rungs): without it, 5 more laws are lost, most with
their mean degree climbing from about 1.3 to 1.8 while under half connected, and connected by 4,096 or 16,384; reading the mean degree's own
trend as well keeps 2 lost laws in place of 3, for about 17% more work in place of 7%. The extra work is the work 169
spent between where a law stops now and where the rule stops it (its budgets).

**Four sizes in a row** (the operator, 11:48, asked; 171 keeps three, "just finish study 171"): replayed the same way,
628 laws stopped, 618 at 4,096 and 10 at 16,384, no scoring law and none of the 3 lost, about 20% more work than one
size. **What a trend is** (11:48: "I do want to know how we define a trend"): here, a direction only, with no size:
empty breaks its row if the last of the three is the highest and above the first, by any amount; disconnected if the
largest component grew at the last step, by any amount; too dense reads no trend (the cap is a ceiling). So a rise as
small as the seeds' own scatter keeps a law going: the rule errs toward running on. A trend read against the seeds'
own spread (a change beyond twice their combined error, as d_s's settling is read), and four sizes, are read on 171's
bundle beside three (`docs/ROADMAP.md`, 9c).

**The operator's word of 11:48** also: studies 169, 170 and 171 are the only data sets kept; the 2019 model's readings
leave with the cleanup's end, which comes first in 829 (`docs/agent/NEXT_BUILD.md`); no larger study without gates:
the let-through keeps testing every gate, and at 100,000 laws it says whether any gate stops a law that later
proves interesting.

## The rule

`Policy.fact_sizes_in_a_row` (0 until now, 3 in study 171's design): each fact gate decides only on that many sizes in
a row, so from 1,024. `empty`: mean degree at most 0.05 at all three and not rising (the last of the three the highest
and above the first); `too_dense`: at the cap at all three; `disconnected`: under half the graph at all three and not
grown at the last step. The verdict says its sizes ("mean degree at most 0.05 at N=64, 256 and 1,024, 3 sizes in a
row, and not rising"). A policy without the field decides as before, and the field is left out of a policy's
fingerprint where it is 0 (`SET_FIELDS`), so a decision recorded before keeps its fingerprint: 170's bundle replays on
this tree, 9,843 of 9,843, every one with the same rules.

## Study 171, revised before any start

Its design gains `fact_sizes_in_a_row: 3` and says why (`decided.fact_gates`); its criterion, committed again before
any start: R3 no fact gate before 1,024; R4 the three stop 55% to 72% of the laws at 1,024 and leave 28% to 45% to run
on at 4,096 (169 under the rule: 633, 29 and 3); R6 about 300 core-hours a 1,000 laws (150 to 650), about 19 hours on
16 workers; new, R7: of the laws a fact gate withholds and lets through, at most 1 in 20 has a start later out of every
fact zone on seeds at rest (169: 3 of 665, none scoring). It reports the fact gates on three sizes against one, every
decision replayed under 827's rule. **827's 171 has the old rule: start 171 on 828.**

## What moved

Against 827's record (`tools/outputs_of_a_law.py --write` on the untouched 827 tree first): **0 outputs**. The rule
acts only where a design sets it; the recorded law's design does not.

## Left

829: the cleanup's end first (the three leftovers and the 2019 model's readings), then the gates' counters the
study's (`docs/agent/NEXT_BUILD.md`). 171's bundle read first by the build it reaches.

## Verification

3683 passed, 2 skipped in 1346.44s (3 lanes at once)
