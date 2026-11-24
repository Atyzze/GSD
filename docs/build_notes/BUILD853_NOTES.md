# Build 853: every start's admin link checked on a real fleet, stopped three ways, and a page holding an earlier run's link now says so and greys its writes. It changes no decision and no score

**Type: a fix, asked for by the operator on 2026-11-24 at 15:24 ("a basic check to test lets me change the worker
count with what was supposed to be a stale token, I rebooted with server with a ctrl c and then restarted expecting
a new admin token but the old one seems to keep working every time? thats an issue, pls fix :)"; 15:26: "or maybe
the tab cached it or something").** New: `graph_scale_dynamics/services/api/admin_link.py` (`AdminLink`,
`gsd-admin-link-1`), `GET /api/access`, `tests/unit/test_a_stale_admin_link_is_shown_and_refused.py` and
`tests/integration/test_a_restart_makes_a_new_admin_link.py`. Changed: `services/api/main.py` (the token check, the
refusals and the accepted writes go through the link), `resources/ui/system.js` and `system.css` (the top bar's
badge, the greyed writes), `resources/ui/app.js` (the write controls marked), `docs/OPERATIONS.md` ("Who may control
the fleet"), `docs/ARCHITECTURE.md`, `docs/HISTORY.md`. Against 852's record (`tools/outputs_of_a_law.py --against`)
0 outputs moved.

## What was looked for, and not found

Every start already made a new token (`main.py`, `secrets.token_urlsafe(24)` for each run, written to
`var/run/dashboard-admin` with the file truncated), and the API reads only that file. The ways an old token could
still pass were tried on a real fleet in this sandbox (`main.py run`, one worker, its dashboard, the folder's
PostgreSQL), each a start, a stop, a second start, and the first token sent to `POST /api/campaigns/manage` through
the web process:

| how the first run was stopped | the old token after the restart | the new one | anything of the first run still serving |
|---|---|---|---|
| one Ctrl-C (SIGINT, exit 130) | 403 | accepted | nothing |
| two Ctrl-Cs 1.5 s apart (exit -2) | 403 | accepted | nothing |
| a kill (SIGKILL, exit -9) | 403 | accepted | nothing |

The services die with the supervisor (`process_ownership.die_with_owner`, a parent-death signal) even when it is
killed outright, and the page keeps no token but the one in its address, sent with every write and checked by the
API each time: nothing caches the answer. So the server refused an old link every time here. What the operator saw
is not reproduced; the likeliest readings are a tab opened by the restart itself (every start opens one, with the new
link, at the same address but for the token), or a tab of the other folder's fleet, which was not restarted. Neither
can be told from here, so 853 makes it visible instead of guessing.

## What a page shows now

`GET /api/access` answers which link the request holds: `current` (this run's), `stale` (a token that is not this
run's) or `none`, with whether it is admin, when this run's link was made, and how many writes were refused since the
start by kind, never a token. The top bar shows **admin** for this run's link and **admin link from an earlier run**
for another, nothing for a viewer without one; it asks at load and every 30 s. Without this run's link the page greys
its write controls (`data-admin-write`: the worker count, the fleet's pause, a campaign's actions, shares and
budgets, the early gate, a study's delete, a new campaign's start), and a write refused for an earlier run's link
says so in its note (the API's `hint`). The services' console (System) says each accepted admin write, its route and
action, and at most once a minute how many writes were refused and with which kind of link, so the next time a stale
link seems to work the console shows which run's link the write carried.

## The gate

`tests/integration/test_a_restart_makes_a_new_admin_link.py` runs a real fleet three times on free ports, stopped by
one Ctrl-C and then a kill, and holds that each start's link works, every earlier one is refused with the reason and
read as `stale`, a write without one is refused, and nothing answers on the port once a fleet is down (about 75 s, in
the PostgreSQL lane). The unit test runs the API's handler for the three links and the refusal hint, and the page's
own badge and worker count code under node.

## A correction to 851

851 read the 8 laws of 174 that settle by value from the twin starts (the catalogue's `grown`) as most likely loops
carrying trees. The rungs table of 174's bundle (`tables/rungs.ndjson.gz`, the chain from empty) says otherwise: none
carries a tree. Four have no cycle at all (2-core 0, mean degree 1.99, the largest piece 0.5% to 70%): open strings.
Three hold every node on a cycle at mean degree just over 2: 18856793523d and 3a8569fc6094 are one loop over 99.7%
of the nodes with about 13 and 35 edges more than a ring at 65,536, a density that holds from 16,384, and
61e41fb7b3cb has about 284. `measurements/estimators.volume_growth` on a clean ring of 65,536 reads a reach of
16,384, with 10 random chords 5,706, with 30 chords 2,598; the two read 4,891 and 2,512. So they are loops with a few
shortcuts, one dimensional only below a few thousand nodes, and the score is right to refuse them, for that reason.
The eighth, 99e25674e37a (the operator's "specimen", 2026-11-24 15:10), is small cliques strung into strands:
clustering 0.96 and every node on a cycle from empty; its triangular and fcc starts became piles of cliques of about
33 and 29 nodes (171 and 143 triangles a node, against (m-1)(m-2)/6 = 165 and 126 for cliques of that size), and its
square start broke into islands of about 11. The catalogue's `grown` entry says so now
(`resources/catalogue/catalogue.json`, its `first_seen`, a description: no kind or rule moved).

## For the folders

Nothing a folder decides or scores changes; 853 may be given to 174's or 175's folder when it suits, each needing one
restart of its own command. After that restart the old tab says **admin link from an earlier run**; the tab the
start opens holds the new link.

## Verification

3896 passed in 1556.50s (3 lanes at once)
