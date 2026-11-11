"""Exploratory run M (Shuttle v5 r3): harder jobs at N=50,000 orders with a child table (lines).
Goal: find where the solver needs extra round trips or has to transcribe numbers/ids — those are the
missing features. Expected states are computed WITHOUT the executor (plain Python over the data).

  python3 -I ops_loop2.py prompt <tid>          -> solver prompt (saved to run/loop2/<tid>.prompt.md)
  python3 -I ops_loop2.py step <tid> <file>     -> execute the message in <file>; record receipt
  python3 -I ops_loop2.py external <tid> <file> -> execute a message as ANOTHER writer (recorded; M5)
  python3 -I ops_loop2.py expected              -> compute expected digests
  python3 -I ops_loop2.py grade <tid>
"""
import sys, json, re, os, random, copy
import os as _os; _R = _os.path.dirname(_os.path.abspath(__file__)); sys.path.insert(0, _R)
import shuttle as SH, weftnext as W, weft
from decimal import Decimal as D

HERE = _R
RUN = f"{HERE}/run/loop2"
os.makedirs(RUN, exist_ok=True)
N = 50_000
SCHEMA = ("doc audit:map\n"
          "table orders key id : id:int status:kw=:unpaid due:dt total:dec tags:list<kw>=[] note:str? lines:lines\n"
          "table orders.lines : sku:kw qty:int amount:dec")
SKUS = ["p01", "p02", "p03", "p04", "p05"]

def dec(s): return weft.Decimal(s)

def data():
    rnd = random.Random(20261109)
    rows = []
    for i in range(N):
        st = rnd.choice(["unpaid", "unpaid", "unpaid", "paid", "shipped"])
        lines = []
        for _ in range(rnd.randint(1, 4)):
            q = rnd.randint(1, 5); price = rnd.randint(100, 9999)
            lines.append({"sku": W.K(rnd.choice(SKUS)), "qty": q, "amount": dec(f"{q * price // 100}.{q * price % 100:02d}")})
        rows.append({"id": 1000 + i, "status": W.K(st),
                     "due": weft.WeftDate(2026, rnd.randint(1, 12), rnd.randint(1, 28)),
                     "total": dec(f"{rnd.randint(1, 999)}.{rnd.randint(0, 99):02d}"),
                     "tags": [W.K("a")] if rnd.random() < 0.3 else [],
                     "note": None, "lines": lines})
    # M5: a unique largest unpaid total, and a unique second
    rows[30000].update({"status": W.K("unpaid"), "total": dec("999.99")})
    rows[30001].update({"status": W.K("unpaid"), "total": dec("999.98")})
    for r in rows:
        if r is not rows[30000] and r is not rows[30001] and r["total"].text in ("999.99", "999.98"):
            r["total"] = dec("999.97")
    return {"audit": {"policy": None, "unpaid": 0, "paid": 0, "shipped_total": dec("0")}, "orders": rows}

TASKS = {
 "M1": "If MORE than 100 unpaid orders are due before 2026-02-01, put all of them on hold (status :hold) and set audit.policy to \"strict\". "
       "Otherwise change no order and set audit.policy to \"normal\".",
 "M2": "Order 7006: set its total to the sum of the amount values of its lines.",
 "M3": "Fill the audit fields: audit.unpaid = number of unpaid orders, audit.paid = number of paid orders, "
       "audit.shipped_total = sum of total over shipped orders.",
 "M4": "In every UNPAID order, lines with sku :p03 must get qty 0. Each unpaid order that had at least one such line must also get the tag :p03-cancelled added. Change nothing else.",
 "M5": "The unpaid order with the largest total must be marked for review: set its status to :review and its note to \"top\". "
       "Change no other order. Note: other writers may change the store between your messages; protect your write with `tx <id> at <version>`.",
 "M6": "Add a new order: id 99001, unpaid, due #2026-12-01, no tags, no note, with two lines: (sku :p01, qty 2, amount 20.00) and (sku :p02, qty 1, amount 5.50). "
       "Its total must equal the sum of its line amounts.",
}
# re-runs with the v6 card (fresh conversations): same tasks, suffix b
for _t in ("M2", "M3", "M4"):
    TASKS[_t + "b"] = TASKS[_t]

# M5: the external write happens right after the solver's first read-only message
M5_EXTERNAL = "set orders where id=31000 : status=:paid"

_CACHE = f"{RUN}/data.pkl"
def cached_data():
    import pickle
    if os.path.exists(_CACHE):
        return pickle.load(open(_CACHE, "rb"))
    d = data(); pickle.dump(d, open(_CACHE, "wb")); return d

def fresh():
    st = SH.Store(SH.Schema(SCHEMA)); st.load(cached_data()); return st

def glimpse(st):
    t = st.schema.tables["orders"]
    g = [f"orders: {len(st.rows['orders'])} rows ({sum(len(r['lines']) for r in st.rows['orders'])} lines in all), e.g."]
    for r in st.rows["orders"][:2]:
        g.append("  " + W.emit_ai(st._row_out(t, r)).strip().replace("\n", " "))
    g.append("doc: " + W.emit_ai(st.doc).strip().replace("\n", " "))
    return "\n".join(g)

