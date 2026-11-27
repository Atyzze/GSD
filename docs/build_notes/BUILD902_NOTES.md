# Build 902: what 893 to 901 learned, folded into the pages, and six questions closed. It changes no code, no decision and no score

**Type: a consolidation, the second of `docs/ROADMAP.md`'s "Next, in order" as laid out for the operator with 897 ("A
consolidation: no behaviour changes; after the N-push's fixes, never in the middle of one") and continued on their
word of 2026-11-27 19:39**, made on 901 (`main` holds 898 to 901, #40 to #43). Changed: `docs/LESSONS.md` (ten lessons under "Environments and sandboxes",
"Releases", "Where defects cluster" and "Memory, and what outlives its owner"), `docs/ROADMAP.md` (six questions
closed, the archive's question put, 902 among the builds made, the Rust engine's bytes an edge among the next),
`docs/HISTORY.md` (902 among the builds), `docs/agent/NEXT_BUILD.md`, `docs/agent/HANDOFF.md` and
`docs/WHERE_WE_ARE.md` (902 written in, 903 named). No file under `graph_scale_dynamics/`, `engine_rs/src/`, `tools/`
or `main.py` changed; nothing to apply to a folder.

## What the builds learned, and where each piece now lives

| what | where it lives now |
|---|---|
| The bundled PostgreSQL refuses root; as root the database tests skip, and `GSD_REQUIRE_NATIVE_POSTGRES_TESTS=1` makes the skip a failure | `docs/LESSONS.md`, "Environments and sandboxes" (900) |
| The release spends the build number itself; set by hand, the gate ran one number high and failed on its own pages | `docs/LESSONS.md`, "Releases" (900) |
| A test never quotes the operator; the contract test reads every test's strings | `docs/LESSONS.md`, "Releases" (900) |
| A page fixed after the gate, when `main` moved under its pull request, moves the build's file list | `docs/LESSONS.md`, "Releases" (900, 901) |
| A build made on an open pull request is opened against `main` and says to merge the one under it first | `docs/LESSONS.md`, "Releases" (899) |
| A start's clean-up cancelled the N-push's probes past its copied spec's seeds | `docs/LESSONS.md`, "Where defects cluster" (897) |
| The fleet ladder counted a seed bought as a graph grown | `docs/LESSONS.md`, "Where defects cluster" (898) |
| A saved state read back as lists of numbers of their own, about 1.4 times the engine's own, and the child kept it for the whole run | `docs/LESSONS.md`, "Memory, and what outlives its owner" (901) |
| Frozen code bounds where a fix goes: the caller empties what it handed the run | `docs/LESSONS.md`, "Memory, and what outlives its owner" (901) |
| A fresh seed holds two checkpoints of its eight chains between saves, about 56 bytes an edge beside the engine's own graph | `docs/ROADMAP.md`, "Next, in order", item 2 (901) |

## The questions closed

| the question | asked | why it closes |
|---|---|---|
| Past 65,536? | 2026-11-22 15:50 | a law goes past it when pushed to the N limit (889), the N-push its own ladder (893), stopped at 1,048,576 unless pushed past it (the operator, 2026-11-27 15:47; 897) |
| E8 | 860 | the operator, 2026-11-25 00:40 and 07:35: checked against its paper first, a side experiment only if the paper gives a law to run (`docs/HISTORY.md`) |
| Study 176's first ten | 860 | 176 was seeded from the map instead (the operator, 2026-11-25 11:06; 865), and has since been followed by 177 and 178 |
| Which law first | 861 | 176's question; since 885 one order for runs and probes, the zone of the law in focus first |
| Home's refresh every 0.5 s | 856 | since 894 the pages read again when the fleet's work changes |
| 897's two questions | 897 | answered 2026-11-27 18:26, made in 899 (`docs/HISTORY.md`) |

Open still, each where it was: a tenth or a hundredth let through; study 176's standing controls; a topology probe;
856's map variant, halvings and system CPUs; 860's counts; the noise floors, the score's list and exponential growth;
G133 off the push list (899).

## The question put

Where the archive of the older data goes public (`docs/ROADMAP.md`, "Questions for the operator", from 902): a
GitHub release with the archives attached, free, deletable and as lasting as the repository; or a Zenodo record,
a DOI a paper can cite, each new version its own DOI, deletable by its owner only within 30 days of publishing
(Zenodo's help, "Manage records"). Recommended: the release now, the Zenodo record when the paper goes out.

## Acceptance

| the acceptance | the test |
|---|---|
| the pages name 902 and 903, the read-first set and its cross references hold | `tests/unit/test_where_we_are_is_current.py`, `tests/unit/test_next_build_is_named.py`, `tests/unit/test_doc_cross_references_resolve.py`, `tests/unit/test_the_read_first_set_is_small.py` |
| no page quotes a gendered pronoun, no test the operator | `tests/contract/test_the_operator_is_they.py`, `tests/contract/test_the_operator_s_words_live_in_the_documents.py` |
| the full lane green | the Verification below |

## Verification

4270 passed, 41 skipped in 1375.50s (3 lanes at once)
