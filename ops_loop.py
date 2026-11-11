"""Exploratory run L (Shuttle v5): query-in-the-loop and bulk conditional tasks at N=5,000 rows.

The solver AI sees the language card, the schema, a glimpse (2 rows) and the task — never the data.
Each solver turn is one message to the executor; the receipt goes back; the solver says DONE when finished.
State per task is the list of messages executed so far (replayed on a fresh store, so every step is reproducible).

  python3 -I ops_loop.py prompt <tid>            -> prints the solver prompt (also saved to run/<tid>.prompt.md)
  python3 -I ops_loop.py step <tid> <file>       -> executes the message in <file>, prints and records the receipt
  python3 -I ops_loop.py grade <tid>             -> compares the final state with the expected state
  python3 -I ops_loop.py expected                -> builds expected states with the reference transactions
"""
import sys, json, re, os, random, hashlib
import os as _os; _R = _os.path.dirname(_os.path.abspath(__file__)); sys.path.insert(0, _R)
import shuttle as SH, weftnext as W, weft

HERE = _R
RUN = f"{HERE}/run/loop"
os.makedirs(RUN, exist_ok=True)
N = 5000
SCHEMA = "doc audit:map\ntable orders key id : id:int status:kw=:unpaid due:dt total:dec qty:int tags:list<kw>=[] note:str?"

def data():
    rnd = random.Random(20261108)
    rows = []
    for i in range(N):
        st = rnd.choice(["unpaid", "unpaid", "unpaid", "paid", "shipped"])
        rows.append({"id": 1000 + i, "status": W.K(st),
                     "due": weft.WeftDate(2026, rnd.randint(1, 12), rnd.randint(1, 28)),
                     "total": weft.Decimal(f"{rnd.randint(1, 999)}.{rnd.randint(0, 99):02d}"), "qty": rnd.randint(1, 9),
                     "tags": [W.K("a")] if rnd.random() < 0.3 else [],
                     "note": "rush" if rnd.random() < 0.05 else None})
    # make the largest unpaid total unique
    rows[2500].update({"status": W.K("unpaid"), "total": weft.Decimal("999.99")})
    for r in rows:
        if r is not rows[2500] and r["total"].text == "999.99":
            r["total"] = weft.Decimal("999.98")
    # fixed rows for the single-order tasks
    rows[2412].update({"status": W.K("unpaid"), "qty": 4})      # id 3412
    rows[2777].update({"status": W.K("shipped"), "qty": 7})     # id 3777
    return {"audit": {"count": 0, "checked": None}, "orders": rows}

TASKS = {
 "L1": "Put every unpaid order that is due before 2026-06-01 on hold: status :hold, and add the tag :late to each of them. "
       "The message must fail if, after it, any unpaid order due before 2026-06-01 would remain.",
 "L2": "Increase the quantity of order 3412 by 2 — unless that order has already shipped (status :shipped), in which case change nothing.",
 "L3": "Increase the quantity of order 3777 by 2 — unless that order has already shipped (status :shipped), in which case change nothing.",
 "L4": "Count the paid orders that carry the tag :a and have a total of at least 500.00. Store that number in audit.count and set audit.checked to the date #2026-11-08.",
 "L5": "The unpaid order with the largest total must be marked for review: set its status to :review and its note to \"top\". Change no other order.",
 "L6": "Two changes: remove the tag :a from every shipped order that has it; and set note to \"Q1\" on every order due in March 2026 that has no note yet (do not overwrite existing notes).",
}

# reference transactions (how the task can be done; the solver may do it differently)
REFERENCE = {
 "L1": ["set orders where status=:unpaid and due<#2026-06-01 : status=:hold, tags+=:late\nexpect count orders where status=:unpaid and due<#2026-06-01 = 0"],
 "L2": ["set orders where id=3412 and status!=:shipped : qty+=2"],
 "L3": ["get orders where id=3777"],                       # shipped -> nothing to write
 "L4": ["count orders where status=:paid and tags has :a and total>=500.00m", "__PUT_COUNT__"],
 "L5": ["show orders where status=:unpaid order total desc limit 1 cols id,total", "set orders where id=3500 : status=:review, note=\"top\""],
 "L6": ["set orders where status=:shipped and tags has :a : tags-=:a\nset orders where due>=#2026-03-01 and due<#2026-04-01 and missing note : note=\"Q1\""],
}

def fresh():
    st = SH.Store(SH.Schema(SCHEMA)); st.load(data()); return st

def glimpse(st):
    t = st.schema.tables["orders"]
    g = [f"orders: {len(st.rows['orders'])} rows, e.g."]
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

def extract(reply):
    m = re.findall(r"^```[^\n]*\n(.*?)^```", reply, re.M | re.S)
    if len(m) != 1:
        return None
    return m[0].rstrip("\n")

def base_tid(tid): return tid.split('.')[0]
def state_path(tid): return f"{RUN}/{tid}.state.json"
def load_state(tid):
    return json.load(open(state_path(tid), encoding="utf-8")) if os.path.exists(state_path(tid)) else {"messages": [], "receipts": []}

def replay(tid):
    st = fresh()
    for m in load_state(tid)["messages"]:
        st.execute(m)
    return st

def step(tid, message):
    s = load_state(tid)
    st = replay(tid)
    r = st.execute(message)
    s["messages"].append(message); s["receipts"].append(r)
    json.dump(s, open(state_path(tid), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return r

def expected():
    out = {}
    for tid, txs in REFERENCE.items():
        st = fresh()
        for tx in txs:
            if tx == "__PUT_COUNT__":
                n = sum(1 for _ in st._select("orders", ("and", ("and", ("=", "status", W.K("paid")), ("has", "tags", W.K("a"))), (">=", "total", weft.Decimal("500.00"))), 0, need_pos=False))
                tx = f"put audit.count = {n}\nput audit.checked = #2026-11-08"
            r = st.execute(tx)
            assert r.startswith("ok"), (tid, r)
        out[tid] = {"digest": st.digest(), "version": st.version, "last_receipt": r}
    json.dump(out, open(f"{RUN}/expected.json", "w", encoding="utf-8"), indent=1)
    return out

def grade(tid):
    exp = json.load(open(f"{RUN}/expected.json", encoding="utf-8"))[base_tid(tid)]
    st = replay(tid)
    s = load_state(tid)
    return {"task": tid, "pass": st.digest() == exp["digest"], "digest": st.digest(), "expected": exp["digest"],
            "messages": len(s["messages"]), "fails": sum(1 for r in s["receipts"] if r.startswith("fail")),
            "solver_chars": sum(len(m) for m in s["messages"]), "receipt_chars": sum(len(r) for r in s["receipts"])}

if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "prompt":
        print(prompt(sys.argv[2]))
    elif cmd == "step":
        print(step(sys.argv[2], open(sys.argv[3], encoding="utf-8").read().rstrip("\n")))
    elif cmd == "grade":
        print(json.dumps(grade(sys.argv[2]), indent=1))
    elif cmd == "expected":
        print(json.dumps(expected(), indent=1))
