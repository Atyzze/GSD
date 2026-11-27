# Operating GSD

Recipes: what to type, what to expect, what goes wrong. How the loop works is `docs/ARCHITECTURE.md`; every tool's
commands are in `docs/TOOLS.md`. Commands are for the operator's fish shell (`docs/agent/TARGET_ENVIRONMENT.md`).

## Starting from an empty folder

`main.py run` brings up the folder's PostgreSQL, builds the Rust engine, adopts the archive's calibration seed ("The
calibration table") and creates the study. Check the host first:

    ./tools/setup_host.sh --verify       # checks only: the Rust toolchain, maturin, PostgreSQL, the engine
    uv run python main.py run

If Rust cannot build the engine, `uv run` fails ("The worker count and the Rust toolchain"). In the first hour laws
are proposed, started and decided within minutes, with no `DECISIONS_BEHIND` on the System page.

**The default study** (no `--study`): four campaigns of 10,000 laws, 1 and 2 at zero temperature, 3 and 4 finite, the
odd ones capped at mean degree 16 and the even at 32, beside the standing controls; when all four read
**done**, make the study bundle and send it. A first start that stopped part-way is finished by the next `run` on the
same build; `run` adds no study to a folder that already has a campaign.

**A designed study**: `--study <id>` at a new folder's first start makes the campaigns of its committed design
(`docs/ARCHITECTURE.md`, "Campaigns, the search, and the fleet") and the controls; any other `--study`, or one with
`--spec`, is refused. Start it with every other fleet on the host stopped (two fleets on one host halve each one's
speed). The folders that run: `docs/agent/HANDOFF.md`, "What is live".

**Your own campaign**, in a new folder:

    cp graph_scale_dynamics/resources/configs/campaign_engine_survey.json my_campaign.json   # edit terms, cap, temperature
    uv run python main.py run --spec my_campaign.json

## The pilots

Runs on the host beside the builds (the operator, 2026-11-13; `docs/ROADMAP.md`, "The pilots beside the builds"): they
check a build and feed the next ones, and no law of one is a finding or reaches the paper. A build's notes say in
their first line whether it may be started for one. Each run takes a folder that has never run a study
(`/data/projects/GSD/pilots/<build>/main`), which stays on the build that started it; stop any other fleet first.

    ./tools/setup_host.sh --verify
    uv run python main.py run --study 174        # the stable trial: 10,000 laws in ten batches of 1,000, 16 workers
    uv run python main.py run --study 175        # the perturbation side study: 595 laws around 174's 35 settled laws

**Study 175 is the perturbation side study (847)**, in a folder of its own (the operator, 2026-11-23 11:21): the 35
drawn laws of 174's first bundle that the score of 848 and the one before it both settle, each run again as it is and
perturbed at random at four radii, four laws a radius: 1e-9, which only gives the law new random numbers, then 0.001,
0.01 and 0.1. 595 laws in one campaign on 174's ladder, starts and fact gates; starts_alike and nothing_read record, so
no variant is stopped on a judgment its holder passed. About 600 core-hours (400 to 900): about a day and a half on 16
workers, or beside 174 on part of them (System, Workers, in each folder). Its criterion, `study_175_criterion.json`,
commits the verdict a holder (a stream, a point, or a region to a radius); `tools/perturb_reading.py <bundle>` reads it,
a holder open while its unread variants could still decide it (849), with each holder kept or made beside it, and
`tools/top_laws_alike.py <bundle>` what the top laws share.

**Study 174 is the stable trial (844)**, in a folder of its own on 844, run for days (the operator, 2026-11-22 15:50):
173's design on ten new search seeds, a batch of 1,000 laws each, so that study A is it ten times over. The gates are
173's but two: `nothing_read` acts only from 16,384 (`engine.gate_from`), its verdict below recorded and the law let on,
and `starts_apart_by_history` records only (the operator, 15:38); the three fact gates and starts_alike stop a law, a
tenth let through. The host runs 16 workers, one a physical core, with no `--workers`: SMT was measured on 173 (16, 23
and 32 slots, the same decisions; 32 about 1.12 times faster) and decided against (15:38). Predicted from 173's
decisions replayed under it: about 1,270 core-hours (900 to 1,700), about three and a half days, 56% of it at 65,536;
its criterion is `study_174_criterion.json`. A bundle at any time reads it so far; the batches read **done** one by
one, and the study at the last.

**Study 173 is the gated pilot (841)**, started on 841 in a new folder once 172's last bundle is read and shows
nothing new for it (the operator, 2026-11-21 20:01): 172's design on a search seed of its own, 2,500 laws in one batch,
172's ladder and budgets, and six gates stopping a law, a tenth let through past each at every size, confirmed or not:
the three fact gates as in 172, starts_alike, starts_apart_by_history and nothing_read (its piece 0.9 of the graph at
4,096). The cut gate records its verdict on every law with a seed cut at its budget and lets it on (the operator,
21:03, "Record only"); every other gate records, as in 172. A longer chain is priced on twice its size's budget; the
ledger counts the verdicts of a law stopped over_budget; a frozen lattice scores 1. Predicted from 172's decisions
replayed under it (`tools/design_on_a_bundle.py`): about 150 core-hours (100 to 260), about half a day on 16 workers,
and none of 172's 22 scoring laws stopped. Its criterion is `study_173_criterion.json`, committed before any start, read by `tools/study_173_reading.py`. It runs
on 841 from 2026-11-21 about 22:30 local; then again on 841 in a new folder with `--workers 32` (the operator, 22:57),
the same seed, to test the replay and what SMT gains, read by `tools/two_runs.py <first> <second>`. On 841
`--workers 32` only set where the ramp started (its floor 1), so the rerun ran at about 23 slots; it ran 80 minutes and
found seeds stopped for memory on a guessed grant (843). 843 holds an explicit count, so its own run with
`--workers 32` is the SMT measurement.

**Five designs are in the tree, study 169's (813), 170's (820), 171's (827, revised on 828 before any start),
172's (835) and 173's (841)**, and no older one (the operator, 2026-11-18 16:43: "ALL old data we want GONE"); 169 and 170 have run
and been read (821, 827). **Study 172 runs on 835** (the operator, 2026-11-21 04:23: "now 172 runs on 1 build, 835 and
thats it"), the bigger baseline asked for at 02:59: 171's design at 2,500 laws in one batch with one random pick a law
a size read by every gate (`engine.one_die`), so a law two of the three gates would hold back goes on at the share and
not at its square; only the empty, too dense and disconnected gates act, each on three sizes in a row and so from
1,024, with the learned let-through (10% of what a gate would withhold goes on, 1% after 100 in a row withheld again a
size up); the budget stops a law whose next size will not fit, and every other law runs to 65,536, its budgets four
times 170's at 4,096 and 16,384 (1.6e12 and 8.0e12 units; "The budgets in work"). It is drawn from one search seed
its design carries (so every start prints the same one and `--search-seed` is refused), without the curvature term
(`terms_left_out`), every coefficient a plain number. About 880 core-hours, two to three days on the host's 16
workers (650 to 1,300), from 171's progress bundle. **Study 171**, the baseline of 1,000 laws (the operator,
2026-11-20 10:09), was stopped for it at 04:23 after running on 829 to 834; its progress bundle of 01:32Z is its
reading unless a later one was made.

**172's bundle, with every chain's peak**: a bundle carries `tables/chains.ndjson.gz` (each seed's chains, their peak
degree) from 836 on. To have it in 172's bundle while every law still runs on 835: once its batch reads **done**,
untick auto extend, stop, apply 836 or later, start and make the bundle; nothing 836 changes is read by the fleet.
Made on 835, the bundle has no chains table, and `tools/cap_reading.py` reads each chain's final degree instead.

**When it is done** every batch reads **done**: press the Reports page's one button and send
`study_<id>_<utc>.tar.zst`; it carries the supervisor's log (`evidence/supervisor_tail.log` in every batch, its
last 2,000 lines). If it has not ended when you want the host back, stop it and
make the bundle anyway. Delete the folder once the build that read it is delivered.

