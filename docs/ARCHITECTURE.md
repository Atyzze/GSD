# Architecture

One process tree, one folder-local PostgreSQL, one blob store. Services coordinate only through the repository
(`db/repo.py`'s `Repo`, made of the `db/repo_*.py` parts) and never import one another, bar the executor, which
composes the worker and the analyzer (`tests/contract/test_boundaries.py`).

## The loop

1. **Proposer**: candidates for each active campaign not extend-only, while its base block has room
   (`spec.max_active_candidates + pool_min`). The controller admits a law while fewer than `max_active_candidates` of
   the campaign's laws are in their base block (`scheduling/admission.admission_slot`; a held law, one bought above
   it, or, up to one learning group, one waiting to learn, holds no place); the decider starts it.
2. **Jobs**, one (law, rung, seed) each, bought a rung at a time, leased by executor slots. A worker child runs
   `scaleflow/one_shot.run_one_shot` until the equilibration certificate passes twice (at zero temperature: every
   chain that decides at rest), the multiplier ceiling, the seed budget or the mean-degree cap, and writes a raw envelope (blob).
3. **Analyzer child**: `scaleflow/one_shot.analyze_one_shot_envelope`, the four probes on the last chunk's recorded
   configurations, a probe valid where most read it; a cap-terminated envelope refuses all four.
4. **Decider**: rung summaries, the phenotype, one engine decision per landed rung (`decisions/engine.decide`,
   `docs/DECISIONS.md`); from 65,536 only for a finite dimension on both chains (`decisions/structure_gate.py`, from
   each seed's census, `DecisionStore.law_structure`), from 262,144 only past `decisions/depth.bar`.
5. **Study runner, API, web**: the reports, the landscape, the dashboard.

The decision engine is the only mechanism that starts, continues or stops a law
(`tests/contract/test_one_decision_mechanism.py`). One exception: at a fleet start the repairs
(`operations/scratch_repair.py`, `operations/failure_repair.py`) set running again, once per rung, a law stopped
`failed` when every failed seed and analysis it had was lost to a full scratch or failed for the fleet. They write SQL
with no decision row (a `law_reinstated` event says why); the engine decides the law again when the rung is complete.
The let-through, `longer_chain` and the lanes are `docs/DECISIONS.md`.

## Campaigns, the search, and the fleet (`operations/campaign_control.py`)

A folder runs any number of campaigns, each with a frozen spec: its term set (`operator_whitelist`) is in
`science_contract_hash` and its grid in `search_policy_hash`, so a different experiment is a new campaign
(`clone_spec`, `derive_spec`, `create_campaign`, the parent recorded). What may change is what it is given: its share
(`workers_target`, 0 a pause), its extend-only switch and its law budget (flag `law_budget:<id>`: `top_up` proposes
nothing past it, `law_budget_reached:<id>` records it once, `budget_state` says **done** once nothing is in flight).
**Auto extend** (829, made to act at 830; `operations/auto_extend.py`, flag `auto_extend`, off unless set from the
Campaigns page): at the end of every controller pass (`controller.finish_pass`), when every campaign with a law budget
that is active or completed is finished, each gets 50 more laws (`set_law_budget`, from what it holds or its budget,
the larger, which clears the budget's reached record so the proposer draws again) and a completed one is active again.
Finished is the Campaigns page's **done** (`study.budget_state`: the budget reached and nothing in flight), or
`completed`. A study's batches are continuous campaigns, never completed, so their **done** is what counts; a bounded
campaign with a law budget is held from completing while it is on, so the fleet does not end before the pass extends
it. A campaign without a law budget (the standing controls) neither counts nor is extended. `auto_extend_last` keeps
the last extension, an event (`study_auto_extended`) each one.

**A folder is a study**, chosen at its first start and recorded in `var/study.json` (`operations/study_record.py`,
`study.study_choice`); its name chooses nothing. No `--study`: the default study (`operations/study.py`, `start_study`:
`quadrant_specs`, every combination of `AXES`' two values, `zero_temperature` and `dense_cap`, each campaign with its
own search seed). `--study <id>` with a committed design
(`graph_scale_dynamics/resources/readings/study_<id>_design.json`, `operations/study_design.py`; the tree holds 169's,
170's, 171's and 172's, on 784's let-through rule, which every design must be on): its campaigns, each with its axes (an axis may be `drawn`), ladder,
budgets in work, starts, rules and law budget. A design may fix its campaigns' search seeds (`search_seeds`, one a campaign;
`study_design.seed_of`): every folder of it then draws the same laws, a law being drawn from its campaign's seed and
its index (`services/proposer/blind.law_stream`), and `--search-seed` is refused. Studies 169 to 172 do, a seed
a campaign, so their laws are their own; `tools/pilot_difference.py` reads a run against another bundle of the same seeds.
A campaign of kind `perturb` (847, study 175; `study_design.perturb_laws`, `research/perturb.py`) draws nothing: its laws
are its holders, rebuilt laws each checked by its fingerprint (`study_175_holders.json`), and each holder's variants:
every real parameter (a term's coefficient, a power's exponent, beta at finite temperature, the locality and the swap
share where drawn) moved together by half to all of a radius, up or down, from a stream keyed by the study, the
holder, the radius and the variant, kept to 12 significant figures and to the declared space (the language's checks
and the proposer's `validity_problem`). A chain's random numbers are keyed by its law's fingerprint, so a variant at
1e-9 is the holder's physics on a new stream: the matched control. The design commits the laws' sha256, and `start`
refuses a tree that draws them otherwise; the campaign is a hand campaign, its laws inserted as proposed.
The default study is on 784's let-through rule too (`study.on_the_let_through_rule`).
The fleet stops at the host's physical cores (`scheduling/cpu.fleet_ceiling`, the operator's rule); `GSD_MAX_WORKERS`
overrides it.

**The search** (`services/proposer/blind.py`) draws each value uniformly from the grid: a list or an interval `{min,
max, spacing}`; `grid.per_term` overrides whole keys for one operator (`term_grid`); `betas` and `term_counts` apply
to the whole law. A draw is kept only if `is_valid` (a sparse phase reachable, `_bounded_below` on the reduced form,
the complexity budget); `equilibrium_identity` deduplicates physics written two ways; a campaign whose draws stop
finding new physics is `surveyed`. A grid names `sampler: blind-sampler-2`, the one sampler, draws each law from its own stream (`law_stream(seed, index)`), and may stratify
(`research/strata.py`) or draw in each operator's own unit (`units: "natural"`). A design since 795 leaves a
term out of its pool (`terms_left_out`: the campaign's `operator_whitelist` lacks it, `operations/study_design.without_terms`).

**A law's dynamics** is drawn the same way (`draw_dynamics`: `localities`, `local_moves`, `zero_temperature`,
`swap_shares`) into the `dynamics` block (`locality`, `local_move`, `zero_temperature`, `move_mix`), written only when
not the default so a law at the defaults keeps its id. Both engines run them draw for draw (`run_chain` in
`engine/engine.py` and `engine_rs/src/lib.rs`): a local move toggles the edge between two neighbours of a node; zero
temperature accepts exactly the moves that do not raise the energy. `dsl.dynamics_regime` derives the regime,
equilibrium or zero temperature, and `dsl.dynamics_record` resolves every axis for a reader. The toggle is the one local
move (`dsl.LOCAL_MOVES`); a law or a grid that names another is refused as not one of them. A grid's `local_moves`, now
`toggle` alone, is still drawn from where a law draws a locality, so a design that lists it draws the laws it drew. The sampler audit (`proposal_locality`) is refused
beside a law's own locality.

**The fleet** (`services/worker/main.py::allowed_campaigns`) offers work first to the campaigns furthest below their
share; with none declared, each is owed an equal part of the running simulations, counting only work a claim could
take (`repo.worker_allocation(claimable=True)`). A share is a floor: with nothing to claim under any share, every
reserve is tried again for every campaign (`claim_simulation_for_owner`, two passes), and a slot over a declared share
is reclaimed only for a campaign under its own share with work queued (`repo.preempt_reason`, `db/share_floor.py`).
The Campaigns page divides the fleet all or nothing: every share is checked before any is changed
(`campaign_control.workers_problem`, 837), and a deletion checks its guard again under the maintenance lock. A
claim tries, in order:

1. the seed memory is held for ("Memory admission");
2. the half of the fleet owed it (`scheduling/fleet_halves.py`, the operator's): extension, every rung from 16,384,
   while it holds fewer than half the running simulations (the asking worker counted, the half rounded down), else
   base exploration; a half with nothing to claim hands the worker to the other;
3. within extension: a lane's rung (from 1,048,576) while fewer than three workers run one (`LANE_RESERVED_WORKERS`), a
   rung from 32,768 while fewer than two do (`EXTENSION_RESERVED_WORKERS`), each deepest first, then its rungs below the
   lanes by the priority each was bought at, then longest queued (741); within base exploration: a rung up to 1,024
   while fewer than two workers run one (`SMALL_RESERVED_WORKERS`), then the base block by queue priority;
4. last, the lanes past their reserves.

A seed refused for memory waits 5 s, and its worker claims again below that seed's size, in the same order, until
one is admitted or none below is left (747): a lane's seed that does not fit leaves the worker to smaller work.

Analyses are divided the same way (`services/analyzer/main.py::claim_analysis_for_owner`): extension's by the priority
its rung was bought at, then longest queued; base exploration's by queue priority (`decision_store.queue_priority`:
the base block's rungs, then priority 1, then 2, then released holds, each by N). No claim is made without room in the
scratch ("Scratch"). At a full lane an audit law's running seeds stop with their chains saved (`preempted_lane_yield`)
and resume later (`lane_resumed`, `db/lane_yield.py`).

**The controls** are campaigns of their own (their laws and criteria: `docs/OPERATIONS.md`, "The controls"): the
standing controls (`operations/standing_controls.py`, to `study_top`, each law's given chain at its answer by
`given_start_by_law`, judged by `research/control_verdict.py` against `controls_criterion_2.json` or the design's
criterion, stamped `controls_judged_by`) and the positive
control (`tools/benchmark_campaign.py start --kind control`). Each is made only in a study's folder
(`standing_controls.a_study_s_folder`). The
fleet start makes those a folder lacks (`scratch_relief.at_fleet_start`) and records them (`standing_controls.MADE`,
`var/controls/made.json`), so one the operator deleted is not made again.

**Reporting** follows the campaign last reported on (`campaign_control.reporting_focus`: the stored `home_campaign`
while it is live, else the newest active continuous one). `services/api/campaign_manager.py` is the Campaigns page's
payloads and actions.

## Limits (`scheduling/limits.py`)

`mean_degree_window`, `connectivity_floor`, `mean_degree_cap_armed_from_n`; the cap is enforced inside the engine
(`run_simulation(mean_degree_cap=…)`). The `disconnected` verdict reads the policy's own floor
(`engine.policy.connectivity_floor`, 0.5): from N=1024 a law whose largest component is under it and not growing
stops, less the let-through (`Policy.salt_share`). A seed's budget is its rung's entry in
`engine.policy.work_budgets`, the only copy (`limits.work_budget`), in units of the engines' weighted count of work
(806): the six parts every chain's move accounting counts (moves, energy evaluations, changes, list operations,
entries, tests) times the whole-number weights of `engine.policy.work_unit` (`gsd-work-unit-1`, a unit 0.1 ns of the
sandbox's process time, fitted once by `tools/work_unit_fit.py` and committed as
`graph_scale_dynamics/resources/readings/work_unit_fit.json`; a running study never moves it). No clock decides
anything a study records: no deadline reaches either engine, and the run is cut at its budget in work
(`scaleflow/one_shot.run_one_shot`): before each chunk it predicts that chunk's work from the last one's work a move
times the moves the next multiplier asks of the chains still running (`predicted_chunk_units`), and ends with reason
`budget` when the work done and the prediction would pass the budget. **Since 840 a chunk that passes the budget all
the same is stopped inside** (in 172, 127 seeds ran past their budget, since work a move can climb): both engines
weigh the chain's work every `WORK_CHECK_MOVES` (64) moves against the room the seed has left (`work_room`,
`engine.units_spent`), stop at the same move, and the seed ends with reason `budget` on its last whole chunk, the cut
chunk's work spent and its state dropped, so a seed cut inside reads what a seed refused that chunk reads. The first
chunk has no whole chunk before it and runs whole: a law's first chunk is weighed before the size is bought.
`rung_terminal.work` (`gsd-seed-work-1`) holds the seed's units, moves, budget, its first chunk, at a budget end the
chunk it refused, and `cut_inside_a_chunk` (the multiplier, the chain, the move and the units spent) where it was cut
inside. A seed whose first chunk
would not fit is not started: the decision engine predicts it from the law's own seeds a size below
(`decisions/engine.first_chunk_prediction`: the median units a move of their first chunks, times their median moves
a multiplier scaled by the sizes' ratio, times the next size's first multiplier; a longer chain at the same size from
that size's own seeds, its reason saying so since 835) and parks the law by `over_budget` (`budget_gate`, an
operational stop like `failed`, no verdict and no let-through). `engine.policy.seconds_a_unit` turns units into estimated seconds for the pages and
the ETAs only (`limits.estimated_seconds`); the pages show each size's budget in units with its estimate beside. The
worker and the analyzer have no watchdog: a lost or hung process is the fleet's heartbeat and lease to catch. A
design's ladder gives `budgets` (`[[n, units], ...]`), which `scheduling/ladder_spec.engine_ladder` writes; a law
bought depth on merit gets `merit_budget_scale` (2) times the size's budget (`depth.budget_scale`), carried on its
jobs and its decision's facts.

## Memory admission (`scheduling/memory.py`)

The guards a claim meets, in order, are `docs/DECISIONS.md`, "3. Memory". A claim is admitted when its reservation fits
the headroom (`admission_headroom`): available memory, less the floor (10 GiB on the research host), less what running
children have yet to take (each one's growth to its rung's median peak, plus the two largest spikes above the median
among them), from the supervisors' heartbeats; a leased seed counts once admitted, its reservation written or its memory
seen (`admitted`), so the seed being admitted and those other workers are taking cost nothing (747). The claim lock
covers only the live leases, the reservations and its own write (`locked_admission`); a claim that fails on the way goes
back uncounted (`returned_on_failure`). Every attempt records its memory at each lease renewal (`pss_timeline`). With
enough runs at a rung a claim opens at the rung's p95 peak, never below the law's own peak there; since 782 a law's
later seed at a size its earlier one ran is priced from that seed's measured peak with the model's safety
(`own_earlier_seed_bytes`), not floored at the fallback, which had held such a seed at 4,096 at 17 times a median
run's peak (781); a law's own peak read only as resident memory (`rss_only`, where a host gives no PSS or USS) keeps the older path; a running child's
reservation is capped at the limit it is stopped at (35% for an analysis given back). A claim of at most 1% of the host
(`SMALL_POOL_FRACTION`) is admitted against a small pool that borrows the growth large children reserved and have not
taken; the floor is never lent.

