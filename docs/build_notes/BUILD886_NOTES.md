# Build 886: the handover of the context that made 871 to 885, and the zone map the project now heads for

**Type: a handover, asked for by the operator on 2026-11-26 at 19:59 ("its perhaps time for a handover build?
theres enough material to work with and the past isnt as relevant anymore as compared to this new more refined
heading").** Only pages change: no code, no score, kind, gate or decision; `tools/outputs_of_a_law.py --against` 880's
record: 0 outputs changed.

## For the folders

Nothing to do: a folder on 885 runs the same on 886. **Study 177**: write its dex on the Map page ("write the dex
now") before stopping it; the dex goes into study 178's `import/` once 178 is designed (887).

## What changed

1. **`docs/agent/ZONE_MAP.md`, new, read first** (the README's list): the heading. The dex a list of zones, each named
   by its central law pushed to the largest N; law space as every coupling of every term (a missing term a coupling of
   0, so term sets meet where a coupling goes to 0), the dynamics, and N as resolution; what separates two zones (the
   curves of the four probes and their companions on every start, quantized by 879's phenotype); zones over N, nested
   and with boundary laws; which shapes the probes tell apart and which they cannot; how a zone is mapped, in the
   operator's order.
2. **`docs/agent/HANDOFF.md` rewritten for the heading**: the builds 871 to 885 a line each, the older ones a paragraph,
   the open threads, what is live; the instrument's known answers, the tree and the system kept whole. From 39 KB to
   23 KB, so the read-first set holds the zone map.
3. **`docs/agent/NEXT_BUILD.md`**: 887 starts study 178 (the blind draw as the base load, a dex read in as its own
   campaign and verified first, the first zone chosen to confirm fast), 888 the zone's search benchmarked on it; "The
   road from here" in place of the road to study A; 884's lessons (a new file tracked before the release, the
   PostgreSQL lane as `claude`, the operator as "they").
4. **`docs/ROADMAP.md`**: "From 886", five steps; "What makes a neighbour alike" recommended anew from the curves; a
   zone's law answered (its central law); a topology probe asked.
5. **`docs/WHERE_WE_ARE.md`**: what is running, what comes next and the decision in front of the operator.

## What 886 read, for the zone map

* **The dex of 2026-11-26 15:11Z** (`dex_177_2026-11-26T15-11-31Z`, 132 laws): 76 term sets, so most laws stand
  alone. One group of 45 laws shares a term set (`degree_anchor`, `degree_anchor_abs`, `degree_neighbor_gradient`,
  `induced_square_count`, zero temperature), every pair within 0.41, 400 of 990 pairs within 0.1: S176-C11-G79
  (S174-C3-f270d87c) and 44 of the neighbours 176's focus drew around it; with the three drawn with one term switched
  off, 47 of its 48 neighbours are in the dex, every one scoring 1, none judged for its kind, 176's focus having
  frozen first. It is the zone most likely to confirm fast, and the ring method's run on it is already paid for.
* **G37's family**: G37 (S176-C11-G25 in 176, 27 there) and its two neighbours at 1e-9, S177-C12-G565 and G586, the
  same physics on new random streams, score 7; their kind matched G37's ("moved") on 177's Map page of 19:02. The
  score moves with the streams, the kind did not.
* **S176-C15-G1** scores 17 and is a standing control: a zone is never chosen from one.

## The operator's words of the evening, and where each went

Their words are in `docs/HISTORY.md`; the notes of 884 and 885 say how each was met.

* 17:22: the zone not seen to work: 884, the zone live on the Map page.
* 19:06, 19:07: blind only when no zone has work, no slider: 885.
* 19:21: one zone at a time with every worker; the central law pushed to the largest N at a zone's end; the dex in
  the end only zones; a lucky hit kept; neighbours not run from 64; importing later; two zones on 177: 885 and the
  zone map.
* 19:49: the central law the zone's signature; a fresh study with the blind draw as the base load, a dex read in as
  its own campaign verified first, the zone likeliest to confirm fast taken first, its edges over every parameter
  and N found as fast as possible, benchmarked on one zone before several: the zone map, 887 and 888.
* 19:59: laws in several zones, overlaps between term sets; which observables tell shapes apart, a circle from a
  torus; what separates two zones beyond term set and coupling: the zone map's sections on law space, behaviour, zones
  over N and shapes.

## Acceptance, line by line

| the acceptance | the test |
|---|---|
| the read-first set, the zone map in it, under its budget | `tests/unit/test_the_read_first_set_is_small.py` |
| the operator's page names this build, within one page | `tests/unit/test_where_we_are_is_current.py` |
| the next build named one above this | `tests/unit/test_next_build_is_named.py` |
| no output of a law moves | `tools/outputs_of_a_law.py --against` 880's record: 0 outputs changed |
| the full lane green | the Verification below |

## Verification

4214 passed, 41 skipped in 1118.36s (3 lanes at once)
