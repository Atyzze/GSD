# Build 843: `--workers K` holds K slots, a seed stopped on a guessed memory bound runs again, no dated rule in the code, and two runs compared on the same work. For a new folder: the rerun of study 173 on 32 workers is made on it.

**Type: the fixes asked for at 12:11 and 12:35 after the rerun of study 173 on 32 workers, with the reading of both
runs; it changes which slots run and when a seed stopped on memory runs again, not what a law decides.**
Changed: `main.py`, `graph_scale_dynamics/scheduling/cpu.py`, `graph_scale_dynamics/scheduling/memory.py`,
`graph_scale_dynamics/domain/model.py`, `graph_scale_dynamics/db/repo_jobs.py`, `graph_scale_dynamics/db/repo_analysis.py`,
`graph_scale_dynamics/services/worker/main.py`, `graph_scale_dynamics/services/analyzer/main.py`,
`graph_scale_dynamics/services/api/fleet_snapshots.py`, `graph_scale_dynamics/decisions/let_through.py`,
`graph_scale_dynamics/decisions/gates.py`, `graph_scale_dynamics/decisions/engine.py`, `tools/two_runs.py`,
`tools/study_173_reading.py`, and the words of 11 more files of code and 12 of tests (below). New:
`tests/integration/test_a_seed_stopped_on_a_guessed_grant_runs_again_postgres.py`,
`tests/contract/test_the_operator_s_words_live_in_the_documents.py`. Tests changed:
`tests/unit/test_one_worker_a_physical_core.py`, `tests/unit/test_two_runs_of_one_design.py`,
`tests/unit/test_the_study_173_reading.py`, `tests/unit/test_a_cut_law_is_stopped_by_a_gate_of_its_own.py`. Documents:
`docs/agent/NEXT_BUILD.md` (844), `docs/agent/HANDOFF.md`, `docs/WHERE_WE_ARE.md`, `docs/ROADMAP.md`,
`docs/HISTORY.md`, `docs/OPERATIONS.md`, `docs/ARCHITECTURE.md`, `docs/TOOLS.md`,
`docs/agent/WORKING_WITH_THE_OPERATOR.md`. The schema
did not change and neither engine did. Four frozen sources moved and were anchored again: `decisions/engine.py` and
`decisions/gates.py` in words only (the structure gate's reason, the gates' descriptions), `decisions/let_through.py`
(the ledger's count of priced laws, which no decision reads), `measurements/calibration.py` (four families' `why`, which
is outside every calibration fingerprint, so no calibration is owed). Against 842's record (`tools/outputs_of_a_law.py --against`) no
output moved.

## The two runs of study 173, read

The first run (`study_173_2026-11-22T09-44-37Z`, 16 slots, 12.5 h) against the rerun (`study_173_2026-11-22T11-07-41Z`,
the same build, the same seed, `--workers 32`, stopped after 1.35 h), on what both had finished: 386 laws, 1,316
decisions, 3,786 seeds. **They are the same but for four laws, none of which scores**:

* `2c948bf61898`: in the first run an analysis at 65,536 passed its runaway bound (2.84 GB against 2.77 GB, a bound of
  four times a reservation of 0.64 GiB guessed from the fleet) and the law was stopped as failed; in the rerun it ran.
* `72b9b104013d`: in the rerun two seeds at 65,536 passed theirs at about 2.13 GB and the law was stopped as failed.
* `3de715630814`: at 16,384 the spectral gap of its random chain's last seed was read on a Lanczos solve that stopped
  at its 60 steps in the first run (0.00127) and converged in the rerun (0.00143); its decision was the same.
* `4382f83f531c`: readings apart by less than one part in 10^8 (the order of a sum), its decisions the same.

The first two are the memory bound below; the third is a solve on the edge of its step limit, which the last digits of
a sum tip one way or the other. 842's comparison also called a seed's CPU die and a recording gate's share of 1 a
difference; neither is (below).