**The runaway bound** (`process_stop_bytes`). A child is stopped when its resident memory passes four times its
opening reservation, at least 2 GiB, or the host's ceiling where that is lower. The reservation is a guess (the law's
own earlier seeds, the rung's peaks, the fleet's profile), so where the bound is that guess's (`runaway`) the stop is the
host's mistake, not the law's: since 843 the seed or the analysis goes back to the queue unspent 30 s later
(`memory_runaway_requeued`, an interrupted attempt), and its next reservation is at least 1.25 times the peak it was
stopped at (`runaway_seen_bytes`), so its next bound is at least five times that. A stop at the host's ceiling fails
the attempt as before (`memory_hard_stop`, `memory_hard_cap`). Before 843 a law could fail by the order its seeds ran
in: 173's two runs each lost a law this way at 65,536.

**The shed.** When available memory falls more than 2 GiB under the floor, each supervisor stops its child if it is in
the cheapest set (compute at risk per byte freed) that brings the floor back (`memory_shed_reason`); the attempt
closes as `preempted_memory_floor`, the work is queued again, and a simulation resumes from its last chunk.

**Room held for a lane** (`scheduling/memory_hold.py`). A lane's seed (from 1,048,576) refused for
memory has its room held, one hold at a time: every other simulation's claim leaves it free (`held_bytes`) and the
held seed is tried first. **No analysis is held back** (749): an analysis consumes a raw result that sits in the RAM
scratch, so holding it back kept that RAM taken and the held seed further from fitting (2026-11-09: a 23.9 GB hold
against 21.1 GB of headroom refused every claim, the 60 analyses waiting too); an analysis's own
reservation counts against the headroom as any claim's does (`locked_admission`).

**A hold starts, and stands, only when its seed can fit** (749). `memory_hold.reach` is the headroom the host could give
once the fleet drains: reach = available + what running children hold now (their PSS) + what the scratch relief may
still move to disk − the floor. What the relief may move is 0 unless the scratch is a tmpfs, otherwise the bytes above
40% of its size, no more than the bodies of the kinds it moves and the disk's room above its 20 GiB
(`scratch_relief.movable_bytes`); the maintenance tick publishes it every four seconds (the `scratch_relief` control
row) and the reach counts it only while under a minute old. Each refusal of a lane seed reads the reach (the worker's
`_hold_for_lane`): a seed asking more gets no hold, and the row keeps it as `unfit` with the numbers for the status
(rewritten at most every 30 s unless a larger ask comes); a held seed that no longer fits ends its hold (`cannot fit`,
which neither rests the fleet nor counts as a run-out) and takes it up again within its hour if it fits again. A seed
that never fits does not stall the fleet: it waits, refused every five seconds as any seed larger than the room does,
while the worker refused takes a smaller seed. On a bundle of 2026-11-08 19:05Z (30.2 GB available, no child
running, the scratch at 40%) the reach is 18.2 GiB and the 1,048,576 seed asked 22.3 GiB: 748 held for it for an
hour, ran out and rested the fleet's holds for eight hours.

The hold ends when the seed is admitted, no longer waits, its campaign pauses or it no longer fits, or after an hour;
then no seed is held for half an hour, doubled for each hold in a row that ran out (to eight hours). Only refusals that
mean the room is taken start one (`HOLDING_REFUSALS`). Workers change the row without a lock, a write taking only if
the row is still what that worker read (`rev`), so there is one hold and one end.

## Scratch (`operations/scratch_namespace.py`, `operations/scratch_holders.py`, `operations/scratch_relief.py`)

The folder's scratch is a tmpfs on `var/scratch`, mounted by a holder inside the folder's own unprivileged user and
mount namespace, which the supervisor joins before PostgreSQL, the blob store or any thread. It holds the blob store's
RAM tier (`transient-blobs`: raw results waiting, every live law's resume checkpoints), stopped chains' states
(`resume`), staging, the services' logs and temporaries (`runtime`), and PostgreSQL's runtime and spill. It is half
the RAM by default (`GSD_SCRATCH_SIZE`), which the kernel cannot reclaim, so admission counts it. It outlives a fleet
restart (a restart costs a chunk, not a rung); a reboot loses it. **An idle holder ends itself** (790): every 30 seconds
it counts the other processes in its mount namespace (`members_of_my_namespace`); once none has been there for
`GSD_SCRATCH_IDLE_GRACE_SECONDS` (600) it moves every file to `var/scratch_parked/` on the folder's disk, paths kept and
PostgreSQL's runtime, sockets and pipes dropped (`park`), and ends; a start that joins moves them back first
(`restore`). The folder's lock (`var/run/scratch-holder.lock`) keeps the two apart: a start joins and restores under
it, and the holder parks only when it can take it, so no process joins a scratch whose files are being moved out.

**Relief** (`scratch_relief.relieve`): past 60% the maintenance tick moves bodies to the blob store's disk tier, at most
4 GiB a tick, until under 40%, coldest kind and largest first (resume checkpoints, raw results nothing will analyse, raw
results waiting, states of chains not running). Nothing is deleted and no reader changes: the store resolves a digest on
disk first. It keeps 20 GiB free on the disk (`DISK_KEEP_FREE_BYTES`, for PostgreSQL's 16 GB of WAL): under that nothing
more moves, the RAM scratch fills and new simulations wait for room, and every tick raises `scratch:disk_floor` on the
page while it lasts (734). PostgreSQL runs `synchronous_commit = off` (`tools/postgres_instance.py`), so a crash can
lose seconds of commits that recovery replays; a commit a file's deletion rests on (a body moved to disk, a body or
checkpoint evicted, an unreferenced artifact collected) is made with `Repo.commit_durably` and reaches the disk before
the file goes (733). Logs of ended processes silent for six hours are deleted. Room (`scratch_relief.room`): a
simulation needs a tenth free and at least 2 GiB, an analysis 256 MiB (`scratch_short` once a minute while waiting).
`scratch_relief.at_fleet_start` runs before any service: the repairs (with `operations/queue_ranks.py`), then the relief
under 40%. Alerts `scratch:pressure` and `scratch:full`.

**The relief gives way to memory** (749). The scratch's pages are RAM the host cannot reclaim, so while admission is
short (`scratch_relief.shortage`: a hold is active, or a seed was refused for memory in the last five minutes, read
from the jobs deferred for memory each tick) and the scratch is a tmpfs (the store's `staging_backend`), the tick moves
from wherever it is toward 40%, as past 60%: the same kinds in the same order, the same 4 GiB a tick, the same disk
floor; moving a scratch on disk frees no RAM, so there it keeps to 60%. On 2026-11-09 a folder's scratch held 25.9 GB of
49.4 GB (52%) while 25 seeds were refused in a few seconds, and nothing moved. Each tick then publishes the scratch's
bytes, what it moved, what it may still move (the hold's reach reads it) and what it is doing, in words
(`scratch_relief.publish`, the `scratch_relief` control row), which the live status shows.

**A folder acts only on its own.** `scratch_holders.discover` reads every folder's tmpfs of this user from `/proc`, a
namespace at a time; `name_other_folders` names the others' and ends none (at `main.py run` and the calibration tool's
start). A holder is known by the tmpfs in its own namespace, whatever path its command line names
(`scratch_namespace._is_holder_of`). A new holder's size is capped (`planned_size`) so every folder's scratch together
stays under the RAM less the floor; a start with no room stops before PostgreSQL (`scratch_namespace.refusal`).

**Nothing of a fleet outlives its folder.** The holder takes its folder's identity
(`process_ownership.folder_identity`) and ends when the folder is gone or replaced (checked every 30 s,
`GSD_SCRATCH_FOLDER_CHECK_SECONDS`); the CPU tile's publisher (`operations/power_sidecar.py`) dies with its run and
checks its folder before every write; `operations/leftovers.at_start`, before anything starts, ends every fleet
process of this user whose folder is gone or was made again, and names another folder's live fleet.

## The simulation child (`services/worker/child.py`)

Every job is one-shot: the child refuses a job without `execution.one_shot` or with an engine version no build made,
runs the rung for one seed from its start or saved state to its verdict, and publishes the envelope. One engine
(`engine-3.3.0`) and one certificate (`one-shot-sampling-2`); an earlier compatible stamp runs on these
(`engine.COMPATIBLE_ENGINE_VERSIONS`, `one_shot.ONE_SHOT_CONTRACTS`). Exit 75 is a stop on request with the state
saved, 74 a full filesystem (`child_diagnostics.exit_code_of`), for the analysis child too. The worker writes the
job's file inside `run_one`'s `try`, so a full scratch hands the job back as an interruption.

**A declared start** (`sampling_contract.given_start`, or `given_start_by_law`) gives every seed a second chain started
at that family's graph, which must reach the rung's N exactly (`job_creation.resolve_given_start`). The edges come from
`measurements/calibration.control_family_edges`, then `measurements/known_answers.py` (lattices folded to every power
of 4; the square torus and honeycomb past 1,048,576); `run_simulation` applies them (Rust: `init_declared`) and the
checkpoint carries the start (`init`). A chain started at a declared answer is read by every probe
(`one_shot.given_probes`). A start may be a shape (`random_geometric_<d>d_degree_<k>`, `measurements/shaped_starts.py`,
from the job's seed) and may name that chain's own moves: `kernel: local_walk` (`engine.LOCAL_WALK`, `_LocalWalk`)
moves it by local deletions, swaps along a path and edges to the end of a short walk, Metropolis-Hastings, no global
move, while the chain from empty grows by the law's own moves. Both engines run it; a continuation that would change
the kernel is refused.

**The starts.** A start is defined once, in `measurements/starts.py` (769): its name, kind (empty, random or a
lattice), family, dimension, neighbours, and whether study A runs it. Eight run: empty, `random`, `square`,
`triangular`, `cubic`, `bcc`, `fcc`, `tesseract`; the honeycomb is known, a family of the calibration table, and no
start. The module imports the lattices' builders and nothing of the calibration table's key imports it, so a change to
it measures nothing again. `observability/starts_reading.LATTICES` and `NAMED`, `research/dimension_rule.LATTICES` and
`GROWN`, and the readers `tools/law_rows.py` and `tools/history_reading.py` are made from it; a design lists the
starts its campaigns run, and `tests/unit/test_the_eight_starts_run.py` holds the shakedown's to the definition.
**A seed's chains share one budget in work**: `scaleflow/one_shot.run_one_shot` counts every chain's work against
it, the chains running one after another within each chunk (`engine/engine.py` and the module beside it for the
further chains, `services/worker/engine_rs.py`), and a seed is read only where a chunk ended whole, so every chain
of a seed has run the same sweeps and a design on eight starts spends 8/5 of what five chains did. A size's chains are grouped (`starts_reading.groups`) by the fewest
groups in which every two meet, searched without walking every partition: 4,140 for eight chains.

**The starts, as the code names them** (`sampling_contract.given_starts`, resolved by
`job_creation.given_starts`; the random start's degree from the law's id, `measurements/random_starts.py`): the chain
from empty always runs; the first listed start rides the job as `given_start`, the rest as `more_given`, and the engine
runs them as one list of chains, the chain from empty first (below, "The engines"). **The twin starts** (781, the
operator, 2026-11-14 18:45 and 18:55) are the chain from empty and the random start's, the only two given no
structure, of equal weight (`measurements/starts.the_twin_starts`; in the engines' list the chain from empty and a first
given chain whose start is random, `domain/chain_list.twin_names`); the six lattice starts are given structure and ask
whether it melts, changes or stays. The word names only this pair. Every chain at the cap ends alone, the chain from empty too; a
chain stopped on request names itself by its start (`in_segment.chain`) and resumes where it stood. The certificate
(below, "The certificate") counts every chain on its own and compares only the twins, the analysis reads every chain
alike (below, "Every chain its own readings"), and every given chain's records are kept alike
(`observability/meeting_reading.py`). Every reader finds a chain in the list by its start through
`domain/chain_list.py`; `scaleflow/engine_door.py` is the one place the tree reaches an engine (`run_simulation`, the
reference's, and `simulate_of`, any registered engine's, below; the kernels and chain names a job is checked against),
and since 775 it translates nothing.
Every committed file and every bundle a reader takes is in today's names (822: the controls' criteria, the findings,
the references and the cost baseline written again in them, nothing else changed; the 2019 model's criteria and
readings left at 829). A folder made before 797 does not
open on this schema (`db/repo.py`), the one refusal of a folder this build cannot run. A gate renamed at 773 draws its
let-through with its name of 772 (`gates.SALT_STREAM_LABELS`, read by `gates.salted`), as `repeats_a_known_result`
draws with its name before 835 (`gates.DIE_LABELS`; a design's `one_die` draws one pick a law a size for every gate,
`gates.die`), and a random start's streams
keep their labels (`measurements/random_starts.py`): a stream's label is part of its draws, so each is kept to the
byte. `engine.policy.every_chain` decides chain by chain (`decisions/every_chain.py`),
and depth by the starts' reading (`observability/starts_reading.py` against the references it makes from the
calibration table's own cells, `table_references`, below; `decisions/starts_rule.py`;
`docs/DECISIONS.md`, "Every chain alike", "The starts decide depth"). A reading stored and read back lists its
lattices in another order than they were measured in, so whatever walks them takes the starts' order
(`starts_rule.in_start_order`): the lattices a law holds, which the reason names and the structure gate reads
first, since 770. The law's page shows its chains alike and none first, each start in a colour, a mark and a dash of
its own and in the page's own order, empty, random, triangular, square, cubic, bcc, fcc, 4D (`START_STYLE` and
`START_ORDER` in `resources/ui/candidate.html`, held to the starts a law runs by
`tests/unit/test_the_law_page_draws_every_start_in_its_own_colour.py`); the chains run in the order of
`measurements/starts.py`, which the page does not change, a seed's chains sharing one budget (`observability/two_chains.py`, `observability/space_score.py`;
`observability/every_chain_graph.py` for every chain's graph and census, read by the one reader
`research/structure_reading.law_structure`, and for every chain's kept curves a size at a time,
`/api/curves/<campaign>/<law>/<N>`, thinned to 120 points a curve); report 28 (`reporting/every_chain_report.py`,
`reporting/starts_decided.py`) and `tools/starts_bundle.py` read the same reading.

