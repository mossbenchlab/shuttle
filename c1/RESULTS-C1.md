# Comparison experiment C-1 — results r5 (primary size N\*=50, plus the large sizes N=500 and N=5,000)

English translation. Original: `ja/c1/RESULTS-C1.md`.

Run according to design d5 and the freeze log FREEZE-C1.md (including amendment A1 and the record of a procedure violation). Solver: claude-haiku-5-5. An exploratory comparison (2 repetitions per cell). At the primary size 48 cells were run, 2 of which are invalid because of a procedure violation by the operator.

Arms: J-full = JSON full rewrite, J-patch = JSON Patch, W-full = Weft full rewrite, S = Shuttle.

## Primary judgment
**Inconclusive (not enough comparable tasks).**
- Common valid trials: 10/12. (T1, repetition 2) and (T6, repetition 2) are removed for all arms (see "Procedure violation" below).
- Tasks for which a ratio can be computed (both repetitions valid, and both J-full and S completed twice): 4/6. This does not meet pre-registered condition 1 (at least 5).
- It is settled that the result cannot reach "at least 5 times faster": the 4 computable ratios are 1.26–2.93, none of them 5 or more. With these 4 fixed, no outcome of the remaining 2 tasks could give "ratio ≥ 5 on at least 5 tasks".
- Completions (10 common valid trials): 10/10 for all 4 arms.

## Measured time (common valid trials only; mean of 2 repetitions, seconds)

| Task | J-full | J-patch | W-full | S | J-full÷S | J-patch÷S | W-full÷S |
|---|---|---|---|---|---|---|---|
| T2 bulk update by condition | 35.1 | 22.5 | 40.3 | 27.9 | 1.26 | 0.81 | 1.45 |
| T3 write back an aggregate | 33.2 | 17.5 | 28.3 | 17.3 | 1.91 | 1.01 | 1.63 |
| T4 update parents by a child condition | 43.0 | 30.4 | 44.2 | 32.4 | 1.33 | 0.94 | 1.36 |
| T5 update the top 1 row | 33.3 | 12.8 | 26.1 | 11.4 | 2.93 | 1.13 | 2.29 |
| T1 (only repetition 1 valid) | 33.8 | 11.2 | 26.5 | 11.2 | not computed | not computed | not computed |
| T6 (only repetition 1 valid) | 35.2 | 13.8 | 33.7 | 16.7 | not computed | not computed | not computed |

| Arm | Completed | Mean measured time | of which machine | Mean replies | Mean of first reply | Mean of DONE reply |
|---|---|---|---|---|---|---|
| J-full | 10/10 | 35.8 s | 1.5 ms | 2.00 | 26.0 s | 9.9 s |
| J-patch | 10/10 | 19.2 s | 1.8 ms | 2.00 | 10.1 s | 9.1 s |
| W-full | 10/10 | 33.8 s | 17.2 ms | 2.00 | 23.4 s | 10.4 s |
| S | 10/10 | 20.6 s | 2.0 ms | 2.40 | 8.0 s | 7.4 s |

Measured time = the solver's response time as reported by the environment + the machine-side processing time. It does not include time the operator spends between replies.

## What can be read from this (outside the primary judgment; facts within this record)
- Of the 4 tasks with a computable ratio, **JSON Patch was faster than Shuttle on 2** (T2, T4), Shuttle was faster on 1 (T5), and T3 was about the same (17.5 s vs 17.3 s). Mean over the 10 valid trials: JSON Patch 19.2 s, Shuttle 20.6 s.
- Machine-side processing was under 20 ms for every arm. Measured time is almost entirely solver response time.
- Time per reply (valid trials): even a reply that only returns DONE took 5.1–13.6 s (the procedure re-reads the task file and the transcript file; per-arm means are in the table above). Whether this is a "fixed start-up time" or proportional to the amount read cannot be separated from this record alone (DONE replies of J-full and W-full tend to be longer than those of S and J-patch, but the cause was not isolated).
- Shuttle used 3 replies in 4 of its 10 valid cells (write → confirming query → DONE). The other arms used 2 replies in every cell (submission → DONE).
- At N=50, the number of tool uses was 2–3 in every reply. No cell had a count suggesting use outside the rule.

## Procedure violation (operator error)
The second replies of S-T1-50-2 and S-T6-50-2 were written after reading only the task file (neither the reply history nor the machine result was passed). The first replies of these 2 cells had been processed with the procedure from before amendment A1, so no transcript file (transcript1) had been created; without noticing this, the operator started the second reply with the instruction "read transcript1". In both cells the solver submitted the same write again.
- In the actual run, both were rejected as "stale version" because of the `tx … at 0` line the solver had added, and the state did not change.
- Had there been no `tx` (as verified by the external review): **T1 would have added the quantity again, giving a wrong state. T6 would have been rejected with `duplicate key id=900002`, leaving the state unchanged.** The version check and the duplicate-key check each do their job.
- These 2 cells are invalid trials. The re-runs (S-T1-50-2: 2 replies, 12.1 s; S-T6-50-2: 2 replies, 16.6 s; both completed) are reference records (run-rerun/) and are not used in the primary judgment. The original records (run/) are unchanged.
- Prevention: from then on, before starting a second or later reply, a tool check confirms that the transcript file exists and contains as many replies and machine results as there have been replies (c1.py `pre`).

