# Comparison experiment C-1 — design (d5, before the freeze)

English translation. The frozen original is `ja/c1/DESIGN-compare-d5.md`; the hash in `FREEZE-C1.md` refers to that file.

This revision reflects the external review of d1–d4 (items C1-01 to 05, C2-01 to 03, C3-01 to 02, C4-01 to 05). It is an **exploratory comparison** with 2 repetitions; conclusions are stated only within the range of the results obtained.

## The question, and what may be claimed (C1-03)
The primary metric is **measured time = the solver's response time as reported by the environment + the machine-side processing time** (C4-05). It does not include the time the operator spends between replies, so it is not "wall-clock time from request to completion" as such. The results use this name too.
The primary judgment may state exactly one sentence: **"Under these conditions, in measured time (reported response time + machine processing time), Shuttle was / could not be said to be at least 5 times faster than the JSON full-rewrite method (J-full)."**
No general claim "faster than JSON" is made. Ratios against JSON Patch (J-patch) and Weft full rewrite (W-full) are computed the same way and all reported, but are not used in the primary judgment. If J-patch is faster than Shuttle, the report says so.

## Arms (4)
| Arm | What the model receives | What the model sends in one reply | Machine-side processing |
|---|---|---|---|
| J-full | format card + schema + whole state (JSON) + request | the whole new state (JSON) | parse → schema check → replace the candidate state |
| J-patch | same | a JSON Patch (RFC 6902) | apply to the current state → schema check |
| W-full | format card + schema + whole state (Weft table form) + request | the whole new state (Weft) | parse → schema check → replace |
| S | Shuttle card + schema + a 2-row sample + request | an operation message | executor v6 r10 |

## Procedure (same for every arm, C1-02)
- 1 cell = 1 new conversation. No history is carried over.
- Each reply is either a submission (one code block) or `DONE`. **At most 6 replies and 600 seconds of measured time in total**, the same for every arm. If measured time is already 600 seconds or more when a reply arrives, that reply is discarded unprocessed and the cell ends (end time 600 seconds). A submission that arrives before 600 seconds is processed to the end even if processing crosses 600 seconds, and its result is used for grading (C4-02).
- The machine processes each submission and returns a result. The kind of information returned is the same for every arm:
  - Success: a note that it was accepted and a count summary (J-full/W-full: number of rows; J-patch: number of operations applied; S: the receipt).
  - Failure: **every mechanically detectable error** (syntax, type and schema violations, duplicate keys, Patch application failure, S execution errors) and its position. A failed submission does not change the state.
  - **The result of the independent grader (whether the state is correct) is never returned during a cell, for any arm.**
- The schema check uses the same rules for all 4 arms (column types, required columns, key uniqueness, shape of the child table, types of the 3 audit fields, dates that exist). Types are checked as the types of each format (a keyword is not a string, and so on); a violating submission is not applied. S is also checked the same way on the state after execution and is not applied on a violation (C4-01).
- The J-patch state keeps the submitted and applied JSON as it is, without rewriting. Numeric normalisation happens only at grading (C4-03).
- An unterminated code block counts as 1 reply and gets "not terminated; nothing was submitted". The cause is recorded as "output limit" only when the environment reports a finish reason; otherwise it is recorded as "unterminated reply, cause unknown". The latter is not treated as a measurement of the output limit (C4-04).
- A cell ends on `DONE`, on reaching 6 replies, or on reaching 10 minutes, and the state at that moment is graded.

## Sizes, tasks, repetitions
- Size N (number of orders, each with 1–4 detail lines): 50 / 500 / 5,000. The size used for the primary judgment is written **N\***. N\* defaults to 500 and changes only by the pilot rule below (C2-03).
- 6 tasks (the same 6 kinds as d1, with new random seeds).
- 2 repetitions (a different seed per repetition). **For the same task and repetition, all 4 arms get the identical initial state and the identical request text.**
- The run order is shuffled with a fixed seed so that the arms interleave. The order table is part of the frozen material.

## Value representation and grading (C1-05)
- In JSON: amounts are strings (`"12.50"`), dates are strings (`"2026-03-01"`), keywords are strings without the colon (`"unpaid"`), nil is `null`. The format card says so.
- Grading compares logical values with the same rules for every arm: amounts match if numerically equal (trailing zeros do not matter); dates, keywords, strings and integers must match exactly; lists must match in order and duplicates; table rows must match in order (added rows go at the end); map key order does not matter.
- The expected state is computed by code separate from the executor and from each arm's processor.

