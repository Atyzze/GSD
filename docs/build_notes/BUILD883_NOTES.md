# Build 883: the first zone unblocked, every law clickable, the dex checked against what it carries

**Type: a fix build, on the operator's words of 2026-11-26 16:20 ("we really need to make sure our dex import/sync
works flawlessly so that once added they are click-able as the other ones are"; "is the focus on the first region
actually working?").** No score, kind or decision of any law in any campaign moves, no frozen source and no schema;
the science is 882's. It is applied to 177's running folder.

## For the folders

* **Study 177**: apply 883 and restart. At its first step the depth worker leaves S177-C4-G10 (skipped on 881 but
  still its law) for the law in focus, S177-C11-G37, in a new depth campaign; the law's kind at 16,384 is taken from
  its seeds' campaign, which read it there on six seeds already; and the Map page says under the law what the zone
  worker still waits for before it maps it.

## What was wrong (177's dex of 15:11Z and the Map page of 16:20)

1. **The depth worker held a law the focus had let go**: "skip this law" on 881 ended S177-C4-G10 in focus but left
   it a contender, so the depth worker went on pushing it (to 65,536 by 16:20) and never read the law in focus at
   16,384, a condition of its mapping. No law could have been mapped.
2. **"its own seeds did not reproduce" compared two sizes**: seed 0 at 4,096 in the law's own campaign ("made")
   against seed 0 at 16,384 in its seeds' campaign ("moved"); and it was read once and kept.
3. **"other" before the law's kind was read**: a neighbour read while the law's own kind was not counted as another
   kind (ring 1e-9: 2 other), and a term switched off as load-bearing.
4. **The law's own kind waited on its own campaign**: S177-C11-G37's campaign climbs 130 seeded laws at once, while its
   seeds' campaign had read it at 16,384 on its six seeds.
5. **A law in several campaigns could not be opened** (`/candidate-data/<law>`: 409 "candidate belongs to multiple
   campaigns"): the Map page's depth table gave no campaign, and the law page refused to choose.
6. **The dex checked nothing**: merging kept one chain a law, size, seed and start, so the folder's own run again
   replaced the chain it was to be checked against; 177's dex said 0 verified.

## What changed

1. **The depth list holds scoring laws and the law in focus only** (`focus.contenders`): any other is dropped, with
   an event, and the depth worker leaves it for a new depth campaign (882's `depth_restart`).
2. **Seeds compared at one size** (`focus.seeds_of`): each of the law's own seeds against the same seed in its seeds'
   campaign at the largest size both read (`compared_at`), read again at every step; nothing is said before the
   law's own kind is read.
3. **Nothing judged before the law's kind** (`focus.tally`, `terms_read`, `alike_to`): a neighbour read while the
   kind is not is counted `read` and waiting; the Map page's rings table has a `read` column.
4. **The kind from its seeds' campaign** (`focus.kind_here`, `kind_from`): its own campaign's reading at 16,384 when
   there is one, else its seeds' campaign's once that has decided at 16,384 (never a stop).
5. **What the zone worker waits for** (`focus.needs`, the Map page's "to map it"): its kind, two thirds of the ring
   of 0.1 alike, its depth read past 16,384, its seeds, every ring and every term switched off, each with its count.
6. **Every law opens** (`services/api/main.py`, `focus.home_campaign`): a law in several campaigns opens in the one it
   was drawn or seeded in, then the zone's, then the depth's; the Map page's depth rows carry their campaign.
7. **The dex checks a run again like for like** (`dex.verify`, `dex.like`): each chain run here against the chains of
   the parts read in, of the same law, size, seed, start, start graph and length; a run of another length is counted
   apart, not judged; merging keeps every distinct outcome, the part read in first.

## What the dex of 15:11Z read

* 132 laws: 176's 130 (72 with 174's codes and scores, every scoring law of 174's bundle; its "73" counts one law in two
  campaigns), and two neighbours of the law in focus that score 7 here, S177-C12-G565 and S177-C12-G586.
* **Run again, seed for seed**: 85 of them run again in 177 on their seeds to 65,536; 8,000 chains against 176's of
  the same length and start: every one identical. The differences a looser match finds are a standing control's,
  whose given start is another graph.
* **The engines on the same chains**, 177 (crate 0.875.0) against 176 (0.840.0): the engine's seconds 0.94, 0.90 and
  0.94 times at 4,096, 16,384 and 65,536; a seed's peak memory 0.74, 0.52 and 0.49 times.

## Acceptance, line by line

| the acceptance | the test |
|---|---|
| a law skipped but left to the depth worker is dropped for the law in focus; what it waits for is said | `tests/integration/test_a_study_is_seeded_from_a_dex_and_writes_its_own_postgres.py`, the fifth |
| a law in several campaigns opens in its home | the same file, the fourth |
| seeds compared at one size, nothing said before its kind | `tests/unit/test_the_focus_reads_seeds_its_own_campaign_never_ran.py` |
| neighbours and terms read before its kind are neither alike nor other; its kind from its seeds' campaign | `tests/unit/test_a_focus_reads_its_law_by_seeds_moves_and_depth.py`, the last two |
| a run again judged like for like, other lengths and starts not, both outcomes kept | `tests/unit/test_the_dex_carries_every_scoring_law_and_checks_a_run_again.py` |
| the Map page says what it waits for, and the read column | `tests/ui/dashboard_smoke.js` |
| no output of a law moves | `tools/outputs_of_a_law.py --against` 880's record: 0 outputs changed |
| the full lane green | the Verification below |

## What it does not do

* The neighbours of a law set aside stay queued in the zone's campaign and run; the law in focus's are not put first.
* The panel of what each worker does on Home is still to come (`docs/ROADMAP.md`, "From 881").

## Verification

4205 passed, 41 skipped in 1097.32s (3 lanes at once)