## Large sizes (outside the primary judgment; added in r4)
The 48 cells of N=500 and the 12 S cells of N=5,000 were run to completion according to the procedure. The 12 W-full cells of N=5,000 were cut off at 3 replies (see "Deviation D2" below). J-full and J-patch at N=5,000 were not run, in expectation of exceeding the input limit. In every cell, the second and later replies were started only after `pre` succeeded. The primary judgment (N\*=50, inconclusive) is unchanged.

### N=500: measured time (mean of 2 repetitions, seconds; a number only where the arm completed both repetitions)

| Task | J-full | J-patch | W-full | S | J-full÷S | J-patch÷S | W-full÷S |
|---|---|---|---|---|---|---|---|
| T1 update 1 row by key (※ a no-change task here) | 10.6 | 12.1 | 8.0 | 15.6 | 0.68 | 0.77 | 0.51 |
| T2 bulk update by condition | completed 1/2 | 123.8 | 326.3 | 24.3 | not computable | 5.09 | 13.40 |
| T3 write back an aggregate | completed 0/2 | 108.0 | 169.6 | 18.8 | not computable | 5.76 | 9.04 |
| T4 update parents by a child condition | 446.1 | 216.0 | 397.9 | 31.7 | 14.06 | 6.81 | 12.54 |
| T5 update the top 1 row | 417.1 | 31.4 | 117.2 | 10.9 | 38.44 | 2.89 | 10.80 |
| T6 add a parent with children | completed 1/2 | 27.3 | 118.8 | 23.8 | not computable | 1.15 | 4.996 |

| Arm | Completed | Mean of completed cells | Range of completed cells | Mean replies | Max machine time |
|---|---|---|---|---|---|
| J-full | 8/12 | 331.2 s | 10.1–499.0 s | 2.33 | 17.5 ms |
| J-patch | 12/12 | 86.4 s | 11.2–226.9 s | 1.83 | 20.5 ms |
| W-full | 12/12 | 189.6 s | 7.1–552.0 s | 1.92 | 177.9 ms |
| S | 12/12 | 20.8 s | 10.3–34.4 s | 2.58 | 15.3 ms |

- ※ In both repetitions of T1 at N=500 the target order was already shipped, so "change nothing" was the correct answer (a coincidence of the generator seeds). For every arm it became a task that ends without writing a change, so it is not a comparison of rewriting. S is the slowest on this task. The other arms finished with DONE alone, whereas in both repetitions S first submitted a conditional update that changes nothing if the target is shipped (0 rows changed). In repetition 1 it then sent a confirming query in a separate reply and then DONE (3 replies); in repetition 2 it put the query in the same reply as the update and sent DONE next (2 replies).
- The 4 uncompleted J-full cells (T2 repetition 2, both repetitions of T3, T6 repetition 1) all ended at the 600-second time limit without ever writing a submission file (counted as format errors). The solver's explanations were that it could not output all 500 orders in one write and that it could not verify the aggregate by hand.
- In the 6 state-rewriting cells that J-full completed, the first submission took 319–436 s.
- Pairs where the ratio was 5 or more: J-full÷S on 2 of the 3 computable tasks (T4, T5); J-patch÷S on 3 of 6 (T2, T3, T4); W-full÷S on 4 of 6 (T2–T5; T6 is about 4.996, below 5; T1 is 0.51). **This is an exploratory record with 2 repetitions, not the size fixed in advance for the primary judgment. It is not material for stating "5 times" as a conclusion.**
- Breakdown for S: 6 of 12 cells used 3 or more replies (3 replies in 5 cells, 4 replies in 1). The reply sequences are not uniform: the 4 cells of T2 and T4 are "two accepted replies → DONE"; S-T1-500-1 is "an update that changes 0 rows → query → DONE"; in S-T6-500-1 the first reply was rejected, followed by two accepted replies and DONE (4 replies).

### N=5,000

| Task | S repetition 1 | S repetition 2 | W-full |
|---|---|---|---|
| T1 | 12.7 s (2 replies) | 11.1 s (2) | no submission (cut off at 3 replies) |
| T2 | 26.3 (3) | 12.6 (2) | same |
| T3 | 39.7 (4) | 16.2 (2) | same |
| T4 | 53.3 (4) | 37.0 (3) | same |
| T5 | 23.3 (3) | 11.6 (2) | same |
| T6 | 15.5 (2) | 32.2 (3) | same |

