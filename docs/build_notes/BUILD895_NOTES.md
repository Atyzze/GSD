# Build 895: the handover of the context that made 886 to 894, the fleet's three modes and the N-push

**Type: a handover, asked for by the operator on 2026-11-27 at 13:00 ("we are probably due for a hand over build
afterwards") and 13:06 ("finish that build and aim for a hand over after/during build as well").** Only pages change:
no code, no score, kind, gate or decision; `tools/outputs_of_a_law.py --against` 894's record: 0 outputs changed.

## For the folders

Nothing to do: a folder on 894 runs the same on 895. **Study 178**: 894 and 895 merged in order and 895 applied; the
fleet stays in the N-push on S178-C15-G73 until it reaches its last size. **The operator's check** (13:06): "once we
have our first workers pushing the 4M size, we'll have confirmed the N-pusher is working fully as intended"; at 12:06Z
the forecast put 4,194,304 on one worker from about 22:23Z.

## What the handover writes, and where

* **`docs/agent/HANDOFF.md`**, rewritten at its head for a context that opens the archive cold: the fleet now (the
  three modes, the N-push and its ladder, the zone search and its look-ahead, the pages' event stream, one code for a
  pushed law); the builds since 886, one line each; the open threads at 895 (the pull requests, study 178 as the
  screenshots of 12:06Z show it, 177's dex, the open questions); what is live; what waits on the operator, the
  sampler's place and Home's refresh brought up to date.
* **`docs/WHERE_WE_ARE.md`**: 895 in the list; 896 read from the first N-push and the first zones; the decision in front
  of the operator.
* **`docs/agent/ZONE_MAP.md`**: the blind draw a mode of its own; a seventh step, each zone with every worker and its N
  by the N-push, and the check of 178's first push.
* **`docs/ROADMAP.md`** pruned to what is open: the plans from 859 to 881 ("From 881", "From 870", "After 860", "After
  859", "After study 172"), made or kept for their reasons, moved unchanged to **`docs/agent/ROADMAP_BEFORE_886.md`**;
  what is still open of them named in "Still open from before 886" (the sampler's trap from empty, bundles as parts of
  the map, the neighbours read at a law's earliest identification). The standing sections ("What still carries the
  past", "The pilots beside the builds") stay.
* **`docs/ARCHITECTURE.md`** read against the code for 889 to 894: the three modes, the push ladder, the pushed law's
  one code, the law page's richest campaign and the event stream have their paragraphs; the depth worker's own law
  (881 to 892) is marked retired where it is described, the fleet's order's step 1 named the N-push.
* **`docs/OPERATIONS.md`**: 881's recipe marked where it no longer holds.
* **`docs/agent/NEXT_BUILD.md`**: 896, the N-push's reading first (the operator's check), then the zones' as at 894.

## What a context taking over should know first

1. **The operator steers through the push list** (08:36): it is their one direct queue; the fleet obeys its order and
   is wholly the first law's while it holds one.
2. **One mode at a time** (10:35): never mix the N-push, the zone search and the blind ladder; free slots go to the
   mode's own work (11:37), the blind draw only when both other queues are empty.
3. **The stack stays ours** (13:00): optimise our own code before adopting a framework.
4. **One law, one name** (13:06): a law is named everywhere by the code it was pushed or found with; a page that shows
   another code for it is a bug.
5. **Stacked pull requests**: 892 and 893 were merged together (11:21Z); 894 (#36) and 895 are open, 895 made on 894;
   merge in order; a new build branches from the newest.

## Acceptance

| the acceptance | the test |
|---|---|
| every page's cross-reference resolves, the moved sections named where they now are | `tests/unit/test_doc_cross_references_resolve.py` |
| no code moves | the tree's diff against 894: pages only |
| no output of a law moves | `tools/outputs_of_a_law.py --against` 894's record: 0 outputs changed |
| the full lane green | the Verification below |

## Verification

4255 passed, 41 skipped in 1281.41s (3 lanes at once)
