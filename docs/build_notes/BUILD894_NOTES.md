# Build 894: one name for a pushed law, each size from the campaign with the most seeds, and the pages told of every change

**Type: an operations build, on the operator's words of 2026-11-27**, made on 893 (#35 and 892's #34, merged at 11:21Z). 12:51, with four screenshots: "there is some confusion, the depth workers link to a different
candidate, one of which clearly has additional ~16 seeds wheras the other is stuck in the 3 seeds original, also, when
do these pages update? it seems to be taking quite a while before the new readings show up on the page, can we not
make this event driven push to the dashboard?". 13:00: "maybe the current stack is fine, adopting tools = more code to
rely on, if ours is sufficient as is then ... perhaps optimize our own instead of adopting a foreign one, the confusion
of the same identical law having 2 different G codes + how slowly these candidate pages update their data points ...
that calls for a build for sure, and also we are probably due for a hand over build afterwards". 13:06, with three
more: "this advertised C17 would instead bring me to S178-C15-G73 ... hence all the confusion", "here in the list ...
it shows the wrong one, but if you click on it, it goes to the right one", "pls fix and make it consistent". No score, kind, gate
or decision of any law moves, no frozen source and no schema. `tools/outputs_of_a_law.py --against` 893's record:
0 outputs changed.

## What the screenshots showed

* **One law, two codes, two pages.** 893's N-push runs a pushed law again in a campaign of its own (C17), where the
  law got a code of its own: S178-C15-G73, pushed from campaign 15, was S178-C17-G1 there. The Top page's list and
  its runs table named it G73 and linked campaign 15; the panel of the law being pushed, Home's Now researching and
  the Top 100 by N named it C17-G1 and linked campaign 17. The two law pages are the same law (8addbb0c): C15's
  showed its own 3 seeds at 16,384, C17's the push's 16.
* **The law page never refreshed.** It loaded once; its curves were cached 30 seconds on the server. Home polled
  every 4 seconds (its landscape 16, its heavy panels 32, the fleet ladder's candidates 60), the Top and Map pages 4.

## What changed

1. **A pushed law keeps the code it was pushed with** (`push.home_of`): the label and campaign it was pushed from, on
   the list, the runs under way, the panel of the law being pushed, the Top 100 by N, and Home's Now researching
   (`overview._pushed_as`: a push campaign's live rows carry `pushed_as`, and their chip reads "pushed" from the row
   itself, where 893 showed "other" when the list of campaigns had not come), and the Map page's Working now
   (`zone_live`: the N-push's runs a role of their own, `PUSHED`, named and linked as pushed); every link goes to its
   home page. Opened
   in the push campaign, the law page is headed with the same code and says it is run again there by the N-push,
   with a link home (`law_elsewhere.pushed_as`).
2. **The law page draws each size from the campaign of the law with the most seeds there**
   (`law_elsewhere.measurements`, `richer`): its curves, every chain's reading and the curves at a size, and its rung
   table, each row marked with the campaign it was read in. A campaign's own readings stay where no other has more.
   The score on the page still reads its own campaign's seeds, as every list of the study ranks the law. So both
   pages of G73 now draw the push's 16 seeds at 16,384 and 65,536.
3. **The pages are told of every change of the work** (`services/api/events.py`, `/api/events`, Server-Sent Events,
   no new dependency). Postgres already notifies `gsd_work` on every change of a run, a probe and a rung summary
   rebuilt (the workers wake on it); the API listens on a connection of its own for each page that follows, gathers
   what came within a second, and sends it on (`gathered`: the tables, whether a reading is new, whether runs
   moved), a ping every 15 seconds while nothing moves. A new reading drops the server's cached curves at once. The
   web service relays the stream as it is written (`streaming.relay_events`); at most 8 pages follow at once, a
   ninth polls as before.
4. **Every page listens** (`GSD_SYSTEM.onWork`, `followEvents`): a change brings the header's overview within a
   second; the Top and Map pages read again; Home reads its selection and landscape again on a new reading; and **the
   law page reloads itself** on a new reading of the fleet, at most every 15 seconds, keeping where you scrolled, not
   while a tooltip is pinned or the tab is hidden (then on its return). With the stream open the header polls every 15
   seconds rather than 4; without it, as before.
5. **The ladder's break-points at one size are one label** ("two passes, one worker · N=4,194,304"), anchored inside
   the chart at its edges.

## For the folders

* **Study 178**: merge this pull request (892 and 893 are on `main`); apply 894 and restart the dashboard (the
  fleet may keep running). The Top page names G73 as you pushed it, both its law pages draw its 16-seed sizes, and an open
  law page brings each new reading within seconds of the probe ending.

## Acceptance, line by line

| the acceptance | the test |
|---|---|
| a pushed law is named and linked as it was pushed: the panel, the runs, the list, Home's live rows, the Map's Working now | `tests/integration/test_the_push_list_is_the_operator_s_queue_postgres.py` |
| the push campaign's law page keeps the pushed code and links home | `tests/ui/candidate_smoke.js` |
| each size from the campaign with the most seeds, the score its own; a campaign with fewer leaves it | `tests/unit/test_the_law_page_reads_every_campaign_of_its_law.py` |
| a change of the work gathered and said; hello, work and pings; the caches dropped on a reading; a page gone ends its stream; past 8 a page polls | `tests/unit/test_the_pages_follow_the_fleet_s_events.py` |
| a run queued reaches a listening page from Postgres; the web relay passes it on as written | `tests/integration/test_the_pages_hear_the_fleet_s_work_from_postgres_postgres.py` |
| two break-points at one size are one label | `tests/ui/dashboard_smoke.js` |
| no output of a law moves | `tools/outputs_of_a_law.py --against` 893's record: 0 outputs changed |
| the full lane green | the Verification below |

## What it does not do, and what the operator decides

* **The stack stays ours** (13:00): no framework is adopted; the stream is the standard library's server and the
  browser's own `EventSource`.
* **A reading still takes its probes' time**: a run's readings appear once its probes end (about 2 minutes at
  65,536, about 16 at 262,144 for G73) and its rung summary is rebuilt; the page now shows them within seconds of
  that, not minutes.
* **Codes are unchanged in the data**: the push campaign's code (C17-G1) still exists in its tables and its bundle;
  the pages name the law as it was pushed.
* **895 is the handover** (13:00).

## Verification

4255 passed, 41 skipped in 1223.34s (3 lanes at once)
