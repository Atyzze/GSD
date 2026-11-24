# Build 825: the score's list marks a study's standing controls, which corrects 821's reading of 169's scorers: its three best are its controls, and every one of the ten drawn laws that score comes through a lattice start. The tests' last study ids before 169 are out. Nothing a fleet runs changed; study 170 runs on 820.

**Type: the code base cleaned of everything before 169 (the operator, 2026-11-20 03:09), fourth step, and a correction to 821's reading of study 169.**
Changed: `tools/score_list.py` (a law of a controls campaign is marked "a standing control" and counted apart; its
JSON row carries `control`), `tests/unit/test_the_score_list_reads_every_chain.py`, the tests that named a study
before 169 by id or as a law's provenance (`test_a_pilot_is_read_against_the_build_before.py`,
`test_the_positive_control.py`, `test_the_steady_chain_gate.py`, `test_the_pilot_reading.py`,
`test_a_study_baseline_reads_the_folder_s_last_word.py`, `test_report_28_scores_every_chain.py`,
`test_the_top_list_ranks_every_scored_law.py`, `tests/integration/test_a_first_start_stopped_part_way_postgres.py`),
`docs/WHERE_WE_ARE.md`, `docs/ROADMAP.md`, `docs/agent/HANDOFF.md`, `docs/agent/NEXT_BUILD.md`.

## The correction

821 read 169's score's list as 13 laws scoring, "the three best through the random start and passed by every gate".
`tools/score_list.py` reads every campaign of a bundle, the controls' too, and did not say which was which: the three
best (`a283415b10db`, 57, d 1.99 with every point to 65,536; `c9b022c38d40`, 50, d 2.9; `6f364db7b709`, 46, d 2.08)
are 169's standing controls, laws whose answer is known, run in their own campaign with no gate. So, read again on
the same bundle: **the standing controls that should score do**, and **all ten of the 1,000 drawn laws that score come
through a lattice start**, each meeting one of 170's gates (one at 256, three at 1,024, six at 4,096, as 821 named
them). The list now marks a control in its table and counts the controls apart; 821's other numbers stand. The pages
that repeated it say it as above.

Seen on the way, not changed: on 169's controls the score names the given chain "given (random)" where it starts at
the declared answer; `tests/unit/test_the_score_list_reads_every_chain.py` holds that a control whose report carries
its `given_family` is called by its lattice, so report 28's entry for these controls lacks it. Recorded under
"Unscheduled".

## The tests' study ids

A test's synthetic study id is 169 where it was 161 or 162; an assertion's message names what it checks where it
named the older study's law it came from (165's `d9e91f4a4bd9`, 166's `ad98684468a0`, 162's top list); a test that
asserted a reading does not say "163" lost that line. Nothing they assert moved.

## What moved

Against 824's record (`tools/outputs_of_a_law.py --write` on the untouched 824 tree first): **0 outputs**. No frozen
source changed.

## Left

`tests/fixtures/space_score_ladders.json` (three standing controls' ladders grown on build 593's code, one of them a
law of study 154) waits for the ladders to be grown again on today's code. The committed controls' criteria keep
the history in their own words (studies 152 and 153 in `controls_criterion_2.json` and `_3.json`): they are pinned
inputs the fleet runs.

## Verification

3674 passed, 2 skipped in 1495.52s (3 lanes at once)
