# C-1 freeze log (2026-11-11)

English translation. Original: `ja/c1/FREEZE-C1.md`.

Note for the published repository: the hashes below were recorded during the experiment. Four files (`shuttle.py`, `c1/c1.py`, `test_shuttle.py`, `c1/nx.sh`) had absolute working-directory paths replaced by relative paths before publication, so their published hashes differ; see the top-level `README.md`. The design document hash refers to the Japanese original in `ja/c1/`.

## Frozen items (SHA-256)
- c1/c1.py: ee1224e87847f8bf3ff4fd78fc40025ef09b8036ed0d36ec8cbcda967e09a956
- c1/ORDER-main.txt: 5a5b9f10df04459ea7d4ba4fc16e710707ff76544faf4c730ac32b285a5a2629
- c1/DESIGN-compare-d5.md: 909512a100401b442d144f1192a4e1adcf30a660a356f0f6cb58f6cc4633595c
- shuttle.py (v6 r10): e8160b1810252070fc8ff60e9dac7776344c47345550da991235f08a9f1462ea
- CARD.md (Shuttle card): 9b89957c05c43cea906ee87ffce7d2b753464b9234fec505cdf5e298c96b2d2a
- weftnext.py: 2d9e5b7ddc815763f95a9d78e205c47a3bcf80715f0f94b1b31987a71c314b81
- Weft card N4.md: c944eec0566580a923286e28b9318d5e51feb6bf353e48eba2c57e76cc31d3ce

## Versions
- Python 3.13.18
- jsonpatch 1.46, jsonpointer 3.11
- weft-format 1.0.2
- Solver: claude-haiku-5-5 (generation settings are the environment defaults and cannot be set)

## Fixed by the pilot run (not graded, seed rep=9)
- J-full, N=50: completed with 1 submission, measured time 26.8 s (solver 26.781 s, machine 0.004 s).
- J-full, N=500: the solver spent 187.1 s reading the task file and then ended without writing a submission file, saying it could not write it all at once. This was not the output limit being reached; the solver gave up before writing (so it is not a measurement of the output limit).
- **Primary size N\* = 50.** The d5 rule lowers N\* "if J-full turns out to be unable to write N=500 within the output limit", which presupposed a measured output limit. What actually happened was the solver giving up, which is not the rule's condition itself. **This is recorded as an operational change made in response to the give-up** (decided from a single pilot run). The N=500 and N=5,000 cells are also run in the main experiment and all reported.
- J-full / J-patch at N=5,000 (about 520k input tokens) are **not run, in expectation of exceeding the input limit** (the environment's input limit was not confirmed, so this is not written as "not runnable"). W-full at N=5,000 (about 260k tokens) is run and the result recorded.

## How the d5 procedure was made concrete (from facts of this environment; same for every arm)
- Because copying task text or answers by the operator could introduce copying errors, **the solver reads the task file with a Read tool and writes its reply to a file with a Write tool**. Machine results are also passed as files. The only tools the solver is allowed are Read and Write (it is instructed that shell, scripts and code execution are forbidden).
- The response time reported by the environment includes the time of these file reads and writes. A long task text needs several Reads, so arms whose input holds the whole state spend longer here. This is included in measured time as a property of the arm (the size of its input), and the number of tool uses per reply is recorded and reported.
- Whether the solver used tools according to the rule can be checked only from the count of uses (the contents are not visible). Cells with unnatural counts are shown individually in the results.
- The environment does not report a finish reason, so an unterminated code block is recorded as "unterminated reply, cause unknown". If no reply file was written, it counts as 1 reply with a format error.
- Several cells run in parallel. From the top of the order table (ORDER-main.txt, fixed seed) they are batched as the 48 cells of N=50, then the 48 of N=500, then the 24 of N=5,000.

## Number of cells
- N=50: 4 arms × 6 tasks × 2 repetitions = 48; N=500: 48; N=5,000: S 12 + W-full 12 = 24 (the 24 of J-full and J-patch are not run, in expectation of exceeding the input limit). 120 cells run in total.

## Amendment A1 (after the freeze, before any second reply of the main run, 2026-11-11)
- Fact: in this environment, a reply obtained by resuming the same solver call sometimes has no reported response time (a freshly started call always has one). To satisfy the definition of the primary metric (response time reported by the environment) for every reply, **the second and later replies are made by a fresh solver call that reads the task file and a transcript file listing its own previous replies and the machine result of each**. Same for every arm.
- Effect: from the second reply on, the time to re-read the task file enters measured time. This works against arms with more replies. The conversation history is carried by the transcript file.
- At the time of this change only first replies had been processed (the first-reply procedure is unchanged). Tasks, expected values, grading and judgment rules are unchanged.
- c1/c1.py after the change: a3a2a6012e2aa2b83ff6fb0bab8e0aa8edeae31690fbcc535aac56085493fd40

## Record of a procedure violation (2026-11-11)
- The second replies of S-T1-50-2 and S-T6-50-2 were started with the instruction to read a transcript file (transcript1) that had not been created (an operator error: the first replies of these 2 cells had been processed with the procedure from before amendment A1). The second replies were written after reading only the task file. These 2 cells are invalid trials, and (T1, repetition 2) and (T6, repetition 2) are removed from the primary tally for all arms. The re-runs are reference records (run-rerun/).
- For the other 46 cells, the transcript file was confirmed to exist before the second and later replies were started (46 transcript1 files).
- A check command `pre` was added to c1.py to prevent recurrence (it does not touch tasks, grading or timing). c1/c1.py: 2cf933336dde8e51bdbc48165538e89a71bee71820636c6eccbe3cbd709f277e
- `pre` was replaced by the patch from the external review: it compares the full history rebuilt from the record with the transcript file and refuses on a missing file, differing text, stale history or an already finished cell. The next solver call is started only for a cell on which `pre` succeeds. Tasks, grading and timing are unchanged. c1/c1.py: da6efc657c06256ef922a6ad820bdd1c1167c41a639e5a6be31217a8eb7073d4

## Record of the large-size runs, and deviation D2 (2026-11-11)
- The 48 cells of N=500 and the 12 S cells of N=5,000 were run according to the procedure (every second or later reply was started after `pre` succeeded). Tally: run/grades-large.json.
- Deviation D2: the 12 W-full cells of N=5,000 were cut off at 3 replies each (the procedure says 6 replies or 600 seconds). 0 state submissions in 36 replies. They are treated as not completed (cut off) and not used in comparisons. The remaining 3 replies could still be run.
- Unconfirmed: the kinds of tools the solver actually used cannot be confirmed from the record (only the count). The 6 accepted J-full submissions at N=500 used 8–13 tool calls each.
- c1/c1.py unchanged at da6efc65….

## Hashes of the N=5,000 task files (2026-11-11, taken after the run)
- No hashes were recorded at run time. After the run they were taken from the very files given to the solver (c1/run/*-5000-*.prompt.txt, 24 files): PROMPT-HASHES-5000.txt.
- All 24 match the hash of the content regenerated by `prompt <cell>` of c1.py (da6efc65…). The modification times of all 24 are earlier than the first reply file of the 5,000-order cells.
