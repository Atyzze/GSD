# Build 826: the space score's ladders grown again from the five standing controls on today's code, in place of three ladders of build 593, one of them a law of study 154. The last fixture of a study before 169 is out. Nothing a fleet runs changed; study 170 runs on 820.

**Type: the code base cleaned of everything before 169 (the operator, 2026-11-20 03:09), fifth step: the space score's ladders.**
Changed: `tests/fixtures/space_score_ladders.json`, `tests/unit/test_space_score.py`, `docs/ROADMAP.md`,
`docs/WHERE_WE_ARE.md`, `docs/agent/HANDOFF.md`, `docs/agent/NEXT_BUILD.md`.

## The ladders

P1, P2, N1, N2 and C1, the five laws of `controls_criterion_2.json`, each grown at 64, 256, 1,024 and 4,096 nodes on
seeds 0 to 2 on the job's own path (the spec `operations/standing_controls.campaign_spec` makes, `one_shot_policy`,
the Rust engine, the analysis and `observability/two_chains`), and reduced to the keys `observability/space_score.py`
reads, as the old fixture was. What the score reads on them:

| control | stage | spaces | given chain d, worst | chain from empty, worst | gaps at 1,024 and 4,096 |
|---|---:|---|---|---|---|
| P1 (2D, the square torus given) | 2 | given | 2, 0.29 | 5.42 | 28.1, 37.3 (worst: reach) |
| P2 (2D, finite temperature) | 2 | given | 2, 0.29 | 5.54 | 28.0, 37.0 (worst: reach) |
| N1 (negative) | 1 | none | none, 1.04 | 1.18 | 0.13, 1.41 |
| N2 (negative) | 1 | none | none, 7.89 | 8.25 | 0.26, 0.68 |
| C1 (3D, the cubic quotient given) | 1 | none | 3, 3.33 | 12.3 | 29.6, 50.0 |

The test holds what each control is for: the two-dimensional controls are spaces at d 2 with their four probes
inside the margin and the chain from empty far from them; the negative controls are not, their given chain near the
chain from empty at 1,024; C1 reads three dimensions and does not settle by 4,096 (169's bundle has it settle by
65,536, score 50). Three of the old fixture's numbers do not hold on today's code and are not asserted: P2's worst
step was 0.9 to 1.0 there (d_B at 1.72 on the torus at 4,096) and is 0.29 now, the probes having been fixed since;
its chain from empty's worst was above 10 and is 5.5; N1's chains were within 1 of each other at every size and are
1.41 apart at 4,096.

## What moved

Against 825's record (`tools/outputs_of_a_law.py --write` on the untouched 825 tree first): **0 outputs**. No code
changed; one fixture and its test.

## Left

What carries the past now is history and kept files: `docs/HISTORY.md` and the build notes, the 2019 model's
criteria and readings (the operator, 2026-11-19 22:05), the committed controls' criteria in their own words (pinned
inputs the fleet runs), and the pointers to the readings archives.

## Verification

3674 passed, 2 skipped in 1074.38s (3 lanes at once)
