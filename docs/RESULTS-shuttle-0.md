# Shuttle v0 → v6 — a working prototype of the core idea, and the observations so far

English translation. Original: `ja/docs/RESULTS-shuttle-0.md`. The log is chronological; it starts on 2026-11-08.

Position: this is exploration at the invention stage. For the sections before the comparison experiment there is no pre-registration and no design for a fair comparison. What was checked is only "does the hypothesis work, and where does it get stuck".

## 1. What was built

- `shuttle.py` (Python, about 600 lines at v0): schema (typed tables, keys, child tables, a document part), state, the operation language, transactions (all or nothing; re-sending the same id returns the same receipt; the `at <version>` precondition), expectations (post-conditions), queries (count / show / get), receipts. Values use the value model of Weft next d6. The whole state can be derived as a document with `materialize()` (used to test equivalence with the correct values of WB-1).
- One operation per line: `set <table> where <cond> : col=value`, `add` (at the end; `after where` for a position; a child table selects its parent by a condition), `del`, `put <doc path> = value`, `expect ...`. Conditions are column comparisons, `in`, `has`, `and/or/not`. A string may span lines (a real line break becomes a newline character).
- Receipt: `ok v=1 set:2 add:1 vid=<12-digit version id>` (v1; in v0 this was a hash of the whole state), or `fail line N: <reason>` with a hint for the fix (the list of column names, the row count, and so on), applying nothing.

## 2. Observation: solving the 6 edit tasks of WB-1 with operations instead of rewriting the document

Solver: claude-fable-5. It was given only the description of the language (about 600 tokens), the schema, part of the state (the first 2 rows of each table and the document part), and the task instruction. The whole document was not given.

| Task | Shuttle in/out | WB-1 N4 in/out | WB-1 W1 | WB-1 J | Result |
|---|---|---|---|---|---|
| e-config | 708 / 30 | 1192 / 159 | 943 / 216 | 1266 / 407 | passed first time |
| e-course | 704 / 35 | 1376 / 333 | 1246 / 497 | 1854 / 932 | passed first time |
| e-inventory | 684 / 38 | 1883 / 809 | 2195 / 1402 | 2959 / 1999 | passed first time |
| e-orders | 824 / 96 | 1869 / 830 | 2232 / 1541 | 3649 / 2888 | passed first time |
| e-readings | 755 / 99 | 1879 / 803 | 2181 / 1437 | 3089 / 2236 | passed first time |
| e-release | 744 / 56 | 1203 / 171 | 912 / 188 | 1121 / 255 | passed first time |
| Total | 4,419 / 354 | 9,402 / 3,105 | 9,709 / 5,281 | 13,938 / 8,717 | 6/6 |

Tokens are o200k counts. (N4 = Weft next with tables, W1 = Weft 1.x, J = JSON; all three rewrite the document.)

- Output: 1/24.6 of the JSON rewrite, 1/14.9 of Weft 1.x, 1/8.8 of Weft next (with tables).
- Input + output: 1/4.7 of JSON, 1/3.1 of Weft 1.x, 1/2.6 of Weft next. Most of the input is the language description (a fixed cost) and can still be shortened.
- In all 6 tasks the final state equalled the correct value of WB-1. 0 repairs.

## 3. What worked

- **The model's output became independent of the number of records.** The operations for the 6 tasks are 3–5 lines and do not depend on the table size (14–24 rows). With rewriting, output was proportional to the number of rows.
- **The model's input was also mostly decoupled from the count.** Only a 2-row example of each table and the document part were given. Targets are addressed by a condition (key), so the model did not need to see the rows concerned.
- **Copying errors in the parts that do not change cannot occur structurally.** Unchanged rows never appear in the model's output. The error of making a condition too broad remains, however (reworded after an external review comment).
- **Semantic checking stayed with the executor.** Types (`status` is a keyword), duplicate keys, non-existent columns and paths, uniqueness of `after where`, post-conditions (`expect`). A failure comes back in the receipt pointing at one line, and nothing is applied.

## 4. Where it got stuck (fed back into the design)

- The solver wrote multi-line strings with real line breaks, not `\n`. That broke a line-oriented language, so the rule became "an unclosed quote continues on the next line".
- Lexical errors crashed with an exception instead of becoming a receipt (fixed). Unclosed strings and extra tokens after a statement were accepted (fixed).
- Addressing the wrong target, as in `set 7010 → :shipped`, is a legal command, so the executor cannot stop it. Whether the habit of having the model write `expect` detects this kind of error is unconfirmed.

## 5. Limits

- 6 tasks, 1 model, 1 run. The tasks are the WB-1 edit tasks and were not made for Shuttle.
- The tables are small (14–24 rows). Independence from the count is not shown at large N.
- Because the counts are small, machine-side time differences have not been measured yet.
- Not compared with an arm that "writes only operations as JSON Patch" (a fair comparison is to be designed separately once the shape exists).

## 6. Next

1. Make N large (5,000 orders, 500,000). See whether output and input stay constant. Rewriting becomes impossible in proportion to N, so the comparison will be against "JSON that writes operations".
2. Add work addressed in bulk by a condition ("put every overdue unpaid order on hold"). See that it stays one line as the count grows.
3. Have queries that return information only when the model asks (count / show / get) used inside the work.
4. Measure executor time (apply, verify, receipt versus parsing and rewriting a document).

## 7. v1 (after the external review, same day)

The 4 defects reproduced by the review were fixed and whole-table processing in the executor was removed. 25 regression tests pass (including the 4 counterexamples).

- Defects: (1) document-part changes of a failed transaction remained (the save was a shallow copy); (2) on an unexpected exception the earlier updates remained; (3) `set` could create a duplicate key; (4) `add` / `put xs[i]` on a document list slipped past the type check. → An undo record per change (no more copying all tables), rollback and a receipt on every exception, key-uniqueness verification on update, checking of the element type of a declared `list<T>`.
- Whole-table processing: a key index (when the condition fixes the key, as in `where id=…`, look it up directly); row positions are computed only for deletion and `after`; the receipt is a hash chain of "previous version id + transaction text" instead of a hash of the whole state (a content hash is computed only when queried).
- Time of one update (2-column table, minimum of 5 runs, Python):

| Rows | v0 | v1 |
|---|---|---|
| 1,000 | 8.6 ms | 0.08 ms |
| 20,000 | 170 ms | 0.08 ms |
| 100,000 | — | 0.07 ms |
| 1,000,000 | — | 0.08 ms |

