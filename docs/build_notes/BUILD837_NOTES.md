# Build 837: the cleanups that touch nothing a study decides, each fixed or closed with its reason. Not for study 172's folder: 172 runs on 835 to the end.

**Type: the roadmap's list of items that touch nothing a study decides, taken whole (the operator, 2026-11-21 06:02:
"yes"); and the plan's study-wide build dropped until 172 measures it (06:01).**
Changed: `services/worker/main.py` (`COMMITTING`: a heartbeat naming the job before its commit),
`services/api/overview.py` (`committing_jobs`, a running row's `phase`), `db/repo_records.py` (the dashboard's job
snapshot carries the job's id), `resources/ui/app.js` (the live list's `committing`; `liveElapsedSeconds`),
`tools/package_release.py` (`tracked_files`, `left_untracked`), `operations/campaign_control.py`
(`workers_problem`; `apply_allocation` all or nothing), `services/api/campaign_manager.py` (the delete guard again
under the lock), `services/api/main.py` (the manage route answers a failure), `tools/disordered_reading.py`
(`study_campaigns`, `left_out`), `.gitignore`. Tests: `tests/integration/test_running_work_is_listed.py`,
`tests/integration/test_campaign_pause_postgres.py` (two cases), `tests/integration/test_operator_path.py`,
`tests/unit/test_archive_and_ignore_agree.py`, `tests/unit/test_operational_resilience.py`,
`tests/unit/test_nothing_outlives_its_folder.py`, `tests/unit/test_the_disordered_reading.py`,
`tests/unit/test_a_resumed_seed_keeps_its_time.py`, `tests/unit/test_the_eight_starts_run.py`,
`tests/unit/test_a_seed_ends_at_its_budget_in_work.py`. The schema did not change, so a folder running now opens this
build; no frozen source moved; against 836's record (`tools/outputs_of_a_law.py --against`) 0 outputs moved; the
table's lock prints `analysis-5.3.0 e639334808716378 89f4fed82d9adc27`.

## Fixed

* **A seed whose worker commits reads `committing`, not evolving.** Once a seed's child exits well, its worker writes a
  heartbeat naming the job and `phase: committing` before the commit, whatever the heartbeat's pace, and a beat that
  fails is logged and never stands in the commit's way (`say_committing`); both overviews
  mark that job's running row, and Home's live list draws it `committing`. A worker committing another job's result
  marks no row.
* **The release ships only what git tracks.** It took every file under its directories but a list of names; a
  host's or a tool's file left in the tree would have shipped. In a git checkout it now ships the tracked files and
  prints each one it left out; an unpacked archive with no git ships what it holds. 836's archive and git's list were
  the same 1,186 files, so nothing had leaked.
* **`tests/integration/test_operator_path.py` runs its fleet in a folder of its own** (`.pytest_operator_var_*`,
  ignored by git), not in the tree's own `var/`; `main.py` refuses a folder outside the tree, so it stays in it.
* **The Campaigns page divides the fleet all or nothing.** `apply_allocation` set each campaign's share in turn, so one
  bad share (a word, a campaign not active, one unknown) left the shares before it changed and the page said refused.
  Every share is now checked first (`workers_problem`) and none is changed if one fails. **The manage route answers a
  failure** as JSON with what failed, where an exception had closed the connection with no answer.
* **A deletion checks its guard again under the maintenance lock.** The guard (paused, no clone of it) was read before
  the lock was taken, so a campaign resumed while the deletion waited would have gone; it is read again inside.
* **The disordered reader leaves a study's controls out**, naming them, where it pooled the standing controls with the
  study's laws; a bundle with no study reads every campaign as before.
* **The last dashboard test that read the page's source as text runs its code**: the time a resumed seed spent before
  is run in node through `liveElapsedSeconds` (a probe never counts it), and the overview's row is built and read.
* **Two timing assertions count work instead**: a stop seen within a tick is now at most 56 moves of 8 ms, which a
  busy host can only make fewer; eight starts grouped walk fewer than 100 of the 4,140 partitions, counted.

## Kept or closed, with the reason

* **The three connectivity floors, `DEGRADED_WITH_N` and `audit_sample` keep their names**: each is a recorded key (a
  campaign's spec, an engine policy's fingerprint, every report's bucket counts), so a rename moves recorded data for
  no new reading. `docs/DECISIONS.md` names the third floor now, the landscape's own default.
* **The CPU tile's btop**: the publisher's dies with it (`power_sidecar._die_with_parent`) and an orphan one is ended
  at every fleet start (`leftovers`, `orphan_tile`).
* **A re-made folder's old PostgreSQL** is ended by `leftovers` (`replaced`); a test now holds it, a stand-in server of
  the deleted folder gone and the re-made folder's own kept.
* **The staleness probe missing in-place rewrites**, named by the 2026-10-20 review, is not in today's code: the
  source fingerprint hashes every byte and the landscape counts inserts, updates and deletes.
* **Moved, not closed**: the claim lock's partial index is a schema change, and `init_db` holds a running folder to the
  schema's checksum, so it waits for "With the next schema"; the control-family match at a nearby size changes which
  laws a control withholds points from, so it is a change to the score, read on the pilots' laws first.

## The plan

The study-wide build is dropped (the operator, 06:01: "we've ran a 50k law study Bundle before and while it took like
10m, it worked fine"). What came after that bundle and grows with the whole study (the decisions' inputs, 135 MB for
171's 4,722 decisions; the learning's pass over every batch; 836's chain peaks) is measured on 172's bundle and scaled
first. Next: 172's bundle when it comes; otherwise stable, last.

## For the operator

Nothing to apply: 172 stays on 835. 837 opens the same schema, so applying it later to a folder for its bundle works
as 836 does.

## Verification

3734 passed in 1152.45s (3 lanes at once)