**A term** is updated by the engine on every proposed move: written in `engine/engine.py` and `engine_rs/src/graph.rs`
(named in `engine_rs/src/lib.rs`), held equal by `tests/scientific/test_engine_parity.py`, priced in `dsl/dsl.py`, and
known to `research/hamiltonian_preflight.py` and the pages' short names.

## The engines (`engine/`, `engine_rs/`, `engine_c/`, `engine_asm/`)

**One list of chains** (775). `engine/engine.py`'s `run_simulation` sets a seed's chunk up (the law's energy model,
the context, the checkpoint's identity) and `engine/chains.py` runs its chains in one list and one code path: the chain
from empty, then the first given chain (`given`), then each further start in the order the study lists it
(`chain_list`, which marks the twins, `is_twin`). For each, in turn, it is carried as it stood (the chunk already ended
by both twins at the cap; a chain that ended alone at the cap, `ended`, which every chain at the cap
does since 781; or a chain before the one a stop request cut, which finished the segment), or rebuilt from its checkpoint
block and run, or started (the chain from empty at the empty graph; a given chain at its declared edges, applied in
order with no random number, `declared_given`; the first given chain with no declared start at the random graph of
mean degree 8 drawn from its initialisation stream, `GIVEN_START_MEAN_DEGREE`). A chain stopped on request returns
the stopped envelope at once, with every chain before it at the end of the segment, itself where it stood and every
chain after it as it stood at the segment's start. The envelope (`raw-simulation-envelope-v2`) holds the run's fields
at its top (sizes, moves, the run's termination, which is the chain from empty's or, when both twins have
crossed the cap, the second twin's crossing with its `chain`, the proposal model, the
initialisation stream) and `chains`, one record a chain in run order, each with the same keys: `start`, `init`,
`kernel`, `sweeps`, `termination`, `skipped`, `skipped_reason`, `ended`, `late` (the last third of its trajectory),
`final` (edges, degrees, energy, ledgers), `final_structure`, `acceptance`, `accepted_moves`, `accounting`, the
fast-path counters, `seconds` and `stream`. Its checkpoint (`adaptive-chain-checkpoint-3`) holds one block a chain that
has a state, named by `start`: the edge list in the state's own order, energy, random state, counters, trajectory (240
points a chunk on every chain since 780), the late change, peak, accounting, `final` and `final_structure` (so a
carried chain needs no graph rebuilt). A chain's final graph and its trajectory live only in its block;
`domain/chain_list.py` finds both (`edges`, `sorted_edges`, `trajectory`). **The late change** (780, the operator's
answer of 2026-11-14 15:49): at 85% of a chunk's moves (`engine.LATE_FROM_FRACTION`) every chain starts two sets on its
graph state (`GraphState.late`, in both engines), the edges added and the edges removed since, an edge that comes back
cancelling out of the other set; the block keeps them as `late_change` (`late-change-1`: `from_move`, `added`,
`removed`), a chunk whose 85% fell before it began carrying on the last chunk's; the late edge overlap is
`(|end| - |added|) / (|end| + |removed|)` (`engine.late_edge_overlap`), the overlap a copy of the graph at that move
would give, exactly. No graph is copied at any size; the chain record keeps the change's size and overlap.

**No final graph** (797, the operator's of 2026-11-14 14:33: a chain's edges take far more room than anyone reads). The
chain record (`chain-record-4`, `artifact_store/chain_record.py`) keeps each chain's graph as its edge count and the
SHA-256 of its sorted edge list (each edge low end first, the list in order, as little-endian 64-bit words:
`graph_digest`), with its trajectory, accounting and late change; no edges. A graph is had by running its seed again
from the law, the size, the seed, the start, and the engine: the same bits on either engine give the same digest
(`tests/unit/test_the_chains_are_recorded.py`).

