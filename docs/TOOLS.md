# The tools

What `main.py` and each file in `tools/` is for, and its commands; a tool's `--help` lists its options. The recipes
that chain them are `docs/OPERATIONS.md`. Commands are written `python3 ...` (the sandbox, with the prefix file); on
the research host the same command is `uv run python ...`. A tool added or changed changes its section here in the
same build. The tools taken out of the release are in the archives sent beside their builds.

## main.py

The command line of the instrument; with no subcommand it is `run`.

    python3 main.py run [--study <id> | --spec <file>] [--workers <n>] [--no-browser] [--no-dashboard]
                                               # bring up PostgreSQL, the engine, the fleet and the dashboard
    python3 main.py serve [--port 8765]        # the dashboard and reports without the fleet
    python3 main.py pause | resume             # stop or let new simulation and analysis claims
    python3 main.py campaign list | start --spec <file> --reason "<why>" | use <id> | provenance <id>
    python3 main.py campaign pause <id> | resume <id> | close <id> | reopen <id> | delete <id> | archive <id>
    python3 main.py candidate show --id <id> | submit --campaign <id> --file <spec>
    python3 main.py status --campaign <id>     # a campaign's jobs by state
    python3 main.py report --campaign <id>     # every law's rungs and decisions, printed
    python3 main.py extend-only <id> --on | --off
    python3 main.py workload [--split A=1,B=1] [--system-cpus 0,1]
                                               # the work groups' shares and the CPUs the system keeps (856)
    python3 main.py focus --study <id> [--law <id prefix>] [--show]
                                               # the study's best laws one at a time beside its blind draw: their
                                               # neighbours, seeds and depth (groups N and D, 861); the Map page
                                               # starts, steers, stops and shows it (862)
    python3 main.py proposal status
    python3 main.py benchmark                  # the analyzer's battery, which `campaign start` needs: four cells
                                               # of the table read through the analyzer, held to the table's rule
    python3 main.py init                       # schema migrations and the blob store
    python3 main.py backup --output <dir> [--allow-live]
    python3 main.py restore <dir> [--force]
    python3 main.py reset [--yes]              # delete this folder's database, blobs and state
    python3 main.py audit                      # cross-check PostgreSQL against the blobs
    python3 main.py artifacts gc [--apply --confirm GC] | retention [--campaign <id>]
    python3 main.py rebuild-phenotypes --campaign <id> [--limit <n>] [--apply]
    python3 main.py calibration-rekey [--sample <n>] [--apply --justification "<why>"]
    python3 main.py selftest [--quick]         # the deploy sequence and every lane
    python3 main.py sweep [--dry-run]          # end this folder's orphaned children
    python3 main.py hardware                   # the CPU power and temperature sensors

## tools/adopt_calibration.py

Carry a calibration table across an edit: re-measure a sample, re-stamp only if nothing moved.

    python3 tools/adopt_calibration.py [--sample 2]            # dry run
    python3 tools/adopt_calibration.py --apply --why "<the edit>"

## tools/base_block_reading.py

