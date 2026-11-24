# Build 829: an open dashboard on a finished study no longer keeps a core busy, auto extend is on the Campaigns page (off unless ticked), and the cleanup is done, the 2019 model's readings with it. It moves no output study 171 runs: apply it to 171's folder only for auto extend or the quiet dashboard, at a restart.

**Type: the operator's btop of 2026-11-20 12:45 answered (the dashboard's landscape built again only when what it
reads was written), their ask of 13:36 built (auto extend), and their word of 11:48 carried (the cleanup's end).**
New: `graph_scale_dynamics/services/api/landscape_inputs.py`, `graph_scale_dynamics/operations/auto_extend.py`,
`tests/unit/test_an_unchanged_landscape_is_not_built_again.py`, `tests/integration/test_the_landscape_s_inputs_postgres.py`,
`tests/integration/test_auto_extend_postgres.py`. Changed: `services/api/main.py` (`_refresh_landscape`),
`services/api/landscape_worker.py` (`--inputs`, recorded in the meta), `services/controller/main.py` (`_completion`),
`services/api/campaign_manager.py` (the `auto_extend` action and state), `resources/ui/app.js` (the Campaigns page's
switch), `scaleflow/flow.py` (`UNCODED_REFUSAL`; the science freeze written again, the table's lock unmoved),
`scheduling/base_block.py`, `services/api/overview.py`, `research/stability_score.py` (the contract read as one),
`operations/scratch_holders.py`, `research/document_claims.py`, their tests, `tests/unit/test_replication.py`,
`tests/fixtures/committed_readings.json` (the 14 pins of the 2019 model's readings and criteria out),
`tests/fixtures/science_freeze.json`, `docs/readings/findings.json`, `docs/readings/README.md`, `docs/ARCHITECTURE.md`,
`docs/OPERATIONS.md`, `docs/RESEARCH_METHOD.md`, `docs/LESSONS.md`, `docs/HISTORY.md`, `docs/ROADMAP.md`,
`docs/WHERE_WE_ARE.md`, `docs/agent/HANDOFF.md`, `docs/agent/NEXT_BUILD.md`. Out, into
`GSD_readings_archive_829.tar.zst`, sent beside this build: `docs/readings/ktb3_*` (4 files),
`docs/readings/replication_ktb2019_*` (6), `graph_scale_dynamics/resources/readings/replication_ktb2019*_criterion*.json` (4).

## The dashboard that kept a core busy

The operator, 12:45, two screenshots of btop on study 170's folder (820), hours after the study ended: "theres still 1
core going to 100% cpu use, though it only lasts for a few seconds and then it is 'dead'". On them: a `gsd-postgres`
backend at 100% of one core for 9 and then 13 seconds, 464 and 470 MiB, each a few PIDs after a new
`.venv/bin/python -m graph_scale_dynamics...` child (189 and 131 MiB), and a load average of 1.12, 1.08, 1.03 on an
otherwise idle host.

**The cause, read in the code and then measured.** Every dashboard page asks `/api/landscape/<campaign>?meta=1` every
4 s, on every tab, open or not (`app.js`, `pollLandscape`). The API builds a batch's landscape again whenever its file
is 16 s old (`DASHBOARD_LANDSCAPE_TTL_SECONDS`, `ticks(4)`), in a child, `services/api/landscape_worker.py`, which
reads every rung summary, measurement and decision of the batch: that is the backend at 100% and the python child. One
landscape slot, five batches in 170's study view: a worker ends and the next poll finds the next batch due, so one
core is busy almost all the time, which is the load of about 1.0. Nothing had changed: the study had ended.

**Measured in the sandbox, on a finished campaign** (a slice-sized fleet run to the end, then `main.py serve`, the
real page open in headless Chromium, the processes counted every 0.2 s):

| build | page open | landscape workers started | requests the page sent |
|---|---:|---:|---:|
| 828 | 150 s | 8 | 40 meta polls |
| 829 | 150 s | 1 (the first look, whose meta had no inputs yet) | 37 |
| 829 | the next 120 s | 0 | as before |
| 829 | 75 s, one row of `engine_decisions_latest` written at 12 s | 1 | as before |

On this one-law campaign a build cost about a second of Python and almost nothing in PostgreSQL; on 170's 2,500 laws
the operator's btop shows what it cost there, 9 to 13 s of a core a build.

**The fix** (`services/api/landscape_inputs.py`, `docs/ARCHITECTURE.md`, "What the fleet does that the sections above
leave out"): before a due landscape starts its worker, the API reads the landscape's inputs, one short query: the write
counters PostgreSQL keeps for each table the landscape reads (`pg_stat_user_tables`, inserts, updates, deletes;
`TABLES`) and an md5 of the score boards in `control` (`law_scores:`). The worker records them in the meta (`inputs`).
When they are the same at the next look, the landscape is kept, its age reset, and no child starts. A write is seen
within PostgreSQL's statistics flush (about 10 s at most), so at the next look after it. The tables were read off a
landscape build, not a list written by hand: on a let-through campaign the build reads `campaign_candidates`,
`campaigns`, `candidate_specs`, `control`, `engine_decisions`, `engine_decisions_latest`, `four_rung_phenotypes`,
`jobs`, `measurements`, `proposal_exposures` and `rung_summaries`, and from `control` only the score board's key;
`tests/integration/test_the_landscape_s_inputs_postgres.py` runs the build and fails if it reads a table the stamp does
not watch. `control` as a table is not watched: every worker writes its import record there, which would build the
landscape again forever. A finished folder with its dashboard served writes only `service_heartbeats` and those
records (measured above: a fleet with no work ends, so the dashboard left on a finished study is `serve`'s), neither
watched. Inputs that cannot be read build the landscape as before. While a study runs, its tables are written all
the time, so its landscape is built as often as before.

**What the operator sees in btop**: with a tab open on a finished study, no `landscape_worker` child and no
`gsd-postgres` backend at 100%, the load average falling to the host's own; a running study looks as it did. Until
829 is applied: closing the tab, or stopping folder 170's server, ends it at once (170 is read).

## Auto extend

The operator, 13:36: "also in build 829 can you also add an 'auto extend' option in the campaign overview, default
off, but when ticked on, once all campaigns are finished, it extends all of them with another 50 laws, for forever,
until its ticked off/stopped manually, so that in case it turns out the study is done way sooner than anticipated at
4am, it isnt idling for 6 hours waiting for me to wake up".

**What it does** (`operations/auto_extend.py`, `docs/OPERATIONS.md`, "The Campaigns page"): a switch under the
Campaigns table (`auto extend: 50 more laws a campaign each time all are finished`), off in every folder until ticked,
kept in the flag `auto_extend`. In the controller's completion step, with it on: a campaign under its law budget is
not completed while laws are still to be drawn; and when the last of the folder's campaigns with a law budget
finishes, every other one already `completed`, it is not completed either: each of them gets 50 more laws (its law
budget raised to what it holds or its budget, the larger, plus 50, as the Campaigns page's budget field does) and the
finished ones are active again. The campaign finishing never leaves `active`, so the fleet never sees a folder with no
work and runs on. The proposer draws the new laws as it drew the first, from each campaign's own seed and its count of
laws (`campaign_rng_seed(seed, held)`), so a study extended is the same study drawn further. Each extension is an
event (`study_auto_extended`) and the line beside the switch says when the last one was and how many campaigns.
Unticked, a study ends when it is finished, as before; a fleet that has already ended is started again with `run`.

**Why the guard on laws still to draw**: the proposer and the controller are separate services. Right after an
extension every law the campaign holds is decided and none of the 50 is drawn yet, so without it the next pass would
complete the campaign again, with nothing extended, and the fleet would end. With it the campaign waits for its draws.
The cost: a campaign whose space can give no more laws (none has run out in any study so far) waits instead of ending,
until the switch is unticked.

Tests (`tests/integration/test_auto_extend_postgres.py`, on PostgreSQL through the controller's own `_completion`):
off, two finished batches complete and the fleet has no work, as before; on, the first to finish completes and the
last extends both from 3 to 53 laws, both active, the fleet with work, and a campaign under its new budget is not
completed again; on, nothing is extended while another batch still works, and switched off again the study ends; the
Campaigns page's action switches it once and records one event.

**On study 171**: its design is 1,000 laws in one batch. Ticked there, every finish adds 50; its criterion's counts are
per 1,000 laws (R6) or shares (R4, R7), so they read the same on more laws, and the bundle says how many there were.
To have it tonight, 171's folder runs 829 (below).

## The cleanup's end

The operator, 11:48: "make sure that we start with the left up cleanup process"; 03:09: "all references to
studies/data older than 169 out".

* **`UNCODED_LEGACY_RECORD` is not legacy, so it is named for what it is**, `UNCODED_REFUSAL = "UNCODED"`
  (`scaleflow/flow.py`). Read first: every estimator writes a code, but a chain's probe reaches the rung summary with
  no code when its block reads valid with no number, or has no block (`one_shot.chain_probes`,
  `decisions/every_chain.chain_metrics`, which keep a code only where there is one). That is today's code, not a record
  older than the codes, so the count stays. A raise in its place failed 4 of the summary's tests and would have stopped
  a decision; the name moves nothing a decision reads: the code is no `RefusalCode`, so it buckets as `NOT_ATTEMPTED`
  as before, and it sorts among the codes where the old name did (after `NO_SCALING_WINDOW`, before `UNPHYSICAL_FIT`),
  so the most common code a reader picks on a tie is the same. Tests: `tests/unit/test_uncoded_refusals_and_lineage.py`
  (the count, its bucket, and a chain's probe with no number reaching the summary uncoded).
* **The contract sets of one** (`ACCEPTED_PHENOTYPE_CONTRACTS`, and `BASE_BLOCK_CONTRACTS`, the same set under a second
  name in `scheduling/base_block.py`) are gone: every reader compares with `BASE_BLOCK_CONTRACT`
  (`services/api/overview.py`, `services/api/landscape_worker.py`, `research/stability_score.py`, `base_block.py`).
* **The scratch holders' word on builds before 790** is gone: a holder whose run record has no idle grace is described
  without a claim about the build that started it (`operations/scratch_holders.idle_words`); its page passage left
  `docs/OPERATIONS.md`.
* **The 2019 model's readings and criteria** (the operator, 11:48: "I do think we can like even drop the results from
  study, what is it, the paper 2019, because frankly from that time we weren't using the budget yet, we also weren't
  using a modern probes yet"): every reader grepped first (`replication_ktb2019`, `ktb3_`, `ktb_host`). The 14 files
  left into `GSD_readings_archive_829.tar.zst`, their pins `tests/fixtures/committed_readings.json`; the findings
  manifest's entries (`docs/WHERE_WE_ARE.md`'s finding 3, `docs/RESEARCH_METHOD.md`'s section "A published model, run
  by its own procedure") and their two claims in `research/document_claims.py`; `docs/OPERATIONS.md`'s "The 2019 model
  on the research host"; `docs/readings/README.md`'s "The literature, run again"; the roadmap's item 13 written without
  them; 797's lesson that guarded their bytes. The model's code stays (`tools/replication.py`, the `ktb` models): its
  four tests that read the committed criteria and runs read criteria written in the test now, the same run lines, so
  every path of the harness is still run (`tests/unit/test_replication.py`). It is run again after the paper's three
  studies, against a criterion written fresh on the final probes (2026-11-19 22:05).

What still carries the past (`docs/ROADMAP.md`): the history, the build notes, the archive pointers, and the frozen
noise floors of analysis 4.0.0 until the floors are each law's own errors (a question to the operator since 805).

## What moved

Against 828's record (`tools/outputs_of_a_law.py --write` on the untouched 828 tree first, `--against` after every
step): **0 outputs**. The table's lock prints `analysis-5.3.0 e639334808716378 89f4fed82d9adc27`, as at 828.
`decisions/` moved nothing; `scaleflow/flow.py` only the name of the uncoded count (above). The controller's
completion changes only with auto extend ticked.

## For study 171

171 starts and runs on 828 as planned; 829 changes nothing its laws read. Applying 829 to its folder (a restart,
resumed byte for byte) gains auto extend and the quiet dashboard after it ends; not applying it costs nothing in its
readings. 170's folder: read, and theirs to stop or delete.

## Left

The gates' counters the study's (`docs/ROADMAP.md`, 9c) need 170's bundle in hand to replay both ways, and this
sandbox had none. The consolidation is due (14 builds since 815, the cleanup done). 171's bundle is read first by
whichever build it reaches.

## Verification

3695 passed, 2 skipped in 1164.45s (3 lanes at once)