**More laws in a folder whose batches are done**: on the Campaigns page, in the column "laws · graphs", each batch's
box takes a larger number and the batch opens again; the laws it holds stay as they are, since a law is drawn from its
batch's seed and its index.

**How its bundle is read**, by the build it reaches, against its criterion
(`graph_scale_dynamics/resources/readings/study_<id>_criterion.json`) and the study before it, each item on every law:

    python3 tools/pilot_reading.py <unpacked bundle> --md <scratch>/predictions.md --json <the same>.json   # kinds, K
    python3 tools/study_baseline.py <unpacked bundle> --out <scratch>/study_<id>_reading    # law by law, one file
    python3 tools/replay_bundle.py <bundle> --json <scratch>/replay.json              # every decision replayed
    python3 tools/read_bundle.py <bundle> --json <scratch>/study.json                 # every report built
    python3 tools/fleet_reading.py <bundle> --md <scratch>/fleet.md --json <the same>.json      # cost, memory, hours
    python3 tools/starts_bundle.py <bundle> --md <scratch>/starts.md --json <the same>.json    # holds, scores
    python3 tools/score_list.py <bundle> --md <scratch>/scores.md --json <the same>.json       # the score's list
    python3 tools/budget_reading.py <bundle> --md <scratch>/budgets.md --json <the same>.json  # cuts, stops, more
    python3 tools/study_172_reading.py <bundle> --json <scratch>/criterion.json      # 172's R1 to R7 (836)
    python3 tools/cap_reading.py <bundle> --json <scratch>/cap.json                  # what a lower cap would cut (836)
    python3 tools/gate_variants.py <bundle> --json <scratch>/variants.json           # the gates on 1 and 4 sizes, one die (838)
    python3 tools/bundle_growth.py <bundle> --json <scratch>/growth.json             # what grows with the study (838)
    python3 tools/design_on_a_bundle.py <bundle> --design <next study> --json <scratch>/design.json   # the next design on it (841)
    python3 tools/study_173_reading.py <bundle> --json <scratch>/criterion.json      # 173's P1 to P12 (842)
    python3 tools/lattice_cost.py <bundle> --json <scratch>/lattice.json             # the lattice starts above 4,096 (842)
    python3 tools/two_runs.py <first> <second> --json <scratch>/two_runs.json        # a rerun against its first run (842)

For study 172, `docs/agent/NEXT_BUILD.md` (838) is the reading step by step, with 171's numbers beside each.

**A replication** (the operator, 2026-11-15 14:07: study A, then the same again) is a second folder of the same design,
read against the first law by law, no record committed:

    python3 tools/pilot_difference.py <the replication's bundle> --against <the first bundle> \
        [--declared <law,law>] --md <scratch>/difference.md --json <the same>.json

A law that moved is named by its id with both values; one a deep size's lane held and one named before the run
(`--declared`) are listed and not judged. Since 806 no clock ends a seed, so a replication on another machine, or the
same one at another speed, decides and reads every law alike or names the one that moved. The reading goes into that
build's notes and its delivery's first lines; nothing of it enters `docs/readings/`.

## The Campaigns page

**Pause and resume**: running chains save at their next tick (`pausing`, then **saving done**); nothing queued is
cancelled.

    uv run python main.py campaign pause <id>
    uv run python main.py campaign resume <id>

A share (`workers`) is a floor, not a fence: blank is an equal part, zero a pause, and only a declared share takes a
running job back. Raising a law budget reopens a campaign that read **done**. Both change at any time; a term set
never. **Stopping the fleet** (under the table) fences every lease at once; rungs in flight start again.
**Auto extend** (under the table, 829, acting from 830; off unless ticked; the operator, 2026-11-20 13:36): once every
campaign with a law budget reads **done** (its budget reached, nothing in flight), each gets 50 more laws and the
fleet runs on, again each time, until it is unticked or the fleet is stopped, so a study that ends at 4am does not
idle until morning. A study's fleet never ends by itself (its batches are continuous campaigns): unticked, a finished
study's fleet waits, as before. The new laws are drawn as the first were,
from each campaign's own seed; the line beside it says when it last extended and how many campaigns. It acts only in
a running fleet that is not stopped (`stop the fleet` holds it).
**`WORK_SUPPLY_STARVED`** (System) names each campaign giving no work and why: a status for your own choices (paused,
at budget, surveyed, holding at a gate), a warning for an active campaign with nothing queued or held.

### Who may control the fleet: the admin link