The laws whose chains read nothing on the base block (781; the operator's first gate of 2026-11-14 18:37): from an
unpacked study bundle's report 28 (`every_chain.laws`, each chain's probe means by size, and `seeds`, each seed's
seconds), the control campaigns left out by `study.json`. For every law that ran 4,096 nodes: whether any chain read
any probe at 64 to 4,096, and at 1,024 and 4,096, where a reading is relied on; for each that read nothing there and
was measured at 16,384, what each chain read from 16,384 up, its class in the starts' reading, the decision that took
it there, and the seconds its seeds spent from 16,384 up. Since 782 it also counts what the gate itself did (the laws
`nothing_read` parked, by id, and its row of report 28's gate tree: withheld, let through, spent) and the laws a seed
of which ended at its budget in work somewhere (report 28's `budget_ended_at`, since 806). A reading means a probe mean any seed gave, which a refusing bucket may
still carry: the gate reads the engine's readings, so the two counts can differ, and the reader says both.

    python3 tools/base_block_reading.py <unpacked bundle> [--json <out>]

## tools/baseline.py

Whether the science still holds: the freeze, the calibration, the estimators, the cost.

    python3 tools/baseline.py                     # all four, against the stored baseline
    python3 tools/baseline.py --skip estimators   # the slow one
    python3 tools/baseline.py --candidate <16-efficiency.json or a report bundle>
    python3 tools/baseline.py --adopt <bundle>

## tools/benchmark_campaign.py

Hand-fed law sets and their campaigns: engine parity and speed, the lattice benchmark, depth, the controls.

    python3 tools/benchmark_campaign.py laws <campaign> --bundle <campaign part> [--ids <file>] \
        --output var/specs/<laws>.json
    python3 tools/benchmark_campaign.py lattice-laws --output var/specs/lattice_laws.json
    python3 tools/benchmark_campaign.py start var/specs/<laws>.json --kind engine|lattice|deep|control \
        --spec var/specs/<campaign>.json --reason "<why>"

## tools/boltzmann_known_answers.py

The engines' chains against exact Boltzmann measures (contract `gsd-boltzmann-known-answers-1`,
`research/boltzmann_known_answers.py`): on every graph of 4 and of 5 nodes the engine's own energy gives a law's exact
measure; each run of `run_simulation` starts one chain at a graph drawn from it and one at the empty graph, and
the graphs they end on are counted against it, for laws drawn as the criterion says, on both engines. Judged against
`graph_scale_dynamics/resources/readings/boltzmann_known_answers_criterion_4.json` unless `--criterion` names another,
read on the engines as 806 left them and run again at 840 on crate 0.840.0, the same in every cell. A control may run its chain at a beta of its own (the toggle control's law at
beta 2), and is judged against the law's measure at beta 1. About twenty-five minutes on two cores with `--workers
2`. It changes no engine; it is run again whenever one changes.

    python3 tools/boltzmann_known_answers.py run [--criterion <file>] [--workers 2] --json <out> --md <out>

## tools/budget_reading.py

What the budgets in work did to a study, from its bundle alone (821, the operator, 2026-11-20 02:54: "are these
current budgets for 170 sound?"): each size's budget and budget a node, the seeds cut and the laws they belong to, the
connected laws cut beside the rest, the laws that passed every gate and were then stopped `over_budget`, the seeds
past their budget by law id and the part of the work that led, the host's seconds a unit by mean degree, and what 2,
4 and 8 times a size's budget would buy. That last is an estimate: a cut seed's need is its law's most moves to the
chain cap a size below, times the sizes' ratio, at its own units a move, so it holds only where cost a move does not
climb further; a stopped law's is its own predicted first chunk. A gate's verdict is read from the decisions (a
withholding rule, or the gates a let-through carried in `salted`), not from `gates_ledger.json`, which leaves out
the verdicts on a law stopped `over_budget`. The controls are left out.

    python3 tools/budget_reading.py <bundle or its folder> [--json <out>] [--md <out>]

## tools/build_engine.sh

Build the Rust engine (`gsd_engine_rs`) into the project's Python and print its fingerprint; `main.py run` calls it
when the crate version moved.

    ./tools/build_engine.sh

## tools/bundle_growth.py

What grows with the study, measured on a bundle (838, contract `gsd-bundle-growth-1`; the roadmap's "What grows with
the study, measured on 172 before anything is built"): the bundle's bytes, each table's rows and bytes packed and
unpacked, each campaign part's bytes and report cycle, the controller's last pass (`evidence/system.json`), and each
reader's time and peak memory, each run as a child of its own (its `VmHWM`, read as it runs, so the figure is the reader's and not its parent's). Each quantity
is then carried to 10,000 and 100,000 laws: on a line through this bundle and an earlier one (`--against`, 171's
progress bundle by default, `tests/fixtures/bundle_growth_171.json`, measured at 838 on the sandbox: 1,005 laws,
the decisions table 134.8 MB unpacked, `counters_reading.py` 15 s and 470 MB at its peak), or, with no earlier one, in
proportion to the laws, an upper bound. A peak past the sandbox's 7 GB is marked. About a minute on 171's bundle.

    python3 tools/bundle_growth.py <bundle or its folder> [--against <earlier --json>] [--readers <name> ...|none] \
        [--json <out>] [--md <out>]

## tools/calibrate_census_memory.py

Each calibration family's census memory price.

    python3 tools/calibrate_census_memory.py            # measure and write the committed table
    python3 tools/calibrate_census_memory.py --check    # compare, write nothing

## tools/calibrate_margins.py

d_s's two AICc margin bands for each calibration family, rung by rung, from the seed table.

    python3 tools/calibrate_margins.py            # say whether the committed bands are the seed's
    python3 tools/calibrate_margins.py --write    # derive them from calibration/seed_table.json

## tools/calibrate_structure.py

The structure thresholds the gate reads.

    python3 tools/calibrate_structure.py                  # write the committed table
    python3 tools/calibrate_structure.py --check          # recompute and compare
    python3 tools/calibrate_structure.py --read           # families added since, against the rule
    python3 tools/calibrate_structure.py --read-chained   # the chained cubic family, three ways, at its criterion's sizes

## tools/certificate_known_answers.py

Every chain's own effective-sample count on series whose answer is known (contract `gsd-certificate-known-answers-2`,
`research/certificate_known_answers.py`): rungs of 2 and 8 chains, each its own stationary AR(1) series of 240 points
of known correlation time, read by the count every chain runs (`certificate.own_count`), the rung's the smallest, beside
the count on the chain from empty alone: every chain too few, every chain plenty, one chain too few (K1 to K3), judged
against `graph_scale_dynamics/resources/readings/certificate_known_answers_criterion_3.json` unless `--criterion`
names another. Thirty seconds. It changes no probe and reads no chain of a study.

    python3 tools/certificate_known_answers.py run --json <out> --md <out>

## tools/check_svg.py

Whether a standalone SVG draws the same outside a browser.

    python3 tools/check_svg.py docs/diagrams/rung_flow.svg
    python3 tools/check_svg.py docs/diagrams/rung_flow.svg --render rung_flow.png   # needs PySide6

## tools/cap_reading.py

The mean degree cap read on a study bundle (836, contract `gsd-cap-reading-1`; the operator, 2026-11-21 04:23): for
each lower cap (`--caps`, 12, 16, 20 and 24 by default) the chains and laws that reach it at each size, the laws the
too dense gate would hold back under it (every chain still going at the cap on every seed at the design's sizes in a
row, before the let-through; a law goes on while one chain does), the scoring laws it touches (`finds.json`) and the
memory a seed takes at each size by its densest chain, with the top size's memory scaled to 262,144 and 1,048,576. It
reads every seed's peak degree from the bundle's chains table (836); on a bundle without one it reads each chain's
final degree from report 28 and says that what a cap would touch is at least that. A chain that reaches a lower cap
would have ended there, so its readings at that size are not what this reads. About 10 s on 171's progress bundle.

    python3 tools/cap_reading.py <bundle or its .tar.zst> [--caps 16 24] [--json <out>]

## tools/cluster_reading.py

Every law read at 1,024 on every chain it runs (the eight starts, from `measurements/starts.py` since 824; contract 2)
clustered by what its chains read there and on to 4,096 (k-means, k by the silhouette), the starts' classes, the dimension test's kinds and
the fates read against the clusters after. Recorded, never judged. A k at the edge of the range searched is said as
the search's bound, not a finding (at 736 it was the lowest, 4), and so is the share of laws whose unread probes were
given their feature's mean (748).

    python3 tools/cluster_reading.py <study bundle> --json <out> --md <out>

## tools/collect_calibration.py

The folder's calibration table packed for the archive's seed, and installed as the seed.

    python3 tools/collect_calibration.py                        # on the research host: writes a zip
    python3 tools/collect_calibration.py --install-seed <zip, bundle or table>   # in the build sandbox

The zip holds the table and a manifest (contract `gsd-calibration-collection-1`): which cells of the table's own plan
are current in this tree, the cells past the ladders, how many cells of this tree's whole table (ten seeds on every
ladder) are current, and the gate's verdict in plain words (`in_plain_words`). Those words say whether the table is
whole and, where it is not, which cells are not measured and why (failed with its error, held back for memory, or
measured by other code); how many readings are held to a band and inside it, how many refusals the rule requires and
are held, and how many are shown and held to nothing (`rows_judged`); and each place the gate fails, by family, probe
and size, with what was read and what it is held to. The tool prints them, then one line on what to do, and the zip's
path last; `tools/probe_calibration.py --whole` ends on the same lines. `--install-seed` takes a whole table of this
suite and refuses the rest, each with its reason: another contract's, another suite's, one with cells that are not
current under this tree, one without its cells past the ladders, and a reduced one (fewer seeds or shorter ladders
than the whole table); `--partial` takes an incomplete one, deliberately.

## tools/counters_reading.py

The gates' counters read two ways on a study bundle (831): what each batch of the study learned from its own laws,
recomputed from the bundle's decisions at the fixed points and held to what every learned decision recorded, and what
it would have learned from every batch of the study at the same points, with each decision whose shares change
replayed on them (`decisions/replay.replay`). Since 835 it holds the shares and signatures a law met at its size, not
the rows its decision listed, so a decision 834 made the determined way, which lists none, is compared on what it met
(on 171's progress bundle: 2,687 learned decisions, 0 differ). Criterion `study_counters_criterion.json` (C1 to C4);
exits 1 unless C1 to C3 hold. It reads every decision of the bundle, about 15 s on 170's 9,843; since 842 from a
disk index (`tools/decision_index.py`), one decision at a time, so 139 MB on 172's last bundle where it held 1 GB.

    python3 tools/counters_reading.py <bundle or its .tar.zst> [--json <out>]

## tools/coverage_reading.py

How evenly a stratified blind study drew and ran its declared space, axis by axis within each stratum (contract
`gsd-coverage-reading-1`); about five minutes on two cores.

    python3 tools/coverage_reading.py <bundle> [--sample 100000] [--seed 160] [--workers 2] --json <out> --md <out>

## tools/curvature_known_answers.py

The curvature probe against Ollivier's curvature, edge by edge (contract `gsd-curvature-known-answers-1`,
`research/curvature_known_answers.py`): on ten graphs, `measurements/curvature_probe.curvature_per_edge` over the two
degrees beside Ollivier's curvature of the same edge, solved exactly as a transport, judged against
`graph_scale_dynamics/resources/readings/curvature_known_answers_criterion_2.json`. Four seconds. It changes no probe.

    python3 tools/curvature_known_answers.py run --json <out> --md <out>

## tools/decision_index.py

The decisions of a bundle on disk, for the readers that read every decision (842, contract `gsd-decision-index-1`):
`tables/decisions.ndjson.gz` copied once into a SQLite file in a scratch folder, each row's own line kept, and read
from there law by law (`by_law`), each law's latest decision at a size (`latest`), each law's last decision
(`last_of_each_law`), every row in decision order (`every`) or one row by its id (`row`). The readers hold one law's
decisions at a time, so their memory stays flat with the study's size: on 172's last bundle `tools/counters_reading.py`
went from 1,032 MB to 139, `tools/study_172_reading.py` from 1,033 to 144 and `tools/design_on_a_bundle.py` from
1,278 to 273, each reading as before byte for byte. The disk is the decisions' own size (about 40 GB at 100,000 laws).
A library, not a command.

## tools/deep_reading.py

The laws of a study that reached 65,536 nodes or more, and every start of those that hold, select or grow nothing
(contract `gsd-deep-reading-1`; analysis round 4).

    python3 tools/deep_reading.py <study bundle> --json <out> --md <out>

## tools/diagrams/export_mermaid.js, tools/diagrams/flatten_in_browser.js

A Mermaid chart exported as a flat standalone SVG through Playwright's Chromium (`docs/agent/ENVIRONMENT.md`, section
9); check it with `tools/check_svg.py`.

    node export_mermaid.js <chart.mmd> <out.svg> "<title>"

## tools/d_s_error_check.py

d_s's reported error judged against the spread of its readings over eight seeds (800), on the held-out graphs of
`graph_scale_dynamics/resources/readings/d_s_error_criterion.json`, committed before they were measured; it writes
`d_s_error_judged.json`. The error is the bootstrap over the walk's own probes; the analytic bound beside it ran about
ten times the seeds' spread.

    python3 tools/d_s_error_check.py --json <where to write the judged reading>

## tools/design_on_a_bundle.py

A study's design on another study's bundle (841, contract `gsd-design-on-a-bundle-1`): every decision of the bundle's
own campaigns (the controls apart unless `--every-campaign`), law by law in the order they were made, replayed from
its recorded inputs under the policy the design gives (`--design 173`, or a design file), the ledger's state as
recorded. A law is followed until the design stops it; where the design lets it on and the record has nothing later
(the record stopped it, bought another run, or the law was in flight) it counts as going on and is not followed.
By size: the laws followed, the ones a gate that acts under the design would hold back, the ones of those that go on,
the stops by rule, the verdicts of the gates that only record, the laws with a seed cut at its budget, and the seconds
a law takes, evolving and probing, from report 28's seeds. It carries each size's shares to the design's number of
laws (`--laws` for another), with the core-hours, and lists the bundle's scoring laws the design would stop below the
size they score at. A seed's ending is the record's: one the record cut on a budget the design doubles still counts
as cut. On 172's progress bundle it gives back 172's recorded stops under 172's design (about 750 core-hours against
880 committed), and study 173's predictions are taken from it under 173's (12 s, 9,000 decisions). Since 842 it
reads one law at a time from a disk index (`tools/decision_index.py`): 273 MB on 172's last bundle, 1.3 GB before.

    python3 tools/design_on_a_bundle.py <bundle or its folder> --design <study or file> [--laws <n>]
                                        [--every-campaign] [--json <out>]

## tools/dimension_reading.py

A study's bundle read with the dimension test (contract `gsd-dimension-reading-1`): every chain of every law from
1,024 nodes judged by `research/dimension_test.judge_chain` as frozen at 729; the laws grown into a dimension from empty
or the random start, the lattice starts that changed theirs, each marked a line or beyond what the test was checked on,
and what the old rules did with them.
The test reads a chain only at the sizes it can use (one piece, a degree inside its window), so a chain whose larger
sizes fell apart or left the window is judged at its last usable one: each is named with its top size and why every
larger size was dropped, and counted (748; the dimensional ones on the page, all in the JSON).

    python3 tools/dimension_reading.py <study bundle> --json <out> --md <out>

## tools/dimension_test.py

The dimension test on its known answers (contract `gsd-dimension-test-1`, `research/dimension_test.py`): `measure`
builds and reads one part of a criterion (by default 808's, `graph_scale_dynamics/resources/readings/dimension_test_criterion_4.json`;
`--criterion` takes an absolute path), `judge` reads the measured parts with the frozen rule.

    python3 tools/dimension_test.py measure --part training|held_out --out <file> [--workers 2]
    python3 tools/dimension_test.py judge --measured <file> [<file>] [--json <out>] [--md <out>]

## tools/disordered_reading.py

Whether any chain reached a disordered geometry: a reader beside the score. On a study bundle it reads the study's
laws alone: a campaign its design does not name (the standing controls) is named and left out (837).

    python3 tools/disordered_reading.py calibrate --run <detection run> --criterion <criterion> [--rule 2] --json <out>
    python3 tools/disordered_reading.py bundle <unpacked study bundle> [--rule 2] --json <out> --md <out>

## tools/finite_size_tolerance.py

The settling rule's finite-size slack, fitted from the seed calibration table.

    python3 tools/finite_size_tolerance.py            # whether the committed fits are current
    python3 tools/finite_size_tolerance.py --write    # fit again from calibration/seed_table.json

## tools/lattice_cost.py

What the six lattice starts cost above 4,096 (842, contract `gsd-lattice-cost-1`; the operator, 2026-11-21 19:52:
"that's the one I want to investigate more on for sure"), from the bundle's chains table, which carries each chain's
moves, accepted moves, work in the campaign's unit and seconds since 841. By size, the twins' work (the chains from
empty and from random) and the lattices', by start, and the lattice chains frozen there (no move accepted on any of the
law's seeds: no edge changed); from 4,096 on, the lattices' share of the work and of the engine's seconds; for each
scoring law, the share of its work above 4,096 its lattice chains took and whether a twin chain earned any of the
score's points. A bundle made before 841 has no chain's work, and the reader says so.

    python3 tools/lattice_cost.py <bundle or its folder> [--json <out>]

## tools/starts_bundle.py

Every law's starts in a study bundle, read against what was decided for it.

    python3 tools/starts_bundle.py <bundle> [--json <out>] [--md <out>] [--laws <laws out>]
        [--against <an earlier bundle's laws file>]

## tools/starts_check.py

The starts' reading checked on graphs whose answer is known, against the references the calibration table's cells
give (`docs/ARCHITECTURE.md`, "Calibration"): this folder's table, or another's with `--table`. The references are
measured by the fleet with its table, at its first start; no command writes them. Its chains are the starts a law
runs (`measurements/starts.run()`), and its criterion by default
`graph_scale_dynamics/resources/readings/starts_known_answers_criterion.json`. About eight minutes on two cores.

    python3 tools/starts_check.py check --judge <criterion> [--out <file>] [--table <a calibration table>]
        [--first-seed 10 --sizes 1024,4096,16384]   # held out: reported, not judged

## tools/fleet_reading.py

How a study's fleet spent its simulations, from a study bundle, and between two bundles.

    python3 tools/fleet_reading.py <bundle> [--against <an earlier bundle or its reading>] [--json <out>] [--md <out>]

## tools/gate.py

The gate's two lanes, one command each (`docs/OPERATIONS.md`, "The gate's two lanes, on any host").

    python3 tools/gate.py fast [--allow-skips] [--since <rev>]   # what changed since the build, and the release's checks
    python3 tools/gate.py full [--allow-skips]                   # every test, PostgreSQL's lane beside the rest

## tools/gate_variants.py

The gates under other settings, on a study bundle (838, contract `gsd-gate-variants-1`; the roadmap's reading of 172:
"the fact gates on three sizes in a row against one and four", "one die against 171's separate dice"): every decision
of the study's own campaigns (the controls apart unless `--every-campaign`) replayed from its recorded inputs
(`decisions/replay.replay`) with one policy setting changed (`--variant key=value`, or `key=flip` for a switch;
`fact_sizes_in_a_row=1`, `fact_sizes_in_a_row=4` and `one_die=flip` by default), the counters as they were. It counts
the decisions that move, by size and from what to what, and each law whose fate changes (stops where it went on, or
goes on where it stopped) at the first size it would, by id. It is first order: a law the setting would stop earlier
has no later decision to read, and one it lets on has none past where it stopped. It streams the decisions table, so
its memory stays flat (39 MB and 11 s on 171's progress bundle, which it reads as 835 did: with one die, at 1,024, 45
laws stopped would have gone on and 28 that went on would have stopped).

    python3 tools/gate_variants.py <bundle or its folder> [--variant <key=value> ...] [--every-campaign] [--json <out>]

## tools/gates_map.py

The map of gates and streams, drawn from the code.

    python3 tools/gates_map.py            # write docs/diagrams/gates_and_streams.json and .svg
    python3 tools/gates_map.py --check    # exit 1 when the committed map is not what the code says

## tools/gsd_pgdata_cow.py

Copy-on-write placement of PGDATA, and moving it to a nodatacow directory.

    python3 tools/gsd_pgdata_cow.py inspect
    python3 tools/gsd_pgdata_cow.py migrate [--yes]

## tools/held_lattice_exactness.py

How near its exact lattice each lattice a study's laws held ends.

    python3 tools/held_lattice_exactness.py <unpacked study bundle> --json <out> [--md <out>]

## tools/history_reading.py

The laws whose starts end apart, by what keeps them apart, and every law whose lattice keeps its reach while
changing up close (contract `gsd-history-reading-1`; analysis rounds 2 and 3).

    python3 tools/history_reading.py <study bundle> --json <out> --md <out>

## tools/holders_lowest_energy.py

Where each law that holds a lattice (`holds`, `selects`, `grows` or `converts`) ends lowest in energy: a held
lattice, alone or not, or another start (contract `gsd-holders-lowest-energy-2`), from report 28's starts' reading
`lowest`, which a bundle made on 742 or later fills. Another start is apart only by the margin a held lattice needs
(2% or two standard errors); within it, `another start, not apart` (748: before, any margin counted, and `converts`
was left out).

    python3 tools/holders_lowest_energy.py <study bundle> --laws <its starts' law file> --json <out> --md <out>

## tools/holds_reading.py

Which holds survive: the laws holding a lattice from one bundle's law file to the next.

    python3 tools/holds_reading.py <law file> <law file> [...] [--md <out>] [--json <out>] [--judge <criterion>]

## tools/import_anchors.py

Import anchors from another GSD folder, read without changing it.

    python3 tools/import_anchors.py <the other folder> [--picks <file>]

## tools/lattice_starts_known_answers.py

The six lattice starts of study A, each built at the ladder's sizes from 1,024 to 65,536 nodes and read by every probe
as the fleet reads the graph of a chain from a given start (contract `gsd-lattice-starts-known-answers-1`,
`research/lattice_starts_known_answers.py`), on three seeds, judged against a criterion
(`--criterion`, none in the tree): which probes read and which refuse, and whether each cell's median lies in the band of the start's dimension. About five minutes on two cores. It
exits 1 when the reading does not pass. It changes no start a campaign runs.

    python3 tools/lattice_starts_known_answers.py run --criterion <criterion> --workers 2 --json <out> --md <out>

## tools/laws_of_a_bundle.py

Every law of a study's bundle, whole (860): taken from the bundle's laws table where it carries `spec` (since 860),
else a blind batch's laws drawn again from its design's search seed on this tree and the standing controls' from
their criterion, each checked by its fingerprint against the law's id. A bundle whose design differs from this tree's
(its `design_sha256`) is refused. Exit 0 when every law is had whole.

    python3 tools/laws_of_a_bundle.py <bundle folder>                       # per campaign: carried, drawn again, neither
    python3 tools/laws_of_a_bundle.py <bundle folder> --out laws.ndjson.gz  # one row per law: campaign, id, spec

On 174's bundle of 2026-11-24 23:19Z: all 10,005, the 10,000 blind laws drawn again bit for bit in 3.4 s.

## tools/law_rows.py

No command: every law of a study's campaigns as one compact row, from each campaign's report 28, for the readers. Its
`LATTICES` are the one definition's (`measurements/starts.py`); a reader that lays out a column or a key a lattice
(`tools/starts_bundle.py`, `tools/sample_reading.py`) takes the lattices its bundle's laws were given
(`lattices_given`), so a bundle of three lattices reads as it did and one of six shows six. Since 771 it also loads a
bundle whole for a reader, as the judges' loader did: `study` gives each campaign with its report 28, its ledger, its
chains and the sections that failed or are absent, and `drawn_laws` every blind law with its fate, regime and score.

## tools/ledger.py

The calibration ledger (`docs/ARCHITECTURE.md`, "The calibration ledger"): the append-only record of every probe
group's readings on the known families, one file a group and fingerprint under `calibration/ledger/`. Nothing in it is
rewritten; a probe that changes files its readings under its new fingerprint beside the old.

    python3 tools/ledger.py from-table [--table calibration/seed_table.json]   # file the table's cells, measuring nothing
    python3 tools/ledger.py status [--max-nodes 65536]                          # cells held and missing, by group
    python3 tools/ledger.py measure --group quantum_walk [--max-nodes 65536] [--workers 16] [--limit 100]
    python3 tools/ledger.py attest --group quantum_walk [--sample 8]            # re-measure, file the agreement
    python3 tools/ledger.py verify                                              # every file's hashes and chain
    python3 tools/ledger.py snapshot                                            # the roots of the current view

`from-table` files each cell under the fingerprint that measured it (the table's analysis and estimator), once: run
again, it writes nothing and names any cell held with other values. `measure` takes only the cells the group's current
fingerprint does not hold, so an interrupted run resumes where it stopped. `attest` exits 1 when a re-measured cell
disagrees beyond the tolerance. `snapshot` prints `root` (the records: who measured what, when) and `content_root`
(the values alone: two hosts that measured the same cells under the same fingerprints to the same bytes print the same
`content_root`).

## tools/leftovers.py

What fleets have left running on this host, by folder, and ending them.

    python3 tools/leftovers.py                   # every fleet process of yours, by folder: live or gone
    python3 tools/leftovers.py --end-gone        # end those whose folder is gone (what every start does)
    python3 tools/leftovers.py --end <folder>    # end every process of a folder that will not start again

## tools/neutral_moves_check.py

Whether a hold is the law's or the rounding's (`run`, `judge`), and every hold of a bundle marked by what its law sees
(`mark`).

    python3 tools/neutral_moves_check.py run --criterion <criterion> --out <run.json> [--md <out>] [--workers 2]
    python3 tools/neutral_moves_check.py judge <run.json> --criterion <criterion> [--json <out>] [--md <out>]
    python3 tools/neutral_moves_check.py mark --bundle <study root> --laws <the starts' law file> --json <out> --md <out>
    python3 tools/neutral_moves_check.py select --bundle <study root> --laws <law file> --out <file>
    python3 tools/neutral_moves_check.py scorers <run.json> --bundle <study root> --laws <law file> --out <file>

## tools/operator_units.py

Each operator's own unit: its typical energy change a move on a reference sparse graph.

    python3 tools/operator_units.py            # print the table
    python3 tools/operator_units.py --write    # write graph_scale_dynamics/resources/calibration/operator_units.json

## tools/score_known_answers.py

What "settles" means for the score (`observability/law_score.py`), judged on known answers committed first
(`graph_scale_dynamics/resources/readings/score_known_answers_criterion_3.json`; its reading,
`docs/readings/score_known_answers_3_judged.md`, names the table it trained on). It sets each probe's relative margin at
each ladder size, and the Einstein relation's tolerance, from the calibration seed's exact lattices and fractals by the
criterion's rule, writes them to `graph_scale_dynamics/resources/calibration/score_margins.json`, and judges them on
the criterion's seventeen structures on seeds 51 to 53. Since 846 it also trains the score's reach rule (q, twice
the widest excess of the table's lattices, the margins' `reach` block since 848) and judges the score's rules of 846 on
criteria 4 and 5 (`score_known_answers_criterion_4.json` and `_5.json`, their pages in `docs/readings/`): the
seventeen structures again, with their reach, and strips, tubes, trees of long paths and soups of cycles built to fool
a probe. `measure` builds and reads criterion 5's structures and crossovers (`research/probes_known_answers.measure`,
219 reads, 31 minutes on two workers in the sandbox) and writes their rows; the reading itself takes a second. It
exits 0 when criterion 3 passes; criteria 4 and 5, kept as they were judged, are printed beside it.

    python3 tools/score_known_answers.py                     # the reading, printed; writes nothing
    python3 tools/score_known_answers.py --write             # the margins and their reach rule, three judged files and pages
    python3 tools/score_known_answers.py measure --workers 2 # build and read criterion 5's structures

## tools/score_list.py

The score's list, read on a pilot's record (the chain from empty, which a bundle's rung rows carry; a record is what
`tools/pilot_difference.py --record` writes, and none is committed since 785) or on a study bundle, where every chain of every law is scored again from report 28's values and its starts' reading's fates, one
campaign's report at a time. Each scored law with its points (of 15 since 784), the size it reached them at and why; a
control's given start is named by its family (report 28's `given_family`). A bundle carries no seed's settle class,
so on a bundle the score reads its floor, its scale and its next step, and counts every seed (848).

    python3 tools/score_list.py <study bundle, or a record> --md <page> --json <file>

## tools/perturb_reading.py

Study 175's verdicts, read on its bundle (847; `gsd-perturb-reading-2` since 849): for each holder of
`study_175_holders.json` found in the bundle, what its scoring chain read at its top size in 174 (the median of its
probes there, and its mean degree), whether its run again reads the same values at every size it has decided, and
each variant's state at each radius. A variant is read when its law was decided at the holder's size, other than by
buying longer chains there: alike (the same chain at that size, its d and mean degree within the criterion's tenth) or
unlike. One stopped, parked or done below that size ended there and is not alike, as the criterion has it; one still
running is unread. A radius holds at three alike, fails when its alike and unread together cannot reach three, and is
open otherwise. The verdict is the criterion's (`study_175_criterion.json`): a stream when the 1e-9 variants do not
hold, a point when 0.001 does not, or a region to the largest radius up to which every radius holds; a holder whose
deciding radii are open is open, with the region it has so far. With every variant read it is 847's verdict. Beside
it, recorded only and added after the study started: kept or made, which of the holder's other starts read alike its
chain at its size (made when one does), and its chain's accepted moves per edge there (`tables/chains.ndjson.gz`).
The laws are made again from the design, so a law is told by its id.

    python3 tools/perturb_reading.py <bundle of study 175> --md <page> --json <file>

## tools/catalogue_reading.py

Every law of a bundle placed in the catalogue of behaviours (850; `docs/ARCHITECTURE.md`, "The catalogue of
behaviours"), control campaigns left out: each law's kind at every size report 28 reads and at its deepest; for the
laws read from 16,384, each kind called at 1,024 and at 4,096 against the kind at the deepest size (held: the early
call was right; caught: the deepest kind was already called); the lattice chains still at 1,024 and 4,096 and whether
they stayed still; and every scoring law under the score in force (gsd-law-score-9 since 856: a still lattice scores
1), each beside what it scored with no chain read as still. Since 856 a chain is also read for the small-world kind
(the catalogue's `rule.small_world`), which needs its reach and the size a quarter below it, and each law is scored
with its chains' accepted moves an edge from `tables/chains.ndjson.gz`, so a bundle made before 856, whose report 28
has no `moved` column, is scored as the fleet scores it now. Seconds on 175's bundle, under three minutes on 174's.

    python3 tools/catalogue_reading.py <bundle> --md <page> --json <file> [--no-scores]

## tools/small_world_reach.py

The random reach the small-world rule assumes, read on known answers (856): the random start
(`measurements/random_starts.build`) at mean degrees 2 to 32 and 1,024 to 16,384 nodes, three seeds each, by the
estimator's own reach (`estimators.volume_growth`), against ln(N/2)/ln(k) plus the catalogue's offset; and the six
lattice starts as built, with each one's reach over the random reach of its degree. Exit 1 when a random start reads
more than 1.05 steps off or past the rule's band. About 35 seconds.

    python3 tools/small_world_reach.py --json <file> --md <page>

## tools/map_first_ten.py

Where a study's map starts (856): the laws of one or more bundles read together by `tools/catalogue_reading.py`
under the score in force, a law in two bundles keeping its higher score; the ten that score above 1 and whose law is
rebuilt exactly (from the bundle's ledger by its fingerprint, or from a study's design when given as `STUDY=path`),
by score, depth and id; and for each its partner, the nearest law of the same terms and dynamics, at least 0.001 away,
whose kind at 4,096 differs. It wrote `study_176_first_ten.json` from the two baseline bundles in two minutes.

    python3 tools/map_first_ten.py 174=<bundle> 175=<bundle> --write <file.json>

## tools/top_laws_alike.py

What the laws the score settles share, read on a study's bundle (847): the drawn laws the score settles, their
scoring start not frozen, beside the laws that reached 4,096. Each term's share among them
over its share among those (with its signs), their term sets with the chains and dimensions they read, the same by the
dimension read, and their dynamics (zero temperature, beta at finite temperature, locality, swap share). The laws'
specs are the law ledger's of report 28; `--as-carried` reads the scores the bundle carries instead of scoring again.

    python3 tools/top_laws_alike.py <bundle> --md <page> --json <file>

## tools/outputs_of_a_law.py

What this tree puts out for one law: the sparse anchor law grown from five of the eight starts on both engines (64
nodes on the Python engine, 64 to 1,024 on the Rust one, two seeds), with each seed's envelope, metrics, curves and
chain record, and the law's readings and decision made from them. Its design is
`tests/fixtures/a_design_of_four_starts.json` (empty, random, square, cubic, 4D; since 823, when it replaced the
starts of build 755 and the record was written again on the untouched tree with the new design first). Clock readings are left out and long arrays folded to a
digest, so two runs on one tree write the same bytes. It is how a change that should move no output, or only named ones,
is held: each build is held to the record the build before it wrote (`--write` on the untouched tree first, then
`--against` it after each step; 797 against 796's).

    python3 tools/outputs_of_a_law.py --write <file.json or file.json.gz>
    python3 tools/outputs_of_a_law.py --against <file an earlier tree wrote>   # names every output that changed; exit 1 if any

`--against` compares the two files key by key, every name as written: a renamed key is a change (822). `reports`
builds every numbered report from a snapshot, as `tools/report_audit.py` does.

## tools/package_release.py

Validate the tree and write the numbered source archive, `GSD<N>.tar.zst`.

    python3 tools/package_release.py --output <dir>          # the full lane, then the archive
    python3 tools/package_release.py --fast --output <dir>   # the fast lane (never two releases in a row)

Refused in a folder where a fleet or a dashboard is live (`tools/gate.py`'s refusal), and while a switch that makes a
test write its own fixture is set (`GSD_WRITE_REPORT_SNAPSHOT_FIXTURE`). Since 742 it also refuses: a tree that moved
while its lane ran (every shipped file but those the release writes, hashed before the lane and checked after); a
moved `tests/fixtures/committed_readings.json` its notes do not name, against the last build's record of its
files; and `--skip-tests`, `--skip-compile` or `--skip-wheel` without `--no-bump`, which then
writes `GSD<N>_unverified.tar.zst` and spends no number.

Since 748 one tree packs to the same bytes: members in path order, owner 0:0 with no names, mode 644 or 755, and one
time for the whole build (2026-01-01 00:00 UTC plus the build number in seconds, so a folder unpacked over another
build keeps no stale bytecode). A link ships as a link, never as what it points at (a link to `.env.postgres` would
have shipped the password); a link out of the tree, or a file reached through one, is refused. The archive is checked
against the hashes taken before the lane (`tested_tree`), and only the files the release writes itself against the
tree as it is, so a file that moved after the lane cannot ship. Since 837, in a git checkout it ships only the files
git tracks, and names every file it left out (`left out, not tracked by git: ...`), so a host's or a tool's leftovers
in the tree never reach an archive; an unpacked archive with no git ships what it holds.

## tools/partial_rows.py

No command: the rows a long run has so far, written when it fails, for the tools that run for hours.

## tools/pattern_scan.py

What the readers do not look for: every drawn axis against every outcome, found on half the campaigns and kept only
where the other half repeats it.

    python3 tools/pattern_scan.py <study bundle> [--md <out>] [--json <out>] [--judge <criterion>]

## tools/pilot_difference.py

A study's bundle against another bundle of the same seeds, or a record written from one, law by law (`docs/OPERATIONS.md`,
"The pilots"): how a replication is read against the study it replicates. No record is committed since 785. Every law
whose last decision, depth or reading moved, by id with both values; a record is a bundle's blind laws, each with its
decision and its readings at every size. A law a deep size's lane held (its last decision `deep_lane_full` or
`lane_resumed` in either run, read from the bundle's `tables/decisions.ndjson.gz`) and a law named before the run are
listed and not judged; since 806 no clock ends a seed, so a seed that ended at its budget in work is judged as any
other. R1 asks
only that every law of the record is in the run: a run of a larger budget holds more, counted, listed in the JSON
(`only_in_the_run_laws`) and read as a wide pilot's (the operator, 2026-11-13 22:06). Exit 1 when a law of the record
is missing, or one moved that none of the three explains.

    python3 tools/pilot_difference.py <bundle> --against <a record, or another bundle of the same seeds> \
        [--declared <law,law>] [--md <out>] [--json <out>]
    python3 tools/pilot_difference.py <bundle> --record <out.json>      # write the bundle's record and stop

## tools/pilot_reading.py

A pilot's predictions read off its bundle (796): each scorer of the study's own campaigns by its kind (a ring, no
edge changed, reshaped the same per node, thinning, irregular), and the criterion's predictions K1 to K5 and K8 on
every law, each with the laws that break it; each study's criterion says which it is read for. The
steady chain is `decisions/steady_chain.block`, the gate's own reading.

    python3 tools/pilot_reading.py <study bundle, unpacked> [--json out.json] [--md out.md]

## tools/planted_faults.py

Stable's first half, run right before study A (made at 838, contract `gsd-planted-faults-run-1`): each fault of `tests/fixtures/planted_faults.json`
planted alone in a scratch copy of the tree (a git worktree of HEAD outside the tree, the uncommitted files copied in,
`calibration/probe_calibration.json` with them), and the tests that read the fault's module run there with
`PYTHONPATH` on the copy and `-x`: caught when one fails, let by when all pass. A fault's tests are every unit and
scientific test file that names its module (`through_its_readers`: and every module that imports it), unless it lists
its own. Each test set runs once unplanted first; a set that fails unplanted is said and its fault not judged. Then
the file is given a neutral edit (a line `PLANTED_NEUTRAL_EDIT = None` at its end), and every test that fails on it
holds the file's bytes (a fingerprint, the science freeze, a recorded hash), not what the code does: it is set aside
(`--deselect`) for that file's faults and counted in the record, since it would catch any edit. A
fault's site must be in its file exactly once, and its file in the science freeze
(`tests/unit/test_the_planted_faults_are_planted_where_they_say.py`). Each fault names the numbers it would corrupt
(`tests/fixtures/numbers_and_checks.json`, below). Exits 1 if any fault is let by. Every test set runs whole twice
(unplanted and with the neutral edit) before its faults, so the whole list takes a few hours on two cores (838's
partial run: the 21 files that read `measurements/estimators.py`, about 12 minutes a whole run); the tree itself is
never written.

    python3 tools/planted_faults.py [<fault id> ...] [--list] [--json <out>] [--md <out>]

`tests/fixtures/numbers_and_checks.json` is the other half: each number the paper states, the code it passes through
(the science freeze's files) and the checks that hold it, each a known answer, two implementations that agree, or a
replay (`tests/unit/test_every_number_is_traced_to_a_check.py` holds every named test to exist).

## tools/positive_control.py

The positive control and the other controls' check (`docs/OPERATIONS.md`, "The controls").

    python3 tools/positive_control.py laws --output var/specs/positive_control_laws.json
    python3 tools/positive_control.py check <study bundle, or its campaign part> [--criterion <file>]   # a criterion of several campaigns is judged campaign by campaign
    python3 tools/positive_control.py sandbox --sizes 4096 16384 --seeds 1 [--criterion <file>]

## tools/postgres_instance.py

The folder-contained PostgreSQL: a server in an unprivileged user namespace, reached over a Unix socket.

    python3 tools/postgres_instance.py ensure | up | down | stop | status | logs
    python3 tools/postgres_instance.py runtime            # whether user namespaces work here
    python3 tools/postgres_instance.py reset-credentials  # re-key the cluster; refused while the folder's fleet runs

The server runs as PID 1 of its own PID and IPC namespaces, so `postmaster.pid` always names PID 1 and PostgreSQL's
own data-folder lock cannot tell a live server from a stale one: a second server in another namespace would take the
folder. Since 748 the start takes an exclusive `flock` on `instance/postgres/server.lock` and hands that descriptor to
the server, so the lock lasts exactly as long as some process of the server holds it. A start while it is held starts
nothing, and `status`, `stop` and `main.py reset` call the server running while it is held (or while a server started
by 747 or earlier, which holds no lock, is alive by `supervisor.pid`). The lock file records the supervisor's pid and
the server's log, which `logs` and the fleet's database watchdog read; a stop with no usable record finds the server by
the processes that hold the lock. A failed `reset-credentials` writes `scram-sha-256` back and has the server read it
(SIGHUP to the postmaster), or stops it, so no server is left accepting `trust`. `.env.postgres` is written to a
temporary file, flushed to disk, renamed, and the folder flushed after.

## tools/prepare_environment.sh

The agent sandbox's bring-up, run as root (`docs/agent/ENVIRONMENT.md`, section 10).

    setsid nohup ./tools/prepare_environment.sh > /home/claude/prepare.log 2>&1 < /dev/null &
    ./tools/prepare_environment.sh --check

## tools/probe_calibration.py

The calibration table by hand, the pipeline trial and the sweep scan.

    python3 tools/probe_calibration.py --whole                         # the table whole, collected; then it stops
    python3 tools/probe_calibration.py --probe-ladders                 # the suite: resume or complete
    python3 tools/probe_calibration.py --probe-ladders --recompute     # deliberate full regeneration
    python3 tools/probe_calibration.py --extend                        # rungs past the ladders, to about 4 M
    python3 tools/probe_calibration.py --structure                     # census of every cell that lacks one
    python3 tools/probe_calibration.py --margins                       # d_s's two AICc margins on every cell
    python3 tools/probe_calibration.py --probes                        # pipeline trial (seconds)
    python3 tools/probe_calibration.py --sweep-scan                    # ESS against sweep budget

**`--whole` is the calibration build's one command** (767; the recipe is `docs/OPERATIONS.md`, "The calibration
table"). It runs, in order, the three functions the flags beside it and the collector run: the suite on every family's
ladder at ten seeds (`calibration/suite.run_suite`), the cells past the ladders (`calibration/extension.run_extension`)
and the collection (`tools/collect_calibration.collect`). It ends on the gate's verdict in plain words and the one
file to send, and starts nothing else: no PostgreSQL, no study, no fleet. The table is written after every cell, so
the same command goes on from where it stopped and measures no finished cell again; typed on a whole table it
measures nothing and collects again. A table of another suite found in its place is copied under
`var/calibration/history/` and a new one is measured. It takes `--workers` and `--var` only; any option that would
make another table is refused. Exit 0 when the table is whole and the gate passes, 1 when a cell is not measured or
the gate fails, 130 after Ctrl-C. `GSD_CALIBRATION_PROFILE=reduced` (with `GSD_CALIBRATION_REDUCED_SEEDS` and
`GSD_CALIBRATION_REDUCED_MAX_NODES`) makes a rehearsal of it: the table and its zip go under `var/calibration/`,
nothing past the ladders is measured, and its last lines say it is not the table a study reads.

**Ctrl-C under `--whole`.** A keypress reaches every process of the terminal's foreground group, and until 767 each
worker of the suite answered it with a traceback of its own while the run ended without a word on what was kept. The
command blocks SIGINT in its main thread before the first worker is spawned: a worker, in the pool or a process of
its own, is born with the signal mask of the thread that spawns it, so no worker hears the keyboard. A thread waits
for the signal (`signal.sigtimedwait`) and raises `KeyboardInterrupt` in the main thread (`_thread.interrupt_main`),
within a second; the suite's own `finally` ends the running cells, the command ends what is left of the pool and
says how many cells are kept. Multiprocessing's resource tracker is started before the signal is blocked, because
its first start unblocks SIGINT and SIGTERM in the thread that starts it (`resource_tracker.ensure_running` blocks
them around its spawn and then unblocks them, whatever the mask was): measured on Python 3.11, 3.12 and 3.13, the
workers are born deaf only with the tracker already running. Where SIGINT is ignored at entry, as in a detached
run, nothing is arranged for it. **Ended from outside** (SIGTERM, as btop's kill sends, or SIGHUP, a closed terminal)
it stops the same way and exits 128 plus the signal's number: before 767 a suite ended so left its pool's workers
behind, idle and held by nothing, since a worker of Python's process pool never learns that its parent is gone
(measured: two workers still there ten minutes after their run was killed). SIGKILL still leaves them; they are the
`python3` processes whose parent is 1 and whose command line holds `multiprocessing.spawn`.

## tools/probes_baseline.py

Every probe's reading, to the last digit, on a wide set of small graphs, and what moved between two such files (contract
`gsd-probes-baseline-1`, `research/probes_baseline.py`): the seven lattices `measurements/known_answers.py` builds, at
64 to 65,536 nodes, and 320 graphs of 9 to 3,025 nodes drawn by seed, each named for whether it has a dimension (random
and random regular graphs, random recursive trees, preferential attachment and rings with rewired edges, which have
none; random geometric graphs in the plane, diluted squares and lattices of 1, 3 and 4 dimensions, which have one).
Write it before a probe is touched and compare after: a mended probe moves its own numbers and no other's, and the
comparison names every reading lost or gained by kind of graph. It caught three mistakes in 760 to 762 before any test
did. About five minutes on two cores.

    python3 tools/probes_baseline.py write <file> --workers 2
    python3 tools/probes_baseline.py against <before> <after>

## tools/read_bundle.py

The first read of a study bundle (or one campaign's), on one screen.

    python3 tools/read_bundle.py <study bundle, or its folder>
    python3 tools/read_bundle.py <study bundle> --against <an earlier study bundle, or its reading .json>
    python3 tools/read_bundle.py <study bundle> --json <where to save its reading>

## tools/replay_bundle.py

Every decision of a study bundle replayed from the bundle alone (since 798). The bundle's
`tables/decisions.ndjson.gz` holds every row of `engine_decisions` of every campaign in it, its facts, inputs and
context as the decider stored them; each is replayed through `decisions/replay.replay_matches` and compared on its
action, rule, reason, sizes, priority and facts. It prints the counts by campaign and by rule, `same_rules` (whether
the policy fingerprint the decision recorded is this build's), and every decision that differs or has no inputs. A
released hold carries no inputs and is counted apart. Exit 0 when every decision with inputs replays and none lacks
them, 1 otherwise, 2 for a bundle without the table. Report 28's `decision_record` still replays a sample inside the
folder; this replays the whole from what the operator sends.

    python3 tools/replay_bundle.py <study bundle, or its folder>
    python3 tools/replay_bundle.py <study bundle> --json <where to save every count and mismatch>

## tools/replication.py

The replication harness, paper 1 (Kelly, Trugenberger and Biancalana), whose shared parts serve every paper: a
published model run by its own rules and read by this instrument. `--plan <criterion>` runs every run line of a
committed criterion in one pool, keeping the runs an output file already holds (`docs/OPERATIONS.md`, "The replication
programme"). Every log G is the 2019 paper's, G = 1/beta-tilde with beta-tilde = beta N^(1 - 2/D): the coupling is
renormalised to grow as N^(1 - 2/D) (section 3, after equation 24), which puts the two-dimensional crossing at the
paper's log G of about 2. Before 748 it was beta N^(2/D - 1), the form printed after equation 24, kept as
`log_g_as_printed_at_half_order`; in two dimensions the two agree, and `--read` gives a file written before 748 the
paper's form.

    python3 tools/replication.py --models <ktb1,ktb1t,ktb1c,ktb2,ktb3> --sizes "<model:N,NxK;...>" --seeds 2 \
        --first-seed 11 [--sweeps <a step>] --workers 16 --judge <criterion>
    python3 tools/replication.py --read <run.json>[,<run.json>] --judge <criterion>

## tools/replication_conrady.py

Paper 2, Conrady (2011, arXiv:1009.3195v3), on paper 1's harness.

    python3 tools/replication_conrady.py --models conrady,conrady_p --scan "<model:N_e,...>" --anneal "<model:N_e@T[xK],...>" \
        --seeds 3 --first-seed 11 --workers 16 --judge <criterion>
    python3 tools/replication_conrady.py --read <run.json> --judge <criterion>

## tools/replication_konopka.py

Paper 3, Konopka, Markopoulou and Severini (2008, arXiv:0801.0861v2, with arXiv:hep-th/0611197v1): its
classical part, counted exactly where the paper counts and run as a chain where it does not.

    python3 tools/replication_konopka.py --chains=<r:NxK,...> --moves 30 --first-seed 11 --census 1000x200 \
        --workers 8 --judge <criterion>
    python3 tools/replication_konopka.py --read <run.json> --judge <criterion>

## tools/report_audit.py

Which reports are read, by what, and what they cost.

    python3 tools/report_audit.py                                    # from the code and the snapshot fixture
    python3 tools/report_audit.py --bundle <study bundle> [--json <out>]

## tools/sample_reading.py

What more laws buy: a study's sample read against itself, from its bundle.

    python3 tools/sample_reading.py <study bundle> [--md <out>] [--json <out>]

## tools/science_freeze.py

Regenerate the science-sensitive source freeze (`tests/fixtures/science_freeze.json`), deliberately.

    python3 tools/science_freeze.py --write

## tools/scratch_holders.py

Every folder's RAM scratch on this host, named; this folder's broken down. Read-only.

    python3 tools/scratch_holders.py [--json]

## tools/selftest.py

The archive as one self-test; also writes the variance windows.

    python3 tools/selftest.py [--quick] [--no-postgres]
    python3 tools/selftest.py --build-windows --window-seeds 4    # write calibration/probe_windows.json

## tools/setup_host.sh

The research host's bring-up from a base Arch/CachyOS install (`docs/agent/TARGET_ENVIRONMENT.md`); safe to re-run.

    ./tools/setup_host.sh            # pacman packages, rustup, maturin, uv sync, the engine, PostgreSQL
    ./tools/setup_host.sh --verify   # check only

## tools/start_admission.py

Which lattices a law of the fourteen terms can tell from a random graph of the same degree, and so which can be a start
(contract `gsd-start-admission-1`, `research/start_admission.py`): each term alone with coupling 1 and scale one, its
energy a node by the Rust engine on the lattice at the ladder's sizes and on random regular graphs of the same size and
degree, judged against `graph_scale_dynamics/resources/readings/start_admission_criterion_2.json`. A term tells a lattice
by an amount a node that does not shrink with N. About a minute. It changes no start a campaign runs.

    python3 tools/start_admission.py run --json <out> --md <out>

## tools/study_173_reading.py

Study 173's criterion read on a bundle (842, contract `gsd-study-173-reading-1`,
`resources/readings/study_173_criterion.json`): P1 to P12, each held, missed or not read, with what it read. P1 is
`tools/counters_reading.py`'s C1 and C2; P2 report 23's unresolved zero-temperature rungs; P3 the gates ledger's held
counts (only the six; a gate that only records holds nothing, and a law its budget stopped while it stood against the
law is named apart, 843), no fact gate before 1,024, and `cut`'s verdict on every decision that bought a larger size or a
longer chain for a law with a seed cut at that size; P4 the decisions at 1,024 and 4,096 replayed with the six gates
closed, the laws they would stop and how many of those went on, and the six's shares at the last decision; P5 and P6
the latest decisions' stops at 1,024 and 4,096; P7 the laws table's top sizes; P8 the over_budget stops; P9 the laws
with a seed cut at a size and decided a size up; P10 the scoring share of cut laws against the rest (the score's list
from report 28, the controls apart); P11 the scoring laws a judgment gate's tenth let on, each decision replayed with
the three closed; P12 the core-hours by size from the evidence. A study not done is read as a progress reading and
says so; a bundle of another study is a dry run (on 172's last bundle: 46 s, about 150 MB).

    python3 tools/study_173_reading.py <bundle or its folder> [--json <out>]

## tools/study_baseline.py

A study's bundle read law by law into one baseline (784): each law's campaign, kind, terms, last decision, largest
size, core-hours by size, lattice fates and score on this tree's rule, with the study's totals by size and by end.
Nothing is committed from it since 799; a law's end is the folder's last word on it (the bundle's `tables/laws.ndjson.gz`), and its title names the bundle's own study.

    python3 tools/study_baseline.py <study bundle folder> --out <path without .json>

## tools/study_172_reading.py

Study 172's criterion read on a bundle in one command (836, contract `gsd-study-172-reading-1`, against
`graph_scale_dynamics/resources/readings/study_172_criterion.json`): R1 every decision replayed and the counters held
to what was recorded (`tools/counters_reading.py`), R2 report 23's ranked laws for an unresolved zero-temperature seed
after the ceiling, R3 the gates' ledger and how every law ended, R4 one die at 1,024 (each decision replayed with each
fact gate alone acting, so a law's gates are known; the share that went on, by one gate or two or more; and, on a
design with `one_die`, every law against its pick), R5 the share the three stopped at 1,024, R6 over_budget before
65,536, R7 the core-hours from each campaign's `evidence/system.json`. On another study's bundle it says so and reads
the same numbers as a dry run: on 171's progress bundle R4 and R7 fail, as separate dice and 1,000 unfinished laws
should. About 12 s there; exits 1 if an item fails. Since 842 it reads its decisions from a disk index
(`tools/decision_index.py`): 144 MB on 172's last bundle, where it held 1 GB.

    python3 tools/study_172_reading.py <bundle or its .tar.zst> [--json <out>]

## tools/study_explorer.py

A study bundle's front page, explorer, gate trees and advice, written for a bundle made without them.

    python3 tools/study_explorer.py <study bundle> [--out-dir <dir>] [--out explorer.html] [--calibration <table or bundle>]

## tools/study_twice.py

Stable's second half, run right before study A (made at 838, contract `gsd-study-twice-1`): a short study run twice,
in two folders, and the two bundles compared. Each run is a folder inside the tree (`.study_twice_<a|b>_<id>`, as
`main.py` keeps a folder in its tree) on a schema of its own in the tree's PostgreSQL: `init`, `benchmark`, study 172's
design cut short (`--laws`, 4; `--sizes`, 64, 256 and 1,024; `--seeds`, 3; its search seed, gates and starts as
committed) started as `run --study` starts a design, the fleet run until every campaign is done for two polls in a row
and then stopped (SIGTERM, since a study's campaigns never complete), each campaign's report cycle and the study bundle
made as the Reports button makes them. The bundles are compared member by member, a campaign's part by its campaign:
every table row and every JSON document, with what is the host's own left out (when a thing happened, how long it
took, the memory it held, which process, core or folder did it, the database's row ids and revisions, the queue's
depth, the host's reports 14 and 25: `HOST_FIELDS`, `HOST_KEY`, `HOST_MEMBERS`), a table's host columns with them and
a list of laws compared as a set; the pages are counted, not compared, their data being the documents beside them.
Exits 0 when the two are the same. Both folders and schemas are removed at the end unless `--keep`; with `--json`
both bundles are copied beside the report. About 25 minutes on two cores (838: 11 minutes a folder).

    python3 tools/study_twice.py [--laws 4] [--sizes 64,256,1024] [--seeds 3] [--workers 2] [--json <out>] [--keep]
    python3 tools/study_twice.py --compare <bundle> <bundle> [--json <out>]

## tools/table_known_answers.py

The calibration table's known answers judged on the final probes (802), against
`graph_scale_dynamics/resources/readings/table_known_answers_criterion.json`, committed 2026-11-19T00:02:01Z, before
the host's table of build 801 was read. It reads the host's zip (its `probe_calibration.json`) or a table's JSON:
every planned cell must be there with 801's cell fingerprint; a family without a dimension must be refused by every
probe on every seed from 4,096 nodes; a family with one is held, probe by probe, to its band around its theory with
the table's own gate (the mean over the seeds that read, half of them at least), the 23 families the old seed held as
the table holds them today and A4 and D4 to the 4D lattice's bands from the size their own cells read on every seed
through the largest. It judges the criterion's five predictions beside the verdict: with `--against` the seed the
table replaces, whether every value and refusal repeats it bit for bit. The judged JSON carries `holds`, the bands
each family was held to, in the shape `table_holds.json` keeps. Exit 0 when it passes.

    python3 tools/table_known_answers.py <zip or table> --against calibration/seed_table.json --json <out> --md <out>

## tools/table_rule.py

What the calibration table holds each cell to, made from its rule and never by hand (765; the rule since 805). The rule
is `graph_scale_dynamics/resources/calibration/table_rule_2.json`: every family is held to what the table's known-answers
criterion (`table_known_answers_criterion.json`, committed before the table's zip was seen) holds it to, as its passing
judged reading (`table_known_answers_judged.json`) found it; a family without a dimension must be refused by every probe
from 4,096 nodes; everything else is measured and shown. The tool reads the rule and the two files it rests on, refuses
a judged reading that does not pass, and writes `graph_scale_dynamics/resources/calibration/table_holds.json`, which
`measurements/calibration.ladder_tolerance` and every family's `refusal_gated_from` read. With no flag it prints what
the rule gives; `--check` says whether the committed file is that, which
`tests/unit/test_the_table_holds_what_its_rule_gives.py` also holds.

    python3 tools/table_rule.py [--write | --check]

## tools/test_suite.py

The test lanes with consistent resource bounds; `tools/gate.py` and the release call it.

    python3 tools/test_suite.py --lane all --require-postgres --shards auto
    python3 tools/test_suite.py --lane fast --require-postgres [--changed-since <rev>]

The fast lane selects the tests that import a changed file, or start it: a module after `"-m"`, every module name a
file holds when it starts one by a name in a variable (as `main.py` starts the services), and a file of the tree right
after `sys.executable` (`[sys.executable, "main.py", ...]`, as `tests/integration/slice_driver.py` does). The tests'
own helpers (`tests/conftest.py`, `tests/support/`, `tests/integration/slice_driver.py`) are files of that graph too:
a change to one selects the tests that import it and those that use a fixture it defines, and a change to
`tests/conftest.py` or to a plugin it loads (`tests/support/postgres.py`) selects the whole integration lane.

## tools/trial_campaign_manager.py

Whether the Campaigns page does what it says, against a real database.

    python3 tools/trial_campaign_manager.py           # twenty-two steps, about a minute
    python3 tools/trial_campaign_manager.py --json
    python3 tools/trial_campaign_manager.py --keep    # leave the trial campaigns behind

## tools/two_runs.py

Two runs of one design compared, the second against the first (842, contract `gsd-two-runs-1`: 173 run again on
the same seed with 32 workers, to test the replay and what SMT gains). The same: the laws, rungs, draws and chains tables row by row with what is the host's own left out
(`tools/study_twice.normal`), every law's decisions in order with the deep lane's holds and releases and what records
when a decision was made (the lane, what the law learned from and waited for) left out and counted apart, and report
28's seeds without their timing (a seed's die is timing); a recording gate's share of 1 is no share; each difference by
law id, and apart the laws whose readings differ by less than one part in 10^8 (the order of a sum, 843). The speed:
each run's wall time from its campaign's creation to its last decision; the seed-hours of the seeds compared (every
evolve and probe second); the slots busy from each bundle's occupancy series (its last samples, simulations and
analyses, and the host's CPU; 843); the hour at which each run had made half, nine tenths and all of the decisions
both made, overall and by size, the same work in the same order (843); the gain, the first's wall time over the
second's, only when both are done; and by size each seed's seconds in the second run over the first, matched seed by
seed. Exit 1 when the runs differ. On 172's last bundle against itself: the
same, in 61 s and 261 MB.

    python3 tools/two_runs.py <the first run's bundle> <the second's> [--json <out>]

## tools/verify_claims.py

Which stated facts about this programme still hold; writes a zip.

    python3 tools/verify_claims.py [--out <zip>]

## tools/work_unit_fit.py

The unit of work a seed's budget is counted in (806, `gsd-work-unit-fit-1`): seeds of a design's laws run on the Rust
engine with their process time and the six parts of their work, and the unit fitted to them by non-negative least
squares on each seed's relative error, the parts' weights rounded to whole units of 0.1 ns with a fixed term a node and
chain beside. The committed fit (`graph_scale_dynamics/resources/readings/work_unit_fit.json`: 48 laws of
`tests/fixtures/a_design.json`, 256 to 4,096 nodes, two seeds, 288 seeds in the sandbox) gives the shipped spec's
`engine.policy.work_unit` and `seconds_a_unit`, which `tests/unit/test_the_work_unit_is_its_fit.py` holds; it is
never refitted under a running study. `sample` is resumable and splits into parts, one a core.

    python3 tools/work_unit_fit.py sample --out <rows.jsonl> [--laws 48] [--part 0 --parts 2]
    python3 tools/work_unit_fit.py write <rows.jsonl> [<rows.jsonl> ...]     # fit them and write the reading
    python3 tools/work_unit_fit.py show                                      # the committed fit
