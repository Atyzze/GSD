# Build 899: a pushed seed held at a tenth over its own peak, and a bundle beside the N-push

**Type: an operations build, on the operator's answer of 2026-11-27 18:26** to 897's two questions ("agree with both
recommendations"), made on 898. It needs a restart of the fleet. No score, kind, gate or decision of any law moves,
no frozen source, no schema; every law outside a push campaign is admitted as before.

## Why

At about 17:26Z three seeds of G73's 1,048,576 ran in study 178, at up to 9.8 GiB each. The admission held each at 1.5
times what it had used (about 14.7 GiB), sized for a law whose memory is unknown, and asked 10.1 GiB to start another,
1.35 times a prediction that grows from the largest peak below. A pushed law's seeds agree: G73's 14 seeds that ran
through 262,144 peaked within 4% of each other (1.47 to 1.53 GiB). And a quiet bundle paused every campaign, so each
running seed of the N-push saved and resumed: the bundle of 14:27Z stopped the 4 seeds of 1,048,576 minutes after the
restart for 896 had.

## What changed

1. **The admission prices a pushed seed itself** (`push_ladder.claim_bytes`, `pushed_ask`, `pushed`; the worker's
   `_admitted`): for a job of a push campaign, 1.1 times the law's own typical whole-run peak at that size or, before
   one, grown from the sizes below (`depth_reach.price`, the same growth the plan uses); never below what that job
   reached before a stop, so a resumed seed, which takes about twice the memory until 900, is asked its own; never
   below 1.25 times a runaway seen there. In 178: a fresh seed of 1,048,576 about 6.6 GiB, a resumed one at 9.8 GiB
   about 10.8.
2. **A running pushed seed is held at 1.1 times its peak** (`push_ladder.PUSHED_SLACK`; `worker.restate_reservation`
   passes it to `memory.settled_reservation_bytes`). 9.8 GiB seeds are held at about 10.8 GiB, so about 5 fit in 54
   GiB where 3 did.
   Whether a job is pushed is read once, at its claim, and kept on the job (`job["pushed"]`) for its restatements;
   the full lane's first run caught a restatement that read it again from a repository without campaigns.
3. **The forecast reads the same numbers** (`push_ladder.asked` is the pushed price; `price`'s hold 1.1 times): the
   Top page says what the admission does.
4. **A quiet bundle leaves the N-push running** (`quiet_report.beside_the_push`): it pauses every other running
   campaign, waits for nothing of the push's work (`work_in_flight(beside=...)`), and names the campaign it left
   running (the record's `beside`, the pausing line). One campaign's report cycle is not refused for the push's work
   either. The bundle's `focus.json` (`push_now`, 897) lists the seeds that ran beside the report; their wall-clock in
   that stretch reads a few minutes of the report's CPU.

## For the folders

* **Study 178**: merge this pull request (897 and 898 first); apply 899 and restart the fleet's services. The seeds
  of 1,048,576 stop, saved, and resume, each asked what it reached before; once running they are held at 1.1 times
  their peak, and the Top page's 1,048,576 says about 5 at once where it said 3. A bundle asked after this leaves them
  running.

## Acceptance, line by line

| the acceptance | the test |
|---|---|
| a pushed seed is asked 1.1 times its law's own typical peak grown to its size, a resumed one its own peak, every other law as before | `tests/integration/test_the_n_push_reads_every_seed_and_stops_at_a_million_postgres.py`, "a pushed seed is asked and held at a tenth over its own peak" |
| a running pushed seed is held at 1.1 times its peak, and the forecast holds it the same | the same test |
| the push's plan buys as many seeds as fit so held | the same file (7 seeds of 1,048,576 on 178's numbers, 5 at 1.5); the climb test (65,536 back to 6 seeds) |
| a quiet bundle pauses every campaign but the push's and waits for nothing of it | `tests/integration/test_quiet_report_postgres.py`, "a quiet bundle leaves the N-push running" |
| the full lane green | the Verification below |

## What it does not do

* **A resumed seed still takes about twice the memory**: 900, measured first.
* **A seed that outgrows its siblings** has a tenth of margin where it had a half; the host's 10 GiB floor, the
  memory shed below 8 GiB and the hard stop at 60% of the host hold as before.

## Verification

4267 passed, 41 skipped in 1398.53s (3 lanes at once)