`get` and `add` addressed by key are also 0.12–0.26 ms and do not depend on the row count. A bulk update that scans all rows by a condition (`set items where status=:unpaid and qty>5`, 100,000 rows, 9,523 updated) took 623 ms, which is simply the per-row evaluation cost in Python (about 6 µs). It can be lowered with per-column indexes or a port to Rust.

With this, **all three — the model's output, the model's input, and the executor's processing — are decoupled from the count for updates addressed by key.**

## 8. v2 (after the external review of v1, same day)

2 reproduced P1 items, 1 P2 item and 1 test defect were fixed. 36 regression tests pass.

- SV1-01 (P1): for a child-table condition `where id=1`, the evaluator read `id` as the child's and the index read it as the parent's, so the updated rows changed depending on whether an index was used. When the child table has a column of the same name, the parent index is not used.
- SV1-02 (P1): `put xs[0] = 7` was accepted and `put xs[0] = [2]` rejected (after descending one level by the path, it descended one more level to the element type). `put` now uses the type at the end of the path and `add` uses its element type.
- SV1-03 (P2): header errors such as `tx a at nope` escaped as exceptions. Header parsing is now inside the range converted to a receipt.
- Tests: one test that always passed because of `or True` was replaced by a check of a multi-line write to a string field of the document.

## 9. v3 (after the external review of v2, same day)

2 P1 items where writing compound data slipped past the type check were fixed. 45 regression tests pass. No whole-table re-check was added (only the written value is checked).

- SV2-01: the check was skipped when the expected type was `map`. The value itself is now checked to be a map (its fields remain free).
- SV2-02: a named `add parents : id=1, children=[7]` stored the child-table value as given. Each child row is now validated against the child table's schema (it is a map; column types and missing columns; duplicate keys in the child table), and only rows that pass are stored.
- Also, an inline map `{k: v}` can now be read as a value (a space is required after `:`, to distinguish it from a keyword `:kw`; without the space an error saying so is returned).

## 10. v4 (after the external review of v3, same day)

1 P1 and 1 P2 item remaining in the map syntax and child-row validation added in v3 were fixed. 54 regression tests pass.

- SV3-01 (P1): a map with a key that is not a valid Weft keyword name, as in `put x = {1: 7}`, could be stored and later failed to encode. Key names are now checked by the Weft rule when the map is read.
- SV3-02 (P2): an empty map in `children=[{}]` was judged "positional" because it has no items, so defaults were not used and it was rejected. Whether an add is named is now passed explicitly; an empty map, and an `add ... :` with no values, are treated as named adds filled with defaults.

## 11. v5 (after the external review of v4 reached a stopping point, same day) — bulk updates by condition, and work with queries in between

At v4, `set ... where <cond>` already applied to every matching row, but (a) updates that the model cannot write without knowing the current value ("increase the quantity by 2") could not be written, (b) the per-row scan cost was heavy at 5–16 µs, and (c) without ordering, work like "the single largest one" had to look at every row. v5 added the following. 84 regression tests pass.

Language additions:
- `col += v` / `col -= v`: numbers add and subtract; lists append and remove (removal fails if the element is absent). The model need not know the current value.
- `where true`: all rows.
- `show ... order <col> [asc|desc]`: ordering (nil is treated as the smallest value: first ascending, last descending; mixed kinds fail).
- `set?` / `del?`: allow matching 0 rows (the receipt shows `set:0`). Needed in L3 below (§11.3).

Implementation changes (meaning unchanged):
- A condition is "compiled" once per statement into a Python closure, with normalisation of the constant side done in advance. Equality was confirmed to return the same result as W.same (identity of canonical binary) for all combinations of 22 kinds of value (484 pairs). Ordering comparison gives the same results as before, **with 2 differences**: (1) mixed types (an integer and a date, and so on) and ordering against a nil constant (`x < nil`) used to be silently False or an internal error and are now a "cannot compare" failure. When the row's value is nil, it is "does not match" as before, not a failure. (2) Date ordering changed from lexical order of the canonical string to comparison of instants with the offset subtracted for dates with a time (`#...T03:04:05Z` and `#...T12:04:05+09:00` are the same instant: `<=` is true and `<` is false; equality is still identity of canonical notation, so it is false). Day arithmetic agrees with datetime on 20,000 cases.
- Column resolution for `set`, and the type check of a constant assignment `=`, are done once per statement. Relative assignment is also turned into a closure per statement. The undo record changed from closures to tuples.

### 11.1 Execution time (Python, same machine, same data)

| Operation (before → after the v5 optimisation, ms, minimum of 5 runs, loading excluded) | 1,000 rows | 10,000 rows | 100,000 rows | 500,000 rows |
|---|---|---|---|---|
| update by key (control) | 0.2 → 0.2 | 0.2 → 0.2 | 0.2 → 0.2 | 0.2 → 0.2 |
| `count ... where status=:unpaid` | 9.2 → 0.4 | 48.9 → 1.8 | 495.3 → 17.9 | 2529.8 → 94.9 |
| bulk update, about 25% of rows, 2-term condition, 2 columns (one a list append) | 12.7 → 1.0 | 130.9 → 8.5 | 1468.0 → 94.2 | 8128.3 → 530.1 |
| bulk update, all rows, `where true : qty+=1` | 2.0 → 0.4 | 25.3 → 4.5 | 403.4 → 54.9 | 2732.6 → 730.1 |
| bulk update, about 20% of rows + `expect count` | 10.3 → 0.5 | 106.4 → 3.7 | 1119.0 → 41.3 | 5470.4 → 248.3 |

Updates by key are unchanged and independent of the count. A condition scan is about 0.18 µs per row (a `count` over 500,000 rows takes 95 ms); with updates it is about 1.5 µs per row (`qty+=1` on all 500,000 rows takes 0.73 s). Against the state before optimisation (the v4 evaluator with only `+=` added) the scan is 28 times faster and bulk updates 4–15 times. These are numbers for plain Python; neither indexes nor Rust have been added.

### 11.2 Work with queries in between (exploratory; N=5,000 rows, 6 tasks, solver claude-fable-5-1, 1 run each)

The solver receives only the language card, the schema, a 2-row sample and the task, and does not see the data. 1 reply = 1 message to the executor; the receipt is returned; DONE ends the task. Grading is equality of the canonical digest of the final state (the expected state is built separately by a reference transaction).

