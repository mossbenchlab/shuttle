# Shuttle

**Status: experimental prototype (v6 r10). Not a stable format or API.**

Shuttle is an operation language for AI models that change structured data.
Instead of rewriting a document (JSON, YAML, ...), the model sends a few lines of
operations addressed by conditions. An executor checks types, keys and
post-conditions, applies the whole message or nothing, and returns a short receipt.
The model never writes the data itself and never needs to see the whole store.

```
tx a1 at 1
set? orders where status!=:shipped : qty+=2, tags|=:late
expect count orders where qty=4 = 1
```

```
ok v=2 set:1 expect:1 vid=f7c3ccf56bde
```

A failed message applies nothing and comes back with a hint:

```
fail line 1: set matched no rows in orders
  hint: orders has 2 rows; check the condition's values and types. ...
  (nothing applied)
```

The whole language fits on one card: [`CARD.md`](CARD.md) (about 1.5k tokens).
That card is all a model is given.

## Try it

```
pip install -r requirements.txt
python test_shuttle.py          # 182 checks
```

```python
import shuttle as SH
s = SH.Store(SH.Schema("table orders key id : id:int status:kw qty:int tags:list<kw>"))
print(s.execute("add orders : 1, :unpaid, 2, []\nadd orders : 2, :shipped, 5, []"))
print(s.execute("set? orders where status!=:shipped : qty+=2, tags|=:late"))
print(s.execute("show orders"))
```

## What has been measured, and what has not

All measurements here are exploratory. Read the limits before quoting a number.

### Comparison experiment C-1 (`c1/`)

Four ways to make the same change to the same data, solved by `claude-haiku-5-5`
(2 repetitions per cell, at most 6 replies and 600 s per cell):
JSON full rewrite, JSON Patch, Weft full rewrite, Shuttle.
Six tasks, three sizes (50 / 500 / 5,000 orders).
The metric is the solver's reported response time plus machine time.

- **Pre-registered primary judgment (50 orders): inconclusive.** Two cells were
  invalidated by an operator error, leaving 4 comparable tasks where 5 were
  required. On those 4 tasks JSON-full ÷ Shuttle was 1.26–2.93. "Five times
  faster than JSON" is **not** shown at this size, and JSON Patch was faster than
  Shuttle on 2 of the 4.
- **500 orders (outside the primary judgment):** Shuttle completed 12/12 cells in
  10–34 s. JSON full rewrite completed 8/12; where both completed twice, Shuttle's
  time was about 1/14 (T4) and 1/38 (T5) of JSON full rewrite. On T1, which turned
  out to require no change at this size, Shuttle was slower (JSON-full ÷ Shuttle
  = 0.68). Against JSON Patch, Shuttle's time was about 1/5–1/7 on the three
  tasks that touch many rows (T2, T3, T4); the ratio JSON-Patch ÷ Shuttle was
  2.89 on T5, 1.15 on T6 and 0.77 on T1 (Shuttle slower).
- **5,000 orders:** Shuttle completed 12/12 cells (11–53 s). Weft full rewrite
  produced no submission in 3 replies per cell and was cut off there; JSON arms
  were not run at this size.
- Across all sizes Shuttle's time stayed within about 10.2–53.3 s; its prompt is
  about 1.5k tokens at every size because the data is not in the prompt.

Disclosed limits of C-1:

- One solver model, 2 repetitions, cells run concurrently.
- The 5,000-order Weft cells were stopped after 3 replies, which departs from the
  frozen procedure (6 replies or 600 s).
- The solver was told to use only file Read and Write tools. Which tools it
  actually used is not recorded (only the count per reply), so compliance is
  unverified for every arm.
- Task-file hashes were not recorded at run time. The files in `c1/run/` are the
  ones given to the solver; all 120 regenerate byte-identically from `c1/c1.py`.

Full record: [`c1/RESULTS-C1.md`](c1/RESULTS-C1.md), design
[`c1/DESIGN-compare-d5.md`](c1/DESIGN-compare-d5.md), freeze log
[`c1/FREEZE-C1.md`](c1/FREEZE-C1.md), every prompt, reply, transcript and
machine result under `c1/run/`.