## Run conditions (C1-05)
- Solver: claude-haiku-5-5. Generation settings (temperature, thinking, output limit) cannot be set in this environment, so the defaults are used, and **a pilot run before the freeze (not graded, different seed) records the observed output limit and context length**.
- If the pilot shows that J-full cannot write the whole N=500 state within the output limit, N\* is set to 50 **before the freeze**, and that fact is written in the results. If it cannot be written even at N=50, the result is "**primary judgment not possible**": no primary judgment, only the report of all cells. N\* does not change after the freeze.
- A cell whose input exceeds the context length is not run and is recorded as "not runnable" (it counts as not completed in the completion rate).
- Infrastructure failures (C2-01):
  - **Failure before start** (a connection failure with no first reply received): the cell is restarted from the beginning. Only the restarted attempt is timed. At most 2 restarts; the count is recorded.
  - **Failure during a cell** (after at least 1 reply, the solver stops replying, and so on): the attempt is **kept in the record as "infrastructure failure" and is an invalid trial**. It is not replaced by a successful re-run. One re-run is made and listed separately as a "reference record"; it is not used in the primary judgment.
  - **Reaching 6 replies or 10 minutes is not an infrastructure failure.** The end reason (DONE / reply limit / time limit) is recorded; completed or not is decided only by whether the final state equals the expected state, regardless of the end reason (C3-01).
  - When a (task, repetition) has an invalid trial, **that (task, repetition) is removed from the primary tally for all arms** (common valid trials). The number removed and the reasons are reported.

## Timing (C1-04)
- **The primary metric is uncorrected measured time** (C2-02, C3-02, C4-05): it starts when the first request is given to the solver. **It ends when the end-of-trial processing is complete**, including the format check and truncation check of the last reply, and including the processing of a submission in progress. If the time limit is reached while waiting for a reply, it ends at the cut-off time. Independent grading is not included.
  - Included: the response time of every solver reply (as reported by the environment), and the machine-side processing per reply (format check, parsing, application, schema check, execution).
  - **A constraint on the clock (a fact of this environment):** a wall clock cannot be placed around a solver call. Reply waiting time uses the duration the environment reports per reply; machine-side processing is measured with a wall clock inside the processor. Measured time = the sum of the two. Time the operator spends between replies is not counted for any arm. The results state this constraint.
  - Not included: generating the initial state, loading the state and building indexes, assembling the input text, independent grading. These are measured and reported separately per arm.
- The time of an empty task ("answer only DONE") is measured per arm but is a **reference value** only. It is not treated as a fixed start-up time and is not used in the primary judgment; values with it subtracted are shown only for reference.

## Judgment (pre-registered, C1-01)
Term: a cell is "completed" when its final state equals the expected state.
- Denominator: at size N\*, 6 tasks × 2 repetitions = 12 (task, repetition) pairs. Removing, for all arms alike, the pairs that had an invalid trial gives the **common valid trials**.
- **Tasks for which a ratio is computed:** at N\*, only tasks where both repetitions are common valid trials and J-full and S **both completed both times**. The ratio of such a task = (mean of J-full's 2 measured times) ÷ (mean of S's 2 measured times).
- The report says **"at least 5 times faster"** only if all of these hold:
  1. A ratio can be computed for at least 5 of the 6 tasks.
  2. The ratio is ≥ 5 on at least 5 of them.
  3. On the common valid trials, S completed at least as many cells as J-full.
- The report sentence includes the actual N\* ("under the N=500 condition, ...").
- If 1 does not hold, the report says "**inconclusive** (not enough comparable tasks)" and reports completion rates. A non-completion is not counted as a win in the ratio.
- If 1 holds but 2 or 3 does not, the report says "could not be said to be at least 5 times faster".
- Ratios against J-patch and W-full are reported with the same computation rule (not used for the claim). For sizes other than N\*, all cells are reported.
- Whatever the result, the times, tokens, reply counts, failure kinds and conversation records of all cells are published.

## Sequence
Design approval → task generator, processors for the 4 arms, grader, format cards → independent check (external review) → pilot run to observe the limits → freeze the SHA-256 of the actual files → run → results. Any change after the freeze is written in the results with what changed and why.
