# Build 844: the stable build, carrying study 174, the stable trial, 10,000 laws in ten batches of 1,000. For a new folder: start 174 on it with `uv run python main.py run --study 174`, 16 workers.

**Type: the stable build the operator asked for (2026-11-22 15:50 and 15:51): the gates they chose at 15:38 and the
study that tries them for days, nothing else.** Changed: `graph_scale_dynamics/decisions/engine.py` (`gate_from`,
`Policy.acts_from`), `graph_scale_dynamics/decisions/let_through.py` (the ledger's share reads it). New:
`graph_scale_dynamics/resources/readings/study_174_design.json`, `study_174_criterion.json`, its entry in
`studies.json`, `tests/unit/test_study_174_is_the_stable_trial.py`. Tests changed:
`tests/unit/test_study_173_is_the_gated_pilot.py`, `tests/unit/test_the_inputs_are_committed_in_one_place.py`.
Documents: `docs/agent/NEXT_BUILD.md` (845), `docs/agent/HANDOFF.md`, `docs/WHERE_WE_ARE.md`, `docs/ROADMAP.md`,
`docs/HISTORY.md`, `docs/OPERATIONS.md`, `docs/DECISIONS.md`. The schema did not change, nor either engine, nor a
probe; no calibration is owed. Two frozen sources moved and were anchored again (`decisions/engine.py`,
`decisions/let_through.py`). Against 843's record
(`tools/outputs_of_a_law.py --against`) no output moved.

## What makes it the stable build

Nothing is added but what the operator chose. 173 ran three times on 841 and 843, on 16, 23 and 32 slots, to the same
decisions law by law but where a memory bound guessed from the fleet failed a law (843 runs such a seed again), and
every decision of each run replays. 843 took the last dated rules out of the code. Left out on purpose (the operator,
15:51): the planted faults, the perturbation of the best laws, a ladder past 65,536 and every other new thing, until
174 has run for days on this build. If it runs as predicted, 844 is the stable point, the data before it can go, and
study A is 174 ten times over.

## The gates

`nothing_read` acts only from 16,384: a design may give a gate the size it acts from (`engine.gate_from`, pairs of a
gate and a size; `Policy.acts_from`); below it the gate's share is 1, its verdict recorded on the law's decision and
the law let on, and from it the gate's own share, a tenth. `starts_apart_by_history` records only (its share 1). In 173
`nothing_read` stopped 115 laws at 4,096 and let on 18, 3 of which score, so it lost about 20 scoring laws a 2,500; one
of the six scoring laws that went on only by a tenth went on past `starts_apart_by_history`. Replayed under 174's design,
none of 173's 63 scoring laws is stopped below the size it scores at. The empty, too dense and disconnected gates (on
three sizes in a row from 1,024) and `starts_alike` stop a law as in 173, a tenth let through; every other gate records.
Every acting gate carries its own share of a tenth through the whole study, never moving as a gate confirms, so that
its 10,000 laws say what a hundredth would give (the operator, 15:55).

## Study 174, the stable trial

`study_174_design.json`: 173's design on ten search seeds drawn with `secrets.randbits(63)` at 2026-11-22T14:52:29Z,
one a batch, each batch 1,000 laws (`law_budget`), the ten batches running together as one study, its ladder to
65,536, its starts, seeds and budgets. Every acting gate carries its own share, so no gate learns and no law waits on
another batch. The host runs 16 workers, one a physical core, with no `--workers` (SMT measured on 173: 32 slots about
1.12 times faster over a whole study, the same decisions; decided against, 15:38).

The criterion (`study_174_criterion.json`, committed before any start), from 173's 8,946 decisions replayed under 174's
design and carried to 10,000 laws (`tools/design_on_a_bundle.py`): every decision replays and all ten batches read
done (P1); only the five gates hold a law, `nothing_read` only from 16,384 (P2); a tenth at 1,024 (P3); 3,800 to 5,100
laws reach 4,096, 1,300 to 1,800 reach 16,384, 550 to 950 reach 65,536 (P4); at most 3 laws let through past an acting
gate score (P5); 230 to 450 drawn laws score (P6); at most 2% stopped over_budget (P7); no law fails on a guessed memory
bound (P8); **900 to 1,700 core-hours, the replay's 1,274, 714 of them at 65,536: about three and a half days on 16
workers** (P9).

**What that says of study A**: ten times 174, about 12,700 core-hours, about 33 days on 16 workers, just past the
month. 174 measures it on laws the gates were not chosen on; 56% of it is the 65,536 rung, the lever if it is too
long, and the same rung is the operator's question of whether to go past it (`docs/ROADMAP.md`).

## Verification

3846 passed in 1315.40s (3 lanes at once)
