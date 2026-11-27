# Build 887: study 178, a dex read in as its own campaign and verified first, the first zone chosen to confirm fast

**Type: a study build, on the operator's words of 2026-11-26 19:49 ("I really want to be able to start a fresh study,
one that does only blind mapping as base load, until a dex is seen, upon first load, it is first verified in the
fleet, its own campaign"; "not the most special/unique one but the one most likely to confirm fast"), sent with 177's
dex of 19:33Z and "next build please" at 20:36.** Items 1 to 3 of `docs/ROADMAP.md`, "From 886". No score, kind, gate
or decision of any law moves, no frozen source and no schema; the science is 886's (f5c045e195fdb4d2), so 177's dex
reads in with its scores. `tools/outputs_of_a_law.py --against` 886's record: 0 outputs changed.

## For the folders

* **Study 177**: nothing to apply. Stop it once its dex is written (it is: `dex_177_2026-11-26T19-33-48Z`).
* **Study 178**, a folder of its own on 887: `uv run python main.py run --allow-host <host> --study 178`, then put
  `dex_177_2026-11-26T19-33-48Z.tar.zst` into its `import/`. Within a minute the dex campaign is made and holds the
  dex's 193 laws; the Map page's line says "verifying the dex first: 0 of 193 laws read again", the Seeds panel lists
  each law as it reads again (confirmed, denied or unmatched), and the fleet runs them before any blind law (the Dex
  step of 885's order). No law is taken into focus and the depth worker waits until every law has read. Then the
  first zone is chosen, its line on the Map page, and its centre taken into focus at the next step.
* **What to watch in btop and the next bundle**: every worker on the dex's laws at first (193 laws, 85 of them to
  65,536 on 177's showing), the blind draw only on slots the Dex step leaves; denied laws (none expected); the hour the
  zone is chosen.

## What changed

1. **Study 178's design** (`resources/readings/study_178_design.json`, its criterion and its line in `studies.json`):
   177's ten blind batches of 1,000 on ten new search seeds, the base load; kept as ten rather than one campaign of
   10,000 so every reader of a bundle compares batch to batch as on 174 to 177, and with 885's one order the blind
   draw runs only on slots no zone, depth or Dex work takes, so its cut into batches changes nothing that runs first.
   The focus is begun with no law. **No seeded campaign is made in advance**: the design's `dex` entry (177's seeded
   campaign's gates, `verified_first`) is the campaign the first dex or bundle read in makes
   (`study_design.dex_campaign`, `study_seed.seeded_campaign(make=True)`), kind `seed`, so the Dex step of the
   fleet's order.
2. **A dex read in is verified first** (`operations/dex_check.py`): once a minute the controller's dex pass checks
   each law the dex campaign has decided, chain by chain against the dex in `import/` (`dex.verify`, like for like),
   and files it as confirmed, denied (its first difference kept) or unmatched (nothing of the same length or science
   to compare). Until every law has its verdict the focus takes no law and the depth worker none (`dex_check.waiting`,
   `focus._step`); a dex let go on the Map page ends the wait.
3. **The first zone chosen to confirm fast** (`operations/zone_choice.py`): among the confirmed laws, standing
   controls never, grouped by term set (the signature a distance is defined within); each group's centre is the law
   with the most others within the focus's confirm radius (0.1), then the smallest mean distance; the group with the
   most laws within 0.1 of its centre is chosen, then the larger group, then the smaller mean distance. Its line and
   the next groups are filed (`zone_chosen`), and the focus's next step takes the centre (`chosen_by` zone), the
   depth worker beginning with it. With no two confirmed laws within 0.1 of each other none is chosen and the focus
   goes on as before.
4. **The Map page**: the Seeds panel opens with the dex's check (how many read again, confirmed, denied, unmatched,
   the dex campaign), the zone with its line and the first groups, and the dex's laws as they read again, each
   opening its law page; the focus's line says it verifies the dex, then why its law was taken.
5. **`tools/dex.py zones`**: the rule read on a dex on a disk, `--as-verified` as a fresh study will find it.
6. A study without a `dex` entry (177 and every earlier one) is unchanged: its seeded campaign is made in advance and
   a dex read in is taken at once, as on 882.

## What 887 read: 177's dex of 2026-11-26 19:33Z

* **193 laws in 76 term sets**, 26,366 chains, no region; 129 laws confirmed by 177's own runs again (every chain of
  the same length identical, 0 differ), 64 unverified (177's own laws, never run elsewhere); 3 of the 5 standing
  controls among them.
* **Three term sets hold most of it**: 45 laws of `degree_anchor k=7, degree_anchor_abs k=6, degree_neighbor_gradient,
  induced_square_count` (G79's family, every one scoring 1), 34 of `degree_anchor_abs k=19, degree_cube_sum,
  square_count` (G37's, S176-C11-G25, 27 there, and its 177 neighbours at 7) and 31 of `degree_anchor k=2,
  degree_fourth_sum, induced_square_count` (S176-C11-G4, 27); every other term set holds three laws or fewer.
* **The rule on it**, every law taken as confirmed (`tools/dex.py zones --as-verified`): 29 laws within 0.1 of
  S176-C12-G100 (mean distance 0.090), 28 within 0.1 of S177-C12-G1015 (0.090), 25 of S176-C11-G4 (0.048). The first
  zone is G79's family by one law; on the dex's own checks alone (177's 64 laws unverified) it is the same, 29 against
  1. It is close: on a tie the larger group wins (45 laws against 34), so G37's family is chosen only if two or more
  of the laws near G79's centre fail to confirm in 178 and none of its own does; study 178's criterion (P4) commits
  S176-C12-G100's before it runs.

## Acceptance, line by line

| the acceptance | the test |
|---|---|
| study 178 makes the blind draw and the focus, no seeded campaign; a dex read in makes its own campaign | `tests/integration/test_study_178_reads_a_dex_in_as_its_own_campaign_and_verifies_it_first_postgres.py`, the first |
| nothing taken into focus or deeper while the dex reads again; its laws listed confirmed, denied or unmatched as they read | the same |
| the first zone chosen by the rule with its reason, its centre taken into focus and first to the depth worker | the same |
| a dex let go frees the focus; 177's design unchanged | the same file, the second |
| the rule: most within 0.1 of a centre, denied and controls left out, ties, no zone | `tests/unit/test_the_first_zone_is_chosen_to_confirm_fast.py` |
| a run again confirmed, denied or unmatched chain by chain | the same file |
| the Map page lists the dex as it reads, then the zone and why | `tests/ui/dashboard_smoke.js` |
| no output of a law moves | `tools/outputs_of_a_law.py --against` 886's record: 0 outputs changed |
| the full lane green | the Verification below |

## What it does not do

* **The zone's search** (888): the zone's centre is taken into focus with the method in force, its rings drawn as
  on 885; judging the laws already there first, and stepping and halving per parameter, are next.
* After the first zone, the focus takes the next law by score as before; zones one after another are item 5.
* A dex read in after the first zone is chosen is verified the same way but no longer holds the focus.
* The pull requests of 871 to 887: this session was refused push access to `github.com/Atyzze/GSD` as 871's to
  886's were; the archive is the delivery.

## Verification

4223 passed, 41 skipped in 1351.52s (3 lanes at once)
