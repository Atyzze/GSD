# Build 848: the score judged in 846 is put in force, as the operator agreed. It may be applied to the folders of studies 174 and 175: it changes no decision, only the score read beside them.

**Type: a reading, asked for by the operator on 2026-11-23 at 15:45 ("I guess I agree with the remaining
recommendations for builds 848", the recommendation being to put 846's candidate in force with trees of long paths
written down as a limit).** Changed: `graph_scale_dynamics/observability/law_score.py` (`gsd-law-score-8`: `counted`,
`CONNECTED_AT_LEAST`, `reach_rule`, `scale_at`, `scale_kept`, the next step in `items_along` and `score`),
`graph_scale_dynamics/observability/two_chains.py` (`chain_stopped` and the `counted` summary beside each chain's) and
`graph_scale_dynamics/resources/calibration/score_margins.json` (its `reach` block, q 0.2, trained as in 846): three
frozen sources, moved deliberately, the science freeze written again (`python3 tools/science_freeze.py --write`).
Also `graph_scale_dynamics/research/score_known_answers.py` (it judges the score in force; criteria 4 and 5's judged
readings and pages come out byte for byte as committed), `tools/score_list.py` (its `--candidate` is gone: there is one
score), `tools/top_laws_alike.py`, and the tests that read the score
(`tests/unit/test_the_score_reads_what_settled_at_its_own_scale.py`, `test_the_score_reads_every_start.py`,
`test_an_unread_lattice_fate_is_not_a_move.py`, `test_the_score_list_reads_every_chain.py`,
`test_the_perturbation_side_study.py`, `tests/scientific/test_the_score_settles_on_known_answers.py`), whose fixtures
now carry a reach that grows as their dimension. Removed: `graph_scale_dynamics/research/score_candidate.py` and
`graph_scale_dynamics/resources/readings/score_candidate_reach.json`. Nothing under `decisions/`, `scaleflow/`,
`measurements/`, `engine/` or `engine_rs/` moved; the schema did not change.

## What moves, and what does not

The score's number and its words move wherever they are read: the score board, the landscape, report 28, `finds.json`
and the law page. A reading counts only the seeds whose rung settled or whose chain stopped changing, only a piece of
half the graph, and a step settles only where the reach grows as the dimension read and the next step does not break
it. No decision reads the score: every one of study 174's 27,571 decisions in its first bundle replays
(`tools/replay_bundle.py`, 0 differ). The score does order a full deep lane's waiting laws
(`db/decision_store.laws_waiting_for_the_lane`), so in a live folder which waiting law a full lane serves first can
change, as the workers' own timing already changes it; never whether a law is bought, parked or stopped. Against
847's record (`tools/outputs_of_a_law.py --against`) 4 outputs moved: the law score's contract, 6 to 8, and its new
`connected_at_least`, on each engine; the law's score itself did not move, since its sizes are under 4,096.

## On study 174's first bundle

`tools/score_list.py` on the bundle: 61 laws score above zero, 4 with every point, 35 drawn laws settle at least one
probe (none frozen, every one from a lattice start), as 846 read the candidate there. A bundle carries no seed's settle
class, so the list counts every seed; in a folder the score counts them one by one, and report 23 calls the rungs
settled for only one of the 35 (`0fa748ea2652`, cubic, at rest), the others relaxing at their cap or metastable there,
so a bundle a folder writes on 848 should settle far fewer. Trees of long paths remain a known limit: they settle at
d 1.1 to 1.4 under this score as under the one before it, a random tree's spectral dimension being 4/3
(`docs/readings/score_known_answers_5_judged.md`).

## For the folders

Study 175 runs as designed on 847 without this build; its verdict reads each law's d and mean degree, not its score.
Given 848, either folder's next start reads its scores the new way; each needs one restart of its own command.

## Verification

3884 passed in 1497.52s (3 lanes at once)