| Task | Content | Round trips | Failure receipts | Solver output tok | Receipt tok | Result |
|---|---|---|---|---|---|---|
| L1 | Put every unpaid order due before a date on :hold and add the tag :late. Fail if any remain | 1 | 0 | 48 | 21 | match (1,287 rows updated) |
| L2 | Add 2 to the quantity of order 3412, but do nothing if it is shipped (actually unpaid) | 1 | 0 | 33 | 44 | match |
| L3 | Same, order 3777 (actually shipped) | 2 | 1 | 41 | 96 | match (no change) |
| L4 | Count the rows matching a condition and write it to audit.count in the doc | 2 | 0 | 38 | 31 | match (148) |
| L5 | Set the single unpaid order with the largest amount to :review | 2 | 0 | 55 | 158 | match |
| L6 | Remove the tag :a from shipped orders, plus "Q1" for those due in March with no note | 1 | 0 | 97 | 18 | match (706 rows updated) |
| Total | | 9 | 1 | 312 | 368 | 6/6 |

Tokens are o200k counts (gpt-tokenizer 4.1.0). "Solver output" and "Receipt" in the table are the round trips only and do not include the initial prompt (card + schema + sample + task, 923–950 tok each, 5,594 tok for the 6 tasks). For reference: the whole state of this store is 243,911 tok as JSON (565 KB). The model-side round trips of the 6 tasks total 680 tok, about 0.28% of the whole state. This is not a comparison experiment; it checks whether the hypothesis "the amount the model touches does not depend on N" also holds for this kind of work (it held).

Points of note in how the solver wrote: in L5 it added `tx t1 at 0` and `expect count ... = 1` on its own initiative (a guarantee that the state did not change between the query and the write). In L6 it combined 2 bulk updates and 2 `expect` lines in 1 message. In L2/L3 it put `and status != :shipped` on the condition side and tried to finish in 1 message without a query (the right idea).