def prompt(tid):
    st = fresh()
    p = (open(f"{HERE}/CARD.md", encoding="utf-8").read() + "\nSCHEMA:\n" + SCHEMA + "\n\nCURRENT STATE (glimpse; version 0):\n" + glimpse(st) +
         "\n\nTASK:\n" + TASKS[base_tid(tid)] + "\n")
    open(f"{RUN}/{tid}.prompt.md", "w", newline="\n", encoding="utf-8").write(p)
    return p

def base_tid(tid): return tid.split('.')[0]
def state_path(tid): return f"{RUN}/{tid}.state.json"
def load_state(tid):
    return json.load(open(state_path(tid), encoding="utf-8")) if os.path.exists(state_path(tid)) else {"log": []}   # log: [{"who","message","receipt"}]

def replay(tid):
    st = fresh()
    for e in load_state(tid)["log"]:
        st.execute(e["message"])
    return st

def step(tid, message, who="solver"):
    s = load_state(tid); st = replay(tid)
    r = st.execute(message)
    s["log"].append({"who": who, "message": message, "receipt": r})
    json.dump(s, open(state_path(tid), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return r

# ---- expected states, computed on plain data without the executor
def expected():
    out = {}
    def digest_of(d):
        st = SH.Store(SH.Schema(SCHEMA)); st.load(d); return st.digest()
    base = data()
    # M1
    d = copy.deepcopy(base)
    hits = [r for r in d["orders"] if r["status"].name == "unpaid" and (r["due"].month, r["due"].day) < (2, 1)]
    if len(hits) > 100:
        for r in hits: r["status"] = W.K("hold")
        d["audit"]["policy"] = "strict"
    else:
        d["audit"]["policy"] = "normal"
    out["M1"] = {"digest": digest_of(d), "note": f"{len(hits)} matching orders"}
    # M2
    d = copy.deepcopy(base)
    r = d["orders"][7006 - 1000]; assert r["id"] == 7006
    tot = sum(D(l["amount"].text) for l in r["lines"])
    r["total"] = dec(format(tot, "f"))
    out["M2"] = {"digest": digest_of(d), "note": f"total={format(tot, 'f')}, {len(r['lines'])} lines"}
    # M3
    d = copy.deepcopy(base)
    d["audit"]["unpaid"] = sum(1 for r in d["orders"] if r["status"].name == "unpaid")
    d["audit"]["paid"] = sum(1 for r in d["orders"] if r["status"].name == "paid")
    stot = sum((D(r["total"].text) for r in d["orders"] if r["status"].name == "shipped"), D(0))
    d["audit"]["shipped_total"] = dec(format(stot, "f"))
    out["M3"] = {"digest": digest_of(d), "note": f"unpaid={d['audit']['unpaid']} paid={d['audit']['paid']} shipped_total={format(stot,'f')}"}
    # M4
    d = copy.deepcopy(base); n_orders = n_lines = 0
    for r in d["orders"]:
        if r["status"].name != "unpaid": continue
        hit = False
        for l in r["lines"]:
            if l["sku"].name == "p03":
                l["qty"] = 0; hit = True; n_lines += 1
        if hit:
            r["tags"] = r["tags"] + [W.K("p03-cancelled")]; n_orders += 1
    out["M4"] = {"digest": digest_of(d), "note": f"{n_lines} lines in {n_orders} orders"}
    # M5: external write makes 31000 paid; the correct target is then 31001
    d = copy.deepcopy(base)
    d["orders"][30000]["status"] = W.K("paid")
    r = d["orders"][30001]; assert r["id"] == 31001 and r["total"].text == "999.98"
    r["status"] = W.K("review"); r["note"] = "top"
    out["M5"] = {"digest": digest_of(d), "note": "31000 became paid externally; 31001 must be reviewed"}
    # M6
    d = copy.deepcopy(base)
    d["orders"].append({"id": 99001, "status": W.K("unpaid"), "due": weft.WeftDate(2026, 12, 1), "total": dec("25.50"), "tags": [], "note": None,
                        "lines": [{"sku": W.K("p01"), "qty": 2, "amount": dec("20.00")}, {"sku": W.K("p02"), "qty": 1, "amount": dec("5.50")}]})
    out["M6"] = {"digest": digest_of(d), "note": "new order appended"}
    json.dump(out, open(f"{RUN}/expected.json", "w", encoding="utf-8"), indent=1)
    return out

def grade(tid):
    exp = json.load(open(f"{RUN}/expected.json", encoding="utf-8"))[base_tid(tid).rstrip("b")]
    st = replay(tid); s = load_state(tid)
    sol = [e for e in s["log"] if e["who"] == "solver"]
    return {"task": tid, "pass": st.digest() == exp["digest"], "digest": st.digest(), "expected": exp["digest"], "note": exp["note"],
            "solver_messages": len(sol), "fails": sum(1 for e in sol if e["receipt"].startswith("fail")),
            "solver_chars": sum(len(e["message"]) for e in sol), "receipt_chars": sum(len(e["receipt"]) for e in sol)}

if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "prompt": print(prompt(sys.argv[2]))
    elif cmd == "step": print(step(sys.argv[2], open(sys.argv[3], encoding="utf-8").read().rstrip("\n")))
    elif cmd == "external": print(step(sys.argv[2], open(sys.argv[3], encoding="utf-8").read().rstrip("\n"), who="external"))
    elif cmd == "expected": print(json.dumps(expected(), indent=1))
    elif cmd == "grade": print(json.dumps(grade(sys.argv[2]), indent=1))