- S: 12/12 completed, mean 24.3 s (11.1–53.3 s), mean replies 2.67, max machine time 164.4 ms.
- W-full: 12 cells × 3 replies = 36 replies, with 0 state submissions. In 34 replies no submission file was written; in 2 replies (the 2nd and 3rd of W-full-T3-5000-1) only an explanation that it would not submit was written (counted as format errors). The task text is about 260k tokens (o200k count), and the solver did not read all of it (it reports the line ranges it read).
- The mean for S is 20.6 s at N=50 (10 valid trials), 20.8 s at N=500 and 24.3 s at N=5,000. The task text for S is about 1.5k tokens at every size.

### Deviation D2 from the procedure (an operator decision; differs from the frozen procedure)
For W-full at N=5,000 the procedure says to continue "to 6 replies or 600 seconds", but each cell was cut off at 3 replies. Reason: 0 submissions in 36 replies; the task text exceeds what the solver can read, and it was judged that rewriting everything would not succeed in the remaining replies either. **These 12 cells are "not completed (cut off)", not ended by the time limit or the reply limit.** Their measured times (59–200 s) are values up to the cut-off and are not used in comparisons. The remaining 3 replies can be run if needed (the records are in a state that can be continued).

### Not confirmed: tool use
- The solver was instructed to use "only Read and Write", but the operator cannot confirm from the record which tools were actually used (the environment returns only the count of uses and the response time).
- The 6 replies at N=500 in which J-full wrote a state that was accepted all used 8–13 tool calls (J-full-T2-500-1: 11, T4-500-1: 8, T4-500-2: 13, T5-500-1: 11, T5-500-2: 12, T6-500-2: 13). The first reply of W-full-T4-500-2 also used 12. It is unknown whether reading a long task text in parts alone explains these counts. **Because Write can only overwrite, a solver that wrote in pieces may have used a tool other than Read/Write (appending or editing). This is not confirmed.** The kind of tool is not recorded for any arm, so whether the rule was followed, and in which direction a violation would have affected the results, is unconfirmed for all arms.
- S used 2–3 tool calls in every reply. J-patch used 4–8.

### What this record does and does not support
- Supported (facts within this record): as the number of orders went 50 → 500 → 5,000, the measured time of S stayed within about 10.2–53.3 s across all sizes. The full-rewrite arms took minutes or did not complete at 500 orders. For full rewriting at 5,000 orders, Weft was cut off with zero submissions through 3 replies, and JSON was not run. JSON Patch completed every cell at 500 orders but took 98–227 s on the tasks that touch many rows (T2, T3, T4).
- Supported with its conditions stated: in this run with 500 orders, 2 repetitions and solver claude-haiku-5-5, the measured time of S was about 1/14 of JSON full rewrite on T4 and about 1/38 on T5, and about 1/5–1/7 of JSON Patch on T2, T3 and T4 (on T1, T5 and T6 the ratio against JSON Patch was 0.77–2.89).
- Not supported: the general conclusion "Shuttle is at least 5 times faster than JSON". At the primary size (N\*=50) the ratios are 1.26–2.93 and the judgment is inconclusive. The large sizes are outside the primary judgment, with 2 repetitions, 1 solver model, and unconfirmed tool use.
- Further caution: there is 1 solver model (claude-haiku-5-5). Several cells ran at the same time, so response times may include effects of concurrency (arms were not skewed, but the effect is not cancelled either).

## History: the table before correction (includes the 2 invalid cells; not to be used)
The first report (r1) gave the primary judgment as "could not be said to be at least 5 times faster" with the table below. It was withdrawn because it includes invalid cells.

| Task | J-full | J-patch | W-full | S | J-full÷S | J-patch÷S | W-full÷S |
|---|---|---|---|---|---|---|---|
| T1 update 1 row by key | 31.5 | 11.6 | 24.2 | 18.0 | 1.75 | 0.65 | 1.34 |
| T2 bulk update by condition | 35.1 | 22.5 | 40.3 | 27.9 | 1.26 | 0.81 | 1.45 |
| T3 write back an aggregate | 33.2 | 17.5 | 28.3 | 17.3 | 1.91 | 1.01 | 1.63 |
| T4 update parents by a child condition | 43.0 | 30.4 | 44.2 | 32.4 | 1.33 | 0.94 | 1.36 |
| T5 update the top 1 row | 33.3 | 12.8 | 26.1 | 11.4 | 2.93 | 1.13 | 2.29 |
| T6 add a parent with children | 33.0 | 13.7 | 33.5 | 21.3 | 1.55 | 0.65 | 1.58 |

| Arm | Mean measured time | of which machine | Mean replies |
|---|---|---|---|
| J-full | 34.9 s | 1.4 ms | 2.00 |
| J-patch | 18.1 s | 1.8 ms | 2.00 |
| W-full | 32.8 s | 17.4 ms | 2.00 |
| S | 21.4 s | 2.1 ms | 2.50 |
