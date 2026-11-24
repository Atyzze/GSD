# Build 849: study 175's second bundle, read by a reader that keeps a variant still running apart from one that differs; the tree made public without the papers. It changes no decision and no score and may be applied to any folder.

**Type: a reading, of the bundle the operator sent on 2026-11-24 at 09:53 with no words, and a delivery change they
asked for that morning (09:02: "You can just add this one to the list of existing public projects on my GitHub";
"make sure that we don't repost any of the papers"; 09:40: "get rid of tests that check that folder, dont make a
separate build lane for it, we just keep the existing two ones").** Changed: `tools/perturb_reading.py`
(`gsd-perturb-reading-2`: `standing`, `verdict_so_far`, `decided_at`, `status_of`, `moves_of`, `kept_or_made`,
`label`) and `tests/unit/test_the_perturbation_side_study.py`. Removed: `docs/references/` (19 PDFs of other authors'
papers and their register) and `tests/unit/test_the_references_are_kept.py`; each paper is cited instead by arXiv id
and the version read in `docs/RESEARCH_METHOD.md`, "The papers read", which `docs/readings/findings.json` names as no
finding. Documents: the README, `ARCHITECTURE`, `OPERATIONS`, `LESSONS`, `TOOLS`, `ROADMAP`, `HISTORY` (two standing
decisions replaced in the operator's words), `RESEARCH_METHOD`, `WHERE_WE_ARE`, `HANDOFF` and `NEXT_BUILD`, which
gains the push. Nothing under `decisions/`, `observability/`, `scaleflow/`, `measurements/`, `engine/` or `engine_rs/`
moved; no frozen source moved; the schema did not change. Against 848's record (`tools/outputs_of_a_law.py --against`,
the record written first on the untouched 848 tree) 0 outputs moved.

## The reader

The criterion's rule is the same, word for word. What changed is when a variant counts as read. A variant is read when
its law was decided at its holder's size, other than by buying longer chains there (a `longer_chain` decision at that
size reads it again): it is then alike or unlike. One stopped, parked or done below that size ended there and is not
alike, as the criterion has it. One still running is unread. A radius holds at three alike, fails when its alike and
unread together cannot reach three, and is open otherwise; a holder whose deciding radii are open is open, with the
region it holds so far. With every variant read the verdict is 847's (a test holds the two equal on every case of
847's own test). The run-again line compares only the sizes the holder's own run has decided. 847's reader counted an
unread variant as unlike and compared sizes still running: on 175's first bundle it gave 24 streams and 2 points where
nothing was decided, and on this one it would call three holders' run again changed where their longer chains were
still running (H08 and H22 at 16,384, H01 at 65,536).

Beside each verdict, recorded only and added after the study started, no part of any verdict: **kept or made**. At the
holder's size, which of its other starts read alike its chain by the criterion's tenth (made when one does, kept when
none does), and its chain's accepted moves per edge there (the median over its seeds, `tables/chains.ndjson.gz`).

## Study 175's second bundle (built 2026-11-24T08:35:35Z, on 847)

595 laws held, the campaign active, 263 core-hours (P3 predicts 400 to 900); 120 laws finished at 65,536 and 254
simulations queued there.

* **P1 so far.** All 35 holders decided at a size of 174 read there exactly what they read in 174, and every seed row
  of the 35 (4,240) is the same as 174's, field for field.
* **Verdicts so far.** Settled: regions to 0.1, H04 (`4598617a56e6`, triangular) and H09 (`4877770006cf`, bcc); a
  stream, H15 (`1b42427547af`). Open, a region to at least 0.01: H06, H07, H10, H11, H13. Open: 27, among them H25,
  H33, H34 and H35, whose variants read alike at their size so far while buying longer chains there. No variant read
  at its holder's size is unlike; 20 ended below it.
* **H15, the stream.** In three of its four 1e-9 twins every lattice start sits at the mean degree cap of 32 at 4,096,
  the empty start reads 0, and the law stops `empty`; the holder and the fourth twin keep a bcc chain near a mean
  degree of 9.8 there, two of its three seeds having left the cap. Its random numbers decide which. The reading of
  175's first bundle guessed that a let-through drawn for the holder's id, not its twins', had carried the holder past
  a gate at 4,096. It did not: the holder's bcc chain, and the fourth twin's, went on past `no_steady_chain`, which
  records only and lets every law through, while the three twins' bcc chains stopped `too_dense`, at the cap. So no
  reading corrects for a let-through. A stop named `empty` while seven starts are full is a roadmap line.
* **Kept or made.** Every holder read so far (8) is kept, at 0 to 0.0045 accepted moves an edge. Read the same way on
  174's first bundle, where all 35 reached their size: 32 accept moves on fewer than 5% of their edges, H30 on 7% and
  H32 on 14%, at 25 to 2,600 moves tried per edge; their chain ends at its lattice's own mean degree (bcc 8.0, fcc
  12.0, triangular 6.0, square 4.0) and reads its lattice's own dimension; 34 of 35 have no other start alike. The one
  that moves is H31 (`3931d03e8edf`, finite temperature, `degree_fourth_sum + induced_square_count + wedge_count`):
  about 645,000 accepted moves a chain at 16,384, its bcc and fcc starts both at d 4.0 and mean degree 26, its other
  starts at 22 to 26.
* **Study 174's bundle, every law.** At 4,096 or above, 168 laws read alike from two starts or more: 161 of them at a
  d below 1.5, rings and chains; seven above, H31 at 16,384 and six at 4,096 only (`fdc563a72c98` 3.9,
  `463fc3bf678f` 3.0, `85f4e1bc29bd` 1.9, `fbbada38df48` 1.7, `c687c3f3c003` 1.6, `dc374cd4f3d5` 1.5).

What this says, for the operator: the regions are real, and they are regions in which a lattice a law is given stays a
local minimum of its energy, not regions in which the law makes a geometry. Two questions follow, in
`docs/ROADMAP.md`: whether 175 runs to its end, and whether the study after it looks for laws whose different starts
arrive at the same d and mean degree.

## The tree is public

From 848 the tree is pushed to `github.com/Atyzze/GSD` after each release, one commit a build on `main`, with no lane
of its own (`docs/agent/NEXT_BUILD.md`); its history starts at 848 and holds no paper by another author. Tags do not
push from the session (HTTP 403), so a commit's message names its build. Applying 849 removes `docs/references/` from
a folder's tree; the 848 archive keeps the papers.

## For the folders

Nothing a folder decides or scores changes. 849 may be given to 174's or 175's folder when it suits, each needing one
restart of its own command; 175 runs on 847 without it.

## Verification

3882 passed in 1354.43s (3 lanes at once)