A start writes the admin link, `http://127.0.0.1:<port>/#admin=<token>`, to `var/run/dashboard-admin` (private to the
folder's user; from another machine, use the host's address). Every write needs it, pause and resume included; the web
process refuses a write from any other page (403). The token is never sent in a URL, and no command line carries it
(the browser a start opens reads `var/run/dashboard-open.html`). The dashboard stays reachable from outside (the
operator shows it at snekpas.nl/research, over HTTPS only). A request without the admin token gets a 500 as
"internal server error" with its request id, the exception's text going to the API's log under that id, and any other
5xx without its `detail`; the admin link sees them whole. Since 748 the token decides this, not the address: a proxy
on this machine that names no client made every viewer look local (734 had decided by the address). Reads write
nothing: `GET /api/runtime-imports` reads the API's import set live, and the admin's `POST /api/runtime-imports`
stores it; the status read of the reports page no longer restarts the quiet report's runner, which the API starts at
its own start and at each admin `POST /api/reports/trigger` while a quiet report is in progress. The services' console
(`/api/supervisor-log`, every service's output) needs the token too, and a page opened without it shows each fault's
summary (where, when, how often, its first line) but no traceback and no worker's stderr; the admin link shows them
whole (742). Reports and bundles download two at a time over 4 MiB, a third told to come back in four seconds.

**Every start makes a new link** (853). A stopped fleet's link stops working the moment the next start writes its own,
however the fleet was stopped (one Ctrl-C, two, or a kill: `tests/integration/test_a_restart_makes_a_new_admin_link.py`
runs all three on a real fleet). A tab left open from an earlier run keeps its old `#admin=` and is refused; the top
bar says which link a page holds: **admin** when it is this run's, **admin link from an earlier run** when it is not,
nothing for a viewer without one (`GET /api/access`, which also counts the refused writes). Without this run's link the
page greys its write controls (the worker count, pause, a campaign's actions, shares and budgets, the early gate, a
study's delete, a new campaign's start), and a refused write's note says the link is not this run's. The services'
console (System) says each accepted admin write and, at most once a minute, how many were refused and with which kind
of link, never a token (`services/api/admin_link.py`).

### Starting a campaign

**new campaign** starts from *the shipped defaults*, which draw every axis uniformly over its whole range, or from a
campaign of the folder (its parent); to study a region, declare it. A sign `−` is a reward (the energy is minimised).
Over `0.01` to `100` a log draw puts about half its laws below 1.0, a linear one under 5%. The preview refuses a
selection that cannot draw a law and names identities (`degree_anchor` and `wedge_count` are both
`degree_square_sum + edge_count`). In a spec file:

    "search_policy": {"grid": {
      "betas": [100.0],
      "term_counts": [2],
      "magnitudes": {"min": 0.01, "max": 2.0, "spacing": "log"},
      "per_term": {
        "edge_count":        {"magnitudes": [1.0], "signs": [-1], "scales": ["one"]},
        "degree_square_sum": {"magnitudes": {"min": 0.015, "max": 0.2}, "signs": [1]}
      }}}

`per_term` overrides whole keys (`magnitudes`, `signs`, `scales`, `power_exponents`, `anchor_k`); law-wide keys are
`betas`, `term_counts`, `localities` and `swap_shares` (lists in [0, 1) or ranges, linear unless declared),
`local_moves` (`toggle`, the one local move since 774) and `zero_temperature` (`false`, `true`).

**`surveyed`**: the campaign has proposed every law its all-lists grid can write and goes on measuring them (one that
draws any value from a range never is). Widen with a clone: a **range**, more scales, a term with a parameter, or
another term.

**The founder** (the operator's first `engine.py`): terms `edge` and `Σd²`, two per law; edge **values** `1`, sign
`−`, scale `one`; `Σd²` **range** `0.015` to `0.2` `log`, sign `+`, scale `one`; beta a `log` **range**, temperature
**finite** (add **zero** for T = 0); locality **values** `0.99`, local move **toggle**; swap share **values** `0`. At
low temperature mean degree locks to the whole number nearest `1/(4c)`, roughly 17 down to 1 over the range.

**Holding mean degree still as N grows, at finite temperature.** `β·c·(4<d> + 2) = ln(N/<d>)`, so `<d>` climbs (4.80
to 6.94 from N = 256 to 2048); an `edge_count` with a **positive** coefficient on `log_N` (0.46 to 0.49) holds it. A
*negative* `Σd²` without a positive degree fourth sum on the same scale is refused as `unbounded_below`.

**Cautions.** With only edge and degree terms at zero temperature a swap never raises the energy: such a law rewires
on at no cost while the certificate, reading only the energy, calls it at rest. Near 0.99 locality or swap share, laws
often run out of their budget. `degree_square_sum` alone lacks the edge term, so its laws die `empty` and `too_dense`
in similar numbers; the negative two-star ERGM is `degree_anchor` (`Σd² − 4k·E`).

### Deleting a campaign

Pause it, press **delete** in its state cell, type its id; refused while running or saving, or while a clone exists.
Blobs stay until a garbage collection on a paused, drained fleet, which keeps every chain record an archived run
names: `uv run python main.py artifacts gc` lists, `uv run python main.py artifacts gc --apply --confirm GC` removes.
The command line also deletes a running campaign (typed id or `--yes`; `--cascade` for clones) and is the only way to
archive:

    uv run python main.py campaign delete <id>
    uv run python main.py campaign archive <id>

### Checking the page against a live database

    uv run python tools/trial_campaign_manager.py    # twenty-two steps, about a minute

It clones the oldest campaign, checks the claim door opens and closes with the pause, and deletes what it made.

## Adding a campaign to a folder that already has some

A new study goes in a new folder. To add one campaign here (no law budget until set; a running fleet picks it up next
tick):

    uv run python main.py benchmark        # campaign start refuses without it
    uv run python main.py campaign start --spec <spec file> --reason "<why>"
    uv run python main.py campaign use <printed id>

Keep custom specs in `var/specs/`: a json under `graph_scale_dynamics/` fences a running fleet with exit 75.

## The campaign's declared boundaries

`spec.limits` (the mean-degree window, the connectivity floor) and `spec.engine.policy` (base block, budgets in work,
audit fraction) are frozen at creation (what each stops: `docs/DECISIONS.md`). They define the population: raising the
cap makes clamped laws dearer, not more numerous. The hashes and lifecycle events are printed (and written under
`var/reports/`) by

    uv run python main.py campaign provenance <id>

## Reports: only when asked, only on a quiet fleet, one bundle for every campaign

The Reports page's **make the study bundle** (**pause everything and make the study bundle** on a busy fleet) pauses
every running campaign, makes every campaign's cycle once no lease is live (logs in
`var/reports/study/runs/<request>/`), gives back what a start gives back, resumes what it paused and writes
`var/reports/study/bundles/study_<study>_<utc>.tar.zst` (its contents: `docs/ARCHITECTURE.md`, "The reports"). An API
restart resumes from its stage; a failed cycle still resumes the fleet; **cancel the study bundle** stops one that
holds the fleet, resumes what it paused and makes no bundle. Since 835 the button is disabled from the first click
until the fleet shows the bundle under way (or two minutes, or the server's refusal), and a second ask while one is
being made joins it rather than failing (the operator, 2026-11-21 02:32). To read one, or two side by side:

    uv run python tools/read_bundle.py study_<study>_<utc>.tar.zst                   # the study, its reading, each part
    uv run python tools/read_bundle.py <later bundle> --against <earlier bundle or reading .json>
    uv run python tools/read_bundle.py <bundle> --json <where to save its reading>

Also on a bundle: `uv run python tools/report_audit.py --bundle <study bundle>` (what each report reads, who reads it,
its cost). `uv run python
tools/gates_map.py` redraws `docs/diagrams/gates_and_streams.svg` from the code; a test fails until it is current.

## Reading what the operator sends

**In this order**, in whichever build they reach: a study's bundles (each batch against its criterion once its ladder
empties), then any rerun of the papers ("The replication programme").
Unpack each in its own folder (while a lane runs in the tree, readers write to a scratch folder, copied into
`docs/readings/` after). Commit each reading as the tool wrote it, named in `docs/readings/README.md` and pinned by its
hash in `tests/fixtures/committed_readings.json`; the numbers an answer states are pinned by a test. Until a study's
ladder is empty its predictions are reported, never judged. A study on 784's rule is read with its own
`gates_ledger.json` and against the baseline of the study it repeats (`tools/study_baseline.py`); no ledger is
committed from it. Answer in one plain sentence first.

### Reading a study's bundles

For a study on any list of starts; a pilot's bundle is read by "The pilots", above. No reader here judges a study's
predictions until study A's trial has its own.

1. **The readers**, each against the last reading in the tree (`<id>` the study):

       python3 tools/starts_bundle.py <bundle> --md docs/readings/study_<id>_starts_<utc>.md \
           --json <the same>.json --laws docs/readings/study_<id>_starts_laws_<utc>.json \
           --against docs/readings/study_<id>_starts_laws_<the last utc>.json
       python3 tools/read_bundle.py <bundle> --json docs/readings/study_<id>_<utc>.json
       python3 tools/fleet_reading.py <bundle> --json docs/readings/study_<id>_fleet_<utc>.json --md <the same>.md \
           --against docs/readings/study_<id>_fleet_<the last utc>.json
       python3 tools/sample_reading.py <bundle> --md docs/readings/study_<id>_sample_<utc>.md --json <the same>.json
       python3 tools/pattern_scan.py <bundle> --md docs/readings/study_<id>_patterns_<utc>.md --json <the same>.json
       python3 tools/holds_reading.py docs/readings/study_<id>_starts_laws_<the last utc>.json \
           docs/readings/study_<id>_starts_laws_<utc>.json --md docs/readings/study_<id>_holds_<utc>.md \
           --json <the same>.json
       python3 tools/neutral_moves_check.py mark --bundle <bundle> \
           --laws docs/readings/study_<id>_starts_laws_<utc>.json \
           --json docs/readings/study_<id>_holds_marked_<utc>.json --md <the same>.md
       python3 tools/disordered_reading.py bundle <bundle> --rule 2 \
           --json docs/readings/disordered_study_<id>_rule_2_<utc>.json --md <the same>.md
       python3 tools/coverage_reading.py <bundle> --md docs/readings/study_<id>_coverage_<utc>.md --json <the same>.json
       python3 tools/positive_control.py check <bundle> --json > <scratch>   # then docs/readings/study_<id>_controls_<utc>.*
       python3 tools/history_reading.py <bundle> --md docs/readings/study_<id>_history_<utc>.md --json <the same>.json
       python3 tools/deep_reading.py <bundle> --md docs/readings/study_<id>_deep_<utc>.md --json <the same>.json
       python3 tools/dimension_reading.py <bundle> --md docs/readings/study_<id>_dimension_<utc>.md --json <the same>.json

   **Say first**, in one sentence, what grew, what held and what the map predicts, as equals (the operator,
   2026-10-13: "we want to equally map what laws/conditions sustain existing geometry"): whether a start without a
   shape reached one that held (grows, one_space), every chain one piece; how many laws hold a lattice they were
   given; how the predictions stand. Then:
2. **The scores** (the starts' page, "The scores"): laws above zero by who built the geometry; the top laws by
   name, and whether their terms read degrees alone or tell the lattice apart. A chain from empty or random *held* in
   a disordered geometry two sizes in a row (`tools/disordered_reading.py`, rule 2) is said first of all and read by
   hand; at one size it is a candidate, read again on the next bundle.
3. **The halves** (`tools/fleet_reading.py`): extension's share of simulation time (a half short of its share is a
   defect); the laws stopped `failed` for their own failures, by name; analysis failures still standing (report 14).
4. **What each park cost** (the starts' page, "What the starts decided"): what its let-through laws read a
   size later (`a_shape` a park overturned, `parked again` one confirmed).
5. **What more laws buy** (`tools/sample_reading.py`, `tools/pattern_scan.py`): whether the campaigns are still one
   sample (a departure from chance is a drift or a defect, said first); what the rare classes and the learning curve
   gained.
6. **The holds** (`tools/holds_reading.py`): each by name, whether it holds a size further, gained and lost, and its
   mark (`tools/neutral_moves_check.py mark`, about three minutes): `blind` (90% or more of a thousand swaps at its
   lattice change none of its terms: the hold is not the law's), `resists` (its swaps raise its energy; what sustains a
   geometry is read from these), `drives` (they lower it), `between` (said apart). A hold at the top at a finite
   temperature, which H1 cannot see, is said beside H1's verdict, never in its place.
7. **The replays**: every decision of the bundle, from the inputs it carries (`tools/replay_bundle.py`, since 798;
   report 28's `the_record.decision_record` is still the folder's own sample). A decision that does not replay as
   made is a defect, and so is one with no inputs that is not a released hold.
8. **The rest**: the controls ("The controls"), the bundle's pages, how each seed ended
   (report 28 `seeds`), the laws given back (report 14's `pipeline_blockers`) and every gate's let-through.
9. **Commit and pin**: a number a standing document states from a reading is held by a claim in
   `research/document_claims.py` (`tests/unit/test_the_documents_claims.py`), and those are the instrument's (the
   operator, 2026-11-15 14:07). A
   study's numbers are read from its own bundle in the conversation that reads it. What the known answers did not
   cover gets its own criterion, committed before it is read; a rule changes only by the operator's word, its cost
   stated first.

## The gate's two lanes, on any host

Either lane is one command on the host (the operator, 2026-11-01 01:10: "simply be a script that can be ran
locally"), in a folder unpacked from the archive, never a study's (it refuses a folder whose fleet or `serve` runs):

    uv run python tools/gate.py fast    # the tests that touch what changed since this folder's build, and the
                                        # release's own checks; refused for a frozen source, the schema or the engine
    uv run python tools/gate.py full    # every test, the PostgreSQL lane beside the rest over the CPUs

The fast lane reads a change against `tests/fixtures/build_files.json`, so it needs no git (`--since <rev>` reads git
instead). `--allow-skips` reports, rather than fails, the browser checks a host without node and Chromium cannot run.
The release runs the same lanes (`tools/package_release.py`, `--fast` for the fast one, never two releases in a row).

## Resetting onto a new schema

A build that changes `graph_scale_dynamics/resources/schema/schema.sql` refuses older databases. Make the study bundle
and download it, stop the fleet, unpack the new build into a **new folder** and `uv run python main.py run` there (the
old folder stays readable with its own build), then bring the anchors over:

    uv run python tools/import_anchors.py <the old folder>

To reuse the folder instead: stop the fleet, `uv run python main.py reset` (type `reset study <id>`; it removes
`instance/`, `var/` and `.env.postgres` and stops the scratch holder), unpack over it and `run`; the fleet restarts at
two slots. A backup: `uv run python main.py pause`, wait for the leases to drain, then `uv run python main.py backup
--output <dir>` (the database, the blobs, and the study's record, the controls made and the carried ledgers from
`var/`); `uv run python main.py restore <dir>` puts one back (`--force` over a folder that holds state). Reset and
restore refuse while the folder's fleet or `serve` runs.

## The controls

Each control is a campaign of its own (how the fleet makes them: `docs/ARCHITECTURE.md`, "Campaigns, the search, and
the fleet"), hand-fed, judged by a criterion in `graph_scale_dynamics/resources/readings/` committed before its run
and never revised. `tools/positive_control.py check <the study bundle, unpacked>` reads every kind and prints `PASS`,
`FAIL` (law, chain) or `INCOMPLETE`; `sandbox` runs the job's path with no fleet.

**The positive control** (`positive_control_criterion.json`): P1 and P2 (the lattice law at beta 2 and 4, a chain
started at the square torus) must read finite on that chain and not on the one from empty; N1 and N2 on neither. By
hand:

    uv run python tools/positive_control.py laws --output var/specs/positive_control_laws.json
    uv run python tools/benchmark_campaign.py start var/specs/positive_control_laws.json --kind control \
        --spec var/specs/positive_control_campaign.json --reason "positive control"
    uv run python tools/positive_control.py check <the study bundle, unpacked>
    uv run python tools/positive_control.py sandbox --sizes 4096 16384 --seeds 1

**The standing controls**: those four and C1 (the curvature action of Kelly, Trugenberger and Biancalana at degree 6,
beta 4, a chain started at the cubic lattice folded to each rung's N), three seeds, 64 to the study's top, judged at
their top two rungs from 16,384 by `controls_criterion_2.json` or the criterion the study's design names. Sandbox: `tools/positive_control.py sandbox --criterion <it> --sizes 4096 16384 --seeds 1`.

`tools/positive_control.py check` finds the standing controls in a study bundle (by their contract's campaign).

**The growth controls** (`controls_criterion_3.json`, 64 to 262,144): no design makes them; a campaign of them is
judged by that criterion (`research/control_verdict.py`): P2 and P3 must
keep their chain from the random geometric start (two dimensions at degree 4, three at 6) finite; N1, N2, N3 and N1 at
zero temperature must melt.

## The lattice benchmark

The lattice law: 5 x `degree_anchor`(k = 4), -6 x `induced_square_count`, +1 x `square_edge_overlap`, scale `one`; its
ground state is the flat square torus at -4.0 a node. The benchmark, 46 Hamiltonians with known ground states, is a
hand-fed campaign (five seeds, audit 100%, budgets of about four hours of work or more, to 262,144):

    uv run python tools/benchmark_campaign.py lattice-laws --output var/specs/lattice_laws.json
    uv run python tools/benchmark_campaign.py start var/specs/lattice_laws.json --kind lattice \
        --spec var/specs/lattice_campaign.json --reason "lattice benchmark"

On the Campaigns page: those three terms, scale `one`, anchor k **values** `4`, magnitudes **values** `5`, `6`, `1`
with signs `+`, `-`, `+` (per-term), beta **values** `2` or a range 1.5 to 4, finite temperature, swap share **values**
`0.15`.

## The let-through, learned from the study alone

A design on the let-through rule (`engine.policy.let_through_rule`) learns every gate from its own decisions, every
batch from every batch's laws at the same fixed points (831 and 832, the operator, 2026-11-20 10:32; `docs/DECISIONS.md`,
"784's one let-through rule"): nothing is carried from another study (the operator, 2026-11-15 14:07). Its bundle carries `gates_ledger.json`, every
gate at every size with how many laws it would have withheld, how many it let through, how many were withheld again
one size up, how many passed, and every signature `repeats_a_known_result` counted (`seen_enough` until 835); Home's box "The gates", under the fleet
ladder, shows the same while the study runs, always open (789, the operator: "it deserves to be visible the entire
time"): every gate grouped by kind (fact, judgment, class, settling, depth, structure) with what it reads, and at each
size its share, the laws it held back, the laws it let through and what became of them one size up. Whether confirmed gates are carried between studies is decided after study A is
run and replicated (the operator, 14:07: "then we'll close them and run again"). A design must be on the rule: one
that is not is refused at its start (`operations/study_design.start`); the default study is on it too
(`operations/study.on_the_let_through_rule`).

## When a fleet stops, and when a worker vanishes

Since 786 no seed is ever "lost", and no law is charged for its fleet. **A fleet that stops** (Ctrl-C, the bundle's
pause) gives its workers longer to close than a worker gives its simulation to save
(`artifact_store/resume_state.FLEET_STOP_GRACE_SECONDS`, 132 s against 120 since 840, when a stop began to wait for
the largest seed's save; a seed that has saved exits at once), and a worker told to stop writes its
attempt's record before it gives the seed back. **A start** queues again at once every seed the last fleet still held,
from its saved state (the start's line "seed(s) the last fleet still held queued again at once"), so none waits for
its lease to run out or counts against its law. **A worker that vanishes while its fleet runs** (killed from outside,
the machine's memory killer among them) leaves a lease that runs out: the seed is queued again from its saved state
after a wait that doubles each time it happens to that seed, one minute, two, four, never more than an hour
(`domain/model.vanished_wait_seconds`), its attempt closed as `worker_vanished`, one of the fleet's interruptions,
and an event `worker_vanished` names the seed, the times and the worker. A seed an older build marked `lost` waits as
pending, never as failed, and the start gives it back.

**A buy that makes no work** (every seed of the size it buys already ran) is recorded with "decide again" in the
same write when that size has been read, so the next decision pass, seconds later, decides the law from what it has;
when it has not been read, or the same buy comes twice with no work, an event `buy_made_no_work` says so, and nothing
loops.

## Leaving a term out

A design leaves a term out of its pool (`terms_left_out`, the operator, 2026-11-17 21:23: "why was it even in the draw
pool for this trial?? ... pick a whole number like 1000 instead"): the campaign's `operator_whitelist` lacks it, the
sampler never draws it, every law drawn runs, and the law budget is the laws that run
(`operations/study_design.without_terms`).

## The budgets in work

Since 806 no clock decides anything a study records (the operator, 2026-11-19 03:49 and 04:12): each size's seed has a
budget in units of the engines' weighted count of work, fixed in the design (`ladder.budgets`, or the shipped spec's
`engine.policy.work_budgets`), and a seed ends there, between two chunks when the next would not fit and since 840
inside a chunk that passes it all the same, read on its last whole chunk; a law whose
first chunk at the next size would not fit, predicted from its own seeds a size below, is stopped `over_budget` and
starts nothing there. So a study run again, on another machine or the same one loaded, gives the same decision for
every law and the same readings, and only takes longer or shorter. The unit is fitted once in the sandbox
(`tools/work_unit_fit.py`); the pages show each size's budget in units with its hours beside, the hours an estimate
from that unit (`engine.policy.seconds_a_unit`), slower or faster on another machine. Nothing to do by hand: there is
no window, observer or repick. A seed paused and resumed counts its work once and ends where the run never stopped
would have. What the budgets did to a study (the seeds cut and the laws stopped by size, the connected laws
and those passing every gate among them, the seeds past their budget, what a larger budget would buy) is
`tools/budget_reading.py` on its bundle (821).

## The study bundle's pages

The front page, the study explorer and the gate trees open from the Reports page (`docs/ARCHITECTURE.md`, "The
reports"). The front page's advice (`advice.json`) ranks each law's reasons (an anchor; the line's reason left at
790) and leads (field pairs correlated given the degree at two successive N): a reading,
not a verdict. In the explorer a drag selects laws on every panel and the view is kept after `#`; a click on a gate
tree opens those laws in it. For a bundle that lacks them:

    uv run python tools/study_explorer.py <study bundle>.tar.zst [--out-dir DIR] [--out explorer.html] \
        [--calibration <table or bundle>]

It writes them and `advice.json` into a folder named for the archive beside it (into an unpacked bundle, in place);
`--calibration` supplies the families' table.

## The replication programme

A published model run by its own rules, read by this instrument, with no fleet or database; it writes
`var/readings/replication_<model>_<utc>.json` (send it). A rerun is judged by a criterion committed before it runs
(`--judge <criterion>`, or later `--read <file>[,<file>] --judge <criterion>`; `!` marks an item not as expected) and
pinned by a test of its own; a run that is not the command's is reported, not judged. The 2019 model is run again
after the paper's three studies, against a criterion written fresh on the final probes (the operator, 2026-11-19 22:05);
its earlier readings and criteria left the tree at 829 (2026-11-20 11:48), into `GSD_readings_archive_829.tar.zst`. The papers are cited by arXiv id and version
(`docs/RESEARCH_METHOD.md`, "The papers read"); the tree is public and keeps no copy of them.

**Paper 1, Kelly, Trugenberger and Biancalana** (`tools/replication.py`), 30 to 40 minutes on 16 workers, then the
connected circle (`ktb1c`) in about an hour; `NxK` runs K seeds at N, `--hysteresis-at` reheats those sizes:

    uv run python tools/replication.py --models ktb1,ktb1t,ktb2,ktb3 --sizes "ktb1:100x50,102x50,104x50,106x50,200,500,1000;ktb1t:200,500;ktb2:200,1024,4096;ktb3:200,1024" --seeds 2 --first-seed 11 --hysteresis-at 200 --workers 16 --judge <criterion>
    uv run python tools/replication.py --models ktb1c --sizes "ktb1c:100x50,102x50,104x50,106x50,200,500,1000" --seeds 2 --first-seed 11 --workers 16 --judge <criterion>

**Paper 2, Conrady** (`tools/replication_conrady.py`): `conrady` (the defined measure) and `conrady_p` (equation (13)
as printed), a **scan** of 26 temperatures and **anneals** (`N_e@T`, `xK` K a seed), about an hour on 16 workers:

    uv run python tools/replication_conrady.py --models conrady,conrady_p --scan "conrady:45,90,180;conrady_p:45,90,180" --anneal "conrady:180@0.625x3,180@2x3,360@0.625,720@0.625;conrady_p:180@0.625x3,180@2x3" --seeds 3 --first-seed 11 --workers 16 --judge <criterion>

**Paper 3, Konopka, Markopoulou and Severini** (`tools/replication_konopka.py`): the named graphs' energies counted
exactly (about ten minutes; deterministic, so a difference from the sandbox's is a defect), then a census of random
cubic graphs' cycles and the paper's exchanges (`--chains` names chains `r:NxK`; the `=` keeps a negative r from
reading as a flag), about 2 hours on 8 workers:

    uv run python tools/replication_konopka.py --chains=-7.1:256x3,-7.1:512x3,7.3:256x3,7.3:512x3 --moves 30 --first-seed 11 --census 1000x200 --workers 8 --judge <criterion>

## A new term from the literature

The same arithmetic in both engines (`engine/engine.py`, `engine_rs/src/graph.rs`, named in `engine_rs/src/lib.rs`'s
`op_name`); its cost in `dsl/dsl.py`; its short name in `services/api/overview.py` (`OP_SHORT`),
`services/api/landscape_worker.py` and `research/hamiltonian_preflight.py`; tested by
`tests/scientific/test_engine_parity.py` and against a direct count (as `tests/scientific/test_the_curvature_term.py`).
Bump the crate version ("A build that changes the Rust engine"); the packager re-anchors the frozen sources.

## A build that changes the Rust engine

`main.py run` compares `gsd_engine_rs.FINGERPRINT` with the crate version in `engine_rs/Cargo.toml` and rebuilds with
`tools/build_engine.sh` (about a minute); the fleet refuses to start if that fails. By hand: `./tools/build_engine.sh`,
then `uv run python -c "import gsd_engine_rs; print(gsd_engine_rs.FINGERPRINT)"`.

## The worker count and the Rust toolchain

**The worker count** (the operator's): one worker per physical core, its second hardware thread left free (16 on the
research host); nothing to set. `GSD_MAX_WORKERS=<n>` in front of `uv run python main.py run` raises the ramp's
ceiling to n, and the ramp still aims at 75% host CPU, so on the research host it settles near 24. `--workers <n>`
holds n slots from the start, the ramp giving none back (843; on 841 and 842 it only set where the ramp started, its
floor 1, so 173's rerun with `--workers 32` fell to 23 slots for most of its run). Neither is the rule.

**Changing it while a study runs** (846; the operator, 2026-11-23 11:48): the System page's Workers panel takes a
number and **set**, which needs the admin link. A lower number stops the slots above it at once, without waiting for
their rungs: each saves its seed where it is and gives the rung back to the queue, and a slot that stays resumes it,
so nothing is lost or charged to a law. A higher number starts slots at once. **let the ramp decide** hands the count
back. The most it offers is one a hardware thread (32 on the research host), or `GSD_MAX_WORKERS` when that is set,
because the folder's PostgreSQL connections are sized by the same rule. Above one a core the second threads share a
core, so 16 to 32 adds less than it seems. Nothing needs a restart, and the count stays across a pause.

**The work groups and the system's CPUs** (856; the operator, 2026-11-24 17:37 and 17:39): a study that names groups
(176: A the blind draw, B the map of the best) shares the slots between them, half each by default. `uv run python
main.py workload` says the split and the CPUs; `--split A=3,B=1` changes the split (any positive numbers, read as
shares; an empty string treats every campaign alike) and `--system-cpus 0,1,16,17` keeps those CPUs, as btop numbers
them, for the database, the controller and the dashboard: every simulation and analysis child starts on the others,
from the next child each worker starts (an empty string gives them back). A group with nothing queued leaves its slots
to the other until it has work again, so the map of a study that has found nothing yet takes no slot. In btop with 16
workers and both groups working: about 8 simulations of each, none on the CPUs named. The System page's Workload panel
does the same behind the admin link, and says which kept CPU shares a core with one that is not: keep both threads of
a core when the dashboard goes stale under a full fleet (856's notes).

**Starting study 176**: `uv run python main.py run --study 176` in a new folder: ten blind batches and the map, which
begins with the 125 points of its first ten (`study_176_first_ten.json`). The map's progress is the bundle's `map.json`
(each region mapping or known, its points, its kind, the size it is spotted at, its boundaries); the controller's
log writes `study_map` when the map adds points or takes a new law into the ten.

**Starting study 177** (881): `uv run python main.py run --allow-host <host> --study 177` in a new folder, every
other fleet on the host stopped and the folder's `import/` left empty: ten blind batches, the focus begun at the start
and an empty seeded campaign. Nothing to press: the focus's step (once a minute) takes the first law that scores here,
the zone worker runs its neighbours, its terms switched off and its seeds (group N), and on 881 the depth worker took
it first, one seed at a time, up to half the host's memory (group D; since 893 a law goes deeper only on the push
list, in the N-push). The Map page's first line says what each does, in
amber if the focus's step fails. Seeding it from a bundle is the step after it runs on its own; a bundle of 176 made on
870 or later reads its science (f5c045e195fdb4d2).

**Seeding a study from the dex** (882). Put a dex (`dex_*.tar.zst`, from a folder's `export/` or `tools/dex.py
make`) into the new folder's `import/`, before or after its start: within a minute the controller reads it in, its
scoring laws go into the seeded campaign and the focus takes the best of them at its next step on its score in the
dex. An old study bundle in `import/` is ticked and synchronized on the Map page as before; one of another science
brings its laws alone. Every folder writes its own dex into `export/` each hour, every part it was seeded with merged
in, so the newest dex there is the one to carry to the next study.

**Is the zone being mapped?** (884) The Map page, under the law in focus: the first line says how long it has been
in focus, how many of its laws are read (in the last hour, and when the last was) and about how much work is left at
the zone's workers now; the next, who runs now against the zone's share. In the rings table, "running", "queued" and
"between sizes" are neighbours under way, "held" in amber are stopped by the decider and do not move by themselves,
"not started" have no run yet. "every law of the zone" (folded) gives each law where it stands and for how long, its
kind so far against the law's; Working now lists every running simulation with its clock, its bar amber past the
typical time of one seed at its size. A neighbour is read only at 16,384, so the "read" column jumps late: the
"between sizes" and "alike so far" columns are the progress before it. **The fleet is in one of three modes**
(893), named on Home beside Now researching and on the Top page: the N-push while the Top page's push list holds a
law, else the zone search while a zone has work (a dex being checked, a law in focus, a zone chosen), else the blind
ladder with its gates. It never mixes them: a run of another mode stops within two seconds, its seed saved, and goes
on when its mode comes back. In the zone search the slots its work leaves free run its lines ahead: the two points
each line may need next, the one it needs read when it comes to it (marked + on the Map page). Within a mode there is no share to set (885):
the fleet takes runs and probes in one order, in the zone search the zone of the law in focus, then the Dex laws read
again (only to the level they are verified at, since 893 also after the check: deeper is the N-push's), then earlier
laws' leftovers; the Map page's first panel says which step it is on and what each has queued. **The N-push** runs
the first law of the push list in a campaign of its own: its whole ladder again from N=64, as many seeds a rung as
the worker count, all at once; when memory binds, fewer at once and fewer seeds, down to 3, then in passes, on two
workers, then on one; when not one seed of the next size fits the host's memory, the law is done and the next is
pushed. Take the first law off, or move another above it, and its runs stop at once, saved. The Top page plots its
ladder ahead with the break-points marked (fewer at once than workers, two passes, one worker) and when it ends,
read again with every finished run. A zone whose ring at 0.1 is not two thirds alike stands at ring 0.01 if that one
is; else the law is a lucky hit, its readings kept. **The pages follow the fleet** (894): each page opens one event
stream (`/api/events`) and reads again when the work changes; an open law page brings a new reading within seconds of
its probe ending. A law pushed to the N limit keeps, on every page, the code it was pushed with.

**If `uv run` fails building `gsd-engine-rs`** with `rustc: symbol lookup error: .../librustc_driver-*.so: undefined
symbol ... version LLVM_...`, the system's `rustc` and its LLVM libraries are from different updates (`which -a
rustc`, `rustc -V`); an upgrade and a reboot do not mend it. Use rustup: `sudo pacman -S rustup`, then `rustup default
stable` (`tools/setup_host.sh` installs rustup when there is no cargo).

**If it fails with `rustup could not choose a version of cargo to run, because one wasn't specified explicitly, and no
default is configured`**: `rustup default stable`, then run again (`tools/setup_host.sh` does the same; `--verify`
reports it).

## The host's memory floor

Admission keeps 10 GiB available and stops children under 8 GiB (`docs/ARCHITECTURE.md`, "Memory admission"). To move
it (the stop line follows 2 GiB under):

    set -x GSD_HOST_MEMORY_FLOOR_BYTES 16106127360   # 15 GiB
    uv run python main.py run

Stopped runs are a line under the ladder's graphs number, "N halted", since 776 (`preempted_memory_floor`); a memory shed loses the chunk, a pause saves
it. A resumed run shows `↻ +21m03s`. While a deep lane's seed waits for room (minutes, at most an hour), the room is
held for it (events `memory_hold_started`, `memory_hold_ended`): seeds of at most 1% of the host still fill the slots
beside it, larger ones wait (747), and analyses are never held back (749). A seed is held for only when it can fit
once the fleet drains, the RAM scratch moved to disk as far as the relief may and nothing running (749, the formula in
`docs/ARCHITECTURE.md`, "Room held for a lane"); one that cannot is not held for and the page says so, e.g. "A
1,048,576 seed asks 22.3 GiB; with the RAM scratch spilled and nothing running, this host gives at most 18.2 GiB": it
waits, refused, and smaller seeds run meanwhile. A hold whose seed stops fitting ends (`cannot fit`) without resting
the fleet.

The verdict says MEMORY_FLOOR only when the headroom is under 1% of the host; above that it is
SEEDS_LARGER_THAN_HEADROOM, every seed that waits asking more than the room left to it. Both say, in words, the hold
(its seed's N and job, its ask, since and until, the room left to other simulations and to seeds of at most 1%, and
that no analysis is held back), a seed refused a hold with what the host gives at most, a rest after holds ran out,
and the RAM scratch (its bytes and what the relief is doing); the same as numbers is `operational_bottleneck`'s
`memory_room` (`hold`, `unfit`, `reach`, `scratch`) on the live overview (749).

## The RAM scratch

Each folder's `var/scratch` is a tmpfs in the folder's own mount namespace (`docs/ARCHITECTURE.md`, "Scratch"); `df`
on the host cannot see it, `uv run python tools/scratch_holders.py` lists every folder's. By hand: `nsenter -t <pid>
-U -m --preserve-credentials ls var/scratch` (pid in `var/run/scratch-holder.json`). **Never delete in it by hand**: a
checkpoint or result may be the only copy. Its alerts: `scratch:pressure` (past 60%), `scratch:full` (no room to
claim). While admission is short (a hold, or a seed refused for memory in the last five minutes) the relief moves it
toward 40% from wherever it is, 4 GiB a tick (749); the capacity verdict says what it is doing. Another folder's scratch is named at each start (`scratch:`), never ended. A fleet that stops with its scratch
empty ends its own holder and says so (`scratch: empty, so its holder ... ended`, 778). From 790 a holder that no
process of its folder has joined for ten minutes (`GSD_SCRATCH_IDLE_GRACE_SECONDS`, 600; 0 turns it off) moves every
file left in its scratch to `var/scratch_parked/` on the folder's disk, paths kept, and ends, so a stopped or
interrupted fleet's RAM is free for another folder within ten minutes and nothing is lost; the next start of that
folder moves them back before anything reads them (`scratch: N file(s) ... moved back from var/scratch_parked`), so a
resume finds its checkpoints where it left them. A start refused for room says when each idle holder ends itself.
`GSD_SCRATCH_SIZE` (`46G`, `50%`) is honoured when it fits beside the others; **a
start that finds no room for its scratch stops first**, naming the others.

## What every start gives back

Before any service, `main.py run` repairs, each said in a console line: `leftovers:` (every fleet process of this user
whose folder is gone, or deleted and made again, is ended; another folder's live fleet is named and left alone;
`python3 tools/leftovers.py` lists them by folder, `--end <folder>` ends a folder's that will not start again);
`repair:` (dead workers' attempts closed, what a full scratch lost requeued, and seeds, analyses and laws failed for
the fleet or storage alone run again once per rung: **no law stays stopped for the fleet's failures**, the operator's
rule; an analysis stopped at the memory ceiling is given back once, with the deepest rung's ceiling); `queue:` (a base-block rung run again waits at the base block's rank); `controls:` (standing controls
made or completed). Every console line is also in `var/log/supervisor.log` as `<UTC time> [<who>] <line>` (`tail -f`
it).

## The calibration table

The table in force is `calibration/probe_calibration.json` (host state); the archive's seed is
`calibration/seed_table.json` (`docs/ARCHITECTURE.md`, "Calibration"). A folder with no table verifies every cell of a
seed of this tree's suite against the code's hashes and adopts it, measuring each family's cheapest cell again (minutes)
and a family whose cell moved again whole. **The seed in this tree is the host's table of 2026-11-18 and 19, measured
whole under analysis 5.3 on build 801 (installed at 805): a first start in a new folder adopts it**, saying so in its
first lines, after measuring one cell a family again (27 cells, seconds to minutes), and measures nothing else; the
lattice starts' references are cells of it. The folder that measured it already holds it as its table in force. Only a
build that changes a file of the table's key makes a folder measure a table again, and such a build says so in its
notes' first lines: the whole table is 189.6 core-hours, about 8 hours on the host's clock with 31 workers (its
`runs`). The host's newest table reaches the seed through a bundle (`evidence/probe_calibration.json`): the
build that reads it installs it when it is current (`python3 tools/collect_calibration.py --install-seed
<bundle>.tar.zst`).

**Measuring the table whole** (767, done on 2026-11-12 and 13, and again on 801 on 2026-11-18 and 19 after d_s's error
changed and four families joined at 800; installed at 805, nothing owed). In a new folder, one command and nothing else:

    uv run python tools/probe_calibration.py --whole

It measures every family's ladder at ten seeds (2,560 cells on 27 families since 800, 390 of them new), the 24 cells
past the ladders, packs the table into one zip and stops: no database, no study, no fleet (`main.py run` would go on
to make the default study and start one). At 767 it took 163.6 core-hours and 7 hours 12 minutes on the host's clock
with 31 cells at once; 105.8 of them were the 174 cells above 262,144 nodes. The four families of 800 add, scaled from
the host's own cells of the 4D, fcc and random families by their edges, roughly 90 to 125 core-hours, most in A4 above
331,776 and D4 above 262,144 nodes: about 11 to 13 hours in all, an estimate. A sandbox rehearsal of 800 (two seeds
to 4,096 nodes, 270 cells) ran whole and its gate passed. One line a cell; the `remaining`
figure in the first lines is a guess from the smallest cells and can say thousands of hours. The large cells come
last and are paced by memory: a line that says memory holds the next cell is the pacing, not a fault, and a paused
cell in btop is a `python3` in state `T` at 0% CPU. **Ctrl-C stops it cleanly**: every finished cell is kept, a cell
that was running starts again from its beginning, and the same command goes on from there; closing the terminal does
the same without the last lines. Its last lines say whether the table is whole, the gate's verdict in plain words (a
failure names the family, the probe and the size, and the table is kept as measured), then `Send this one file, and
start nothing else:` and the zip's path, `calibration_<host>_<UTC>.zip` in the folder. The file is sent whether the
gate passes or not. If the last lines say the table is not whole, the same command measures only what is missing; a
cell held back for memory twice is named with its reason.

**An older table.** Three backfills; on a current table each finds nothing:

    uv run python tools/probe_calibration.py --extend      # the cells past each family's ladder
    uv run python tools/probe_calibration.py --structure   # every census a size limit cut short
    uv run python tools/probe_calibration.py --margins     # d_s's two margins on cells measured before

Each resumes as it goes, paced by memory; **a paused cell in btop is a `python3` in state `T` at 0% CPU**.

**After a new seed**: `python3 tools/calibrate_margins.py --write` and `python3 tools/finite_size_tolerance.py
--write`; after an estimator change, `python3
tools/selftest.py --build-windows --window-seeds 4`. `tests/unit/test_derived_files_say_what_they_came_from.py` fails
until each is current.

## Anchors

The laws the operator marks, in each study bundle's `anchors.json` and read by the advice; anchors decide nothing.
Since 790 a law enters only by the operator's hand: the automatic rule (d_s 0.3 or more off ⟨d⟩ − 1 from 16,384) was
the tree line, and left with it. From another folder, whose database is read without change (every anchor and law
named in `--picks FILE`; existing statuses kept):

    uv run python tools/import_anchors.py <the other folder>

## The structure gate

The gate (rule 8, `docs/DECISIONS.md`) stops laws as `no_finite_dimension` or `no_giant_component`, counted
under the fleet ladder's `gated` and by name in Home's gates box (792; `parked` before 839). Its panel, under the Campaigns table, has one recorded admin control: **the early stage's switch**
(folder-wide, off by default; it changes which laws are refused only once its agreements are in). Its one known
pattern, the branching line, left with the tree line's logic at 790. `structure_gate: false` under `engine.policy` exempts a new campaign.

## Rebuilding stored phenotypes

Derived data only: no decision, no simulation, **no work created**.

    uv run python main.py rebuild-phenotypes --campaign <id> --limit 50   # trial
    uv run python main.py rebuild-phenotypes --campaign <id>              # dry, whole campaign
    uv run python main.py rebuild-phenotypes --campaign <id> --apply

Only laws with a summary for every base rung (four). It recomputes extension rung states from an empty history
(`research/phenotype_rebuild.py`): fix that before a report reads rebuilt phenotypes.

## Reading the dashboard

Classify, Bundle and Anchors are in the study bundle. A campaign is picked on Home's **The study now** cards; with two
or more batches (every campaign with a law budget), Home opens on **All batches**, every batch read together, and the
Reports page reads the first batch. A click on a box's title folds it, and the browser remembers (792). The fleet
ladder's stops are `empty`, `dense`, `discon` (the fact gates), `gated` (every gate that reads the probes, the starts
or the structure, the structure gate's stops among them), `priced` (laws stopped `over_budget` before a run, their next
run priced above its budget; `budget` on 839 and 840) and `total` (every law stopped, a failed one only here), with
`stopped cut` beside them once a design's cut gate has stopped a law (841); `cut`, among the evolving columns, counts
laws with a seed cut at its budget, which the cut gate records and which does not stop the law in 172 or 173; each
gate's own counts are in the gates box under it. A probe's time there is its median over the seeds it ran on, the
share of seeds beneath where that moves the median, and a seed's time counts every run it took, the stopped ones too.
The work left is given twice (839, `observability/work_left.py`): at least what is queued, each seed at its size's
median, and the work expected, each queued seed at its size's mean with the sizes the laws still climbing are expected
to buy, from the share of laws that went on at each size. When something looks wrong:

- **`DECISIONS_BEHIND`** (System): laws waited over ten minutes for a decision; look here first when something seems
  stuck. The proposer's heartbeat's `admission` says why it is open or closed.
- **`MEMORY_FLOOR`** is the fleet at the floor's operating point, not a fault. Held laws are counted beside stranded
  ones; a law held for a full lane is bought as it frees.
- **`SEEDS_LARGER_THAN_HEADROOM`**: the seeds waiting each ask more than the room left to them. It names the room held
  for a lane's seed (and until when), a seed too large to hold for, and what the RAM scratch relief is doing ("The
  host's memory floor", above).
- **Underfilled**: the System page's capacity verdict names the limit; the Campaigns page shows slots and queue.
- `failed` on Now Researching carries its reason on hover; `gap` is no result and no job.

Home's **Filters** panel (857), under the landscape and beside the Top 100, keeps the laws of a kind, a map region, a
group, a batch or settled or not in the landscape, the Top 100 and the fleet ladder alike; the Now researching box
shows every law. **clear** shows everything again. The row of the landscape, the filters and the Top 100 is the
landscape's own height plus the filters' measured height (`--gsd-filter-h`, 859), so the plot is never cut off below
and the Top 100 grows by the same amount.

## Sending evidence for a diagnosis

A build that needs fleet data ships a collector in `tools/` and names it here; run it and upload the zip. Each runs
from the folder whose fleet it measures, needs no arguments, writes only its zip, and prints its path last.

    uv run python tools/verify_claims.py            # what in the documents is still true; a minute
    uv run python tools/collect_calibration.py      # the calibration table, for the archive's seed; seconds
    uv run python tools/scratch_holders.py          # every folder's RAM scratch and what fills it; prints, no zip

A collector that arrives with a newer build can be copied into the running folder's `tools/`: nothing there but the
PostgreSQL helper is in the runtime fingerprint.
