# Working with the operator

How the work with the operator goes. What they have decided about the system is `docs/HISTORY.md`, "The operator's
standing decisions"; their host is `docs/agent/TARGET_ENVIRONMENT.md`.

## Their clock, and files both ways

* **Their clock is UTC+1** (central European time; UTC+2 in summer): the times in their messages and on their screens
  are local; a bundle's name and the records are UTC.
* **Files both ways go through the session.** Theirs arrive in its uploads (`/mnt/user-data/uploads/`, or
  `/root/.claude/uploads/<session>/`; each
  name prefixed with an id) or as an image in the conversation. A build goes to them with the session's file-sending
  tool; they apply it with their own `apply_build.py` ("Apply build N to <folder> and commit/tag it? [y/N]") and
  restart with `uv run python main.py run`.
* They continue a conversation by typing, never by retrying (`docs/HISTORY.md`).

## What they send

* **A study bundle** (`study_<id>_<utc>.tar.zst`, the Reports page's one button), often with no words: read it by
  `docs/OPERATIONS.md`, "Reading what the operator sends" (what it holds: `docs/ARCHITECTURE.md`, "The reports"),
  answer in one plain sentence first, and build what the reading calls for.
* **Never ask them to run a command or a query of your own.** Ask for a bundle: what the database holds belongs in it
  as a report section, so one quiet bundle is the whole ask. A collector's zip is only for what a quiet fleet cannot
  show (live processes over minutes); if no existing tool gathers what is needed, write one in the build and name its
  command (`docs/OPERATIONS.md`, "Sending evidence for a diagnosis").
* **When something breaks** they send screenshots (read them for numbers; a terminal usually shows a tool's log beside
  `btop`), the supervisor's log (`var/log/supervisor.log`), the dashboard's JSON and `df -h`. Read those first.
* **A bug report of their own** comes in sections (evidence, root cause, required changes, acceptance): build it as
  written, map each acceptance line to a test named in the notes, and say plainly what the tree cannot reach.
* **Ideas mid-build**: give each its roadmap line at once, say which build it goes in, and finish the build in hand.

## How they decide

* **They batch** several requests and questions in one message: answer every one.
* **A decision that is theirs** is asked in plain words with numbered options (as choices, where the session can offer
  them), the recommended one first and labelled so, each with its cost. A qualification ("2, but...") is part of the
  answer. The question goes into `docs/ROADMAP.md`, "Questions for the operator", in the same turn and leaves it when
  answered; an answer that keeps constraining the work goes into `docs/HISTORY.md`, "The operator's standing
  decisions", with its date and their words, and into the next build's spec in `docs/agent/NEXT_BUILD.md`.
* **A recommendation states its measured cost before its gain.** They weigh clean, comparable measurements above
  throughput.
* **Is the data enough before a rule acts?** Answer from what the rule rests on; where the live data has not tested a
  margin, propose a shadow stage that records what it would do.
* **What does more data buy?** Answer from the data's own spread, claim by claim: what is settled, what still sharpens
  with every law, what a size would need to see, with the cost in days on their host first.
* **"Did we check?"** Say what was compared, on how many cases, and what was not checked yet; then check it.
* **"Cannot" is a claim to check before it is said**: build or run the smallest case first. A case where a tool reads
  little is still run and shown, its limits stated.
* **Outliers matter most**: never average them away; name them by law id.
* **The whole of it is read, not a sample**: a reading meant to conclude covers every chain of every start and says
  what it could not reach; offer a cheaper part only with its cost.
* **Reading before deciding**: a new reading is checked on known answers committed before its run, then read on their
  data, then offered as a rule with its cost before its gain; the rule is theirs to choose.
* **Data before a new study**: its changes are measured on the last study's own laws first, predictions committed;
  only a confirmation run is exempt, and where little would change they choose one.
* **A setting nobody has fixed is drawn, not chosen**: every new setting, a study's starts included, is drawn from its
  whole range and recorded. Offer a fixed value only where drawing cannot work, and say why.
* **They judge a fix by what it does on their host, in btop**: say what it should show there (cells running, memory in
  use, CPU) in numbers, and which part the host itself limits.
* **They change their mind when the data says so**: never write a test that asserts their last preference has not come
  back.
* **A table keeps its shape**: a new number goes into its column's mouse-over, not a new row or column, and no table
  gets a horizontal scroll bar.
* **A chain is named by its start**: the chain from empty, the random start's, a lattice's. No start is first, and
  the names an older design gave the chains are gone from the code and the pages (2026-11-10 20:05,
  `docs/HISTORY.md`); a word carried from an older design is said in today's terms. **The twin starts** are the chain
  from empty and the random start's, of equal weight, and the word names only that pair; the six lattice starts are
  given structure (2026-11-14 18:45). One rule: every graph must stop changing; at a finite temperature the twin
  starts must also land together; at zero temperature where each rests is the finding.
* **A consolidation is timed by the work**, about every ten builds (`docs/ROADMAP.md`, "Build cadence"): never in the
  middle of a fix a live folder waits for; offer one when the notes pile up.

## The pace of builds, and what is remembered

* **Keep building while nothing waits on them**: stop only for what they must decide, send or run, and say which.
* **Decided work** is a line under the build that carries it, in `docs/ROADMAP.md`, "Planned builds, in order", by
  priority.
* **What is open lives in the roadmap and the handoff, not only in replies**: a context is summarized when it fills.
* **Remember by pointer, not by prose**: keep what the data cannot recompute; for everything else keep the query,
  report section, test or bundle that recomputes it. The consolidation builds are that loop for the repository.
* **A turn does not end on a request to go on.** While nothing waits on them the builds go on (2026-11-11 13:30: "so why
  did you pause and ask me for a continue?"); a turn ends on a delivery, a question that is theirs, or a limit said
  plainly.
* **A context reset is theirs to call**: asked for a hand-over, the build rewrites the documents for a context that
  knows nothing (the handoff's path, the data in the tree, what waits on them) and reads their latest bundle. Every
  build's pages are written so that the next conversation can start from its archive alone, since any build may be
  the last of its conversation.
* **What they decided after a build and before the next conversation** arrives typed at the top of that conversation,
  numbered, their words quoted: record each in `docs/HISTORY.md` with its time and words, and build what it changes.

## How to answer them

* **One plain sentence first**, on what it means, before any number; then what was done, then what they do. Plain
  words and the numbers behind them, short tables for comparisons, no lettered lists or fixed reply structure. The
  project on one page is `docs/WHERE_WE_ARE.md`, at most 90 lines and current every build: point them to it rather
  than re-explaining.
* **No em or en dashes anywhere** (replies, documents, pages): use a hyphen, a comma, a semicolon, a colon or a full
  stop.
* **They are "the operator" or "they"**, never a gendered pronoun.
* **Say first what a build is for, to them.** A reading or a measurement in the sandbox needs nothing applied: say so,
  then what it found. A build that changes what the fleet runs: what it changes there, what applying it gains in
  readings (by law, when few), and what not applying it costs. Then what they do (replace, restart, reset or not, any
  command) and which numbers to watch in the next bundle.
* **A build is delivered only as the archive `tools/package_release.py` writes** (`GSD<N>.tar.zst`), after its gate
  passed: never a patch or hand edits, never `BUILD_NUMBER` edited by hand.
* **The sandbox is yours**: its git, branches, signing, permission checks, folders and processes are never theirs to
  decide or allow; mention them only when they change what they get.
* Do not change scoring or decision semantics in a build about something else, and move a frozen science file only
  deliberately (`python3 tools/science_freeze.py --write`), saying so in the notes.
* Never send their email address to any service.

## The code and the pages

* **The code carries no comment or docstring**: its names say what it does; why, and how to run it, go in `docs/`.
  `tests/contract/test_the_code_carries_no_comments.py` holds it, bar the tool directives (`# noqa`, `# type:`,
  `# pragma`), shebangs and the engines' sources, which lose theirs with the engine's next change.
* **Who decided a rule, and when, lives in the documents only** (2026-11-22 12:11): no code, test, page or printed line
  names the operator with a date or a time, or calls a rule theirs; it says what the rule is. Their words and the date go
  in `docs/HISTORY.md` and the build's notes. `tests/contract/test_the_operator_s_words_live_in_the_documents.py` holds
  it.
* **A report is a dynamic HTML page, not a picture.** A new view of the data is a page in the study bundle (as the
  explorer and the gate trees are), standing alone with its data inside, linked from the front page and the Reports
  page. A diagram they may open outside a browser follows `docs/LESSONS.md`, "Diagrams and exports" (exported with
  `tools/diagrams/export_mermaid.js`, checked with `tools/check_svg.py`), and is sent as the `.svg`.
