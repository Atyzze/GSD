# Build 874: the pages' and reports' build numbers in words

**Type: a cleanup build on the dashboard's pages and the reports' builders, the operator's 2026-11-25 10:00, made on
their word of 23:25 to keep building to the roadmap's end.** No score, kind or decision moves: only text a reader sees
changed; `tools/outputs_of_a_law.py --against` 870's record (unchanged through 873): 0 outputs changed. No schema
change. It may be applied to a running folder.

## For the folders

* Nothing to press, nothing to wait for. The pages and the reports read as before, their build numbers said in words.

## What changed

1. **The pages** (`resources/ui/`: `app.js`, `map.js`, `system.js`, `candidate.html`): every "(784)", "(608)",
   "before 544" and the like said as the rule or the reason it stood for ("before the curvature was read", "before the
   meeting of the chains was read"), or dropped where the sentence already said it. The dashboard's smoke reads the gate
   trees' page for an old build number instead of one named build.
2. **The reports and the messages** (25 files under `reporting/`, `research/`, `operations/`, `services/`,
   `observability/`, `calibration/` and `scaleflow/`): the same in every text a report, a page's data or a refusal
   carries; a sentence that leaned on a number now says the rule ("the fixed limit the thresholds replaced", "its
   thresholds committed in resources/calibration/structure_thresholds.json", "a review's finding L19").
3. **What the numbers stood for** is kept in `docs/HISTORY.md`, under "Reports, pages and papers", one line each.
4. **Kept as written**: a decision's recorded reason (`decisions/`, which `decisions/replay.py` replays word for
   word); four values in a law's or a report's own outputs, which `outputs_of_a_law` holds fixed or a report compares
   with (the reporter's transport "in place (548)", the stability score's tolerance rule, the equilibration note, the
   claim ledger's pointer into `docs/HISTORY.md`); and the documents' claims (`research/document_claims.py`), which
   quote the docs word for word. The docs keep their build numbers; they are the history.
5. **873's save test measures the processor's time**: its extrapolation of a seed's save to 1,048,576 read the wall
   clock, so a host busy with the gate's lanes read as a slow save (133 s here beside a running gate, about 56 s
   alone); it now reads `time.process_time`, the save's own work.

## Acceptance, line by line

| the acceptance (`docs/agent/NEXT_BUILD.md` at 873) | the test |
|---|---|
| no build number in a page's text | `tests/unit/test_the_pages_and_reports_say_no_build_number.py`, the first: every `.js` and `.html` of `resources/ui/` |
| no build number in a report's text, the decisions' reasons untouched | the same file's second: every string in the package's code outside `decisions/` and the five kept files, and a decision's reason still carrying its number |
| no score, kind or decision moves | `outputs_of_a_law --against`: 0 changed |
| the full lane green | the Verification below |

## What it does not do

* The docs' build numbers stay: `docs/HISTORY.md`, the notes and the roadmap are where the builds are the history.
* A test's own failure message may still name the build that made its rule; it is read by whoever changes the code.

## Verification

4053 passed in 1295.38s (3 lanes at once)