**The speed.** Each seed ran 1.32 to 1.35 times longer in the rerun, at every size (the median beside its twin;
p90 1.43 to 1.59). Every slot was busy in both runs, in every ten minutes of their last samples: the first run 16 of
16 (13.8 simulations and 2.0 analyses) at 57% host CPU, the rerun 23 of 23 (18.1 and 4.7) at 77%. The rerun held 23,
not 32: on 841 `--workers 32` was only where the ramp started, its floor was one slot, and the ramp gives slots back
above 83% host CPU and stops near 75%, so within minutes it stood at 23 and held the CPU between 75% and 85%. On the
same work the rerun was ahead: it had made half of the decisions both runs made by 0.58 h against 0.72 h, nine tenths
by 1.17 h against 1.27 h. The base sizes (64 to 1,024) it finished by 1.34 h against 1.42 h, only 5% sooner, because a
law stays in its base block until its 4,096 seeds are done and only 48 laws are in their base block at once (the
campaign's `max_active_candidates`); the extra slots went to the deep sizes, 18 laws decided at 16,384 by 1.2 h that
the first run reached only after 11.5 h. That is the pace at which laws come in, and it costs no work: no slot waited.
A figure for SMT needs a run that holds 32 slots, compared on the same work; 843 makes one.

## `--workers K` holds K

`--workers K` now holds K slots: the ramp never gives one back (`scheduling.cpu.held_slots`, the ramp's floor and its
ceiling both K, or the ceiling `GSD_MAX_WORKERS` where that is larger), and the supervisor says so in one line. Without
`--workers` the fleet runs as before: the ramp grows to one worker a physical core, or to `GSD_MAX_WORKERS`, and gives
slots back above 83% host CPU. The start line no longer names a rule with its author and date; it says what the code
does.

## A seed stopped on a guessed memory bound runs again

A seed's or an analysis's memory bound is four times its reservation, at least 2 GiB, and its reservation is guessed
from the law's own earlier seeds or the fleet's profile. A seed that passed that bound was failed, so a law could fail
by the order in which seeds ran (the two laws above). Now a stop at that bound (the runaway) goes back to the queue
unspent, 30 s later, its peak recorded as `memory_runaway_requeued`, an interrupted attempt that is not the law's
failure; its next reservation is at least 1.25 times the peak it was seen at (`scheduling.memory.runaway_seen_bytes`),
so its next bound is at least five times that. A stop at the host's ceiling still fails as before. No decision reads
when a seed ran, so nothing a law decides moves; a law the first run failed this way would in a new run go on.

## The operator's words live in the documents

No code, test or printed line carries a rule with its author and date any more (the operator, 12:11). The rules stay;
who decided them and when is in `docs/HISTORY.md` and the notes. Changed: the slot line, the gates' and the
calibration families' descriptions, the structure gate's reason and the live panel's line on its switch, the explorer's
presets, the dashboard's two notes, the claim ledger's guideline, the study record's reading, three reports' letters
of an old decision, `tools/pilot_difference.py`, and the messages of 12 test files.
`tests/contract/test_the_operator_s_words_live_in_the_documents.py` holds it: on 842's tree it finds 32 lines.
The structure gate's reason now reads "its switch is on"; a reason recorded before is read in today's words by replay
(`gates.FORMER_PHRASES`).

## Two smaller fixes to the readings

The ledger counted a law stopped by its budget (`over_budget`) as held by every gate that stood against it, even a gate
that only records: in 173 the cut gate showed 25 held and held none. It now counts such a law as `priced`, and as held
only where the gate acts; with it 173's P3 holds. `tools/study_173_reading.py` reads an 841 ledger the same way (a
recording gate holds nothing) and names what it leaves out.

`tools/two_runs.py` leaves a seed's die and a recording gate's share of 1 out of the comparison, tells a reading apart
by less than one part in 10^8 from a difference, reports the slots busy from each bundle's occupancy series, and the
hour at which each run had made half, nine tenths and all of the decisions both made (the same laws in the same order,
so the same work); a wall-time gain only when both runs are done.

## The rerun on 843

Unpack 843 in a new folder and run `uv run python main.py run --study 173 --workers 32`, to its end or as long as
suits. It holds 32 slots, the same seed and the same laws as the first run, so `tools/two_runs.py <first run's bundle>
<this one's>` reads it against the first run, 841's: the same law by law except where a memory stop now runs again,
and the SMT figure on the same work. The host has 92 GiB and admission lends about 64 GiB: at 65,536 a seed takes 1.65
GB at the median and up to 6.3 GB, so 32 of them may not all fit; the governor holds the rest back.

## Verification

3842 passed in 1238.46s (3 lanes at once)
