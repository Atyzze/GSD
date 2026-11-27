# Lessons

The rules this project learned by shipping their opposite, each once, with the shortest pointer to its case and its
guard where it has one.

## What not to do, in short

The three that cost most often:

* **Do not ask the operator to run a query or a command of your own, and do not hand them a patch.** Ask for a bundle
  (what the database holds belongs in it) or an existing collector's zip ("Evidence"); they apply archives
  ("Releases").
* **Do not ship a fix for a fault you have not measured.** Reproduce it on the path it happens on first ("Diagnosis").
* **Do not change scoring or decision semantics, or fix a validity predicate, in a build about something else.** A
  validity predicate is the search's denominator: measure a change to it, write the numbers down, and change it only
  on the operator's decision.

And:

* Do not weaken a test to make a change fit: every guard that refused a change here was right. Reversing a standing call
  is a design change, not a test deleted.
* Do not compare a frozen spec with a raw one: freeze both sides first.
* Do not type out a shared set, or compare against a state the producer never emits: import the module's constant
  (`decisions.engine.WINDOW_TERMINATIONS`, `TERMINAL_CANDIDATE_STATES`, `INTERRUPTED_ATTEMPT_CLASSES`; a test fails on a
  literal list of states outside `domain/model.py`).
* Do not validate a stored fragment as though it were the whole: validate it as its reader sees it.
* Do not read a search through `head`: read the whole result, or count it first.
* Do not build a recommendation on an idea of the operator's before saying it back to them. Their "two sets of probes"
  (2026-11-12 10:42) meant a second set of four; the answer split the four into two pairs, recommended a verdict from
  their agreement, and both went: theirs as more than is needed, the answer's as not what they meant.

## Environments and sandboxes

The recipes are `docs/agent/ENVIRONMENT.md`.

* Try the bring-up before calling a lane impossible: one so recorded needed only host binaries for a blocked registry.
* Detach anything long and wait inside a call, never polling in quick succession: a background job dies with its call.
* The engine needs Python 3.12 and a current Rust; match `uv.lock` before comparing numbers (pip resolves older numpy
  and scipy, and a borderline fit is where it bites).
* A test that skips without host state never ran there: run the instrument tests where the table is.
* A script that starts the calibration's workers carries `if __name__ == "__main__":`; without it each worker runs the
  script again and the pool breaks (766).
* A keypress is rehearsed on a terminal that answers it: a script started detached hands "ignore Ctrl-C" down to all it
  runs, so the first rehearsal of 767's command ran on through its Ctrl-C with no word of why. On a pseudo-terminal,
  the default is put back before the command starts (`docs/agent/ENVIRONMENT.md`, section 9).