**Every chain its own readings** (781). `scaleflow/one_shot.analyze_one_shot_envelope` reads the chain from empty at the
top of a seed's metrics, as the decision engine has always read it, and every other chain that ran and did not end at
the cap by `chain_probes` (contract `gsd-chain-probes-1`: the four probes, the half-volume radius, the diameter's bounds
and the log-diameter flag and state, the d_s shape and the whole-range reading), into `chain_probes`, one entry a chain
named as the engines' list names it. The census, the curvature, the move accounting, the descent record and the chunks'
timing are one map each, a chain to an entry (`census.cubic`, no `more_given`), and so are `chain_mixing` and
`chains_course`. A chain at the cap is not read: the chain from empty's probes are refused with
`REFUSED_MEAN_DEGREE_ABOVE_WINDOW` where it ended alone, and `limit_refusal` is set only where the rung ended at the
cap; `ended_at_cap` lists the chains that did. Every reader finds a chain's entry through `domain/chain_list.py`
(`of_chain`, `chains_in`, `chain_probes`, `probes_of`), which read a seed of 780 and before (`more_given`,
`given_probes`, `more_given_probes`, the descent's `given:<name>`) as well. The structure reading
(`research/structure_reading.law_structure`) gives every chain the half-volume radius, the local d_s, the log-diameter
guard and the three readings; `decisions/structure_gate.rung_structure` keeps each chain's log-diameter flags beside its
census.

**The certificate** (`measurements/certificate.py`, `scaleflow/equilibration.py`, `every-chain-certificate-2` since
781). One rule (the operator, 2026-11-14 18:37 to 18:55): every graph must stop changing; at a finite temperature the
twin starts must also land together; at zero temperature where each rests is the finding. Each chain that ran counts
on its own record: its effective samples (`own_count`: the windowed autocorrelation sum and the 8-batch means on its
late 60% of the chunk's points, the smaller), its late energy drift (`own_drift`, its last 30%, in its own errors
widened for lag-one correlation, `widened_line`, 803), its late activity and
late edge overlap (`own_activity`; frozen at most 0.05 accepted changes a node over its last 30% and at least 99.9% of
its edges kept), its structural trend (`structural_trend`: each chain's slope, the twins' residuals pooled as they meet
and every other chain's its own, `trend_groups`; at zero temperature over the rest reading's late window), and at
zero temperature its rest, which needs the trend too (803). Every chain that ran and did not
end at the cap decides (`equilibration.deciding_chains`: `decide`); only the twins meet (`meet`, compared by
`pair_certificate`: the split of their late means in their correlated errors, the structural split held to the pair's
own spread); a chain at the cap or not run is left out (`left_out`), a twin alone at the cap being the twins apart at a
finite temperature (`twins_apart_at_the_cap`) and nothing at zero. A chunk passes when every chain that decides passes
its own and the twins meet; the rung's count is the smallest, its split, late activity and drift the largest, its
overlap the smallest, so `terminal_at_ceiling` classes a rung frozen only when every chain is. Each chunk records what
the certificate asked (`asked`: the samples, the split and the drift). The chunk loop records the chains it decided by
on the envelope (`certificate_chains`), and the analysis's health reads the same certificate with them. A spec's
`lattice_chains_meet` is carried and read by nothing that decides. Its count is judged on known answers, read again at 816
(`docs/readings/certificate_known_answers_3_judged.md`).

**The random streams** are named by their labels with the engine contract, the law's id, N and the seed
(`domain/randomness.stream_id`): `simulation-declared-chain` for the chain from empty, `simulation-control-chain` for
the first given chain and the same with the start's name added for each further one, `simulation-control-initialization`
for the first given chain's random start (`engine/chains.py`). The labels predate the chains' names and are kept to the
byte, since a new label draws every chain again: `tools/outputs_of_a_law.py --against` names every output it would move.

**The engine contract** (797; the operator, 2026-11-13 18:47: the Python engine stays the reference, and any other
engine can be added). `services/worker/engine_registry.ENGINES` is the one place an engine is named: each declares its
name, whether it is the reference, its source files (`engine_sources_digest`, which guards resumes, lists them from
here), its extension and the file its version is read from, and its doors; `DEFAULT_ENGINE` is the one a job runs on
unless it names another, `simulate_of(name, door)` the way in. The Python engine is the reference and runs whole
chunks; another engine answers a **boundary of plain data** (`engine/boundary.py`, `gsd-engine-boundary-1`) of four
operations, `init_random_graph`, `init_declared`, `run_chain` and `rebuild_graph`, each a request and an answer of
numbers, strings, lists, maps and nulls only: the terms with their coefficients at this N, the random state as
`getstate()`'s 624 words and index, the edge list in the state's own order, the counters, the late change, the
accounting, the clock's limits; back, the edge list, adjacency, energy, ledgers, counters, trajectory points, late
change, termination and random state. A fault comes back named (`ValueError`, `KeyError`, `FloatingPointError`,
`RuntimeError`) and is raised as that error. The Rust crate answers it through two doors: in the process
(`gsd_engine_rs.call(operation, request)`, the move loop run with the interpreter released) and through a C ABI
(`gsd_engine_call(operation, request)`, the request and the answer as JSON text, the answer freed by
`gsd_engine_free`; floats written in the shortest form that reads back to the same bits, `NaN` and `Infinity` as
Python's `json` writes them; no third-party crate). An engine in another language needs only the C door.
`services/worker/engine_rs.py` builds the requests from a chain's context and reads the answers back into a graph
state. The parity lane runs every comparison over every engine the registry lists and every door it declares, against
the reference (`tests/scientific/test_engine_parity.py`), and both doors give every operation the same answer
(`tests/scientific/test_the_engine_contract.py`). The curvature probe calls the crate on its own until the
recalibration, its source being in the calibration table's key.

**The C engine** (876, `engine_c/`): the Rust engine ported to C, the second of the reference set
(`docs/agent/APPEND_ONLY_PLAN.md`, R3), answering through the C door only. The registry compiles it the first time it
is asked for (`engine_registry.library_path`: `cc -std=gnu99 -O2 -ffp-contract=off`, into `var/engines/` under the
hash of its sources) and reports it unavailable on a host with no C compiler. Its version and science version are in
`engine_c/engine.toml`, read as the crate's are; while it computes the same chains its science version is Rust's, and
the parity lane and the contract hold it to that. The default engine stays Rust in process.

**The assembly engine** (877, `engine_asm/kernel.S`): x86-64 (System V) for the Mersenne Twister, `random()`,
`randbelow`, the acceptance and the energy change of the terms it covers, inside the C engine's boundary built with
`GSD_ASM`. An engine that covers part of the terms declares which (`Engine.covers`, `engine_asm/engine.toml`), refuses
the rest by name through the C door's `OutsideCoverage` fault, and the parity lane and the contract run it on what it
covers (the plan's R2, coverage by declaration).

**The engines' memory** (875): the Rust graph keeps each edge's slot beside its ends' neighbour lists and its square
and cycle counts in arrays by slot, no hash map per edge; the in-process door shares one Python number per node; a
run's Python state (`engine_rs.RanInRust`) keeps its edges and degrees and builds the rest only if asked. The crate's
version moves with its code and its science version (`engine_rs/Cargo.toml`, `[package.metadata.gsd] science`) only
when a chain can come out different; the science hash reads the second.

**The same bits on both engines.** The Rust crate (`engine_rs/src`, built by `tools/build_engine.sh`) owns the move
loop (`run_chain`), the checkpoint rebuild (`rebuild_graph`) and the two initialisers (`init_random_graph`,
`init_declared`), behind the boundary above, and everything else is the Python engine's. They agree to the last bit
because: the generator is MT19937 exactly as CPython's `random.Random`
drives it (`engine_rs/src/mt.rs`: seeding by `init_by_array` from the integer's 32-bit words, `random()` from two
draws, `getrandbits` and `randrange` by rejection on the bit length), and its state crosses as `getstate()`'s 624 words
and index, so a chain begun on one engine continues on the other; every draw is made in the same order, each
neighbour list walked ascending; every ledger change is an integer held in a float, so the order a neighbourhood is
walked in changes no value; a move's energy change is summed from its terms' changes in term order, and a change no
larger than `EXACT_ZERO_SHARE` (1e-12) of the sum of its terms' own sizes is exactly zero (two terms on one scale whose
couplings stand in a whole-number ratio cancel only to a unit in the last place); a cooling law's beta at a move is
computed by the same four operations (`cooled_beta`). The clock is read on a stride sized by time
(`next_clock_stride`: from one move, doubled while a stride takes under half a tick, shrunk in proportion past a tick,
at most `CLOCK_STRIDE_MAX_MOVES`), so a stop request is read every two to four seconds whatever a move
costs (`STOP_CHECK_SECONDS`, 4); a rebuild reads it every `REBUILD_CLOCK_EDGES` (64) edges, fixed, since a rebuild's
edges get dearer as the graph fills. A recorded point carries the graph's structure every `STRUCTURE_POINT_STRIDE`
(20) points, about 7% of a chain's cost. The move accounting counts every proposal that reached an energy change by
kind, scope, sign and outcome, with a log2 histogram of the change clamped at `DELTA_H_BIN_LIMIT` (40) and a late
window of a segment's last quarter, in integers. Since 794 it also counts the chain's **work** (`work`, and the late
window's own), one integer both engines compute by one rule whatever their data structures (the Rust engine scans
lists where the Python engine looks up sets): an energy change costs 1, plus, for each term it computes, the
neighbour lists it reads, each by its length: u's and v's for the degree gradient; u's and v's for the common
neighbours of any neighbourhood term; v's, u's and every neighbour x's of u (but v) for the square paths; for the
induced squares 2 a square path and 1 a pair of common neighbours; for the square overlap 3 a square path and 1 an
edge it touches; for the triangle overlap u's, v's and twice w's for every common neighbour w; for the curvature u's,
v's, twice every x's and every z's of x (but u and v) for its cycles, then u's, v's and 1 an edge it touches. An
applied edge change costs 1, a try of the non-edge sampler 1 (and 1 a node its last scan passes), a local pair's
node list its length, and the local walk every neighbour list it copies and every copy it searches, by length. The
structure points, the start's building and the checkpoint's rebuild are not counted. Work replays exactly from the
seed. The one count decides nothing (an entry read costing a few nanoseconds where a move's own overhead costs
hundreds, it did not track CPU seconds at 794); the budget weighs the work's **parts** (`parts`, whole and late;
`engine.policy.work_unit`, "Limits", above):
`moves` run, `evaluations` (energy changes), `changes` (edges applied), `lists` (neighbour lists opened, and for the
degree gradient every neighbour's degree read), `entries` (list entries read) and `tests` (the units above, and every
membership test a proposal makes: the swap's, the walk's end, a local or audited pair's, the global swap's), each
counted alike in both engines, and a stop and resume leaves them as an unbroken run would. A checkpoint's edge list is refused by both engines alike for an
endpoint outside the graph, a loop or a repeat (`engine/checkpoint.py`, `check_edge_list`). A given start may name
its own way of moving, `local_walk` (`LOCAL_WALK`, `_LocalWalk`): a node, then a deletion of one of its edges (a
fifth), a swap along a path from it (two fifths) or an edge to the end of a walk of two or three steps, each toggle
accepted by Metropolis-Hastings with the chance of proposing it and its reverse. The parity lane holds all of it
(`tests/scientific/test_engine_parity.py`), and `tests/scientific/test_the_running_energy_is_the_graph_s.py` holds
every chain's running energy to its graph's at every chunk's end on both engines and across them.

## Resume (`scaleflow/one_shot.py`, `artifact_store/resume_state.py`)

At every chunk boundary a run hands out its state (both chains' checkpoint, the next multiplier, the passes, the
chunks, the prediction of the next chunk's work, the seconds spent). After 20 s of a seed's own time the child keeps the latest, by rename, in
`<scratch>/resume/<job id>.json.gz` (the relief may move it to `<blob root>/resume/`). The next attempt continues from
it only under the same `execution_spec_hash`, which carries both engines' sources
(`engine_registry.engine_sources_digest`); otherwise it starts again and records `resume_refused`. The file, and a
copy the relief moved to disk, stays until the worker's commit of the rung is on disk: the worker writes the rung's
`job_done` event with `Repo.commit_durably` after the result's commit and only then deletes them
(`services/worker/main.done_and_state_let_go`), so a lost lease, a database away past the commit wait or a kill at a
drain resumes the rung where its chain stood (742); a state left behind goes with the prune once its job is no longer
queued or leased. A resumed rung equals an uninterrupted one, on either engine (the parity lane).

**A resumed run's time** is its own: `rung_terminal.wall_seconds` counts every stretch its save carried
(`resumed.seconds_before`), and the fleet ladder's "time per
seed" reads it (`Repo.resumed_run_seconds`, found through the measurement whose input is the job's result); an attempt's
`wall_seconds` is its own stretch, so etime adds each attempt once and a paused stretch stays in the "halted" line.
Until its rung is measured a resumed run counts at its last stretch. A seed not yet finished counts in the ladder's
slowest at its time so far, marked +: a running one at its lease's age and the save's time before it
(`live_panel.resumed_seconds_of`), a paused one at its save's `seconds_spent`, the note read from the RAM scratch
or, once the relief moved it, the blob root (`live_panel.resume_note_of`). Every batch shown, the fastest is the least
of the batches', the slowest the greatest and its mark that batch's (`study_scope.merge_ladder`). A seed whose chains
have finished and whose worker is writing the result reads **committing**, not evolving, on Home's live list: the
worker's heartbeat names the job and `phase: committing` before its commit (`services/worker/main.py`,
`overview.committing_jobs`, 837).

**A probe's time on the ladder** (`observability/rung_distribution.py`) is its median over the seeds it ran on, from
`measurements.probe_seconds_*`. The box probe's median jumps (862, the operator 2026-11-25 09:12): it answers in
under a millisecond on a graph with no window of box sizes (it refuses, or the ball probe has already called the
growth exponential) and takes seconds on one that has a window, so its median reads 0 ms while most graphs at a size
have none and seconds from the size where most of the laws still running have one. Its 95th percentile shows the
full cost growing smoothly: in study 174 (06:26Z, campaign 1) 0 ms, 30 ms, 0.2 s, 1.1 s, 6.4 s and 29 s from 64 to
65,536, about five times for four times the nodes. The ladder's headers keep to one short line (787), so this lives
here; splitting the time into "read" and "refused" needs the probe's verdict stored beside its time, a schema change,
planned with the fleet ladder under the filters.

A stop does not wait for a boundary: a pause, a shutdown or a lane yield writes `<staging>/stop`; both engines look at
most every `STOP_CHECK_SECONDS` (4), stop after the current move and return a checkpoint inside the segment
(`in_segment`); the loop raises `StopRequested`, the child saves it and exits 75, and the resume is byte-identical to
a run never stopped. The worker, and the supervisor for a suspended compute group or a shutdown, kill a child only
after `STOP_GRACE_SECONDS` (120 s since 840, 8 before): a save is JSON of every chain's edges, 19 s for the largest,
densest state of 65,536 nodes (eight chains at mean degree 32, 52 MB) and 38 s with its last whole chunk beside it,
and the 8 s ended 5 of 14 seeds of study 172 unsaved at one restart, three of them 5.2 hours into a chunk. A child
that has saved exits at once, so a stop is as quick as before for every seed but the largest. A memory shed and every
other preemption kill at once. **A seed also saves inside a long chunk** (840): every `SAVE_EVERY_UNITS` of work (8 T,
`scaleflow/one_shot.py`, a quarter to three quarters of an hour on the host) the engines stop as they do at the
budget, the loop saves that state and goes on from it in the same process, byte for byte the chunk never stopped, so
a kill costs at most that much work. Measured at 16,384 nodes on two chains: 1.2 s to write a save and 0.5 s to stop
and go on, which scaled to eight chains at 65,536 is under a minute in every quarter hour or more. A state saved inside
a chunk, or where one ended, carries the seed's last whole chunk (`whole`, `whole_envelope`), which a seed resumed
from it and then cut at its budget ends on.

## Retries (`observability/child_diagnostics.py`)

No count cap: the third failure with the same `error_class` stops the job. `REFUSED_COMPUTE_BUDGET`, which nothing
has written since 782, is still a bucket the reports count (`docs/ROADMAP.md`, "Unscheduled"). `no_space_left` (exit 74) never counts: a simulation's claim goes back
unspent (`repo.finish_job(spent=False)`), retried after a minute, doubling to an hour (`no_space_deferral`); an
analysis's a minute later (`repo.fail_analysis_claim`). The interrupted classes
(`domain/model.INTERRUPTED_ATTEMPT_CLASSES`: a pause, a shutdown, a shed, a lane yield, a full filesystem, a share
taken back, a fenced lease and the like) stay out of the timing statistics and never count toward the three
(`same_reason_exhausted`); the storage's (`STORAGE_ATTEMPT_CLASSES`) do. Since 786 no job is `lost`: an expired lease
puts the seed back from its saved state, its attempt closed as `worker_vanished` (one of the interrupted classes),
after a wait that doubles each time to an hour (`Repo.reclaim_expired`, `domain/model.vanished_wait_seconds`), and
never charges the law. A fleet start closes every attempt never closed and queues again at once every seed the last
fleet still held (`scratch_repair._close_never_closed`); the fleet's stop gives its workers longer than they give their
simulations (`FLEET_STOP_GRACE_SECONDS`). A buy that makes no work is recorded with "decide again"
(`decider._no_work`, `decision_store.record_decision`).

**The console, on disk** (`observability/console_log.py`, the operator's): each service's output goes through a pipe
to a reader that copies it to the terminal and appends it to `var/log/supervisor.log` (`evidence_sources.TeeStdout`);
a failed write is counted, never raised. The services' own logs stay in the scratch (`GSD_RUNTIME_LOG_DIR`).

## The score read from every start (`observability/law_score.py`, gsd-law-score-9)

The board's and the law page's number, 0 to 100 (the operator, 2026-10-09: 100 only for a law that builds geometry
from empty and holds at 4 million N; 2026-11-11 05:07: every probe that settles adds to it; 2026-11-15 13:52: a reading
under 4,096 is pilot data, and converging earns extra points): 100 times who times depth times points over fifteen, the
best of every chain and size. **Readings**: from 4,096 only, and only where the chain's largest component holds 4,096
nodes or more and half the graph (`piece_holds`, `CONNECTED_AT_LEAST`, the decision engine's own floor, 848); a reading
is the fleet's, more than half of all its seeds read **and count**: a seed counts when its rung settled
(`EQUILIBRATED_ACTIVE`, `EQUILIBRATED_LOW_ACTIVITY`, `AT_REST`, `FROZEN_OR_ABSORBING`) or that chain's own last chunk
changed no edge (`two_chains.chain_stopped`, the `counted` summary beside each chain's; 848). A bundle's report 28
carries no seed's class, so a tool that scores a bundle again counts every seed. **Scale** (848, `scale_at`,
`scale_kept`): a step from a to b settles only where the graph's reach grows as the dimension the probes read at b,
|ln(r_b / r_a) - ln(b / a) / d_b| within q ln(b / a) / d_b, half a hop at each end and two standard errors (q = 0.2,
twice the widest excess of the calibration table's lattices, in `score_margins.json`), and only where the chain's next
step does not break it; a probe read at both sizes still earns its 1. A strip or a tube settles only as the line it is
at the size read, and a tree of long paths settles at d 1.1 to 1.4, a known limit (a random tree's spectral dimension
is 4/3; `docs/readings/score_known_answers_5_judged.md`). **Points**: along a chain's
sizes from 4,096, each step the larger at least three times the smaller (4,096 to 16,384, then 65,536), each probe
earns 1 when it reads at both sizes of a step, 2 when it settles there (its relative step within its margin at the
larger size), 3 when it settles again at the next step; the Einstein relation (d_s within tau of 2 d_V / d_w and of
2 d_B / d_w) is the fifth item, 1 when it can be read at both sizes, 2 when it holds at both, 3 at three in a row: 15 at
most (`items_along`). **Who**: the twin starts count 1, a lattice start whose fate is anything but `holds` or
`unmoved` 0.6, one that kept its shape or whose fate was not read 0.3; a lattice start whose fate is `unmoved` (no
edge changed: the law froze and the start went on existing) is `frozen` and the law it leads scores 1, the lowest
score there is (841, contract `gsd-law-score-6`; the operator, 2026-11-21 19:54 and 20:02). A lattice chain `still` at
a size (856, `still_at`, the catalogue's rule: its mean degree within 5% of its lattice's, most seeds not at the cap,
the median over its seeds of its accepted moves an edge at most 0.05) scores 1 the same way, as
`still_lattice_criterion_1.json`, passed at 854, said it would. The moves come from each seed's move accounting
(`two_chains.accepted_moves_of`, the snapshot keeping only their sum as `accepted_moves`), summed per chain over the
final edges, the median over seeds in `moved`; report 28's values carry it as the column `moved`. A chain with no
moves read is never still, so every structure of the score's known answers reads as 8 read it. **Depth**: a seventh a size from 1,024 to
4,194,304. The margins by probe and size and tau are `resources/calibration/score_margins.json`, made by
`tools/score_known_answers.py --write` from the calibration seed's exact lattices and fractals (twice the widest
training step, on a grid) and judged on structures the table never measured, read by the final probes
(`docs/readings/score_known_answers_3_judged.md`, 817).
**Judged twice before it was put in force** (846; criteria `score_known_answers_criterion_4.json` and `_5.json`, each
committed before its structures were read): criterion 5 held everywhere but on trees of long paths, which the score
before it settled alike, and the operator put the rules in force at 848 (2026-11-23 15:45).
The score is read beside a decision, never in it, kept per campaign in a control flag (`observability/score_board.py`,
which a new contract rescans; since 857 it keeps every scanned law's catalogue kind beside it, scored or not, and the
landscape marks each point with its kind, group, batch and region for Home's filters, `landscape_worker.marked`, each
start's point as well as its law's since 859) and read by the landscape, `/api/structure` and report 28; `compact`
carries each part's items so the landscape can band a law by its twins alone or by every start.

The Top 100 (`landscape_worker.top_candidates_of`) ranks the laws by their score, then (since 860) the campaign's
number and the graph's, in one order the server and the page share (`services/api/law_order.law_rank`, the page's
`lawOrder`, filtered or not): every law the chain from empty read, and every law it did not that scores above zero.
Since 859 the places left empty are given to the laws that read nothing from empty and score 0, the deepest first, so
a campaign of fewer than a hundred laws lists every one (the standing controls' five, their two negatives last).

**The study now, one bar** (865, `resources/ui/app.js`, `renderStudyNow`): the overview's campaigns split by laws into
blind (design kind `blind`, or a study batch with no kind) and zoned (seeded, the focus's neighbours, seeds and depth,
a map), each side its share, laws, graphs (bought and done), scoring laws (`high_score.scoring`, from the campaign's
cached landscape), what runs, is queued and is left; the standing controls (`campaign-standing-controls`) a tick with
their verdict. A click reads every blind batch in the panels below; one batch is chosen in the filter panel.

**How old Home's numbers may be** (`services/api/freshness.py`, 860). The overview is rebuilt in the API every refresh
period (one tick) when a poll finds it due; the study's view answers with the oldest of its batches' snapshots, each
rebuilt alone, through the API's database slots. The answer carries the age (`source_age_ms`), shown in the FRESHNESS
tile, and the age past which the page shows the orange banner (`stale_after_ms`): twice one round of the refreshes by
their own measured build time (`build_ms`), the refresh period, the page's poll and the slowest rebuild times the
waves the batches need through the slots; never under three refresh periods nor over a minute. A rebuild waits 16 s
for a slot; a batch whose rebuild failed is named in the study's answer (`last_refresh_error`, `refresh_errors`), and a
failure shows the banner whatever the age.

The landscape's bands (`services/api/landscape_worker.band_of_items`, since 784) are the score's: how many of the four
probes settled (2 points or more) on the part the law is read by, 1 to 4, and the 5th band, `einstein`, four settled
and the Einstein relation held at two sizes. `landscape_band` is the twins' (the chain from empty and the random start),
`landscape_band_with_lattices` every start's; the page's one toggle, "include lattice starts", chooses, and draws the
law at its scoring start's readings, whichever of the score's lattice names set it (changed, kept, frozen or still:
the landscape's `lattice_who`, read from the score's own list since 860). The stability blocks of the base rungs no
longer band a law.

## The catalogue of behaviours (`observability/catalogue.py`, gsd-catalogue-2)

Every kind of behaviour the survey has seen, kept as data in `resources/catalogue/catalogue.json` (850; the operator,
2026-11-24 10:22): for each kind, what it is, how a law is placed in it at a size, and how it scores. At a size each
chain reads its d (the median of its probes), its mean degree, its giant piece, its accepted moves per edge (the median
over its seeds) and whether most seeds ended at the degree cap; the law's kind there is the first that applies:
`grown` (any probe on the empty or random start steps within the score's margin at three sizes in a row from 4,096,
by its value alone; the operator, 2026-11-24 10:43), `small_world` (856: starts agree, and every agreeing chain read at
the size and a quarter of it reads at both a reach at most twice ln(N/2)/ln(k) + 0.63, a random graph's of its own mean
degree k, and a d that rises by a tenth: `rule.small_world`, its random reach read on the random start by
`tools/small_world_reach.py`), `made` (two starts or more agree on d and mean degree within a
tenth, d at least 1.5), `ring` (the same below 1.5: told from made by the d they agree on, not the mean degree),
`empty`, `full`, `frozen` (a lattice chain at its own degree, within 5%, that accepted no move), `still` (the same
with at most 0.05 accepted moves an edge, some), `rewired` (at its own degree, moving more), `moved` (lattice chains
off their degree), `broken`, `apart`, `unread`. The stream and the tree of long paths are listed but read elsewhere. Nothing decides by it: `tools/catalogue_reading.py` places every law
of a bundle, says how early each kind was known and how often that early call held at the deepest size, and scores
every law in force with its chains' accepted moves from the bundle's chains table, beside what it scored with no chain
still. `observability/law_kind.py` reads the same kinds from a law's rungs in a live folder, for the map. A new kind is
a new entry; a changed rule is a new criterion (`small_world_criterion_1.json`, committed at 856).

## The map of the best and the work groups (`operations/study_map.py`, `scheduling/work_groups.py`, 856)

A study's campaigns carry a group (`study_design.group`): in study 176, A the blind draw and B the map. **The
split**: the flag `work_groups` gives each group a share (A and B half each by default, `main.py workload --split`);
a worker claims from the group furthest below its share of the simulations running, among the groups with work
queued, and inside it as before (`in_shares`, then `allowed_campaigns`), so a group with nothing queued leaves its
slots to the others. **The system's CPUs**: the flag `system_cores` (btop's numbers); the worker and the analyzer pin
themselves to the other CPUs just before each child starts (`pin_to_work`), and the child inherits it; with none
named every CPU is the children's. **The map**: its state is the flag `study_map`. It begins from a committed list of
holders (176: `study_176_first_ten.json`), each with its points: the holder run again, each real parameter moved alone
a step up and down (`research/neighbourhood.alone`), and the midpoint of a line toward its partner, the nearest law of
the same terms whose kind at 4,096 differs and at least 0.001 away. At the end of every controller pass, at most once a
minute (`step`), a point decided is read for its kinds (`law_kind`), a line is halved on the side where the kind flips
until its halvings are spent, and a region whose points are all decided and whose lines are done is marked known:
its kind, the smallest of 1,024 and 4,096 at which every point of that kind already reads it, its boundaries and its
points' kinds. Every law's place on the map is read by `regions_of_laws` for the landscape's points (857). Free places
among the ten go to the best laws of the study by the score boards, above 1 and in no
region; a law of another campaign is not run again, its points are run in B. The bundle carries the state as
`map.json`.

## The focus (`operations/focus.py`, `resources/readings/focus_plan_1.json`, 861)

The study's best laws by the folder's score, one at a time, inside the study's own folder and beside its blind draw.
`main.py focus --study` makes three campaigns once, each of the study's own design, its laws chosen (a hand search
policy) and outside the let-through ledger and the gates' learning batches: **N**, each law's neighbours (rings of
1e-9 to 0.4, every parameter moved at once, `research/perturb.variants`) to 16,384; **S**, the law itself on twice the
design's seeds to 16,384, each seed read alone (`seed_kinds`) beside its own campaign's; **D**, the law in focus and the
study's best five to 262,144, its learning gates recording only. N and S are work group N, D group D, beside A, the
blind draw (an ungrouped campaign is A when the shares name A). Its state is the flag `study_focus`. At the end of every
controller pass, at most once a minute (`step`): the rings' tallies at 16,384 against the law's kind, the law's
sensitivity (its seeds, its exact parameters, or robust), D's kinds against the law's own campaign's at each whole
size; then confirmed (two thirds of the ring of 0.1) or ended unconfirmed, rings outward to 0.8 or lines halved four
times toward each neighbour of another kind from 0.01 out, D reading another kind ending it invalidated; an ended law's
summary kept in `done`, and the next law by score begun, passing over one inside a mapped region or skipped. The bundle
carries the state as `focus.json`.

**The Map page** (862, `resources/ui/map.js`, `services/api/focus_route.py`): one line at its top says what the focus
does and why (`focus.doing_of`, 871), and the page reads itself every 4 s; `GET /api/focus` answers the focus's
state as read (one flag), the folder's studies and the work groups; `POST /api/focus`, behind the admin capability,
takes `do`: start (or start again after a stop), law (focus one now, by label or id), skip, back (put back), stop
(pause the three campaigns), settings (the next law's rings, confirming share, deep laws, widest ring and inside
share, checked by `focus.settled` and applied by `start_next`), split (the work groups' shares). **GG numbers**
(`operations/focus_regions.py`): a law is a point on one axis a term (its coupling, 0 where it lacks the term; a term
with a parameter an axis a value) and the dynamics' axes; a law mapped gives a region of itself and every neighbour or
line point that read its kind, its ranges each axis's least and greatest; it takes the next number unless a region of
the same kind overlaps it on every axis, which it then joins.

**A study seeded from bundles** (865, `operations/study_seed.py`): a design with `"focus": true` begins the focus at
its start, and a campaign of kind `seed` (hand policy, empty, its gates recording `starts_alike` and `nothing_read`)
outside the let-through ledger and the learning batches (`db/decision_store.OUTSIDE_THE_LEDGER`, `_study_place`). The
Map page's "seed from a bundle" (`do: seed`) reads a bundle's `study.json`, laws table and `focus.json` (a `.tar.zst`
through `zstd`, streamed, or a folder), refuses another science hash, puts every law the bundle scores into the seeded
campaign by its spec, and joins its GG regions to the focus's state (`seeded_from`, the holder recorded as mapped); a
region from a newer bundle of the same study widens the one it gave, a taken number from another study moves to the
next. The records are the state's `seeded`, on the page and in the bundle's `focus.json`.

**The seeds as a selection, and a seeded law on its bundle's score** (871). A seed record is one per bundle
(`study_seed.records` merges any written twice) and holds each scoring law's bundle score and code (`laws`), the laws
table's sha256 and whether it is ticked (`selected`). `focus.best` takes a ticked bundle's law on its bundle's score
(`origin`, `standing: bundle`) until the seeded campaign holds a decision on it at the plan's `read_n` or past
(`focus.read_here`), then on the folder's own score, and leaves out a law whose every bundle is unticked
(`study_seed.let_go`). A law in focus without its own kind at `read_n` waits for it before its neighbours are judged,
and `depth_of` compares only the sizes its own campaign read, or every size once it is decided. A seed is refused when
the bundle is ticked already, when a ticked bundle has the same laws table, or when it adds no law and no region.
`imports.synchronize` (the Map page's `do: synchronize`, the ticked bundles' names) lets go of a ticked bundle no
longer ticked first (`study_seed.release`: out of the focus's lists and the depth seeker, the law in focus set aside,
each region that names it alone in `sources` and that no law mapped here joined moved to `regions_let_go`), then reads
in each newly ticked one (`study_seed.seed` from the import folder, or `study_seed.choose` from its record, which
brings its regions back). A let-go law stays in the seeded campaign and its runs go on: nothing measured is rewritten.

**The depth seeker's reach** (873). The focus's depth campaign climbs a ladder open to 4,194,304
(`focus_plan_1.json`'s `depth.beyond`; `focus.renew_depth` moves an older focus to a new depth campaign once, the old
paused). At each step `focus.depth_ceilings` asks `operations/depth_reach.py` to price each contender's next size from
its own peaks there (`peaks`, the attempts' `peak_rss_bytes` by size; `price`, the growth between its two largest
sizes as a power of N between 1 and 2, times 1.1) and to write the ones past `memory_hold.reach`'s `reach_bytes` into
the flag `memory_ceiling` (`decisions/memory_ceiling.py`, contract `gsd-memory-ceiling-1`), once a law. The decider
reads the entries for its campaign (`DecisionStore.memory_ceilings`), records the one it applies in the decision's
inputs, and `memory_ceiling.settle` turns a decision buying that size or past it into `stop memory_ceiling`
(`PARKING_RULES`, an operational gate, not salted); `decisions/replay.py` applies it from the inputs. A saved seed
(`artifact_store/resume_state.py`) writes every list of 4,096 or more whole numbers or pairs of them packed
(`packed`, `unpacked`: base64 of a 32- or 64-bit array inside the gzip JSON, marked `__gsd_packed__`).

**One depth worker, and a step that cannot fail unseen** (881). The depth campaign holds one law at a time
(`focus.depth_next`, `depth_line`): the law in focus first, then the depth list in its order; the contenders are only
the laws it will take. The next enters once the decider ends the last (`study_map.decided`: done, stopped or parked),
recorded in the state's `depth_now` and `depth_done`; its one worker (`DEPTH_WORKERS`) runs one seed at a time, a
size's three seeds in turn (three is the fewest `scheduling/base_block.py` lets a campaign measure a size on). The
plan's `depth.memory_share` (0.5) is copied into the depth campaign's spec (`study_design.focus.memory_share`); its
room is that share of the host's total memory (`depth_reach.room_for`, `room_of_share`: reach the share, the rest kept
free), and `DecisionStore.memory_ceilings` prices the campaign's laws (`depth_reach.refresh`) before the decider reads
the flag, so the price is never a step behind. A renewal adopts a depth campaign of the focus that already fits the
plan (`depth_fits`: ladder top, seeds, share) before it makes one and saves at once; `tidy_depth` pauses every other
active depth campaign of the focus. `focus.step` runs `_step` and, on any exception, writes the flag
`study_focus_failed` (`since`, `last`, `times`, `error`) before it raises; a step that passes clears it, and
`focus.reading` puts it first in the Map page's line. `focus.verdict` reads a law's kind at `read_n` once its campaign
has decided at `read_n` or past (`decided_past`), not only once it has ended it.

**The dex** (882, `operations/dex.py`, contract `gsd-dex-1`). The data a study hands to the next, with no report in
it: a `dex_<study>_<utc>.tar.zst` holding `dex.json` (every law that scores, best first: its spec, whose fingerprint
is its id; every code it was known by; every reading of its score as `seen`, each with its source, study and science;
its `score` under the dex's own science, null where no part of that science read it; the sizes its chains reach; its
`verified` checks), `chains.ndjson.gz` (per law, size, seed and start: the moves, accepted moves, edges, largest degree
and work a run again on the same science must reproduce, with its seconds and peak memory) and `rungs.ndjson.gz`.
`read_part` reads a dex or an old study bundle alike (a bundle's scoring laws, and the earlier studies' laws its
`focus.json` records as seeded, with their codes and scores); `merge` joins parts by fingerprint, `ranked` orders
them by the score under the dex's science, then the best score anywhere; `top` is the first hundred that score.
A folder's dex (`of_folder`) is its own scoring laws from every campaign of the study, every seed record's laws, the
focus's regions and the chains of those laws from the blob store (`study_tables.chain_rows(..., laws=...)`), merged
with every ticked part still in `import/`; `verify` compares each of its chains with a recorded chain of the same
law, size, seed and start under the same science, and files the count that agree and differ under the law. The
controller's pass (`controller.dex_pass`) reads in any dex newly put into `import/` (`absorb`, through
`study_seed.seed`) and writes the folder's dex into `export/` once an hour (`keep`, the flag `dex_written`); the Map
page's "write the dex now" (`do: dex`) writes one at once. `study_seed.read` takes a dex as a seed (`dex.seeding`):
its laws scored under the folder's science stand on that score until read here, as a bundle's do; a dex or bundle of
another science brings its laws alone (`laws_only` in the seed record), each run here from nothing, no score or region
carried, and is no longer refused.