### Earlier exploratory runs (`docs/RESULTS-shuttle-0.md`, `run/`)

- `claude-fable-5` / `claude-fable-5-1`: 6/6 on the first edit tasks and 6/6 on
  the L tasks (query, then update); 5/6 on the harder M tasks, then 3/3 on the
  re-run of the affected tasks after v6 added existence conditions and
  aggregates as values.
- `claude-haiku-5-5`: 12/12 on the L and M tasks, including an L6 re-run after an
  executor fix (the first L6 run ended in a wrong state because of an executor
  defect). The runs exposed three executor defects, which were fixed.
- Qwen3.5-4B (local, llama.cpp): passed M1–M4 and M6 by r6; M5 (update the top
  row) never passed in four attempts.
- Bulk operations scan at roughly 0.18 µs per row in this Python executor.

## Layout

| Path | What |
|---|---|
| `shuttle.py` | executor (schema, store, operations, transactions, receipts) |
| `weftnext.py` | value model and text syntax for scalars (vendored draft, see below) |
| `CARD.md` | the language card given to models |
| `test_shuttle.py` | 182 regression checks |
| `c1/` | comparison experiment C-1: harness, design, freeze log, all records |
| `run/`, `ops_*.py`, `bench_bulk.py` | exploratory harnesses and their records |
| `wb1/` | fixtures used by the tests and by the Weft arm of C-1 |
| `docs/` | log of the exploratory runs and of each executor revision |
| `ja/` | Japanese originals of the design, freeze log and result documents |

The design, freeze log and result documents were written in Japanese and translated
for this repository. The originals are kept under `ja/` because the frozen hash of
the C-1 design refers to the Japanese file.

## Notes on this repository

- `weftnext.py` is a draft ("Weft next", d6) of a successor value model to
  [Weft](https://github.com/mossbenchlab/weft). It is included only because the
  executor depends on it; it is not a released format, and its draft spec is not
  part of this repository. The value syntax a model needs (`42`, `1.50m`, `"text"`,
  `:kw`, `#2026-11-05`, `true`, `nil`, `[a, b]`) is on the card.
- Absolute paths of the working directory were replaced by paths relative to
  each file before publication. This changes the hash of four files; nothing
  else in them was changed. Hashes recorded in `c1/FREEZE-C1.md` refer to the
  originals:

  ```
  shuttle.py       recorded e8160b1810252070fc8ff60e9dac7776344c47345550da991235f08a9f1462ea
                   published 42adc680e0727196d7d49b82d501a72f19b8c30e2bc4494cfef5a509175883ef
  c1/c1.py         recorded da6efc657c06256ef922a6ad820bdd1c1167c41a639e5a6be31217a8eb7073d4
                   published dbeabf3f6c68324aadd839ad8c7a05902396b6c794526676ce2233c4179e30d2
  test_shuttle.py  recorded d7a47bc37466e6ad5601fcaebd4c165ef8656c70b04aa183431eccd8ab5bbce3
                   published 7bf81386cd22e2040df346594495421b6b5c157b65e4d6d3309651b9fd98f144
  c1/nx.sh         recorded c3a4d6f37a49c98fd8ece973b871cd229a9394ff53c267e85e3daf2e6a1a998a
                   published d73827e333c619c13aa61e6c884fb816c78ad78bdad5f13f0a4b0008abf509e4
  ```

  `CARD.md`, `weftnext.py`, `wb1/cards/N4.md`, `c1/ORDER-main.txt` and
  `ja/c1/DESIGN-compare-d5.md` are byte-identical to the frozen files.
  The published `test_shuttle.py` also has one Japanese comment word translated
  and `encoding="utf-8"` added to its file reads (needed on Windows). The same
  encoding argument was added to the exploratory harnesses (`ops_*.py`,
  `bench_bulk.py`).
- Requires Python 3.13 (used for the runs), `weft-format==1.0.2`,
  `jsonpatch==1.46` (C-1 only).

## License

MIT. See [`LICENSE`](LICENSE).
