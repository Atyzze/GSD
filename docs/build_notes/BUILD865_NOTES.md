# Build 865: study 176 designed again and seeded from bundles, Home's top one bar, a law's type where DONE stood, the least known type first, and each term switched off

**Type: a feature build, asked for by the operator on 2026-11-25 at 09:42, 11:06, 11:58, 12:03 and 12:12 (their words in
`docs/HISTORY.md`).**
It may be applied to study 174's folder: no score, kind or decision of a law moves (`tools/outputs_of_a_law.py
--against` 864's record: 0 outputs changed; `tools/replay_bundle.py` on 174's bundle of 2026-11-25 09:59Z: every
decision replays). Nothing under `decisions/`, `scaleflow/`, `measurements/`, `engine/` or `engine_rs/` changed, and
nothing in `main.py`. `tests/fixtures/committed_readings.json` moved: study 176's design and criterion, committed at
856 and never run anywhere, are replaced (below). Made from 864's archive in a session that could not reach the
repository: the operator opens the pull request.

## For the folders

**Study 174**: apply it for Home's new bar; nothing else changes there. **Study 176**: not yet: start it in a folder of
its own when the two questions below are answered, with `python3 main.py run --study 176`, then seed it from the Map
page ("seed from a bundle": the path of 174's newest bundle on the host, and 175's if wanted).

## Study 176, designed again (09:42, 11:06)

"lets design study 176 that we seed with the existing top scoring ggs+overall map space so far, and then again same 10
batches of 1k laws each". `study_176_design.json`, written from 174's: **group A**, ten blind batches of 1,000 on 174's
grid, starts, ladder, budgets and gates, on the ten blind seeds 176 drew at 2026-11-24T17:00:58Z (never run); **the
focus** begun by the study's own start (`design.focus`), its campaigns N, S and D made at once, its first law taken the
moment one scores, nothing to press; **a seeded campaign** (group N, empty, drawing nothing, its gates recording
`starts_alike` and `nothing_read` only, as 856's map did, so no seeded law is stopped on a judgment its first run
passed). The split is the focus's: A 2, N 1, D 1. No map campaign (B): the focus maps instead. The seeded and the
focus's campaigns stay out of the let-through ledger and the batches the gates learn from (`OUTSIDE_THE_LEDGER`,
`_study_place`). The criterion (`study_176_criterion.json`), committed before the first start: P1, every seeded law run
again reads what it read in its source bundle on the same seeds and engine; P2, every seeded law and region is one a
seed record names, numbers kept unless taken; P3 to P5 reported (the blind and zoned shares, every region with the
map's own check of confirmed, unconfirmed and invalidated laws, A beside 174). The 856 design and criterion are in git
history and `docs/build_notes/BUILD856_NOTES.md`; `study_176_first_ten.json` stays, read by nothing now but its test.

## The seed (`operations/study_seed.py`)

The Map page's new panel "Seeds" takes the path of a bundle on the host, its `.tar.zst` (read through `zstd`, streamed,
only `study.json`, `tables/laws.ndjson.gz` and `focus.json` kept) or its folder (`POST /api/focus`, `do: seed`, behind
the admin capability). It is refused unless the bundle's science hash is the folder's (`reporting/science_contract.same`:
the probes, the starts' reading, score, catalogue, engine and the table's cells). Every law the bundle's folder scores
above zero (`law_score`) is put, its spec whole and its id checked, into the seeded campaign, run again here and taken
by the focus in its turn by its score here. Every GG region of the bundle's `focus.json` joins the focus's regions
with its kind, ranges and holder laws (run again too), its number kept unless taken, `seeded_from` naming the study,
bundle and number; its holder is recorded as mapped, so it is not mapped again and a scoring law inside it is passed
over. A second seed appends: a law already there is skipped, a region from a newer bundle of the same study widens the
one it gave (`regions_grown`), another study's region of a taken number takes the next. Each seed's record (bundle,
built time, science hash, scoring laws, laws added, regions) is in the focus's state, the page and the bundle's
`focus.json`. **Today**: 174's bundle of 09:59Z carries no `focus.json` (the focus was not started), so a seed from it
brings its scoring laws and no region; a bundle sent after the focus has run on 174 brings its regions.

## Home's top, one bar (11:06)

"1 bar of random laws tried vs zoned-hand-picked region-laws % and counters instead of needing even care about batches
or controls". "The study now" is one bar split by laws: **blind** (group A, the batches together) against **zoned**
(seeded, neighbours, seeds, depth), each with its share, laws, graphs, how many score, what runs and is queued, and
the work left; a click reads every blind batch in the panels below, and a batch alone is chosen in the filter panel's
batch. The standing controls are a tick, "known answers: pass". The campaigns overview carries each campaign's group
and design kind, and its landscape's count of scoring laws (`high_score.scoring`). The class is `study-split`, apart
from the campaign progress bars' `study-bar`.

## A law's type where "DONE" stood (11:58)

"the poke/gg-type should be visible where it says 'DONE' currently instead". The law page's header chip, once the
chains are read, says the law's **type**: its kind by the catalogue at its highest reading (`law_kind.kinds`, the
largest size read), for a law whose starts settle or agree its **form** (d under 1.5 at a mean degree within 0.04 of
2: "a ring", or "rings" when its largest piece holds under 95% of the nodes; under degree 2 "open strings", else "a
line"; d 1.5 and over its d), and its place on the map: its GG region and "mapped", "inside, passed over", "in focus
now", or "no GG region yet" (`law_status.phenotype`, `focus.place_of`, in `/api/structure` as `phenotype`). The
status (waiting to be extended, settled at its highest reading) stays in the chip's mouse-over and the first line.

**C2-G3187, classified** (law f8f26f0cf5, the operator's specimen, now the highest score, 38): **rings**, a 1D
geometry, as the operator saw. In 174's bundle of 09:59Z its chain from empty reads mean degree 2.000 at every size
(2.0001 from 16,384: one edge more than a set of cycles in every 16,384 nodes), d_s 1.00, d_V 1.00, d_B 0.98 and d_w 2.03 at 65,536
(d_s times d_w over twice d_V: 1.02), no triangle (clustering 0) and no square, its largest piece 61% of the nodes at
64, 80% at 4,096 and 96% at 65,536, its reach 11,719 there. Its terms say why: `|degree - 2|` at +2.06 outweighs the
rest, so at zero temperature every node is pushed to degree 2, and a graph of degree 2 everywhere is a set of
cycles; the squares' +0.0106 keeps 4-cycles out. Its page reads "settled from empty or random, a ring at N=65,536"
and, until the focus maps it, "no GG region yet": started on 174, the focus takes it first, its score the highest,
and the region it maps takes the next GG number. Every chain agrees on it, so it is the trivial
geometry, d 1; what the map then says is how wide its region of rings is and where it turns into open strings.

## The least known type first, and the Top 100's rank kept (12:03)

"frankly id rather see C8G2983 explored first than that ring". The focus no longer takes the best score alone: of the
scoring laws not yet mapped, skipped or inside a region, it takes the one whose **type** is least known, the score
deciding among equals. A law's type is its kind and its form at 16,384, the size the focus reads (`law_status.type_of`:
"grown ring", "made d 2", "rewired"); a type is known by the laws of it the focus has mapped, up to three (the Map
page's "a type known after", `mapped_per_type`), and a type the calibration table already holds counts one from the
start: a one-dimensional form, a ring or a line (the table's periodic ring; Home counts 316 laws of "ring or chain
made" on 174, and 168 reproduce the ring family across its ten batches), and a lattice start kept, frozen or still.
So on 174 the focus takes C8-G2983 (27) before C2-G3187 (38), rings and kept lattices come after every type not yet
mapped, and each type is mapped a few times before the score alone decides again. The queue on the Map page shows each
law's type. **Home's Top 100**: with a filter on, each row keeps its place in the whole Top 100 (C8-G2983 reads 2 with
the rings hidden), the gaps saying what the filters hide.

**The lexicon and the matrix** (planned, `docs/ROADMAP.md`): the catalogue's kinds say how a law's starts end (grown,
made, kept, rewired, melted...) and the form says what was grown (a ring, a line, d 2...); 174 shows why both are
needed, rings sitting under "grown" (C1-G6940, C2-G64, C6-G1015, C2-G3187) and under "ring or chain made" (316). A
law's name in the lexicon is its type, kind and form; the GG region is where it sits. Each law read against every
known type, a similarity a type in a table of laws by types, is the next step of this, the single score kept for what
the extender pushes deepest.

## Each term switched off (12:12)

"the explorer should by default always also explore what turning any of the selected couplings back to 0 does ... to
see if it was even load bearing at all". When the focus takes a law, beside its rings it now adds, in the neighbours'
campaign, the law with each of its terms switched off in turn (coupling 0, the term absent; a law of one term has
none to switch off, said in `terms_kept`), read at 16,384 like a ring. A term whose law without it reads another kind
is **load-bearing**; one whose law without it reads the same kind is not, and its coupling's range in the region then
reaches 0. The law waits in its neighbourhood stage until every one is read; its **core** is its load-bearing terms
(`focus.knockouts`, `terms_read`, `core_of`), kept in its summary and on its region (`cores`), shown on the Map page
for the law in focus, the ended laws and each region. A law in focus before 865 has none and goes on as it was. It
costs one law a term, three for most laws, beside the 44 of its rings.

## The control campaign, the question asked

Recommended: keep the standing controls, as a tick. They are five laws of known answer, 3.1 core-hours of 174's 750
(0.4%), and the only check inside a folder that the instrument on this build and host reads right; a map read by a
wrong instrument agrees with itself. The map checks itself (its neighbours confirm a law, its seeds reproduce it, its
depth may invalidate it), the controls check the instrument. In `docs/ROADMAP.md`, "Questions for the operator", with
when 176 starts.

## Tests

`tests/integration/test_study_176_starts_its_blind_draw_its_seed_and_its_focus_postgres.py` (ten blind batches, an
empty seeded campaign of hand policy and recording gates, the focus's three campaigns, none of them in the ledger or
the learning batches, the split, a start again making nothing twice and keeping a split set; a bundle seeds its
scoring laws and none other, its region with its number, its holder mapped; another science refused; a newer bundle
of the same study widens its region, a third time changes nothing, another study's region renumbered; a `.tar.zst`
read; the page refusing a path that is no bundle); it replaces `test_study_176_starts_its_two_groups_postgres.py`. The
dashboard's smoke draws the bar from blind, seeded, focus and control rows (shares, counters, work left, the tick, an
archived batch left out, a queue with no price).

## Left for the next builds

The pages' and reports' build numbers in words (10:00); 866, the engine's diet, timed on 176's seeds; C and assembly
after it (11:10); the outliers' queue; the shared effort only once one node has proven the mapping (11:08)
(`docs/agent/NEXT_BUILD.md`, `docs/ROADMAP.md`).

## Verification

4025 passed in 1282.40s (3 lanes at once)
