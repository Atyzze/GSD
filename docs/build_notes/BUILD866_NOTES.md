# Build 866: one slider between the blind draw and the focus, the focus's and the depth's lists in the operator's order, one depth worker, and the earliest size a law is identified at

**Type: a feature build, asked for by the operator on 2026-11-25 at 13:11 (their words in `docs/HISTORY.md`).** It
may be applied to study 174's folder: no score, kind or decision of a law moves (`tools/outputs_of_a_law.py --against`
865's record: 0 outputs changed; `tools/replay_bundle.py` on 174's bundle of 2026-11-25 09:59Z: every decision replays).
Nothing under `decisions/`, `scaleflow/`, `measurements/`, `engine/` or `engine_rs/` changed, and nothing in `main.py`.

## For the folders

**Study 174**: apply it and restart; open Map. The focus's first step after the restart keeps its law and its rings;
the slider shows the lean it reads from the shares (33% focus for 174's A 50%, N 25%, D 25%); the next law the
focus takes leans the folder 50-50 unless the slider was moved first, and the depth campaign is held to one worker from
the first lean.

## Is the focus working? (13:11)

"I either way basically cant tell whether or not work has started or not". It had: in the operator's screenshots the
focus held C8-G2983 with its 44 rings and 3 terms switched off started at 64, Home's zoned side running 2 and queued
9, and the depth campaign's five laws at 64. A focus law's rings climb the base block before they are read at 16,384,
and a group with nothing queued gives its slots to the blind draw, so little runs at first. The Map page now says,
under the slider, each focus campaign's work: running, queued, done and its deepest size (`focus.work_of`, `work` in
`GET /api/focus`).

## The slider (13:11)

"turn the split into a slider between allocating workers to random draws vs in focus ... no need for a 'stop' or
'focus now'". The Map page's split box, "stop the focus", "start again" and "focus now" are gone; one slider from
"random draw" to "in focus", in steps of 5%, sets the share (`POST /api/focus`, `do: lean`, `focus` from 0 to 1,
`focus.lean`): the blind draw (A) and the focus's neighbours and seeds (N) share the workers as the slider says, and
the depth seeker (D) always holds one, its campaign capped at one worker and given one sixteenth (one worker of the
folder's count) so it takes its one when it has work. At 0 the focus is off (its three campaigns paused, the shares A
alone); any share above 0 turns it on again. "100 random first and on first reading ... 50-50": a focus takes its
first law at a lean of 50% unless the operator set one; until then N and D have nothing queued, so the blind draw has
every worker. A group at its campaign's cap leaves its slot to the others (`work_groups.in_shares`).

## Two lists in the operator's order (13:11)

"two selection menus, 1 for each? with a top10 by default suggested by the best data and then set manually up/down".
**Focus next** lists the ten laws the focus takes next, in its order (the least known type first, then score, 865),
**Depth next** the ten laws the depth seeker takes, by score; each row has up and down, the focus's list skip too, and
"the suggested order" forgets the hand order. A law moved is placed by hand (a dot), the rest follow the suggested
order (`do: order`, `list`, `law`, `move`: up, down, top or reset; `focus.reorder`, `suggested`, `depth_order`). The
focus takes the first free law of its list when its law ends; a law reaching the depth list's top `deep laws` joins
the depth campaign, one already in it keeps running. "The queue" stays as the overview of every scoring law, without
"focus now".

## The earliest identification, read beside 16,384 (13:11)

"let's pick the smallest rung that was needed for the first confirmed data point ... and then we compare results to
auto identify the earliest possible identification". Each law's **identified from** is the smallest size from which
its kind stays the one it reads at its largest (`focus.identified_from`), shown in both lists and for the law in
focus ("its kind at 16,384: ring, read so from N=64"). The focus still reads its neighbours at 16,384; beside it, it
now reads each neighbour's kind at its law's identified size and says how often that early call agrees with 16,384
(`early_call`: "the call at N=64 agrees with 16,384 on k of m neighbours read"). When those readings say the early
call holds, a later build reads the neighbours there and confirms a sample at 16,384, which would map a ring's region
in seconds instead of hours; the rule is the operator's to choose on that reading, as the method asks.

## Smaller

* **"ring ring"** in the queue (865's type of a law the catalogue calls "ring or chain made") now reads "made ring";
  a folder's types are read again under the new words.
* **Known answers**: Home's tick names each control law that fails and, on its mouse-over, every control law's verdict
  and why; each bundle's `study.json` carries the verdict with every law's row (`known_answers` on the campaign), so
  174's "fail" can be read from its next bundle.

## The depth seeker to the memory limit, next

"always just 1 worker thread responsible for always pushing the memory limit to the system max (+ its free buffer
zone ofc) but automatically testing how far N is feasible". 866 holds it to one worker. Its ladder still ends at
262,144: a size past the host's reach is today held by memory admission and waits queued, and with one worker held
that would idle a slot. The seeker comes next: the depth campaign's next size priced from the law's own peak growth
and bought only when it fits the host's reach less its free 10 GiB, else the law settled at its memory ceiling with
the size it reached and the bytes it would need (`docs/ROADMAP.md`).

## Tests

The Map page's smoke (the slider and its words, the work line, both lists with up, down and the suggested order, no
"focus now", stop or split); `test_the_map_names_its_regions_and_takes_the_operator_s_hand.py` (a capped group yields
its slot, the earliest identification, the hand order first and reset); the focus's Postgres test (the first law
leans 50-50 with the depth campaign at one worker, the slider at 0 pauses the focus and gives A everything, at 0.8
resumes it).

## Verification

4028 passed in 1285.52s (3 lanes at once)
