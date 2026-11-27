# Build 889: a law pushed to the N limit from its page, and a Top page to watch it

**Type: an operations build, on the operator's words of 2026-11-27 02:22, on S178-C15-G133's law page** ("I
reaaaaallllly want to see the N Being pushed higher here"; "a new button on this page so that we can manually toggle
whether or not to push this law to the N limit and as soon as that list is non empty, we still allocate 1
thread/worker on top of all the other seed work going on, we push this specific law on top, single seed by single
seed"; "a dedicated page for the 'top' pushing, where we keep a list of the top100 not by score but by sheer N count";
"the memory ballooning basically so it can predict when it will hit the memory limit and how much more would be
needed"; "this would still share the same queue as the zone mapper"). `docs/ROADMAP.md`, "From 888's run". Also
recorded: the operator's answers of 01:55 ("B, and the rule": "Yes"): a neighbour is alike by its locked-in curves,
its kind as fallback, and the first zone is the rule's, G79's family, then G37's (890). No score, kind, gate or decision
of any law moves, no frozen source and no schema. `tools/outputs_of_a_law.py --against` 888's record: 0 outputs
changed.

## For the folders

* **Study 178**: apply 889 and restart the fleet. Open a law's page (S178-C15-G133's, say) and press "push to the N
  limit" (the admin link's page: the button posts to the focus). Within a minute the depth worker takes it, even while
  the dex is verified and no law is in focus: its one worker runs the law from 64 upward, one seed after another, each
  size past 65,536 bought only while it fits half the host's memory (873's pricing). The new **Top** page (beside Map)
  shows it: the law being pushed, its peak memory at each size it has read, the sizes ahead priced from its own peaks,
  where it will stop and how much more memory the next size would need; then every law of the study by the deepest N
  it has read, each with a push button.
* **What to watch**: btop's one busy core on the pushed law beside the Dex work; the Top page's chart filling a point
  a size; the law page's curves gaining 262,144 and beyond.

## What changed

1. **The push list** (`operations/push.py`, the focus state's `pushed`): a law is put on it or taken off by the focus's
   `push` and `unpush` (POST `/api/focus`, `{"do": "push", "law": ..., "campaign": ...}`), with its whole id and
   campaign from its page, or an id's beginning. A pushed law is a contender of the depth worker that is never dropped
   for not scoring, and the first of its line, in the list's order (`push.front` in `focus.depth_line`); pushing a law
   sets the depth campaign's one worker. The depth worker runs it with or without a law in focus, and while a dex is
   verified. A law it already runs is finished first: the next pushed waits, so the zone's laws and the pushed share
   one queue on one worker. Taken off the list, a law that does not score is no longer a contender, and the depth
   worker turns to the next.
2. **The law page** has a "push to the N limit" toggle beside its repro buttons; it reads whether its law is pushed
   (`/api/focus/top`) and says "pushed: stop pushing" when it is.
3. **The Top page** (`/top`, `GSD_TOP` in `map.js`, `/api/focus/top`, `push.reading`): the pushed laws with their
   deepest N, the law the depth worker runs now; the law being pushed, with its peak resident memory, time a run and
   largest edge count at each size (`push.sizes`, from the attempts), a log scale chart of its memory over N with the
   depth worker's reach, and the sizes ahead of it priced from its own peaks (`push.forecast`, `depth_reach.price`):
   the first size past the reach, and how much more memory it would need; and the study's laws by the deepest size
   any of their runs has finished (`push.deepest`), the top 100, each with a push or stop button.

## Acceptance, line by line

| the acceptance | the test |
|---|---|
| a pushed law goes to the depth worker with nothing in focus and nothing scoring; its campaign holds one worker | `tests/integration/test_a_law_pushed_to_the_n_limit_goes_first_to_the_depth_worker_postgres.py` |
| a second pushed law waits for the first; taken off the list, the first gives way to the next | the same |
| the Top page's reading: the laws by N, the law's sizes and memory, where it stops and how much more it needs | the same |
| the Top page draws all of it; the nav reads Home, Map, Top, ...; `/top` boots | `tests/ui/dashboard_smoke.js`, `tests/unit/test_spa_routes.py`, `tests/unit/test_dashboard_smoke.py` |
| the law page has the toggle and asks whether its law is pushed | `tests/ui/candidate_smoke.js` |
| no output of a law moves | `tools/outputs_of_a_law.py --against` 888's record: 0 outputs changed |
| the full lane green | the Verification below |

## What it does not do

* It does not stop a law the depth worker is running for a pushed one; a pushed law waits for it. Say so if a pushed
  law should go first at once: that drops the running law's queued sizes.
* It is a stopgap by the operator's own words: once the zone's search pushes each zone's central law (890), the push
  list may go.

## Verification

4230 passed, 41 skipped in 1505.47s (3 lanes at once)