Notes on the record: the solver of L1 read the prompt text from a file itself (by a mistake on the running side a file reference was passed instead of the text; the content is the same as the others). The replies of L4 and L6 arrived with `>=` HTML-escaped as `&gt;=` on the transfer path; what was executed was the `>=` form, and the executed text is in run/loop/*.state.json.

### 11.3 A design gap seen in L3

The first message of L3, `set orders where id = 3777 and status != :shipped : qty += 2`, has the correct intent, but because the executor made a 0-row match a failure, the solver checked with `get` and then sent DONE (the result is correct but with 1 extra round trip). Making a 0-row match a failure catches mistyped conditions and should stay. So `set?` / `del?` (allowing 0 rows) were added, and the failure hint now says to write `set?` if 0 rows is correct because of a guard condition. The v5 trials used the card from before this change, so the numbers in the table are from before it.

### 11.4 Not done yet

- A condition scan is O(n) in Python: 0.1–0.7 s at 500,000 rows. Whether to lower it with column indexes (equality, range) or a Rust port will be decided by the shape of the work measured next.
- A comparison experiment (JSON full rewrite / JSON Patch / Weft in bulk, and so on) is not designed yet. It will be pre-registered and run once the shape is settled.
- 1 solver model, 1 run each. Trials with other models (GPT, local models) are not done.

## 12. v5 r2 (after the external review of v5, next day)

2 P1 and 1 P2 items at the boundaries of the new features. 96 regression tests pass.

- SV5-01 (P1): `+=` and `expect sum` computed Python Decimals in the default context (28 digits of precision), so merely adding 0 to `12345678901234567890123456789m` changed the value. The precision of an addition is now decided from the digits of the operands, and Inexact / Rounded are trapped, so it "fails rather than rounds" (with that precision an addition does not round, so this is in effect insurance). The result is turned into a string with `format(d, "f")` (no exponent notation). Tests were added that 59-digit additions, subtractions and sums pass without loss of digits.
- SV5-02 (P1): only the judgment of `expect <path>.<col> where ... < v` still used the old `_cmp` (dates by lexical order of the canonical string). It now uses the same comparison functions as conditions (`_eq_fn` / `_ord_fn`), and `_cmp` was deleted. Tests cover, for both `count` and `expect`, that for the same instant written with `+09:00` and with `Z`, `<=` is true and `=` is false (equality is identity of canonical notation).
- SV5-03 (P2): the wording of the report was matched to the implementation. The rules are: "if the row's value is nil it does not match an ordering condition (not a failure)", "if the constant side is nil it is a failure", "in ordering, nil is treated as the smallest value". The relevant part of §11 was rewritten.
- Also, it was made explicit that the token counts in the table of §11.2 are the round trips only and exclude the initial prompt (5,594 tok for the 6 tasks).

## 13. v5 r3 (after the external review of v5 r2, same day)

2 places the previous fix had not reached. 104 regression tests pass.

- SV5-01, remainder (P1): in `-=`, the sign flip `d = -d` before entering the precision-safe addition rounded in the default context (28 digits) (the unary minus of Decimal also applies the context precision). It was replaced by `copy_negate()`, which does not round. Tests were added that subtracting a 29-digit value from itself gives exactly 0 and that subtraction of 29-digit integer notation is exact. Constructing a Decimal from a string is exact regardless of context, so the only remaining arithmetic is inside `_dec_add`.
- SV5-03, remainder (P2): the refusal of ordering comparison with a nil constant (and with true/false, lists, maps, symbols) was moved from per-row evaluation to the compilation of the condition (when the statement is read). The same command gives the same result (failure) even for an empty table or when every row is nil. The error text now points to `missing <col>` / `<col> != nil`. `expect ... >= nil` is refused by the same path.

## 14. Exploration M — where extra round trips and copying appear in harder work (v5 r3, same day)

The purpose is not to add features but to **have the current Shuttle solve the tasks and find where the model's judgment is needed, where copying appears, and where round trips increase**. 50,000 orders plus 124,824 detail lines (child table `orders.lines`). Solver claude-fable-5-1, a new conversation per task, shown neither the correct answer nor other answers. The expected state is computed by rewriting the data directly in plain Python without going through the executor (ops_loop2.py `expected`). All receipts and messages are in run/loop2/*.state.json.

| Task | Content | Round trips | Output tok | Receipt tok | Result | What was found |
|---|---|---|---|---|---|---|
| M1 | If more than 100 unpaid orders are due before a date, put them all on :hold and set policy strict; otherwise only set normal | 2 | 67 | 40 | match (2,589 rows) | 2 round trips: count → decide → write. Both the condition and the action are fixed, yet the model received the count and decided |
| M2 | Set the total of order 7006 to the sum of its line amounts | 2 | 41 | 81 | match (550.62) | The model looked at the 2 lines, added them, and copied 550.62. With 50 lines it would be 50 additions |
| M3 | Write the unpaid count, the paid count and the sum of shipped totals into audit | 6 | 413 | 142 | match | Copied 2 counts. With no sum query, it lined up 18 `expect sum ... >= v` statements to try a binary search, and **obtained the value from the "got 4944994.12m" of a failure receipt** (6 round trips) |
| M4 | Set the :p03 lines of unpaid orders to qty 0 and add a tag to those orders | 5 | 210 | 120,669 | **mismatch (cut off)** | Parents cannot be selected by a child condition. `lines has {{sku: :p03}}` passed the syntax and **silently returned 0 rows** (equality with the whole map). In the end the only path left was copying 12,333 ids, and the run was cut off there (a 208 KB receipt) |
| M5 | Set the single unpaid order with the largest amount to :review (right after the query, another writer sets that order to :paid) | 4 | 113 | 119 | match (31001) | `tx at 0` failed as stale → it **queried again instead of just swapping the version**, and correctly chose 31001. 4 round trips, 1 failure. It had also put `and status=:unpaid` in the write condition |
| M6 | A new order with 2 lines, total = sum of the lines | 2 | 151 | 31 | match | `note:str?` was treated as having no default, so it had to write `note=nil`, costing 1 round trip. The total 25.50 was computed by the model (the values are in the task text) |
| Total | | 21 | 995 | 121,082 | 5/6 | |

Tokens are the round trips only (excluding the initial prompts, 1,016–1,072 tok × 6). Almost all of the 120,669 receipt tokens of M4 are the final id list (executed before the cut-off). Excluding M4, the receipts are 413 tok.

### 14.1 Executor defect (found and fixed during the run)

- In a child-table query, naming a parent column as in `cols id` caused a KeyError internal error (the 2nd message of M4). It was fixed to take the value from the parent row at output, and the same message was re-executed (the original receipt is kept in the notes of state.json). 105 regression tests.

### 14.2 Gaps found (not implemented yet at this point; listed as candidates)

From the places where copying and extra round trips appeared, the following were found to be missing.

1. **An aggregate cannot be used as a value** (M2, M3). If the executor could turn an aggregate into a value, as in `put audit.unpaid = count orders where status=:unpaid` or `set orders where id=7006 : total = sum amount of orders.lines where id=7006`, the model would neither see nor copy a number. The binary search in M3 is the model filling this gap from the failure text of a receipt.
2. **There is no aggregate query** (M3). `sum` exists only in `expect`. Together with 1, `sum` should also be a query. That a failure receipt shows the aggregate is not a problem, since reading is free anyway, but it should be stated in the specification.
3. **No branching on a count** (M1). With a one-message branch like `when count orders where ... > 100 : <ops> else : <ops>`, the model's decision is unnecessary and it becomes 1 round trip. This was not "a situation that needs the model's judgment".
4. **Parents cannot be selected by a child condition** (M4). An existence condition such as `set orders where status=:unpaid and any lines where sku=:p03 : tags+=:p03-cancelled`. Without it, work across a child table falls back to copying ids.
5. **A meaningless condition passes silently** (M4). `has {...}` on a child-table column is equality with a whole map and almost always matches 0 rows. Passing the syntax and returning 0 rows goes against "hard to get wrong". `has` on a child-table column should be refused, pointing to the form in 4.
6. **Updating the top 1 row** (M5). With `set orders where status=:unpaid order total desc limit 1 : status=:review`, query → copy id → write becomes 1 message, and the window for a version conflict disappears.
7. **Default for `T?`** (M6). An optional column should default to nil.

### 14.3 What was learned

- Among the 6 tasks, the only "situation that needs the model's judgment" was **the decision after the stale failure in M5** (query again, or just swap the version). The solver chose the right one. All other round trips and copying come from gaps in the language and can be moved to the machine side by 1–7.
- The version conflict was guarded twice, by `tx at` and by the guard in the write condition (`and status=:unpaid`). Either one alone would have prevented wrongly setting 31000 to :review.
- Work across a child table (M4) cannot be written in a size-independent form in the current language. This is the largest thing to fix next.

## 15. v6 — carrying the result of a selection or aggregate into the next step inside the machine (after the external review of exploration M, same day)

Following the advice of the external review, instead of adding 7 syntaxes, only the mechanism "carry the result of a selection or aggregate into the next step inside the machine" was added. 122 regression tests pass.

Added (3 things):
- **Existence conditions** `any <child> where <cond>` / `none <child> where <cond>`: look at child rows inside a parent-table condition. Parent columns can also be used inside the child condition (as in `any lines where sku=:p03 and not tags has :x`).
- **Aggregates as values**: `count <path> [where …]` and `sum <col> of <path> [where …]` can be written wherever a value is written (the right side of `set`, `+=`, `put`, the values of `add`, the comparison constant of `expect`). The executor computes them when the statement runs (seeing the effect of earlier statements in the same message). The computed value appears in the receipt as `computed sum amount of orders.lines = 550.62m`. They cannot be used inside a condition (refused). Type checking is the same as for ordinary values.
- **A `sum` query.**

Also, `has` on a child-table column is refused with a pointer to the `any` form (the meaning of `has` itself is unchanged; as the review pointed out, it is correct as exact match). The examples on the card use different table and column names so that they are not answers to the tasks.

### 15.1 Re-solving 3 tasks of exploration M in new conversations (the v6 card, solver claude-fable-5-1)

| Task | v5 r3 (§14) | v6 |
|---|---|---|
| M2 sum of lines to the parent | 2 round trips; the model added and copied 550.62 | **1 round trip**, `total = sum amount of orders.lines where id=7006`. Output 20 tok, receipt 27 tok, match |
| M3 3 aggregates to audit | 6 round trips; 2 counts copied; the sum picked up from a failure receipt | **1 round trip**, `put … = count …` ×2 and `put … = sum …`. Output 40 tok, receipt 46 tok, match |
| M4 update parents by a child condition | cut off (needed copying 12,333 ids; receipt 120,669 tok) | **done in 1 round trip + 1 confirming query**, `any lines where sku=:p03`. Output 126 tok, receipt 55 tok, match (15,053 lines + 12,333 orders updated) |

Copying became zero in all 3 tasks. The 2nd message of M4b is a check the solver wrote on its own initiative (a `count` each that unprocessed orders, orders wrongly tagged, and lines wrongly set to qty 0 are 0), correctly using `any … and not tags has …` and mixing parent columns into a child-table condition.

### 15.2 Execution time (Python, 50,000 orders, minimum of 3 runs, loading excluded)

- `count orders where status=:unpaid and any lines where sku=:p03`: 40.5 ms
- The 2 statements of M4 (updating 15,053 lines + 12,333 orders): 144.5 ms
- The 3 statements of M3 (count ×2, sum ×1): 75.9 ms
- The 1 statement of M2 (by key + sum of 2 lines): 0.4 ms

### 15.3 Not done yet

- A one-message syntax that branches on a count (M1). M1 is still 2 round trips with no copying.
- A syntax that updates the top 1 row directly (M5). Not started, including specifying the policy on conflict (a review comment).
- Scan indexes and a Rust port (left as is, since 50,000 rows take on the order of 0.1 s).

## 16. v6 r2 (after the external review of v6, same day)

Consistency of result types, which became important now that aggregates can be passed to other operations. 129 regression tests pass.

- SV6-01 (P1): `sum` skipped non-numeric values, so `sum label of t` (a str column) silently returned 0 and could overwrite something with a plausible value. Only `int` / `dec` columns (including `?`) can be summed; the declared column type is checked and the statement refused before execution (the query, `expect` and as-a-value paths all go through the same `_agg_eval`).
- SV6-02 (P2): the result type was decided from the values, so an empty set or an all-nil `dec` column returned an int 0, and writing it to a `dec` doc field failed. The result type is now decided from the column type: `0m` for a `dec` column even when empty, `0` for an `int` column. nil is skipped (stated on the card and in the grammar description).

## 17. Step 2 — replacing the solver with a smaller model (Haiku 5.5, 12 tasks, the v6 r2 card)

Purpose: does the card alone get through to a smaller model? Solver claude-haiku-5-5, a new conversation per task, shown neither the correct answer nor other answers. The tasks are L1–L6 (5,000 orders) and M1–M6 (50,000 orders plus lines). The procedure is the same as §11 and §14. GPT and local models were not used this time because of manual pasting and GPU capacity (the limit that the models are from the same company is stated in the results).

| Task | Round trips | Failures | Output tok | Receipt tok | Result | Remarks |
|---|---|---|---|---|---|---|
| L1 bulk + tag | 2 | 0 | 128 | 55 | match | done in the 1st message; the 2nd is a self-initiated check |
| L2 guarded +2 (unpaid) | 1 | 0 | 45 | 44 | match | used `set?` and `tx at 0` on its own; 1 round trip |
| L3 guarded +2 (shipped) | 1 | 0 | 31 | 41 | match | 1 round trip with `set?` (the syntax added in §11.3 worked) |
| L4 count to the doc | 1 | 0 | 53 | 29 | match | used `put … = count …`; 1 round trip |
| L5 the 1 largest amount | 3 | 1 | 127 | 146 | match | wrote `tx vid=000000000000 at 0`, 1 syntax error, fixed in the next |
| L6 remove tag + March note (2nd run) | 1 | 0 | 104 | 18 | match | the 1st run (L6.h) was a mismatch → an executor defect, §17.1. Re-run in a new conversation after the fix: match |
| M1 branch on a count | 3 | 0 | 154 | 175 | match | 3 round trips: count → checking query → write. Wrote `tx 0` (no `at`) → §17.1 |
| M2 sum of lines to the parent | 1 | 0 | 28 | 69 | match | used an aggregate as a value; 1 round trip |
| M3 3 aggregates to audit | 1 | 0 | 40 | 46 | match | 1 round trip |
| M4 update parents by a child condition | 1 | 0 | 116 | 32 | match | used `any`; 1 round trip, with the checking `count` in the same message |
| M5 version conflict | 5 | 2 | 307 | 247 | match | queried again after stale and chose 31001 (correct). Reused a tx id on the way and failed once → §17.1 |
| M6 add a parent with children | 1 | 0 | 119 | 60 | match | wrote `note=nil` from the start; 1 round trip |

12/12 match (L6 on the re-run after the executor fix). Even the small model read aggregates-as-values, existence conditions, `set?` and `tx at` from the card and used them on the first move. Zero copying.

### 17.1 Executor defects exposed by the small model (3, fixed → v6 r3, 140 regression tests)

1. **Ordering comparison between a date and a date-time** (L6.h, P1-equivalent). The solver wrote `due >= #2026-03-01T00:00:00Z and due < #2026-04-01T00:00:00Z`. The column holds dates only. The executor ordered a date-only value "before the date-time of the same instant", so March 1 (9 rows) dropped out and April 1 (15 rows) came in, `expect` passed too, and the state was **silently wrong** (digest mismatch). Fix: ordering comparison between a date-only value and a date-time fails, with the guidance "the column is a date, so write the bounds as dates too". Mixing also fails in ordering.
2. **Reusing a tx id** (M5.h, P1-equivalent). The solver put `tx mark-top-review at 0` on a read-only message and the same id on the following write. The executor took the same id as a "re-send", returned the old receipt, and **silently dropped the write**. Fix: the same id with a different body fails ("an id is the name of 1 message; the same id only when re-sending"). With the same body it is treated as a re-send as before.
3. **`tx 0`** (M1.h, P2-equivalent). Writing `tx 0` after forgetting `at` passed as "a tx named 0, no version pin". A digits-only id without `at` now fails, pointing to `tx <id> at 0`.

In addition, the display of rows in `show` wavered between 2 forms per row (a block form and a `{…}` form) and was unified to the `{…}` form.

### 17.2 What was learned

- The 3 items not found with the larger model (§11, §14, §15) were all "slightly different ways of writing that the small model wrote naturally" which the executor let through silently. **Holes in "hard to get wrong" are found by weakening the solver.** Step 2 was meant as a check of the card but in fact became a check of the executor.
- No place where the card failed to get through was found this time. The `tx vid=… at 0` syntax error was self-corrected in 1 try.
- Not yet tried: a model from another company. A tool to automate this over an API (the API key supplied by whoever runs it) can be prepared, but was not built at this point.

## 18. Step 2 continued — a small model of another family (Qwen3.5-4B, local environment, no API fees)

The external reviewer built a runner (shuttle-api-runner) that sends tasks to a Chat Completions-compatible API, returns receipts, builds the expected state with logic separate from the executor (integer-cent arithmetic), and compares all data structurally. M1–M6 were run with Qwen3.5-4B in a local environment (llama.cpp, thinking output on, limit of 8,192 tok per reply, up to 12 replies per task). (From the SHA in run.json, the executor used in this run was **v6 r2**; the version swapped to v6 r3 was not used in this run.) The resulting summary.json was received. The conversation logs of M4–M6 (events.jsonl) were read in §18.2.

| Task | End | Final state | Replies | Output tok total | Limit hits | Solve time | Executor |
|---|---|---|---|---|---|---|---|
| M1 | done | match | 4 | 7,307 | 0 | 57 s | 304 ms |
| M2 | done | match | 2 | 5,063 | 0 | 39 s | 1 ms |
| M3 | done | match | 2 | 7,933 | 0 | 61 s | 116 ms |
| M4 | done | mismatch | 8 | 22,471 | 1 | 174 s | 687 ms |
| M5 | turn_limit | mismatch | 12 | 38,712 | 2 | 299 s | 107 ms |
| M6 | turn_limit | mismatch | 12 | 58,102 | 6 | 447 s | 4 ms |

Output tok includes thinking output. Solve time is almost entirely model generation; the executor took 1.2 s in total for the 6 tasks.

### 18.1 What was learned

- **M1–M3 match even with the 4B model.** It read from the card how to branch on a count (M1, 4 round trips) and how to use aggregates as values (M2, M3; 2 round trips each = write + DONE).
- **M4 mismatch = the tag was added twice.** The 6th message updated correctly, and the 7th did `+=` with the same tag again. Haiku 5.5 added the guard `and not tags has :x` itself (§17), but the 4B model did not. `+=` allows duplicates, so "add a tag" work is not safe to re-run. → v6 r4: without changing the meaning of `+=`, **`|=` (add if absent, do nothing if present)** was added, and the card says to use it for tags.
- **M5 reply limit:** in addition to syntax errors, **sending the corrected message with the same tx id returned the earlier failure receipt again** (messages 10–12). The executor used in the run was confirmed as v6 r2 from the SHA in run.json (the version before v6 r3 was swapped into the runner). r2 treated the same id as a re-send without looking at the body, and also reserved the id of a failed message. r3 fixed the former, and → v6 r4 fixed the latter too: **only a message that changed the store owns its id.** The id of a failed message or a read-only message can be reused freely. The card now states the id rule (one name per message; the same id only for re-sending the same body; after a failure the corrected message may use the same id). It also did not query again after the conflict (2 truncations of thinking output consumed round trips).
- **M6 reply limit:** in addition to 6 truncations, format mistakes in a date and a map, and finally a missing `where` in an add to the child table. It did manage to write `note=nil`. The executor's error text did not point at the cause (§18.2).
- Executor time stayed under 1 second for every task. **The bottleneck is model generation (especially thinking output):** it used up the 8,192 tok of a reply 10 times. Thinking-off (llama.cpp `--reasoning off`) was added to the runner, so M5 and M6 are worth re-measuring with that setting (as a separation of model settings, not as an evaluation of Shuttle).

149 regression tests for v6 r4.

### 18.2 What reading the conversation logs showed → v6 r5 (better error text)

The events.jsonl of M4–M6 (every model reply and every receipt) were read. Most of the 4B model's failures came from the fact that, **for 4 variations in writing that a small model tends to produce, the executor's error text did not state the cause and the fix**. Haiku 5.5 self-corrected in 1 try even with vague error text (§17), but the 4B model relies on the error text.

| What the 4B model wrote | Old error text | Times | Behaviour in r5 |
|---|---|---|---|
| `where … :qty=0` / `:tags+=:x` (the `:` before the assignments written tight) | `expected :, got ':qty'` | 2 in M4 | **accepted**, since only the spacing differs and the meaning is single (same as `: qty=0`) |
| `:status=:review, :note="top"` (`:` on column names) | `expected :, got ':status'` | 4 messages in M5 (4th–7th); after that 2 truncated messages and 3 re-sends of the old receipt by the same id | `':note' is a keyword value; a column name has no colon` + `write note=...` |
| `set … where id=31000 status=:review` (missing `:`) | `expected :, got 'status'` | 1 in M5 | `expected ':' before the values` + guidance on the form |
| `tx 0 at 0 set …` (header and operation on 1 line) | `unexpected 'set' after the tx header` | 1 in M5 | + `the tx header is a line of its own` |
| `due:#2026-12-01` (`:` instead of `=`) | `not a value: ':#2026-12-01'` | 2 in M6 | `` `due:` — in a named add write `due=#2026-12-01` `` |
| `{sku:::p01, qty:2}` (no space in a map's `key: value`) | `expected a value, got ':'` | 3 in M6 | + `in a map write key: value with one colon and a space; sku: :p01` |
| after stale, swapping only the version and aiming at the same row | `fail stale: you assumed version 0, current is 1` | M5 | + `Read again before writing … and guard the write with the condition you relied on` |

Only the tight `:` was accepted (its meaning is uniquely determined). For the rest the syntax was not loosened; the cause and a rewritten example were put into the error text. The 4B model's actual messages were passed through r5 as they were, confirming that each produces the text above (added to the tests). 157 regression tests.

Cases where the executor's error text was accurate and the 4B model fixed it in the next message: `any orders.lines` (→ `children: lines`), `any orders` (→ `lines has no child tables`). The error text for the missing `where` in a child-table add was also accurate, but it was the last reply of M6, so whether it could have been fixed was not observed.

What remains is truncation of thinking output (2 times in M5, 6 in M6, 8,192 tok each), which is a matter of model settings. Thinking-off was added to the runner, so M4–M6 are re-measured with the r5 card and executor.

### 18.3 Re-measurement with r5 and thinking off (Qwen3.5-4B, M4–M6) → 3/3 failed, v6 r6

M4–M6 were re-measured with the r5 executor and card and thinking output turned off (the reviewer confirmed that the SHA in run.json matches r5). Truncations: 0. Solve time for the 3 tasks: 919 s → 27.7 s. But all 3 failed. **The centre of the failures was not form but how targets were chosen and misreading the state after a failure.** Writing "most of the failures were error text" in §18.2 was an overstatement; error text fixes only variations in form.

| Task | Messages | What happened | What can be fixed on the executor side |
|---|---|---|---|
| M4 | 5 | `set orders.lines where orders.status=:unpaid and sku=:p03` → the error text said "no column 'orders.status' … hint: columns: sku, qty, amount", **listing only the child's columns**, so the model dropped the unpaid condition and updated the 24,927 :p03 lines of the whole state (the set:37260 in the receipt is the total with the 12,333 parent rows that got the tag) | the hint misled. List the parent's columns too and say "`status`, not `orders.status`" (r6) |
| M5 | 6 | changed 30,051 rows with `set orders where status=:unpaid : status=:review, note="top"` without a query. Conflict recovery also untested | error text cannot stop this (correct syntax, just not the intent). The language had no way to "update the top 1 row directly" and forced query → copy id → write → added `set … order total desc limit 1 : …` (r6). Whether it then passes needs checking with another model |
| M6 | 12 | did not write total in `add`, got "missing orders.total (no default)" → tried `set` on a row that does not exist, tried to use the sum of all lines shown in a `set?` receipt (18,948,216.68m) as the total, and repeated the same add 5 times | the hint was insufficient. Added to the hint: "write a column with no default inside the add (`total=0m` is fine); you can update it in the next line of the same message" (r6) |

Changes in v6 r6 (165 regression tests):
- The hint when a parent column is not found in a child-table condition: lists both the child's and the parent's columns and, for `orders.status`, says to write `status`.
- The hint when a column with no default is missing in a named add: gives an example fitting the column's type (`total=0m`) and says it can be updated in a later line of the same message.
- **`set/del … where <cond> order <col> [asc|desc] limit n : …`**: applies only to the first n rows in that order. Fails if the n-th and (n+1)-th rows are equal (which one to choose cannot be decided). `limit n` without `order` is the first n rows in table order. Query → copy id → write becomes 1 message, and the window for a version conflict disappears.

"Changed 30,051 rows" in M5 is the executor executing correctly; the language has no ground to stop it. Preventing "meant 1, got many" is done by the solver writing `expect count … = 1` or using `limit 1`, both of which are on the card. Beyond that it is not the executor's responsibility but the solver's ability.

### 18.4 Re-measurement with r6 and thinking off (Qwen3.5-4B, M4–M6) → 2/3, v6 r7

| Task | Result | Replies (incl. DONE) | Solve time | What happened |
|---|---|---|---|---|
| M4 | match | 6 | 5.4 s | read the new hint for `orders.status`, changed it to `status`, and succeeded keeping the unpaid condition (the place where r5 failed by dropping the condition). On the way it also wrote `lines has :p03` and `any(orders where …)`, each fixed in 1 message from the error text |
| M5 | mismatch | 5 | 3.7 s | wrote `… limit 1 : status=:review : note="top"`, received only "expected a column name, got ':'", and **split it into 2 statements**. After the 1st line 31000 was no longer unpaid, and the `limit 1` of the 2nd line chose 31001. The executor behaved according to the rules, but had the error text said "separate with a comma" it would have been 1 statement |
| M6 | match | 3 | 2.7 s | succeeded with 1 statement that included `total=25.50m` from the start (the effect of the r6 hint was not observed) |

2 P2 items from the reviewer: (a) when parent and child have a column of the same name, the hint for `parents.id=1` recommended `id=1`, which refers to the child's `id` and would update a different target. (b) The card's `set/del … limit 1 : …` fails if the trailing `:` is put on `del`.

v6 r7 (169 regression tests):
- When a 2nd `:` comes between assignments, the guidance is "separate assignments with a comma in 1 statement (a 2nd statement selects again, so `limit 1` may choose a different row)".
- When `parents.id` is written with same-named columns in parent and child, it no longer recommends the plain name but says "the child's `id` hides the parent's `id`, so it cannot be referenced from the child; select the parent first or use another column". There is currently no syntax to reference a hidden parent column from a child condition (to be added if needed).
- The `set` and `del` examples on the card were separated, with no `:` on `del`.

Conflict recovery in M5 (querying again after stale) remained untested with the 4B model in both runs. The runner now separates "task achieved" and "went through the conflict scenario" into different fields (`passed` and `passed_original_protocol`).

### 18.5 Re-measurement of M5 with r7 and thinking off (Qwen3.5-4B) → mismatch, v6 r8. Tuning for the 4B model stops here

12 replies, 0 writes. From the 3rd to the 12th reply the model repeated a form that embeds `get` inside a condition: `set orders where id = get orders where status=:unpaid order total desc limit 1 : status=:review, note="top"`. The executor's diagnosis was "a `:` is needed before `orders`" and did not point at the problem (`id = get …`). The assignments were comma-separated from the start, so the effect of the r7 comma guidance is untested. The first reply was consumed when the runner rejected a block opened with ```sql (the card said nothing about the language tag).

v6 r8 (171 regression tests): when `get` / `show` comes in the position of a value or a condition, the guidance is "a query cannot be placed inside a value or a condition; to change the top 1 row directly use `set … order … limit 1 : …`". The card now says a code block opens with ```shuttle or with no tag.

This result is kept not as "the limit of the 4B model" but as an example of "when the diagnosis for an unsupported syntax is off target, a small model cannot repair". M5 was measured 4 times with the 4B model and mismatched all 4 times, each for a different reason, and conflict recovery was never tested. No re-measurement with r8 was made.

### 18.6 v6 r9 (external review of r8, 1 P2 item)

R8-01: the r8 diagnosis refused whenever a word followed `get` / `show`, so it mistook even legal symbol values (`put audit = {x: [get show]}`, `{x: get y: 1}`) for queries. The look-ahead refusal was removed. **Only when the statement actually fails**, and the statement contains the sequence "`get` / `show` right after a comparison operator or `in`, followed by a word that looks like a table name", the hint is replaced by the embedded-query guidance while the original error text is kept. Tests were added that all 5 inputs from the review succeed, that `s = get and …` on a symbol column remains a legal condition, and that a failure from a non-matching condition gets no such guidance. 179 regression tests. No re-measurement with the 4B model.

v6 r10 (P3): in r9 the guidance was also attached to a statement where a type error occurred after a legal symbol assignment (`s=get n="bad"`). The guidance is now limited to **failures where parsing stopped in the middle of the statement** (not attached to type or semantic failures). 182 regression tests. Whether the success rate with the 4B model improves remains unconfirmed.

## 19. Comparison experiment C-1 (pointer added for the published repository)

After the exploration above, a comparison against JSON full rewrite, JSON Patch and Weft full rewrite was designed, frozen and run. Its design, freeze log, results and all records are under `c1/` (`c1/RESULTS-C1.md`). The primary judgment was inconclusive; see that file for what the record does and does not support.

## 20. v7 — closing the task in the same message, and receipts that say what changed (2026-11-11)

Written in English from the start; there is no Japanese original for this section.

### 20.1 What prompted it

After publication, M1–M6 (50,000 orders) were run once each with a local model, Qwen3.8-Flash-Next (Q8_0 quantisation, thinking off, server-default sampling, seed 1), on a private inference engine, with the v6 r10 executor and card. **The records of that run are not in this repository**, so the numbers here are reported, not reproducible from the published files.

- 5 of 6 final states matched. In M5 the model wrote `set … order total desc limit 1 : …` as its first message without reading first, so the scripted concurrent write (placed "after the first read-only message") never happened; the final state equals the correct state without that write. Conflict handling was therefore not tested.
- In M2, M3, M4 and M6 the store was already correct after the **first** message. The commands themselves were 32–50 tokens, but the 6 tasks used 4,566 output tokens and 37 replies: most replies and tokens went into not knowing how to finish (echoing `ok`, re-sending a command that had already succeeded, prose around `DONE`) and into misreading receipts.
- Receipt problems seen: `set:27386` for a message with two `set` lines (15,053 lines + 12,333 orders) left the model unsure what the number counted (855 tokens of deliberation, then a retry); a repeated `|=` returned the same `set:12333`, so the model could not tell that nothing had changed; `expect count orders where id = 7006 = 1 and total = 550.62m` failed with only "unexpected 'and' after the end of the statement".

In C-1, at 50 orders, Shuttle averaged 2.4 replies per cell against 2.0 for the other arms. Together with the run above, this was the motivation to try cutting round trips; neither record isolates reply count as the cause of the measured time.

### 20.2 Changes (270 regression tests as of v7 r4)

- **`done` as the last line of a message.** If every line before it succeeds, the receipt ends with `done` and `Store.done` is true: write, check (`expect`) and finish in one round trip. If anything fails — including a syntax error on a line before `done` — nothing is applied and the receipt ends with `(not done: fix the message and send it again)`. `done` anywhere but the last line is an error. A message containing only `done` is accepted. A replayed message (same tx id, same body) keeps `done` as the last line of its receipt, after the `; (replay)` note.
- **Per-statement receipt lines.** When a message has two or more `set`/`del` statements, the receipt adds one line per statement: `line 1: set orders.lines 15053 row(s)`. The `set:` on the first line stays the total.
- **Matched vs changed.** "Changed" uses the executor's value identity (canonical binary equality, the same as conditions and digests): `{n: 1}` → `{n: true}` and `1.5m` → `1.50m` are changes. When some matched rows already had the assigned values, the line says so: `line 2: set orders 12333 row(s), 0 changed (every row already had these values)`. This line is shown even for a single statement.
- **A `set` that changes no value no longer makes a new version** (the version and `vid` stay; such a message does not take ownership of its tx id). `add`, `del` and `put` count as changes as before (`put` is not compared with the old value).
- **Hint for an `expect` with a trailing `and`/`or`:** the comparison comes last and every condition goes inside `where`.
- **Card:** nothing outside the code block; how to read the per-statement lines and `0 changed`; how to finish with `done`.

### 20.3 Not measured yet

No solver has been run with v7. Whether `done` brings the reply count to 1, and whether the new receipt lines stop the re-sending, is untested. The change in version behaviour for a no-op `set` means a later `tx … at <version>` sees the old version number after such a message.

### 20.4 v7 r2 (after the external review of v7)

1 P1 and 3 P2 items, all reproduced. 245 regression tests.

- V7-01 (P1): "changed" was decided with Python `==` after comparing only the outer type, so a map or list whose contents changed between `1` and `true` (`{n: 1}` → `{n: true}`) was reported as `0 changed`. The stored value and digest did change, but the version and `vid` did not move and the tx id was not owned, so a writer pinned to the old version was still accepted and the id could be reused for another body. The decision now follows canonical equality (`W.same`); a shortcut is used only for values with nothing inside them and exactly the same type.
- V7-02 (P2): the receipt of a replayed `done` message ended with `done  ; (replay)`, so a client that ends on "the last line is `done`" did not end. The replay note now comes before the `done` line.
- V7-03 (P2): a parse failure on a line before `done` (for example `tx bad at nope`) returned no `(not done: …)` note. Every failure of a message that has a `done` line now ends with that note.
- V7-04 (P2): the README said all earlier measurements used v6 r10. It now states which version each group of measurements used.

### 20.5 v7 r3 (after the external review of v7 r2)

No P1; 2 P2 items, both reproduced. 259 regression tests.

- V7R2-01 (P2): the look-ahead that decides whether a message has a `done` statement worked line by line, so a `done` line inside a closed multi-line string counted as a request, and a parse failure later in the message got the `(not done: …)` note (a run-time failure did not, so the treatment depended on the stage). The look-ahead now uses the parser's own statement splitter, which knows multi-line strings and comments. A `done` after an unclosed quote is part of that string: the message fails on the quote and gets no note.
- V7R2-02 (P2): `_unchanged` returned "changed" whenever the two Python types differed, so values accepted by `Store.load()` such as an `OrderedDict` or an `IntEnum` were reported as changed when overwritten by the canonically identical value: the digest stayed the same but the version moved and the tx id was owned. Only the shortcut for two values of exactly the same flat type remains; everything else, including differing Python types, is compared with `W.same`.

### 20.6 v7 r4 (after the external review of v7 r3)

1 P1 item, reproduced. 270 regression tests. This defect is not from v7: it is present in v6 r10 as published.

- V7R3-01 (P1): the statement splitter stripped comments only on lines that began outside a string. On the line where a multi-line string closed, a `"` inside a trailing comment was read as opening a new string, so the following lines were swallowed into it: in

  ```
  put note = "a
  b" ; "
  expect count t = 0
  done
  ```

  the `expect` and `done` were dropped and the `put` was committed although the expectation should have failed. The splitter now scans character by character, carrying the quote and escape state across lines, and stops scanning a line at a `;` outside a string. The `done` look-ahead uses the same splitter.
- Effect on the records: this repository stores 161 Shuttle messages — 97 Shuttle replies of C-1 including the re-runs (38 of them the bare word DONE), 58 messages in the exploratory logs under `run/`, and the 6 early edit tasks (`run/e-*.r1.md`). For all 123 executed message bodies (everything except the DONE replies), the old and the fixed splitter give identical statement texts and starting line numbers, so no recorded receipt or result depends on the defect.