**A dex verified first, then the first zone** (887, `operations/dex_check.py`, `operations/zone_choice.py`). A study
whose design carries a `dex` entry with `verified_first` (178) makes no seeded campaign in advance: the first dex or
bundle read in makes the dex campaign (`study_design.dex_campaign`, kind `seed`, so the Dex step of the fleet's order;
its index one past the batches, `study_design.entry_of`). Its focus (`dex_first`, set by `focus.begin` from the
design) takes no law and gives the depth worker none while a dex is read again (`dex_check.waiting`: a dex in the map
and no zone chosen). The controller's dex pass runs `dex_check.keep` once a minute: each law the dex campaign has
decided (`study_map.decided`) is checked chain by chain against the dex in `import/` (`dex.verify`, like for like:
law, size, seed, start, start graph and length; `dex_check.judged`) and filed in the state's `dex_check` as
confirmed (some chains agree, none differs), denied (one differs, its first difference kept) or unmatched (nothing to
compare: another length, or another science). Once every law of the dex campaign has its verdict, `zone_choice.first`
chooses the first zone from the confirmed laws, standing controls never: grouped by signature
(`neighbourhood.signature`: the term set and its parameters, the dynamics), each group's centre the law with the most
others within the focus's confirm radius, then the smallest mean distance; the group with the most laws within the
radius of its centre is chosen, then the larger group, then the smaller mean distance; with no two within the radius
none is, and the focus goes on as before. The choice is filed as `zone_chosen` with its line (`why`) and the first
groups; the focus's next step takes its centre into focus (`chosen_by` zone, `focus.zone_entry`) and the depth worker
begins with it. A dex let go while it is read again ends the wait. The Map page's Seeds panel lists the dex's laws as
they read again and the zone with its line (`focus.reading`'s `dex_check`); `tools/dex.py zones` reads the rule on a
dex on a disk.

**A dex read again: its level, law by law, from the start** (888). The import folder ships in the tree
(`import/README.md`), and the controller makes it at its start and the study's start too (`study.make_import_folder`); a dex in it when a study starts is read in
by the start (`study.read_in_at_start`), before the fleet's first pass. The dex campaign's ladder stops at its level
(`study_design.verify_level`, `ladder_to`): the ladder's base, N=4,096, unless the design's `dex` entry or the dex's
own `verify_to` (`tools/dex.py make --verify-to`, carried through `dex.merge`) asks for more, never past the design's
top; the level is filed as `study_design.verify_to`. `dex_check.read_to_level` judges a law once every seed has run at
every size to the level, or once it is decided, so a campaign made before 888 with a deeper ladder is judged at 4,096
too. In a study that verifies its dex first its laws are read in term set by term set, the largest first
(`study_seed.reading_order`), and the Dex step of the fleet's order claims `by_law` (`work_groups.claim_bounds`):
`ORDER BY` the job's rank, the law's admission, its size, first with `max_n` the level (4,096), then without, so every
law reads to 4,096 before any law goes deeper. "Working now" groups the runs under way by law (`zone_live.law_rows`):
its runs done of those planned (seeds times sizes, to the level for a Dex law), what runs now, and its progress. The
folder's dex is written every hour, and between the hours when `dex.news` finds what the last one lacks (a law scoring
here not in it, a zone mapped since, more of the dex verified here), looked at once a minute and never two within ten
minutes; the `dex_written` flag keeps why, and the ids of the laws it held.

