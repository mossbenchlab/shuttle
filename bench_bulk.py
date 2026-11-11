"""Executor wall time for bulk conditional operations vs. row count (Shuttle v5).
Load time excluded; each figure is the minimum of 5 runs on a freshly loaded store."""
import sys, time, random, json
import os as _os; _R = _os.path.dirname(_os.path.abspath(__file__)); sys.path.insert(0, _R)
import shuttle as SH, weftnext as W, weft

SCHEMA = "table orders key id : id:int status:kw=:unpaid due:dt total:dec qty:int tags:list<kw>=[] note:str?"

def make(n, seed=1):
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        st = rnd.choice(["unpaid", "unpaid", "unpaid", "paid", "shipped"])
        due = f"2026-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}"
        rows.append({"id": 1000 + i, "status": W.K(st), "due": weft.WeftDate(*map(int, due.split("-"))),
                     "total": weft.Decimal(f"{rnd.randint(1, 999)}.{rnd.randint(0, 99):02d}"), "qty": rnd.randint(1, 9),
                     "tags": [W.K("a")] if rnd.random() < 0.3 else [], "note": None})
    return {"orders": rows}

CASES = [
    ("keyed set (control)",           lambda n: f"set orders where id={1000 + n // 2} : qty+=1"),
    ("count where status=:unpaid",    lambda n: "count orders where status=:unpaid"),
    ("bulk set ~25% rows (2 terms)",  lambda n: "set orders where status=:unpaid and due<#2026-06-01 : status=:hold, tags+=:late"),
    ("bulk set all rows (where true)", lambda n: "set orders where true : qty+=1"),
    ("bulk set + expect",             lambda n: "set orders where status=:paid : note=\"ok\"\nexpect count orders where status=:paid > 0"),
]

def main():
    out = {}
    for n in (1_000, 10_000, 100_000, 500_000):
        data = make(n)
        out[n] = {}
        for name, mk in CASES:
            best = None; hit = None
            for _ in range(5):
                st = SH.Store(SH.Schema(SCHEMA)); st.load(data)
                tx = mk(n)
                t0 = time.perf_counter(); r = st.execute(tx); dt = time.perf_counter() - t0
                assert r.startswith("ok"), r
                best = dt if best is None else min(best, dt); hit = r.split("\n")[0]
            out[n][name] = (best * 1000, hit)
            print(f"n={n:>7} {name:<34} {best*1000:9.2f} ms   {hit}", flush=True)
    json.dump({str(k): {c: {"ms": v[0], "receipt": v[1]} for c, v in d.items()} for k, d in out.items()},
              open(_R + "/bench_bulk.json", "w", encoding="utf-8"), indent=1)

if __name__ == "__main__":
    main()