* The sandbox's tests stop at about 65,536 nodes (the operator, 2026-11-12 22:01): a million nodes is the host's. The
  suite's admission cannot place a million-node cell in the sandbox's 7.8 GiB at all (767: one priced 8.7 GiB from its
  family's smaller cells).
* Read a file's outline before the file (`grep -n "^def "`, `sed -n` a range): 771 printed four whole test files, 30
  KB, to read ten lines of each.
* Grep code, not committed readings: a version number grepped across every `.json` printed 846 KB of a reading whose
  digits held it (782); name the files a pin lives in, or add `--include=*.py` and `| head`.
* Read the gate's exit from the gate, not from `tail` (append `EXIT $?` to the log); stop a run by the PID it wrote
  (`pkill -f` can match its own shell); after an interrupted lane, check `pgrep -x btop`.
* The bundled PostgreSQL refuses root ("refusing root execution"): where the shell is root, the gate and every
  database test run as the folder's own user with the prefix file (`runuser -u <user> -- bash -c '. <prefix>; ...'`).
  Run as root they skip as "folder-local PostgreSQL is unavailable", which `GSD_REQUIRE_NATIVE_POSTGRES_TESTS=1`
  turns into a failure (900).

## Releases

* A page build fails on one word: `tests/contract/test_the_operator_is_they.py` reads every page for a gendered pronoun,
  of anyone, a reader the operator quotes included (856's ROADMAP failed its gate on one).
* A change to what the landscape carries moves its inputs' contract (`landscape_inputs.CONTRACT`), or a finished
  campaign, whose tables no longer move, keeps the landscape it had (859); a flag the landscape reads goes into
  `WATCHED_FLAGS`, or an idle folder's landscape never sees it move (857).
* The fast lane is not fast for a build that spends a number: `BUILD_NUMBER`, `pyproject.toml` and `uv.lock` count
  as changed, so it takes nearly every test file (456 at 855, with the PostgreSQL slices). Time it as the full lane.
* Two contexts on one repository spend the same number: whoever's pull request is merged second renumbers and runs
  the gate again (`CLAUDE.md`, 855).
* Only `package_release.py` makes an archive; write the notes for the number it assigns.
* The release spends the number itself: a build is made with `BUILD_NUMBER` at the last release. Set by hand to the
  new number, 900's first gate ran as 901 and failed on its own pages, 25 minutes spent.
* A test never quotes the operator either: who decided a rule and when lives in `docs/HISTORY.md` and the notes, and
  `tests/contract/test_the_operator_s_words_live_in_the_documents.py` reads every test's strings (900's first gate
  failed on one assertion's message).
* A page fixed after the gate, when `main` moved under its pull request (900, 901), moves
  `tests/fixtures/build_files.json`: write it again (`tools/test_suite.write_build_files`) and run the page tests.
  The archive is the gate's tree; the pull request adds the page commit and its description says so.
* A build made on an open pull request is opened against `main` and says to merge the one under it first; until then
  its diff shows both (899 on 898).
* A killed release is recovered by the next run's journal, never by editing `BUILD_NUMBER`.
* The first PostgreSQL bootstrap after a sandbox idles fails every lane started together, so the lanes warm it alone
  first (`tools/test_suite.warm_postgres`, one integration test, twice at most; 738). Before 738 it was a step by hand.
* A patch is not a delivery: it passes no gate and carries no number. When the gate will not run, fix what stops it.

## Host state

* With a simulation on every hardware thread the API waits for CPU and Home goes stale (2026-11-24 18:26: 32 of 32
  slots, the round trip 463 s, the status route answering 503). A faster refresh asks more of the process that is
  starved; CPUs kept for the system free it (856's Workload panel).
* One key over every probe makes every probe change a full recalibration (the table's 2,584 cells, 7 h 10 min on 31
  workers): a reading is keyed by the code that made it, by group, and filed once (`calibration/ledger.py`, 855).
* The clean start is three paths, together, or a folder locks itself out of its database and the next move destroys a
  campaign.
* The calibration table and the compiler are host state: an orphaned table is an invisible recompute; rustup's
  toolchain is the project's own, since a host package can break and show only in a new folder.
* A tree reads nothing outside itself (`tests/unit/test_a_tree_reads_nothing_outside_itself.py`): check a path rule
  against the operator's paths, not the sandbox's.
* A derived file says what it came from (`tests/unit/test_derived_files_say_what_they_came_from.py`).
* `schema.sql` is applied once and checksummed whole: no in-place upgrade; a new campaign status strands every
  database.
* Know a process, or a study, by what it holds or stamped (`GSD_CHILD_KIND`, `GSD_PROJECT_ROOT`;
  `operations/study_record.py`), never by a path or a name match; name it by `/proc/<pid>/exe` before explaining it
  (the bundled database runs as `gsd-postgres`).

## Where defects cluster

* Paint paths: execute the renderer and assert what it draws; a render test that renders nothing, or a source-text
  assertion, covers nothing.
* SQL only the database rejects: test a repository method on a live database, a per-tick query at the operator's scale
  (`tests/integration/test_overview_scales_postgres.py`).
* Fields nobody writes or reads: a key storage never held reads as nulls that look like nothing to say.
* A clean-up's rule knows every campaign that buys past its spec: a start read the N-push's probes beyond its copied
  spec's 8 seeds as a crash's leftovers and cancelled 8 of G73's 16 at 262,144 (897).
* Bought is not grown: the fleet ladder counted a seed bought as a graph grown, so 1,048,576 read 64 with none
  finished, and a seed's rough time divided by 3 seeds where 16 had run (898).
* A lever built at both ends works once it runs through the middle
  (`tests/unit/test_the_given_chain_starts_at_the_answer.py`).
* One idea, one name, one function, one rate, one number in one place: fold a second mechanism into the first with a
  knob (`decisions/gates.py`); check a new name against those in use.
* An action reported as done must have done it: a recorded decision carries the count of what it changed.
* A value something sets while a study runs has one reader function, and every page and report takes it (798): 796
  made the windows live for the decider and job creation, and nine readers kept building the policy from the design,
  showing the priors while the seeds ran on the live windows. When a value
  becomes live, grep every reader of the old one in the same build, and test them all against a moved value.
* An order a mapping got from its evidence is no order: what is stored comes back with its keys sorted, so a reason
  joined in arrival order does not replay; name things in a declared order (745, `starts_rule.in_start_order`).
* A hook outside its function runs once, an edit in the wrong block moves an event: anchor on a block's end, read it.
* A limit is checked on its own stride, sized by time, where nothing else happens; bound the work, not only the loop.
* Waiting by design is not stuck: count held beside stranded (`held_sql`), and set-aside work as waiting, or a short
  backoff reads as an empty queue.
* Bound the rows a pass is for, after the filter that decides relevance, not the first rows.
* A resume must reach the work where it stands, not only at boundaries.
* Read no history under a lock and put no minutes-long work between two readings of the clock: work the lock does not
  protect times out the claims behind it (`tests/integration/test_claim_lock_postgres.py`).
* A sweep that retries its head never reaches its tail: walk a cursor.
* A rule change and its `RULES_REVISION` go in one commit.
* A guard is as wide as the predicate, not the case behind it; a gate never run on the README's host is untested
  there.
* Assert the rule true now: a negative ratchet goes the second time its subject changes, named in the notes.
* Delete a compatibility shim with the rename it covered, and test producer and consumer by name.
* A renaming is held by what the code puts out, not by its diff: two names folded into one overwrote a field of the
  same record with every test green, and only the outputs of the build before, read through the map of names, showed
  it (756, `tools/outputs_of_a_law.py --against`). A word with several senses is renamed by the list of its uses,
  never by the word. A name can be part of a draw or a key of a committed file: the let-through hashes its gate's name
  and the committed salt ledger is keyed by it, so a renamed gate would have let other laws through and lost its record
  (773). Read what a name feeds before renaming it.
* Every check runs in the lane (`tests/scientific/test_instrument_reads_known_objects.py`); a check removed is named
  in the notes; a tool's tests run the tool, its `main` included.
* An argument list is a contract: run the subprocess both ways and count the bytes; seed a config from the user's own.
* Number or drawing? Test for absence before coercing (`+null` and `+''` are 0), run the formatter in the test, and
  make a collector ask the thing it names.
* Do not score a thing whose answer is known, or read a calibration table as a prediction (the operator: "the scoring
  mechanism is meant to surface interesting cases within a unknown group of graphs"; "the atlas just says how our
  probes behave on known objects").
* A criterion that fires where its premise fails generates findings, and a threshold is a measurement or a comment
  (`fit_ds`'s AICc margin is set from null families, `tools/calibrate_margins.py`).
* A report describes the arithmetic it publishes: a replaced contract's prose is part of the replacement.
* A list of files typed by hand beside a closure goes stale. At 758 the instrument's fingerprint named five files and
  lacked the box-covering probe, so a change to it would have left the committed response looking current; three tests
  each typed the calibration key's files again. Derive the list, or hold it by one test that says why each file is in
  it.

## Evidence

* Say where a number was measured before saying what it shows: 856's context credited SMT's gain to the work
  unit's fit, which is 288 seeds of the sandbox and never read SMT; the gain was measured by running 173 on 16, 23 and
  32 slots (843), and the operator decided by it (2026-11-22 15:38).
* A probe that reads the spectrum alone cannot see where the eigenvectors sit (855): `d_s` reads the Sierpinski
  gasket and a uniform random tree as 1.37 and 1.29, and a quantum walk does not spread on either (its return
  exponent 0.00 to 0.03), while the two agree on the ring and the square torus. A space that diffuses need not carry
  a wave.
* Starts that agree on d and the mean degree are not yet one state (2026-11-24, H31 at 4,096, seed 1, its own 63
  sweeps): from empty and from the cubic torus the mean degree is 22.4 and 22.7, but the triangles a node 6.5 and
  12.6 and the squares a node 50 and 142, the cubic start still remembered. Both are within four steps of the whole
  graph, as a random graph of the same degrees is (balls of 24, 450, 3,701 against 24, 480, 3,800), and a quantum
  walk reads them as it reads that random graph. Compare a law's state with a degree-matched random graph before
  reading a dimension in it.
* Ask for a bundle, never a query: look in `tools/` for a collector; write one, naming its command, only for live
  processes a quiet report cannot see.
* Find the code that writes a log line's exact text before naming its statement.
* A log where the failure is cannot describe it: console lines go to the folder's disk; a failed write is only
  counted.
* A reading to be compared later is code, its output kept in `docs/readings/`: a comparison needs the same arithmetic
  twice, and a determinism is known only once a rerun is compared.
* Two trees' outputs are held to each other value for value; a comparer that renames one side only shows a name both
  keep as moved (774: sixteen certificate failures in report 23, which neither tree had changed).
* A handover is evidence, not instruction: check the build number and what launches the process; read it cold first.
* A promise about the next bundle is checked in a bundle the tree can read, or its field is added in the same build.
* Every build that reads data or states a claim has a second reader before the gate, an agent that did not write it; a
  claim about one law is checked against every reading of it, its marks included.
* Do not state a reason that was not computed: name a stop by its own record's numbers (in the bundle first); a cause
  read from the one code path that could produce it is "the signature of" until the row's own error says.
* The supervisor's log is part of a bundle's reading (`tools/fleet_reading.py`), so rates are per hour the fleet ran.
* A verdict has three answers: with no outcome or laws on one side there is nothing to measure; an outcome on one side
  only is a ratio past any bound, not an undefined one.
* A bundle's host load is the pause that made it, not the running state (2026-11-06: 54 GB read as other programs).
* Do not project a pace from two bundles' states: count the decisions between them by name, and the attempts an hour
  (2026-11-06: "seven finished" was seven reached, two decided).
* What the code does is said after it is read, one reading a claim. On 2026-11-10 two things were said of a running study
  before the code was read and taken back the same evening; on 2026-11-11 two files were named as read by the decision engine, one
  had been read, and the other, read afterwards, feeds a report only. A sentence that makes two claims needs two
  readings.

* **Read the code before the plan.** A plan's sentence about the code is a claim like any other: 774's plan said the
  chain from empty keeps snapshots "since 5.2 reads none", and the activity's late edge Jaccard, which classes a rung
  frozen and reaches a decision, reads the last one (775 kept them). The same plan took a stream's label for something
  that changes with the engines anyway; a new label draws every chain again. Before a step of a plan, grep for every
  reader of what it removes or renames.
* **A new name in the engine's loop is checked against its closures.** 780 named the late change's first move
  `late_from` inside `engine.run_chain`, where the move accounting's `tally` closure already read a `late_from` of its
  own; every late count moved, and only `tools/outputs_of_a_law.py --against` showed it, before any test. Run
  `--against` after each engine step, not at the end.
* A test that builds an envelope by hand pins the envelope's layout, not what it tests: 775 changed the layout and
  touched 47 test files, most of them through such builders. Build test envelopes through one helper
  (`tests/support/chains.py`) and read them through `domain/chain_list.py`.

* **A structural word is a number first** (853): 851 called the laws that grow from the twins "loops carrying trees"
  while the same bundle's rungs table said every node of the loops was in the 2-core. Before naming a structure
  (tree, loop, string, clique, small world), read the number that says it: the 2-core share, the extra edges over a
  ring, the clustering, the reach against a random graph's of the same degree.
* **Starts that agree may only have forgotten** (854): H31 was read for two days as starts agreeing on d 3.4 to 3.5;
  its reach grew from 3 to 4 steps over sixteen times the nodes, a small world's. Read how distances grow with N before
  calling an agreement a space.
* **A positive control that starts at its answer says nothing of the search** (854): the controls' criterion expected
  "from empty no finite dimension", and the roadmap said such a study "cannot tell a search that finds none from one
  that cannot get there", yet the survey ran on; an outside review measured the trap in a day (P1 at 68% to 81% of its
  lattice's energy). Run every positive control from the start the survey judges by, and measure how far it gets.
* **A criterion that fails is reported as failed, even when its rule is adopted** (854): the score of 848, the starts'
  reading (8 of 11) and the structure rule are each in use by the operator's decision and each failed by its own rule;
  the paper lists them as fails.
* **An early call is as safe as its kind** (854): the still call held on every chain in both baseline bundles; the
  frozen call stopped short of a law that changed at 16,384 (de7ab4a85198). Judge each kind's early call on its own.
* **A report that does not reproduce is made visible, not argued** (853): a stale admin link said to work was tried on
  a real fleet stopped three ways and refused every time; the build then made the page say which link it holds, and
  the gate holds the restart.

## Documents

* Name a planned build by what it makes, and give it its number when it is made: two builds made in between in one
  evening (858, 859) each moved every number of the plan on five pages.
* Give each fact one home (`docs/agent/HANDOFF.md` names them); the read-first set has a budget
  (`tests/unit/test_the_read_first_set_is_small.py`), and the newest notes are in it: 771's first notes carried 9 KB of
  file lists and broke it. A list goes to the file that holds it (a test's own list) and the notes point there.
* A build that removes code keeps the words a decision records and a report prints until the build whose pilot may
  differ by names (771 kept two reasons and a gate's description for 773), and keeps a guard that names nothing it
  removes, saying so (771 kept two refusals its page had listed).
* Documents drift invisibly between consolidations: consolidate about every ten builds, when the work allows.
* What lives only in a reply is lost at the next summary: write an open item into `docs/ROADMAP.md` in the same turn.
* A number said or written is a copy of its reading: copy it from its file that turn, never memory, and hold it by a
  check the gate runs (`tools/verify_claims.py`, `research/claim_ledger.py`,
  `tests/unit/test_the_findings_manifest.py`), naming its home exactly. A number shown answers the question asked now,
  and gives way when the question changes.
* Describe the operator's work from their account, say where a description comes from, name a thing for what it does.

## Scale, processes and predicates

* A process group is not a family: after a Ctrl-C, children in their own sessions can compute for hours.
* A keypress reaches every process of the foreground group, so each worker of a pool answers Ctrl-C with a traceback
  of its own unless it is born deaf to it: block the signal in the thread that spawns the workers, after Python's
  resource tracker is running, since the tracker's first start unblocks SIGINT and SIGTERM in the thread that starts
  it (767, `docs/TOOLS.md`, `tools/probe_calibration.py`).
* A worker of Python's process pool never learns that its parent is gone: a run that a signal can end ends its own
  workers on the way out (767: two workers idle ten minutes after their run was killed).
* A process is ready when it can take the next thing it is sent, not when it has started: PID 1 of a namespace drops
  a signal it has no handler for, and a detached lane inherits SIGINT ignored. A test's stand-in says it is up only
  after its handler stands (750: one failure in the full lane, 10 of 11 runs under load).
* An order that serves the cheapest first starves the scarcest, and a large request never fits a pool small ones keep
  filling: reserve for what the general order will not reach, and hold room until it fits, with a limit.
* A cap is not a share: a declared division is what the scheduler converges on; a rank is one line for every campaign,
  and in a study a blank share is an equal part.
* A request the proxy abandoned is still running: time the server's phases.
* A cache shorter than its poll is a rebuild per poll; reports skew wall-clock windows, so they wait for a quiet
  fleet.
* Do not read a list once at boot and call it live.
* Schedule the next run from when the last one ended, not from a `now` read before the work.
* A paused fleet tests a background loop: what burns CPU then is overhead; idle loops back off
  (`cadence.idle_backoff`).
* Fixed points held across batches only if a group is closed in every batch: within one batch a later number means
  the earlier ones are drawn, across batches it does not (831's study-wide counters fed a group a slower batch had not
  finished drawing, and kept the ledger when members joined; the second reader found it before delivery, 832 fixed it).
* Test a switch on the campaigns it is for: 829's auto extend was tested on a bounded campaign and hooked to the
  completion step, which a study's batches, continuous campaigns, never reach, so on 171 it could not act; read from
  171's bundle (`api_samples/campaigns.json`, `"mode": "continuous"`) and made at 830 to read the page's **done**,
  tested on the batch spec a study design makes (`study_design.campaign_spec`).
* A cache that expires on its age rebuilds an idle folder for ever: the dashboard's landscape was built again every
  16 s while a tab stayed open on a study finished hours before, a core at 100% for 10 to 13 s a batch (829, the
  operator's btop). A cache is rebuilt when what it reads was written (`services/api/landscape_inputs.py`), and the
  test that names what it reads runs the build.
* Check where a controller starts against where it aims; measure the operating point; give back once, then wait.
* A phase that says finished is not a process that has: wait for the artifact the next step reads, with a limit.
* Test a mechanism in the regime it runs in, with the settings the fleet gives it, and compare candidates there.
* A threaded process cannot join a user namespace, and BLAS starts threads in C: count `/proc/self/task`; join first,
  import after.
* psutil's `cpu_percent(interval=None)` counts from this thread's last call: the sampler keeps its own window
  (`observability/host_resources.cpu_percent_sampled`).
* A test that sets a clock owns every state compared with it (`observability/kappa_seconds._LAST_SCAN`,
  `tests/integration/test_kappa_seconds_postgres.py`).

## Diagnosis

* Before fixing, find the observation only one cause can produce: run the same thing on each side of the boundary.
* Disproving evidence reads as noise: start from why the working case worked; a component names its own conditions
  (`why_no_watts`).
* State the mechanism you measured: its folklore version points at the same fix and survives nothing else.
* A reading with no age is not a reading: a cached value is withdrawn on its own age.
* A fix that removes a retry can uncover what the retry was hiding.

## The search space and its grid

* A term set is not an orthogonal basis: `sum_v (d_v - k)^2 = sum_v d_v^2 - 4kE + Nk^2` and `wedge = 1/2 sum_v d_v^2 -
  E`, so `degree_anchor` and `wedge_count` are each `degree_square_sum + edge_count` (`effective_basis` reduces both;
  state the reduction). `degree_anchor` is the operator's first Hamiltonian less its edge term: ask what they built.
* Most operators cannot carry a law alone: admission asks the real drawer (`blind_law`, `effective_basis`).
* Rewarding `sum_v d_v^2` is the degenerate two-star model (Strauss 1986; Park and Newman 2004), near-empty or
  near-complete: want the penalty sign; `blind._bounded_below` does not cover the bistable regime.
* An admission check runs against every campaign the folder holds: on a frozen field it is a creation-time check
  (`_whitelist_problems(spec, stored=)`) or none.
* A grid bounds a campaign as firmly as its term set: ask what bounded an empty search (a narrow space, `surveyed`, is
  a result), and whether a limit that matches your configuration's shape is the physics' at all.
* Ask how big the space is, not whether a draw succeeds or a ratio: Good-Turing coverage counts laws seen once
  (`space_advice`).
* Log-spacing is the default: a linear draw over `[0.01, 100]` puts 99.99% of its mass above a hundredth of the range;
  a range per term is `grid.per_term`.
* Ask why a law works at all: `beta*c*(4<d> + 2) = ln(N/<d>)`, so the mean degree drifts up the ladder unless a
  positive `edge_count` on `log_N` holds it.
* A deterministic outcome with a poor fit lacks a function nobody wrote down, not data: the energy per node predicted
  the mean degree at R^2 0.99 where a fitted model reached 0.56.

## Pages, controls and settings

* A box added to a row of fixed height takes its height from the boxes already there: 857 put the Filters panel in
  the landscape's row and the plot lost 88 to 198 px at its bottom, on the operator's screen. The stylesheet's checks
  did their arithmetic without the new box; a page is measured where it is drawn (`tests/ui/hero_check.js`, 859).
* A rule that keeps a long list short hides what a short one holds: the Top 100 took a law that reads nothing from
  empty only if it scored, and left out two of the standing controls' five (859). Fill a list's empty places.
* A field added to every point is added where every kind of point is made: the lattice starts' points were made apart
  from the list `marked` walked, and read "not read yet" (859).
* A switch that decides whether half an experiment runs lives on the campaign's row, not in an environment variable.
* One state, one name; one word, one subject; one meaning a setting (it loses the rest one at a time and keeps its
  name), read in one place.
* A slow operation that says nothing reads as a broken one: say what it preserves.
* No display state decides a permission (`_controls`).
* Do not call the operator's own decision a warning, or draw a control that cannot be pressed.
* Do not keep a column that says the same on every row, or one the next column prints in full.
* A table that negotiates its widths cuts its headers: declare a `colgroup` with `table-layout:fixed`, no column below
  its words (`tests/ui/layout_check.js`).
* A page built for one kind of campaign makes the next look wrong: check a recipe against the drawer first.
* A setting replaced is lost to every reader of it: `grep` each and give it the new source (`study_design.axes_of`).
* A page's number read on a path that runs only while work is live vanishes when the fleet ends, and a finished fleet
  is what the operator reads: 770's ladder read the runs' durations only while a law was alive, so a finished pilot's
  ladder lost 135.6 hours of evolution and showed ptime 100% (776). Test a page on a fleet with nothing left alive.
* A list drawn from one view's rows inherits that view's filter: the top list was built from the landscape's points,
  which are the chain from empty's, and hid 26 of 29 scored laws, all 24 at zero temperature among them (776). Rank a
  list from what scores it, and say on a chart which chain it draws.
* A cell with no value is a dash, never a zero: `Number(null)` is 0 in JavaScript, so a missing band read "0.0s" (776).
* A refusal's remedy is one the code performs: 634's told the operator to stop a fleet whose holder no stop ever
  ended, and they had (778). Test the remedy a message names, not only that the message is said.
* A redraw on a timer closes whatever the pointer rests on: the ladder, the lists and the cards were drawn again every
  four seconds and took their tooltips with them, while two panels already waited (781). Every panel redrawn on a tick
  waits for the pointer to move (`deferrableRedraw`); a new panel joins it.
* A test fixture that leaves out what the rule reads passes the rule by accident: the given chain of the tests' pairs
  had no random start, so no pair had twins until 781 gave it one (`tests/support/chains.pair`).

## Diagrams and exports (the operator's rules)

`tools/check_svg.py` checks them, and `tests/unit/test_svg_portability.py` runs it on every SVG under `docs/`. Valid
is not portable: Qt and Gwenview are roughly SVG Tiny 1.2 and skip in silence what they do not support. An SVG that
must work outside a browser:

* is strict XML (every tag closed, `<br/>`; `xml.dom.minidom.parse` passes): a viewer stops at the first error;
* has no `<foreignObject>` (browsers only; in Mermaid 11, `htmlLabels: false` goes at the top of the configuration,
  not under `flowchart` alone), no scripts and no markers (arrowheads as paths);
* has one `<text>` per line with numeric `x`, `y` and a `text-anchor`, anchored at its centre since fonts are
  substituted (Qt ignores `tspan` x and y, `dy` chains, `em` offsets and `dominant-baseline`), or paths;
* sets `fill`, `stroke`, `font-family` and `font-size` on each element: CSS outside browsers is partial.

Render it in Qt with `tools/check_svg.py <file> --render out.png`; `tools/diagrams/export_mermaid.js` makes such a
file from Mermaid (`docs/diagrams/rung_flow.svg`).

## Memory, and what outlives its owner

* A budget is set against what it protects (available memory less a floor), not a prediction; growth is measured from
  what is held now, and a reservation already spent is not charged again.
* Count a row by what it holds, not by its status: admission read every leased seed as a running child, the one being
  admitted among them, so a seed paid for itself twice; and a refusal that ends the worker's turn idles it while work
  that fits waits behind (747).
* A process meant to outlive its owner needs a way to be found, a rule for when it is unwanted, and a report: it
  writes only into its own folder and dies with its run, the next start looks for what a gone folder left
  (`operations/leftovers.py`), and a loop that makes its own directory brings a deleted folder back.
* Do not keep in RAM what has no ceiling: bound the scratch, overflow to disk, check room before writing, write inside
  the `try` that gives work back, and give infrastructure failure its own class (`no_space_left`, exit 74).
* A path is part of a test's input: a check that excludes paths with a word fails under a directory so named.
* Price from the whole measurement and reserve for the peaks that can coincide, not for all (a cell peaks in its last
  fifth); charge what was measured, and convert in place rather than copy (`sanitize_json_in_place`).
* When prediction cannot be exact, make being wrong cheap: admit on the likely case and pause the youngest climbing
  cell; a policy chosen on a simulation is chosen on its inputs (`tests/support/pacing_sim.py`).
* Weigh a one-time measurement against how often it is paid (the operator: "I see it as an investment").
* One host, one scheduler: cells on the operator's host run through the suite's workers, priced from what they hold.
* A forked child copies every page its collector walks: `gc.freeze()` first, and build the reports that read every
  measurement before the fork (`BUILT_BEFORE_THE_CHILDREN`).
* A state read back is not the state written: JSON gives a list where the engine keeps a tuple, and an object of its
  own for every number, so a resumed seed's checkpoint held about 1.4 times the engine's own; the child also kept it
  for the whole run beside the engine's graph. A resumed seed held about twice a fresh one's memory from 873 to 900:
  decode as the engine keeps it, and let go of what was handed in once it is used (901).
* Frozen code bounds where a fix goes: the run (`scaleflow/`) holds its `resume` for its whole call, so the caller,
  which is not frozen, empties what it handed in (901).

## Counting what could be judged

* Do not count an interruption as a failure: what the fleet ended (pauses, shutdowns, the memory floor, fenced leases,
  dead workers, a full disk) is given back once per rung and says nothing about the law.
* A missing reading is not a failed one: a rule built on "not X" inherits every way X can be absent
  (`decisions/engine._looks`).
* A rule's second chance must be something that happens: say how often on a live campaign.
* A threshold for "stopped" needs a scale the process cannot outrun: rest is measured against the chain's own descent.
* Count what runs, not what has not been collected yet; a fake ends the way the real thing does.
* A step that makes what is missing remembers what the operator deleted.
* Keep what the readers read, and record what they read (`tools/report_audit.py`).

## References, readings and criteria

* Known answers that only confirm pass a rule that cannot fail: the score's margins were judged on structures whose
  probes all agree, so it gave a strip 32 nodes wide a dimension its reach does not grow by, and settled seeds still
  relaxing at their cap (845, read on 174's laws). Build the cases that should fool a rule (strips, tubes, subdivided
  trees, a giant piece of half the graph) beside the ones it should pass, and commit what each must read first.
* A prediction about a fooling case is itself a claim about the case, and can be the thing that is wrong: criterion 4
  said no strip may settle, and a strip 16 wide at 65,536 nodes is a line, which the probes read and the reach agrees
  with; criterion 5 said no tree is a ring, and a random tree's spectral dimension is 4/3 (846). Work out what the
  structure is at the sizes read before writing what it must read; a miss is kept as it was judged either way, and
  the rule it gates stays out of force until a criterion written fresh passes.
* A reading that mends how data is read replays every decision unchanged: the faults found in 845 were all in what
  reads the instrument, none in what it collects (the operator, 2026-11-23 11:21), so a build that changes a reading
  says which outputs moved and that no decision did.

* A flat zero or a flat all in a reading is a question: could it have been predicted? A pilot reported "none the honeycomb"
  for several builds before the operator asked why that start (2026-11-10 19:54), and the answer was a calculation of
  minutes: no term tells the honeycomb from a random 3-regular graph. Ask it when the zero is first read, and offer it
  in a line.
* Read a reference through the same rule on the same rungs first (a shape change reads as an exponent), and say with
  numbers what a new reference object moves.
* A build's changes are made on the tree it delivers (797): a branch kept outside the tree could not be handed on, and
  the stable build was made again on 796 from its description.
* A criterion is written after the sandbox, before the fleet (`before_any_fleet_run`), and never revised after its run;
  pass the whole lane before committing it (a lint fix moves its hash). Controls are made only where a study is.
* Before taking a law as a control, list what else has the answer's energy, and build and read those shapes.
* A start at a degree the law does not hold tests something else: the given chain starts at the degree held.
* A change that leaves a law alone can still move every run: retake a criterion's readings on the shipped code; a shape
  read once is a sample (read three seeds near a balance).
* A count resting on one reading of a dimension counts its errors: a chain from empty holds where gap and walk agree.
* A model built from a paper's words is checked against what the paper's space cannot do.
* A probe's ceiling draws a shape: draw what it can read at that N first, and a ceiling only
  where 100 laws or more read (`reporting/study_explorer.CEILING_MIN_LAWS`).
* A threshold counts its near side: say how much lies just past it. A judgement says first how many predictions the run
  answers, then what held.
* A fit says what it rests on: 30 readings, 10 a coefficient, 5% of the axis, drawn over the middle 90%.
* Try a reading on what fools it, its exact answers and its null on as many laws as it will meet
  (`starts_known_answers_criterion.json`), before it ranks or a criterion rests on it; a rule changed until its known answers
  pass is run on seeds and a size it was not changed on, its misses kept.
* A criterion's own design is tried before it is committed, on a seed it will not use: a coupling set by its energy's
  spread put five laws' whole weight on one graph, where a count reads nothing (753,
  `boltzmann_known_answers_criterion.json`); a criterion that cannot read a cell is kept as read and followed by one
  that can, committed before its run.
* A let-through is a price only once its next size runs: read the queue a plan waits in (report 25's ladder).
* Dividing the fleet divides every queue between a seed and its reading: a share must serve what arrives in each.
* A rule's tie-break is part of every decision it took: the replay reads the decision's revision
  (`every_chain.STRONGER_FIRST_FROM`), and an order that decides is stored as a list (`inputs.chain_order`).
* Name what a class reads before what it means: a fate is a shape only where the shape's measures are read against the
  start's at the same sizes. One size is no space, and a group is not a piece: read a geometry across two sizes, one
  piece first.
* Ask what the energy says of the shape before reading a hold as a preference: an energy equal on many wirings holds at
  zero temperature until the moves wander off, a finding about the run.
* Ask what a term can see change before what it does; a comparison against an exact zero is decided by rounding.
* Test what the physics guarantees, not only engine agreement: relabelling, an energy's zero and a coupling's scale
  against the temperature are symmetries, and an exactly neutral move is taken at zero temperature
  (`tests/scientific/test_engine_exact_neutral.py`).
* A search for what was missed covers every axis on data it did not see: control false discoveries over all, keep what
  the other half of the campaigns repeats, and write the new as predictions first (`tools/pattern_scan.py`,
  `tools/sample_reading.py`).
* A test against theory is as good as its tolerance: one widened until the probe passes tells nothing. The calibration
  table held d_B within 1.15 of 3 on a cubic lattice, so a reading of 1.9 was "confirmed" (759). Set a tolerance by a
  rule written before the number is seen, and let the probe refuse where it cannot meet it.
* Read every probe on every structure a study is given, at every size, before the study: the body-centred and
  face-centred cubic starts were built two builds before any probe but d_s had read them, and the first reading found
  one at 0.22 (759).
* A judged set that holds only the easy refusals passes a probe that reads the hard ones. 760's held random graphs of
  mean degree 3 and 4 from 4,096 nodes, every one refused, while the mended d_B read a binary tree and random graphs of
  mean degree 2 as a dimension near 2: 20 of 168 graphs of the calibration table's own families, found by the table's
  gate after the judgement. Put every family the instrument must refuse into the judged set, at its sparsest and its
  smallest.
* A probe confirmed on lattices is confirmed on lattices. d_s read every lattice and Sierpinski fractal right for the
  whole project and reads a random geometric graph in the plane as 1.44 (761): its window is the calmest third of its
  running slope, a lattice's slope is flat, and where a slope dips and climbs the calmest stretch is the bottom of the
  dip. Judge every probe on irregular graphs of known dimension before anything else is built on it, since what a law
  grows is irregular.
* A window that ends where a curve is steepest reads the short scale of anything thicker than a line. d_V's window ends
  at the steepest radius, exact on a torus, where the slope climbs to its value and falls only at saturation; on a strip
  four around the steepest radius is the second and nothing is read, on a slab four thick d_V reads 2.50, on a random
  geometric plane 2.10 to 2.15 from 10 to 21 of its 64 radii (762). Hold a probe to structures whose slope comes down to
  its value as well as up: a strip, a slab, an open patch.
* A rule keyed to a symptom refuses what merely shares it. "No probe reads where the balls cannot be tested" took a
  window too short to test as its sign and refused a plain strip, whose window is short because of where it is cut;
  keyed to what was meant, a graph whose balls hold most of it within four steps, it refuses the wrong readings it was
  made for and no line (762).
* Two populations that touch have no threshold between them. The rise of the balls' exponent across the window separates
  a lattice with shortcuts seven spacings across (0.35 or more on every design draw) from every geometry of the design
  set (0.32 at most), and not one five or six spacings across (0.31 to 0.36): the limit, a third, was set where no
  geometry is lost, and what it lets through is said (762).
* A median of slopes lands on one side of a curve that alternates (the kagome lattice's ball, 761), and a window cut at
  an extreme of a noisy curve moves with the sample. Fit a line through a window set by what the curve is, not by where
  it is calmest or steepest.
* Whether a graph has a dimension is asked of its balls, once, and not of each probe's own curve: over the few radii a
  cover has, the boxes of a sparse random graph fall like a power, and the balls, with more radii and no cover's noise,
  do not (760).
* A dimension is the same from every node. A tree with hubs passed every test made on its mean ball, whose bend at
  saturation reads as a power, and was read by three probes at 65,536 nodes; the spread of the sources' own balls parts
  it from every geometry tried (763). Before fitting a curve averaged over sources, ask whether the sources agree.
* Hold a reading to what its own window gives on the exact curve, not to the answer at infinity. d_w on the 4D start at
  65,536 nodes read 1.85 and was counted a miss for 2 in 762; the simple walk's exact mean square distance, read through
  the probe's own window of five times, gives 1.89 (763): the criterion was wrong about the scale. Where every node is
  alike the exact curve costs seconds; compute it before a band is set.
* An error from a bootstrap that keeps a window the data chose understates wherever that window moves. d_V's bootstrap
  resampled its sources and kept the window; on the fractals, where the window's end moves with the sources, the seeds
  lay two to four times further apart than the error said (763). Every replicate makes every choice the reading made.
* A target written before a design is a guess, and the notes say which were met. 762's page asked that every lattice
  stay within 0.001 and the carpet no worse than 1.80; 763 met neither and its notes hold the table.
* Ask at what size a claim can be made before trying to make it at every size. A random recursive tree of 1,024 nodes
  was read on one draw of three (763). Thirty draws of every kind then showed that at 1,024 nodes a hyperbolic geometric
  graph is read on 24, no measure of its six to ten radii parting it from a geometry, and at 4,096 on none from 128
  sources (764). The operator set the limit there, at the last size every law runs. A limit said plainly is worth more
  than a threshold tuned at its edge.
* A verdict made from few draws moves with them. From 24 sources a hyperbolic geometric graph of 4,096 nodes was read on
  four draws of thirty, from 128 on none (764). Where more draws cost nothing, take them before a limit is tuned.
* A rule that no cell may pass four of its errors fails by the count of cells alone. Of 388 cells held, three passed it
  by 2% to 4% (763); on sixteen draws each error was its draws' spread (764). Say what a rule gives by chance over the
  cells it is put to, before the reading.

* A cost is said with its unit. "The last table took the host 51 hours" was the sum over its cells, core-hours; on the
  clock, with 31 workers, it was 1 hour 42 minutes, and the operator was told days where it is hours (765). Read the
  run's own record (`runs` in the table) before quoting a total.
* A cost carried over from older code is checked against one cell measured under the new. 767 told the operator the
  whole table would take about 61 core-hours and two to three hours; it took 163.6 and 7 hours 12 minutes. The 61 came
  from the last table's cells, measured under analysis 5.1; the one million-node cell 767 had measured under 5.3 took 28
  minutes, and the 134 cells of that size alone are 62 core-hours at that rate. The number that would have caught it was
  in the same notes (768).
* A list that several parts read is changed for all of them or for none. The table's families are read by the gate, by
  the stability score as its controls, by two reports' histograms, by the census memory and by the classifier; six
  families added for the gate changed three of those until each was read (765). Before a name joins a shared list, find
  every reader of the list.
* A band typed by hand is wide where the instrument was once wrong. The table held a cubic lattice's d_B within 1.15 and
  a tree's d_w within 1.2 because the probes of their day read that far off, and nothing ever tightened them. A band
  comes from a judged reading by a rule committed first, or the cell is shown and not held (765).
* A check nothing can run hides its own defects. The starts' check could not run from 755 to 765, having no
  references; when a rehearsal gave it some it missed two known answers of eleven, by the names in its criterion and
  not by a reading: the renaming of 756 reached the criterion's keys and not the labels inside its lists (766). When a
  debt makes a check skip, run it once on a rehearsal's data before the debt is paid on the host.
* The tree's boundary tests are read before code is placed, not after. The table's code may import neither the
  research nor a score, and nothing reaches into `calibration/` past its package
  (`tests/contract/test_boundaries.py`, `test_known_objects_are_not_scored.py`); 766 wrote the references across
  three of those lines first and moved them after (766).

## Cite the paper with the claim, and read its figures

* Cite the paper by its arXiv id and the version read (`docs/RESEARCH_METHOD.md`, "The papers read"), never a copy in
  the tree, which is public; check a claim against its page and figure, not a web tool's text: a figure is often a
  paper's only data.
* A paper's figure fixes its claim; its schedule may not be printed: predict from the figure, run the harness's own,
  and on a miss try a fixed set committed first, reporting every one (719, 721).
* Sample the measure a paper defines (checked by enumeration) and run what it printed beside it: which one the numbers
  follow is a finding, not a quiet choice.
* A low-discrepancy sequence does not survive a rejection sampler: keep Sobol on coordinates no rule rejects, draw the
  rest independently with an acceptance that keeps the measure exact, and measure the gain first (717).

## Sources and settings

* A fingerprinted source is an input: ask what its fingerprint keys (`calibration/fingerprint.py`);
  the freeze re-anchors, a fingerprint does not; an engine's source changes only with a new engine version.
* How a job ended is the job's, not its last part's (`rung_terminal`).
* A default that names an old behaviour is a fault waiting: a rung ended at the cap had its certificate counted as
  analysis 4.0 counts it for five analyses, because its health was read with no analysis named (759). One behaviour, no
  switch, no default to fall back on.
* A wall-clock window is shorter the busier the host (one worker a physical core): a recommendation that trades a
  measured cost for throughput states the cost first.
* A load that checks on its return whether what it was asked still holds asks by the rule it began with: the Explorer
  read "every batch" from its scope menu when it began and from the home view as well when its data came, so the home
  view's All batches threw every load away without a word (779). One function says what was asked; a page that stops
  says why.
* What is written and never read still costs and still raises questions: the chain from empty wrote copies of its
  graph at 55%, 70% and 85% of its moves and only the last was read (779). Find every reader of a thing before
  explaining it, and keep what is read.
* A page is tested through the path the page reads: 789's gates box was fed one batch's landscape, passed, and showed
  nothing in the study view, whose merge kept no ledger (790). A test of a view that merges several sources goes
  through the merge, and holds that the merge keeps every key a source has.
* A resource freed only when it is empty is never freed: a stopped folder's scratch held a few small files, so its
  holder lived on and its whole size stayed reserved against every new folder (778 to 790). Free it after a grace,
  moving what it holds to where it survives.