**The fleet's three modes** (893, `operations/modes.py`, the flag `fleet_mode`). The fleet is always in exactly one
mode and never mixes them: **the N-push** while the Top page's push list holds a law, else **the zone search** while
a zone has work (`modes.zone_work`: the dex read in being checked, a law in focus not ended, a zone chosen and not yet
taken), else **the blind ladder** with its gates. `modes.compute` names the mode, why, and the campaigns it runs:
the push campaign alone for the N-push; the focus's parts N, S and E and the Dex campaign for the zone search; every
other active campaign (the blind batches, the standing controls) for the blind ladder (`modes.kind_of`, by each
campaign's design). `modes.keep` writes the flag at every focus step, every ladder tick and every change of the push
list, keeping `since` while the mode holds. Every claim keeps to it: a run is claimed only from the mode's campaigns
(`worker.claim_simulation_for_owner`, `worker.in_mode`), a probe likewise (`analyzer.claim_analysis_for_owner`,
`repo.claim_analysis_job(campaigns=)`), and a run under way of another mode is stopped within two seconds, its seed
saved, and given back to the queue (`lane_yield.mode_yield_reason`, class `preempted_fleet_mode`), to go on when its
mode comes back. Within a mode the fleet's order (`work_groups.ordered`) still decides which campaign's run goes first.
In the zone search the slots its work leaves free (`zone_search.free_runs`: the worker count less the mode's queued and
running runs) run its lines ahead (`zone_search._look_ahead`, `ahead`): while a line's step is read, the two points it
may need next are made (marked `ahead`), three runs a point, and the line reads the one it comes to without a new law
(`_put`, `_take`; its last step out counted by the steps read).
While a dex is checked its laws run only to the level it is verified at, and since 893 also after the check
(`dex_check.keep` keeps `dex_verifying_to`, `work_groups.verifying`): a Dex law deeper is the N-push's.

**A law pushed to the N limit** (889, `operations/push.py`; its own ladder, 893, `operations/push_ladder.py`). The
focus state's `pushed` is the operator's queue: a law pushed from its page or the Top page joins the end, as does a
zone's central law when its zone is mapped (`zone_search._central`, `push.add`); the law the depth worker held when
892 came in was put first once (`push.adopt_now`, `push_list_adopted`). The first law of the list that has not
reached its limit (`push.ahead`) is pushed; taken off (`unpush`, kept in `let_go`, not taken again until pushed
again) or moved below another (`push_move`), its runs under way stop at once, saved, and the next law is pushed; a
law moved down keeps its runs and goes on where it was when it is first again. **The push ladder** runs in a
campaign of its own, part P (`push_ladder.campaign`, a copy of the focus's depth spec, its ladder from 64 to
4,194,304), which the controller's decision engine leaves alone (`push_ladder.is_push`): the ladder buys its own
rungs. `push_ladder.step`, every 5 seconds in the controller (`push_ladder.tick`) and at every focus step
(`focus.depth_next`), holds the law in the campaign (`EXTENDING`, "pushed to the N limit") and redoes its whole
ladder from N=64: a rung's seeds are bought once the rung below has a finished run, each priced from the law's own
peaks below (`depth_reach.price`) against the host's reach (`push_ladder.reach`, `depth_reach.room_now`), by
`push_ladder.plan`: as many seeds as there are workers (the worker count), all at once, while they fit; when memory
binds, as many at once as fit, and the rung takes that many seeds, never fewer than `LEAST_SEEDS` (3), then in passes;
when not one seed of the next size fits, the law is done (`push.ended`, `pushed_done`, rule `memory`, or `ladder` at
its top) and the next law is pushed. Its runs are claimed by every slot (`worker.claim_depth_for_owner`: the first
law's queued runs, smallest first, a later law's only below 16,384; memory admission as for every run) and probed as
any run; the evidence rebuild writes its rung summaries. `push_ladder.forecast` reads the ladder rung by rung: done,
under way (its seeds left) and ahead, each with its seeds, how many at once, its passes, the memory a seed needs (its
peak, or priced), the time a run takes (its mean, or priced from the law's two deepest sizes by `push.run_seconds`),
the hours the rung takes and when it starts and ends from now; the break-points (`marks`: the first rung with fewer
at once than workers, the first with two passes, the first on one worker), the size past the host's reach (`limit`)
and the end. The Top page (`/top`, `GSD_TOP` in `map.js`) reads `/api/focus/top` (`push.reading`): the mode and why,
the runs under way with the memory each holds now and at most from the executor's heartbeat (`push.slot`,
`push._memory_of`), the list with who put each law there and its order buttons, the laws waiting and those done, the
law's ladder as a timeline with its break-points marked, the rung table and its memory over N against the reach, and
the study's laws by the deepest N any run of theirs has finished (`push.deepest`). The focus's depth campaign (part
D) takes no law since 893; its readings are kept.

**A zone's search** (890, `operations/zone_search.py`, `observability/likeness.py`). A law taken into focus by the zone
rule (887) is searched instead of ringed: `focus.start_next` calls `zone_search.begin`, and `focus.advance` hands each
step to `zone_search.advance`, through four stages kept in the law's `search`. Members: the zone's laws judged
against the centre at `JUDGE_N` (4,096) from the runs the dex check made; two thirds of those within the plan's
`confirm_radius` must read alike, else UNCONFIRMED. Edges: each `perturb.parameters` path, both ways, stepped from 10%
of its value doubling (`next_at`, five steps, 95% at most down), each point a new law in the focus's part E campaign,
laddered to 4,096 and in the zone step, judged by `likeness.alike`; at the first step read other, the gap halved
three times (`HALVINGS`); each term switched off once (`focus.knockouts`) in the same campaign. Confirming: the two
points either side of each edge in the zone campaign to the plan's `read_n` (16,384), against the centre's own seeds
there; an edge holds when the inside reads alike and the outside other. Done: `central_spec`, the middle of each
parameter's alike extent, made in the zone campaign and put at the end of the push list (since 892; 890 and 891 kept
a `central` list after the pushed laws); `benchmark` prices the search from its attempts beside the plan's
rings; the law ends MAPPED and its region is named as before. Likeness fits each law's curves from its rungs up to
the size read by the phenotype's forms (`phenotype.fit`) and calls two laws alike when their kinds agree and every
curve both have locked in has the same form and value or exponent within the phenotype's margins; with none shared,
the kind alone.

**Zones one after another** (891, `zone_search.zone_of`, `zone_search.ended`, `dex_check.next_zone`). When a searched
law ends, `focus._finish` keeps its zone (`zone_of`: centre, kind, curves, term-set `signature`, the laws alike and
near, the `box` of each parameter's alike extent from the lines' `lo`, the edges and whether each held, `held_to`, the
central law, the cost) in the focus state's `zones` and, when mapped, on its region's `zones`; then `next_zone` moves
the chosen zone to `zones_chosen` and asks `zone_choice.first` again over the dex's verified laws less those
`dex_check.searched` names: every centre tried, the laws near an unconfirmed centre, and every law inside a mapped
zone (`zone_search.within`: the same signature and each parameter's relative offset from the centre within its
extent, `passed_over`). The first choice passes over the same set, `zone_search.zones` reading the zones read in on
seeded regions too. A region's `zones` travel in the dex (`_regions_of`, kept by `study_seed` on a read-in region),
each zone's central law is among the dex's laws (`own_part`, from the focus state's `central`), and the dex's `lucky`
lists the laws that ended UNCONFIRMED here, merged by law across parts. `tools/dex.py zones` prints a dex's zones and
the next zone with what they pass over.

**The focus's choices** (882). `focus._chosen` records why it took a law (`chosen_by`: score, bundle, outlier,
operator), said on the Map page's line. An outlier is taken only once the study has a scoring law and every one is
mapped, inside a region or skipped; an outlier in focus (or a law of score 0 taken before 882 with no reason
recorded) is set aside the moment a scoring law is free (`set_aside`, kept in the state's `set_aside`); since 893 the
depth worker takes no law of its own (a law goes deeper only on the push list, in the N-push's own ladder).

**What the zone worker waits for** (883). The depth list (`focus.contenders`) holds the study's scoring laws and
the law in focus only. A law's kind at 16,384 is read in its own campaign, else in its seeds' campaign once that has
decided at 16,384 (`kind_here`, recorded as `kind_from`); before it, a neighbour or a term switched off is read but
not judged (`tally`'s `read`, `terms_read`'s `load_bearing` None). Its seeds are compared seed by seed at the largest
size both campaigns read (`seeds_of`'s `compared_at`), again at every step. `focus.needs` lists, under the law in
focus, each condition of its mapping with its count; the Map page shows it as "to map it". A law in several
campaigns opens in its home (`focus.home_campaign`: the blind or seeded campaign, then the zone's, then the depth's).

**The zone now** (884). `operations/zone_live.py` reads, without writing, what the fleet does for the focus:
`reading(repo, state)` lists every leased simulation by role (`roles_of`: a focus part's N, S, D as zone, zone seeds,
depth; a `seed` campaign as Dex laws; `blind`) with its attempt's start and the median seconds of one seed at its size
(`typical`, the zone's campaigns' finished attempts over six hours, else the fleet's), and each law of the zone's
stage (`where`, from its jobs by size and status, its pending analyses and its latest decision), its largest whole
size (`reached`), the work left at most, the rings counted by stage (`rings_of`) and the pace (`pace`). The focus's
step keeps what it needs over time in the state: `read_at`, `so_far` (`kinds_so_far`), `needs_at`, `typical`
(every five minutes, `typical_of`), and `zone_first` (`focus.zone_first`): the queued runs of laws no longer in focus,
in the zone's and seeds' campaigns, priority raised by `focus.BEHIND` so the law in focus's are claimed first, lowered
again when their law is in focus. `/api/focus` serves it as `zone_now`, `zone_live.safe` turning a failure into an
`error` the page shows; a bundle's `focus.json` keeps it. The work groups count a campaign of kind `seed` in A
(`work_groups.group_of`), whatever its design says.

**One order for the fleet** (885). In a folder with a focus campaign, `work_groups.ordered(allocation)` lists the
steps with work, each a list of campaigns: 0 the zone (focus parts N and S, runs below `BEHIND`), 1 the depth worker
(part D), 2 the Dex laws (kind `seed`), 3 the blind draw and the rest, 4 earlier laws' leftovers (runs at or above
`BEHIND`, raised so by `focus.zone_first`); a campaign below its own `workers_target` joins the first step. The worker
(`services/worker.offers`) claims step by step, each kept below `BEHIND` by `claim_job(under=)` until the last, then
anything. A probe takes its step from its campaign (`work_groups.TIER_SQL`, computed once a claim) and is ordered by
it before its priority (`repo.claim_analysis_job`); the analyzer claims steps 0 and 1 first (`tier_at_most`), then its
two halves. `repo.refresh_scheduler_state` splits the slots on the probes and runs of the first step with either
(`allocation.first_work`, `analysis_backlog_tiers`, `simulation_work_counts(ordered=True)`) and publishes the whole
backlog, an executor slot with nothing of its kind taking the other kind. A folder without a focus keeps its shares
(`in_shares`). A zone whose ring at 0.1 is under two thirds alike stands at the largest ring from 0.01 that is not
(`focus.confirmed_at`, kept as `confirmed_at`), else ends unconfirmed, "a lucky hit" on the Map page.

**Home's selection and hours** (872). `observability/selection_ladder.py` makes one fact a law (`FIELDS`: its
campaign and id, the sizes it has a reading at, `under way`, `waiting`, `settled` or `not started` from
`law_status.of_row`, the rule and size of its latest decision, its next size, its score and the size it was scored
at), from the live folder (`facts`) or from a bundle's `tables/laws` rows (`facts_of_rows`), and `ladder(facts, keep)`
counts them by size; `GET /api/selection-ladder/<campaign or study>` (`services/api/selection_route.py`, the study's
blind batches and its focus and seeded campaigns) answers the facts, and `resources/ui/selection.js` counts the ones
Home's filters keep with the same function. `observability/study_hours.py` (`GET /api/study-hours/study`) adds each
campaign's attempts (wall seconds, and peak bytes times wall seconds) into the parts A, N and D by
`study_design.group` (blind A, seeded N), and the system's part as the host's from `resource_telemetry` (CPU share times
seconds times cores; memory in use times seconds) less the workers'.

**A law's code** (871, `operations/law_code.py`): `S<study>C<campaign>G<graph>`, the study of the campaign's design,
the campaign and the number of the law's first graph in it (`MIN(graph_ordinal)`, as the ensemble code); where no
graph has run, `S<study>C<campaign>-<the id's first 8>`; a campaign with no study keeps `C<campaign>-G<graph>`. Its
fingerprint is the identity underneath. The focus's labels, `/api/structure`'s `code` (with a seeded law's `origin`),
`/api/campaigns`' `study` (which `system.js`'s `lawCode` and `lawCodeQuery` read for Home, the Explorer and the law
page) and the bundle's `tables/laws` (`code`, `graph`) all make it the same way; `law_code.parse` and `same` read
S176C11G79, s176-c11-g79 and C11-G79 alike.

**Held laws run on** (864, `operations/run_on.py`): the Map page's last panel reads each study's committed run-on list
(`study_<id>_run_on.json`, `tools/held_by_a_gate.py`) and offers "run them on" (`do: run_on`, the flag `run_on`, how
the decider takes it in `docs/DECISIONS.md`, "A law run on by word"); once named, it lists each law as waiting, running
on or settled again with its latest decision, and "name no more" clears the flag, a law already run on going on.

## A law's status in words (`observability/law_status.py`, 864)

No law is done: the ladder a study declares is where it stops for now, and any law can be taken higher. Every page
says a law's status from its state and its latest decision: **waiting to be extended** (read to the top of its
ladder, the state `DONE` stored as before, or held for a place at its next size), **settled at N=...** by a gate, its
budget or a condition (the rule named; by a region, GG#n, where the focus names one), the size its highest reading
was taken at said every time, since a reading at a larger size carries more weight; **running** to its next size; or
**not started**. The law page's header and its first line, the explorer's state column and Home's lines read it
(`candidate.status`, `status` on the explorer's rows); nothing stored changes, so every decision replays. Since 865
the law page's header chip says the law's **type** once its chains are read (`phenotype` in `/api/structure`,
`law_status.phenotype`): its catalogue kind at its largest size read, its form where its starts settle or agree (a
ring or rings at degree 2 and d under 1.5, open strings or a line, else its d), and its GG region and place on the map
(`focus.place_of`: mapped, inside and passed over, in focus now, or none yet); the status moves to its mouse-over.

## The science a bundle was read by (`reporting/science_contract.py`, 856; contract 2 at 861)

`study.json`'s `science`: the analysis version, the estimator's and the starts' fingerprints, the score's and the
catalogue's contracts, the engine crate, the calibration table's cells' SHA-256 (its analysis version, estimator
fingerprint and cells; not its adoption times) and one SHA-256 over them all; the table itself is in the bundle
(`calibration/probe_calibration.json`), its file's own SHA-256 beside the hash. Two bundles with one science hash were
read the same way on the same table; `science_contract.same` names what differs.

## The stability blocks (`research/stability_score.py`, gsd-stability-score-14)

Five blocks, the mean degree and the four probes of the chain from empty, each saying whether its quantity settles
over the law's valid rungs, with a bucket saying why; the gates (no metric structure, control family, density flowing)
relabel a settled block's bucket; the branching line's left at 790. No total is summed: reports 04, 05, 10 and 22, the landscape and
the bundle's reading classify laws by the blocks and gates. A d_s step with a measured error is judged as the decision
engine judges it, within twice that error plus a known geometry's finite-size drift (`research/d_s_slack.py`); the
noise floors are `research/noise_floors.py`.

Nothing reads the score or the blocks to buy, park or stop a law. They order a full deep lane's waiters
(`db/decision_store.laws_waiting_for_the_lane`, with `DecisionStore.control_family`; `docs/DECISIONS.md`, "The
lanes").

## Calibration (`calibration/`, `research/probe_atlas.py`)

How a folder adopts and backfills its table is `docs/OPERATIONS.md`, "The calibration table". The table
(`calibration/probe_calibration.json`, host state; an archive carries it only as the seed,
`calibration/seed_table.json`) is 2,584 cells in the seed, 2,560 on its 27 families' ladders and 24 past them at
about 1,048,576, which never gate a verdict and set the per-N noise floor where no ladder reaches; every one is the
host's of 2026-11-18 and 19, measured on 801, and current (805). Every plan stops at `contract.MAX_NODES`
(1,048,576). The runtime gate refuses to start if the estimator fingerprint moved; an adoption re-stamps only the cells
current before its edit and measured under this tree's analysis (`adopt.restamp_current`), and the bands and control
families read only current cells (`table.cell_is_current`). The atlas reads the table as how much to trust each probe
at each N. A cell carries d_s's two AICc margins (`calibration/margins.py`) and the full census on the large ones, so a
fresh folder owes no backfill. The bands derived from the seed (`resources/calibration/d_s_margin_bands.json`, stamped
with its sha256) are read by report 28 and the Calibration page and decide nothing. Every report bundle carries the
table.

**A cell's key names its analysis** (766). A cell's fingerprint is the analysis's name
(`measurements/version.ANALYSIS_VERSION`, read from the tree whose cells are judged), the estimator's fingerprint and
its family's (`fingerprint.cell_fingerprint`); the cell says each in words (`analysis`, and
`fingerprint.what_a_cell_was_measured_by`). A cell is current only when its fingerprint is known and is this tree's
(`table.cell_is_current`): one without a fingerprint, or measured under another analysis, is measured again and never
re-stamped. The table is suite 3 (`contract.SUITE_VERSION`): a table of another suite holds cells of another shape, is
not resumed from (`table.verify`), and a new table is measured whole. The seed in the tree
(`calibration/seed_table.json`) is this suite's: the table the operator's host measured whole under analysis
5.3 on build 801, 2026-11-18 and 19 (`tools/probe_calibration.py --whole`; 2,560 cells on the ladders and 24 past
them, 189.6 core-hours), judged against the criterion committed before its zip was seen and installed at 805 by
`tools/collect_calibration.py --install-seed`. Every cell of it is current under this tree, so nothing is
owed: `calibration/recalibration_owed.json` is gone, and `calibration/owed.py` and the branch of
`suite.ensure_calibration` that measures an owed table whole stay for a later change to a probe, held by
`tests/unit/test_an_owed_recalibration_is_measured_whole.py` on the seed with its deep cells made stale. A first start
in a new folder adopts the seed after measuring each family's cheapest cell again (`adopt.spot_check`, a cell a
family), and `margins.seed_bands` and `finite_size.measure` read it for the d_s margin bands and the finite-size
tolerance.

**The lattice starts' references are the table's own cells** (766). Every lattice start is a family at every size a
law runs, built as a chain's start is built (`measurements/calibration.control_family_edges`). Each cell records the
probes' reach beside the four probes (`half_volume_radius`), and the cells of a lattice start at the sizes a chain is
read (from 1,024 nodes, the sizes a law runs), on three seeds, record the start read as a chain's last state is read
(`calibration/start_reading.py`, the cell's `start`): its mean degree, triangles and squares a node, largest piece and
curvature, by the census and the curvature probe a chain's record goes through, and the reach and mean degree of a
random wiring of its degrees. `observability/starts_reading.references_from` makes a reference from them: the probes over
every seed of the cell, the counted quantities and the wiring over the three, in the summaries a chain's seeds have.
`table_references` reads the folder's own table, so a fleet measures its references by measuring its table, with no
command; a size whose cells are not current has no reference and is said so (`NO_REFERENCE`). The start's reading has
a fingerprint of its own (`start_reading.sources`: the census, the curvature probe, the random wiring and the two
functions that read; the ball count is the estimator's and in the cell's key): a cell whose probes are current and
whose start was read by other sources is owed only its start, measured beside it without the probes
(`cells.measure_the_start_beside`, `table.its_probes_are_current`).

**One test of the probes against theory** (766). The table, held by its rule, is it. The analyzer's benchmark battery
(`measurements/benchmarks.py`, run at `run` and cached by the analyzer's identity) reads four cells of the table
through the door a chain's record goes through (`measurements/analysis.analyze_envelope`): the ring of 4,096 nodes,
the square torus of side 64, the cubic of side 20 and the 4D torus of side 12, on three seeds, each probe held to the
rule's band where the rule holds it (`benchmarks.held_as_the_table_holds`), beside its checks that a random graph, a
tree, an empty graph, a dense one and one in two pieces are flagged. It types no band of its own.

**The whole table by one command** (767, `tools/probe_calibration.py --whole`; `docs/TOOLS.md` says how it stops).
It runs the suite on every ladder at ten seeds, the cells past the ladders and the collection, reads no seed, and
starts no database, study or fleet; the functions are the ones a first start and the tool's other flags run
(`suite.run_suite`, `extension.run_extension`, `tools/collect_calibration.collect`), so the cells on its ladders are
the cells a first start would have measured. A first start still adopts a seed of this suite after verifying it.

Cells up to 20,000 nodes run in a pool, each larger one in its own process (`suite._LargeCell`). Admission
(`calibration/admission.py`) counts each running cell's growth to where it settles and room for the largest spike; a
claim that does not fit pauses its cell with SIGSTOP (the estimators keep no clock), the oldest never pausing, and
under the fleet's 8 GiB line the youngest is ended and queued again. A family is priced from its own measured peaks
(4 KiB a node until it has one), a census from `extension.census_memory`; `tests/support/pacing_sim.py` replays
measured memory curves through these rules. A cell's fingerprint is the analysis's name, its family's builder and the
estimators' closure, and its start's reading has its own: nothing of the scheduler, so it can change without a cell
going stale.

## Fingerprints

- Estimator (`calibration/fingerprint.py`): the import closure of `measurements/estimators.py` in the package (today
  with `box_covering.py`, `walk_dimension.py` and `fits.py`), each as a normalized syntax tree: a change to the
  program moves it, a comment, docstring or local rename does not. Since 758 that file holds the probes and nothing
  else: the certificate is `measurements/certificate.py` and the reading of a chain's record `measurements/analysis.py`,
  which import the probes and are no part of the key, so a change to either leaves the calibration table current
  (`tests/unit/test_only_the_probes_recalibrate.py`). Analysis-side additions go there or in `scaleflow/one_shot.py`.
- A cell (`fingerprint.cell_fingerprint`): the analysis's name, the estimator and the family (its slice of
  `measurements/calibration.py` and the modules its builder imports).
- What reads a start beside its cell (`calibration/start_reading.sources`): the same syntax tree, of whole files and
  single functions (`measurements/parsed_code.py`).
- Science freeze (`tests/fixtures/science_freeze.json`): every science-sensitive source by its bytes;
  `tools/science_freeze.py --write`, deliberately, when one moves.
- The engines (`services/worker/engine_registry`): the Python engine's files and the Rust crate by their bytes, since
  a saved chain is continued only under the same dynamics. Their comments go at their next change.
- Runtime: the whole tree; children verify it before and after work.

## The calibration ledger (`calibration/ledger.py`, `calibration/probe_groups.py`, `probes/`, gsd-calibration-ledger-1)

The table keys every cell by one fingerprint over every probe, so a fifth probe, or an edit to one of four, makes all
2,584 cells stale and the whole table is measured again. The ledger keys readings by **probe group** instead, and only
ever grows.

- **A probe group** is a set of channels measured together under one fingerprint. `geometry` is the four probes of the
  table (`d_s`, `d_V`, `d_B`, `d_w`), keyed by the analysis's name and the estimator's fingerprint, as the table is;
  they share one stream of randomness and code, so they stay one group. Every module of
  `graph_scale_dynamics/probes/` is an **appended group**: it declares `GROUP`, `VERSION`, `CHANNELS` and
  `measure(n, edges, seed)`, draws its own randomness from the cell's seed and its own stream, and is keyed by its
  version and its own import closure (`probe_groups.group_fingerprint`). `probes/` is outside the frozen trees and
  outside the estimator's closure (`tests/unit/test_an_appended_probe_moves_nothing_frozen.py`), so appending a group
  moves no frozen source, no science fingerprint, no running study and no table cell.
- **A ledger file** is `calibration/ledger/<group>/<fingerprint>.jsonl`: one JSON record a line, each carrying the hash
  of its own canonical content and the hash of the line before it (the first, a genesis hash of the group and
  fingerprint). A rewritten or dropped line breaks the chain and `ledger.problems` names it; nothing is appended to a
  ledger that does not verify. A cell is measured once under a fingerprint; reading it again is an **attestation**
  (`kind: attest`, `of`: the measured record's hash, the host, the environment, the largest relative deviation, and
  whether the values are the same bytes). A new fingerprint is a new file: the old one is never touched, so every
  reading made against it can still be checked against exactly what it used.
- **The view** is, for each group, the records filed under the tree's current fingerprint for it. A **snapshot**
  (`ledger.snapshot`, `ledger_runs.view_snapshot`) names each group's fingerprint and two roots: `root`, a Merkle root
  over the record hashes (who measured what, when), and `content_root`, over each record's `values` hash (the cell,
  its family's fingerprint and its channels alone). A root is the set's and not the order's: two hosts holding the same
  records print the same root whatever order they appended them in. A reading that pins a snapshot can be checked
  later against the ledger, however much the ledger has grown since.
- **The table stays** what the gate, the score and the readings read. `tools/ledger.py from-table` files its cells in
  the ledger under the fingerprint that measured them, measuring nothing. An appended group has **no vote**: nothing in
  the gate, the score or a decision reads its channels until a criterion committed before its known answers says what
  they must be.

The first appended group is `quantum_walk` (`probes/quantum_walk.py`): a continuous-time quantum walk under the
degree-normalised adjacency of the largest component, from four starts, stepped by an exact Chebyshev expansion. Its
channels are `q_alpha`, the exponent of the walk's mean squared graph distance (2 is ballistic, a wave that travels),
and `q_decay`, the exponent of its smoothed return probability (the dimension on a clean lattice), each read from
4 pi to the time the walk reaches half the eccentricity, refused as `SATURATES_EARLY` when that span is under four.
Where `d_s` reads the spectrum alone, the quantum walk reads where the eigenvectors sit: on the ring and the square
torus the two agree (1.0 and 1.01; 2.0 and 2.08), on the Sierpinski gasket and a uniform random tree `d_s` reads 1.37
and 1.29 and the walk does not spread (0.00 to 0.03): a space that diffuses but does not carry a wave.

## The reports

The study runner (`services/reporter/study_run.py`) makes each campaign's cycle from one REPEATABLE READ snapshot,
only when requested and only on a quiet fleet (`operations/quiet_report.py`; how it is asked for:
`docs/OPERATIONS.md`, "Reports: only when asked, only on a quiet fleet, one bundle for every campaign"). The quiet
report pauses what runs (a campaign already paused stays paused), gives back what a start gives back, makes one cycle
for every reportable campaign at once and resumes exactly what it paused; the API process writes the study bundle
(`reporting/study_bundle.py`) under `var/reports/study/bundles/`, and the web process lists and serves it
(`/api/reports/study`). Every report is reporting-only: no search, evaluation or scheduling policy reads one. The
catalog is `research/report_catalog.py`.

**The study bundle**, `study_<id>_<utc>.tar.zst`, every member a plain file, the study's own first:

* `index.html` (`reporting/study_front.py`): what the study found, what deserves a closer look, and what a law costs
  before it runs (report 16's model);
* `explorer.html` (`reporting/study_explorer.py`): every law of every campaign at every rung, placed against the
  calibration families (`research/classification_report.place`), its data inside, fetching nothing, opening on the
  Classify maps (script and style in `resources/explorer/`);
* `gate_trees.html` (`reporting/gate_trees_page.py`): every campaign's report 28 gate tree, with pages Tree, Gates,
  Survival, Table and About; a click on a piece opens those laws in the explorer;
* `study.json`; `advice.json` (`research/advice.py`, from the bundle's reports only); `anchors.json`;
  `gates_ledger.json` (784); `finds.json` (795, `research/finds.py`: every law scoring above zero, its spec, its score
  with `d`, the dimension read, and every chain's values by size: the study's own data); `tables/`
  (`reporting/study_tables.py`, a row per
  law and per law and rung, `*.ndjson.gz`, `draws.ndjson.gz` among them, and since 798 `decisions.ndjson.gz`, every decision with its inputs; each law's row carries its regime,
  and since 860 the law whole (`spec`, its fingerprint its id) and the folder's own score of it (`law_score`, the
  score board's entry), so a study can start from a bundle's laws (`tools/laws_of_a_bundle.py` draws an older
  bundle's again from its design's seeds);
  since 836 `chains.ndjson.gz`, a row per seed and chain from each run's compact evidence in the folder's blob store
  (`var/blobs`), its final and peak edges and mean degree, whether it ended at the cap and the seed's peak memory, read
  by `tools/cap_reading.py`; since 841 also its moves, the moves it accepted (none means no edge changed), its work in
  the campaign's unit with the six counts the unit weighs, and its seconds in the engine; the database keeps only the
  empty start's peak);
* every campaign's bundle, `campaign_<id>_reports_<utc>_<rev>/`: its reports as numbered JSON files with a `body`, and
  `evidence/` (`memory_ledger.json`, `system.json`, `calibration.json`, `probe_calibration.json`, API samples).

`tools/study_explorer.py` writes the pages and `advice.json` for a bundle that lacks them. `reporting/study_reading.py`
reads a bundle the same way every time (`tools/read_bundle.py --against` sets two side by side) and writes nothing
into it. A bundle holds only the cycles
finished in its own request, checks each part before it writes (`report_bundle.check_coherence`), names every campaign
it lacks (`study.json`'s `absent`), stamps what it read after the fleet resumed (`read_utc`), and writes the next
study's ledgers only once its archive is written. While a quiet report holds the fleet a resume, reopen or allocation
is refused (409, `campaign_manager.HELD_BY_A_QUIET_REPORT`); the admin's `cancel` (the panel's button, action `cancel`)
stops it while it holds the fleet (the report runner's group ended), resumes what it paused and makes no bundle. A
runner step that fails is printed to the API's log and kept on the record (`runner_error`); fifteen in a row resume the
fleet the same way (734).

The runner forks one worker per campaign, as many as their measured costs fit, each collecting a snapshot
(`research/report_pipeline`, `research/snapshot_rows.py`, `reporting/snapshot_transport.py`) of only what the reports
read (no peer campaign, rows streamed without their text; what it keeps is declared, "The blockers"). The reports that
read every measurement (04, 14, 16, 23, 28, `services/reporter/main.BUILT_BEFORE_THE_CHILDREN`) are built before the
fork. `tools/report_audit.py` says what each report reads and what reads it.

| # | slug | question |
|---|---|---|
| 04 | flow | How do the probes evolve with N? |
| 05 | phenotypes | Which regions are populated, and why do laws refuse? |
| 10 | decisions | Every engine decision by action and rule, with each law's trail |
| 14 | compute | What limits the fleet right now? |
| 16 | efficiency | What does each stage, size, sampling and operator cost? |
| 22 | stability-score | Does each probe settle, and when a block scores zero, why? |
| 23 | hang-autopsy | Which laws cost the most and what stopped them? |
| 25 | fleet-and-host | Who owns the fleet, and how did the host behave by the hour? |
| 28 | decision-engine | What did each engine rule decide and cost, and what would each final-verdict stop lose? |

Where to look: 05 holds per law its connectivity and dimensional classes and rung vectors; 14 the queues, failures,
capacity and memory admission deferrals; 25 running and queued per rung by hour (starvation shows here). A new report takes the next number
(`report_catalog.catalog_payload`'s `next_report_number`).

**28** reads the engine's own record (`engine_decisions`). `the_record` holds the draw ledger, the depth audit, the
decision replays, the cost split per contract, and the structure section (`the_record.structure_gate`): what the
structure gate refused, where, what that saved and what its audit found a rung later (`research/gate_report.py`; the
gate panel reads the folder-wide half, `/api/gate`, `services/api/gate_route.py`), with `three_readings`,
`chains_by_law` and `given_only_finite`. Its stop losses are measured on the laws each final verdict let through (keys
still `audit_sample`), one rung past the stop, with their denominators: a zero over none examined is not a zero.
Beside `the_record`: `gate_tree`, `lanes` (`research/lane_reading.py`), `law_ledger` (`research/law_ledger.py`, with
`research/degree_prediction.py`'s predicted mean degree), `given_probes_by_law`, the law scores (`every_chain.scores`)
and `d_s_shape` (d_s's running exponent, `measurements/d_s_shape.py`). **22** is every law's blocks, the gates' labels
and its control family (`every_law`; `metric_class`, the half-volume radius test); it ranks nothing.

## Outside the fleet

The replication harnesses grow graphs with no database, campaign or fleet, and write a reading under `var/readings/`
that a build commits to `docs/readings/` and judges against a criterion committed before the operator's run:
`tools/replication.py` (paper 1, a published model in its own configuration space and moves, read by the instrument's
probes), `tools/replication_conrady.py` (paper 2), `tools/replication_konopka.py` (paper 3). They share the engine's
energy and the instrument's readings, never its decisions; the papers are cited by arXiv id and version in
`docs/RESEARCH_METHOD.md`, "The papers read".

## What the fleet does that the sections above leave out

* **It finds its own size**, up to one worker per physical core: it aims at 75% host CPU, learns what one child costs
  the host, gives back what is over above 83%, and keeps the lesson for the next start. An explicit `--workers N`
  holds N: the ramp's floor and ceiling are both N (843; before, N was only where it started, its floor 1). Every simulation attempt
  records the host load around it, its moves per CPU second, its core and its die.
* **Its worker count changes while it runs** (846, `scheduling/worker_count.py`, its `tick` in the run loop, the
  System page's Workers panel, the Campaigns manage route's `fleet_workers`): a count the operator sets, from 1 to one
  a hardware thread within the connections the folder's PostgreSQL was sized for (`compute_worker_most`, never below
  the run's own ceiling), is the flag
  `compute_worker_target`, read by the supervisor every half second. The ramp stands aside while it is set. A lower
  count stops the executors above it at once: each is sent SIGTERM, its child saves the seed where it is and the rung
  goes back to the queue uncharged (`release_job`), a slot that stays resumes it from the save, and an executor that
  has not ended within the stop grace is killed. A higher count restarts held executors once they have ended and starts
  new ones. Cleared, the count goes back to the ramp and every held executor starts again. A pause and a resume keep
  the held ones held.
* **The loops rest**: a wait consumes every notification waiting, the controller wakes only for finished work and the
  pause switch, and a loop that finds nothing doubles its rest.
* **Nothing a run starts outlives it**: a process dies with its owner however the owner ends; `run` and `serve` drain
  on SIGTERM and SIGHUP; an archive carries its name only once verified.
* **A law left running with no work under a stop is decided again** at every start (`operations/stranded_laws.py`),
  for a folder an older build left so; since 786 a buy that makes no work is recorded with "decide again" itself.
* **An anonymous viewer's cost is bounded** (742). The web process streams files and the API's answers in 1 MiB
  pieces, with their length, at most two over 4 MiB of each kind (files, API answers) at once; a third is told 503
  with `Retry-After` (`services/web/streaming.py`). The API writes a MiB at a time too, waiting as long as the web
  does (60 s a write), so a large answer goes at its reader's pace. It reads and drops any body a request declares, so
  a kept-alive connection is never read out of step, and refuses one over 1 MB or without a length, closing the
  connection. In the API every read that walks the database or the disk waits for a dashboard database slot
  (`GSD_DASHBOARD_DB_CONCURRENCY`, 4) or answers 503 after 2 s, as the Campaigns routes do
  (`services/api/dashboard_limit.py`). The admin token is the run's (`services/api/admin_link.py`, 853): `GET
  /api/access` tells a page whether its link is this run's, an earlier run's or none, and refusals are counted and
  said on the services' console at most once a minute. A request without the admin token (or the study runner's
  internal one) sees a fault's where, when and first line, never its traceback or a worker's stderr, and not the
  services' console (`services/api/admin_view.py`); since 748 its 500 says only "internal server error" and its
  request id, whatever address it comes from (a proxy on the same host names no client), and a read writes nothing. A
  law's structure and the gate are computed once for many readers (748, `services/api/answer_cache.py`): an answer is
  kept by the database, the campaign and the law for 30 s, at most 64 of them, one computation for readers asking at
  once, and the gate's own writes drop its answers at once; the rows they read are written all the time, so the answer
  is withdrawn on its own age rather than keyed by them.
* **A landscape is built again only when what it reads was written** (829). Every page asks for the landscape's meta
  every 4 s, and from 16 s old (`DASHBOARD_LANDSCAPE_TTL_SECONDS`) a batch's landscape is due; before it starts
  `services/api/landscape_worker.py`, the API reads the landscape's inputs (`services/api/landscape_inputs.py`): the
  write counters PostgreSQL keeps for every table the landscape reads (`pg_stat_user_tables`, inserts, updates and
  deletes; `TABLES`) and a digest of the score boards in `control` (`law_scores:`), in one short query. The worker
  records them in the landscape's meta (`inputs`); when they are the same at the next look, the landscape is kept and
  its age reset, and no worker starts, so a finished study's open dashboard starts none. A write is seen within the
  statistics' flush (about 10 s at most), and so at the next look after it; the API's own writes (the workers' import
  records, its heartbeat) are in tables it does not watch. Inputs that cannot be read build the landscape as before.
  `tests/integration/test_the_landscape_s_inputs_postgres.py` holds `TABLES` to every table a landscape build reads.
* **One server holds a folder's data** (748). PostgreSQL's own lock (`postmaster.pid`) reads PID 1 in the server's
  namespace and takes any other PID 1 for stale, so the folder's lock is `instance/postgres/server.lock`: an exclusive
  `flock` the start takes and hands to the server, which holds it as long as it lives (`operations/server_lock.py`,
  `tools/postgres_instance.py`). The database watchdog (`services/db_watchdog.py`) reads the same lock and the log its
  record names.

## The blockers: where the tree has no room

Measured on this tree (bytes by `wc -c`, lines as `tests/unit/test_size_ratchet.py` counts them). Its bounds: 100 KiB
(102,400 bytes) a file and 400 lines a function, past which only the allowlisted go, each under its own ceiling. A
build that grows past one moves code out first or raises the bound and says so in its notes (`docs/ROADMAP.md`,
"Standing constraints").

* `main.py`: 128,030 of 130,000 bytes; `_cmd_run_locked` 640 of 655 lines. Move something out before adding
  (`operations/study_design.py` is the model).
* `engine/engine.py`: 63,161 bytes; `run_chain` 350 lines. A new engine concern goes in a module or helper of its own
  (`engine/summaries.py`, `engine/chains.py`, `_declared_start`), a new way of moving in a class beside the chain
  (`_LocalWalk`), the parity lane holding both engines.
* Full: `services/worker/main.py::run_one` (427 of 440), `services/analyzer/main.py::run_analysis_job` (384 of 400),
  `scheduling/campaign.py::_validate` (389 of 400).
* The repository: a method goes in the `db/repo_*.py` part whose tables it touches (largest `repo_analysis.py`, 57,100
  bytes), a new family of queries in a module of its own (`db/share_floor.py`).
* The API: `services/api/main.py` is the server and handler (74,234 bytes; `build_handler` 1,148 of 1,160 lines,
  `_get` 535 of 560), `host.py` the host's sensors, `fleet_snapshots.py` the fleet's and database's, `overview.py` the
  overview (65,956 bytes; `build_fast_overview` 507 of 520). A route goes through `services/api/readings_route.py`.
* `research/report_pipeline.py`: 54,783 bytes (`_collect_snapshot_rows` 318 lines).
* `reporting/study_reading.py` (41,706 bytes) and `reporting/study_bundle.py` (27,256): a new part goes in a module
  beside them (as `research/advice.py`, `reporting/gate_trees_page.py`), called once from each. The bundle is made in
  the API process after the fleet resumed, so a part that computes for minutes is measured once and committed, and a
  section that needs a campaign's whole report 28 (tens of MB) streams it (`ijson`, as `reporting/study_explorer` does).
* `tools/replication.py`: 45,645 bytes. A paper goes in a module of its own (`replication_conrady.py`, 39,440;
  `replication_konopka.py`, 24,743) that imports the harness's `instrument`, `parse_sizes`, `_meets` and
  `render_verdicts`, so every paper is read and judged the same way, with its own runs where its protocol is. The
  `instrument` reads the four probes with `estimators._measure_graph`, a few seconds a graph. Paper 3's chain
  (`replication_konopka.exchange_delta`, held equal to the whole recount by a test) is about 0.1 s a move at a cutoff
  of 20 on a random cubic graph, 7 ms at 16: a larger chain is hours, not a new method.
* JavaScript and HTML are outside the ratchet: `resources/ui/app.js` (243,346 bytes, `tests/ui/dashboard_smoke.js`), the
  law's page `resources/ui/candidate.html` (150,035, `tests/ui/candidate_smoke.js`, `tests/unit/test_two_chains.py`,
  `tests/unit/test_every_chain_is_shown_alike.py`) and `resources/explorer/explorer.js` (143,832,
  `tests/ui/explorer_check.js`, in the release lane, about a minute). A page's new part is a function beside its
  section's others (the law page's `tc`, `ss`, `fs`, `ec`, `cv`); a dashboard panel that reads one campaign names it (a
  `campaign-scope` span whose id joins `CAMPAIGN_SCOPE_IDS`).
* **A rule that reaches a running study.** A campaign is never edited, so a new rule reaches a study only through what
  its campaigns already declare (as `engine.policy.every_chain`) or through `RULES_REVISION` (649), whose move decides
  their held and parked laws again (`docs/DECISIONS.md`, "When the rules move"). A decision replays from its recorded
  inputs (`inputs.starts_reading`, `inputs.chain_order`) under its own revision (before 602, its own tie-break); a
  replay whose facts differ names each fact that differs with both values (745, `decisions/replay.facts_differ`). A next
  rule does one or the other and moves the freeze deliberately (`python3 tools/science_freeze.py --write`, saying so).
* **What the snapshot keeps is declared**: metrics lose `snapshot_rows.UNREAD_METRICS_SECTIONS` and keep of `descent`
  each chain's `final_energy` alone (742: the starts' reading's `lowest_energy` reads it), a job's spec keeps
  `snapshot_rows.JOB_SPEC_READ`, so a report reading a let-go path reads nothing. `tests/unit/test_report_audit.py`
  records what the reports read of real rows (the unread list empty and only shrinking);
  `tests/contract/test_snapshot_rows_drop_their_text.py` lists the modules that may name a let-go section. A report
  that starts reading the measurements joins `BUILT_BEFORE_THE_CHILDREN` (a test holds the two equal). A collector
  change that adds or drops a snapshot part writes the fixture again (`GSD_WRITE_REPORT_SNAPSHOT_FIXTURE=1`,
  `tests/integration/test_reports_read_no_raw_text_postgres.py`).
* **The streams are declared**: a rule the engine can write that `decisions/gates.STREAMS` does not declare, or one it
  writes nowhere, fails `tests/unit/test_gates_map_is_current.py`; a new gate, rule, refusal or evidence table redraws
  the map (`python3 tools/gates_map.py`).
* **What is pinned.** Every committed criterion, design and run of a past study, by its hash
  (`tests/fixtures/committed_readings.json`, `tests/unit/test_committed_readings_do_not_change.py`); and
  `research/degree_prediction.py` and `research/degree_prediction_extended.py`, held to their parsed code
  (`PARSED_AT_709` in `tests/unit/test_the_extended_predictor.py`): no change to the program without a new predictor.
* `research/phenotype_rebuild.py` builds extension rung states from an empty history: fix it before a report reads
  rebuilt phenotypes.
