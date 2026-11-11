"""Comparison experiment C-1 (design d4): task generator, four arm processors, independent grader.

Logical state (the common ground of all arms):
  {"audit": {"unpaid": int, "paid": int, "shipped_total": Decimal},
   "orders": [{"id": int, "status": str, "due": "YYYY-MM-DD", "total": Decimal, "qty": int,
               "tags": [str], "note": str|None, "lines": [{"sku": str, "qty": int, "amount": Decimal}]}]}

  python3 c1.py prompt <cell>                    cell = <arm>-<task>-<N>-<rep>, e.g. S-T3-500-1
  python3 c1.py step <cell> <reply-file> <model_ms>
  python3 c1.py grade <cell>
  python3 c1.py selftest
"""
import sys, os, json, re, copy, random, time
from decimal import Decimal as D
_R = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, _R)
import shuttle as SH, weftnext as W
weft = SH.weft
import jsonpatch

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.environ.get("C1_RUN", f"{HERE}/run")
ARMS = ("J-full", "J-patch", "W-full", "S")
TASKS = ("T1", "T2", "T3", "T4", "T5", "T6")
MAX_REPLIES, MAX_SECONDS = 6, 600
SKUS = ["p01", "p02", "p03", "p04", "p05"]
SCHEMA_S = ("doc audit:map\n"
            "table orders key id : id:int status:kw due:dt total:dec qty:int tags:list<kw> note:str? lines:lines\n"
            "table orders.lines : sku:kw qty:int amount:dec")
SCHEMA_TEXT = """SCHEMA (the same data in every format):
  audit: {unpaid: integer, paid: integer, shipped_total: decimal}
  orders: list of rows, unique by id; row order matters (new rows go at the end):
    id: integer, status: keyword, due: date, total: decimal, qty: integer,
    tags: list of keywords (order and duplicates matter), note: string or null,
    lines: list of {sku: keyword, qty: integer, amount: decimal}"""

# ------------------------------------------------------------------ data and tasks
def seed_of(n, rep):
    return 77000000 + n * 10 + rep

def gen(n, rep):
    rnd = random.Random(seed_of(n, rep))
    rows = []
    for i in range(n):
        st = rnd.choice(["unpaid", "unpaid", "unpaid", "paid", "shipped"])
        lines = []
        for _ in range(rnd.randint(1, 4)):
            q = rnd.randint(1, 5); price = rnd.randint(100, 9999)
            lines.append({"sku": rnd.choice(SKUS), "qty": q, "amount": D(q * price) / 100})
        rows.append({"id": 1000 + i, "status": st, "due": f"2026-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}",
                     "total": D(rnd.randint(100, 99999)) / 100, "qty": rnd.randint(1, 9),
                     "tags": ["a"] if rnd.random() < 0.3 else [], "note": None, "lines": lines})
    top = rows[rnd.randrange(n)]
    top["status"] = "unpaid"; top["total"] = D("9999.99")          # unique largest unpaid total
    for r in rows:
        r["amount_fix"] = None; del r["amount_fix"]
        for l in r["lines"]:
            l["amount"] = l["amount"].quantize(D("0.01"))
        r["total"] = r["total"].quantize(D("0.01"))
    params = {"t1_id": rows[rnd.randrange(n)]["id"], "t2_cutoff": f"2026-{rnd.randint(3, 6):02d}-01",
              "t6_id": 900000 + rep, "t6_due": f"2026-12-{rnd.randint(1, 28):02d}",
              "t6_a": D(rnd.randint(500, 5000)) / 100, "t6_b": D(rnd.randint(500, 5000)) / 100}
    return {"audit": {"unpaid": 0, "paid": 0, "shipped_total": D("0.00")}, "orders": rows}, params

def task_text(task, p):
    return {
     "T1": f"Increase the qty of order {p['t1_id']} by 2 — unless that order's status is shipped, in which case change nothing.",
     "T2": f"Every unpaid order that is due before {p['t2_cutoff']}: set its status to hold and append the tag late to its tags.",
     "T3": "Fill the audit fields: audit.unpaid = number of unpaid orders, audit.paid = number of paid orders, audit.shipped_total = sum of total over shipped orders.",
     "T4": "In every unpaid order, each line with sku p03 must get qty 0. Each unpaid order that has at least one such line must also get the tag p03-cancelled appended to its tags. Change nothing else.",
     "T5": "The unpaid order with the largest total: set its status to review and its note to \"top\". Change no other order.",
     "T6": f"Add a new order at the end: id {p['t6_id']}, status unpaid, due {p['t6_due']}, qty 1, no tags, no note, with two lines: "
           f"(sku p01, qty 2, amount {p['t6_a']:.2f}) and (sku p02, qty 1, amount {p['t6_b']:.2f}). Its total must equal the sum of its line amounts.",
    }[task]

def expected(state, task, p):
    """Independent of every arm processor and of the Shuttle executor: plain Python on the logical state."""
    d = copy.deepcopy(state); rows = d["orders"]
    if task == "T1":
        r = next(r for r in rows if r["id"] == p["t1_id"])
        if r["status"] != "shipped":
            r["qty"] += 2
    elif task == "T2":
        for r in rows:
            if r["status"] == "unpaid" and r["due"] < p["t2_cutoff"]:
                r["status"] = "hold"; r["tags"].append("late")
    elif task == "T3":
        d["audit"] = {"unpaid": sum(r["status"] == "unpaid" for r in rows), "paid": sum(r["status"] == "paid" for r in rows),
                      "shipped_total": sum((r["total"] for r in rows if r["status"] == "shipped"), D("0.00"))}
    elif task == "T4":
        for r in rows:
            if r["status"] == "unpaid" and any(l["sku"] == "p03" for l in r["lines"]):
                for l in r["lines"]:
                    if l["sku"] == "p03":
                        l["qty"] = 0
                r["tags"].append("p03-cancelled")
    elif task == "T5":
        r = max((r for r in rows if r["status"] == "unpaid"), key=lambda r: r["total"])
        r["status"] = "review"; r["note"] = "top"
    elif task == "T6":
        rows.append({"id": p["t6_id"], "status": "unpaid", "due": p["t6_due"], "total": p["t6_a"] + p["t6_b"], "qty": 1, "tags": [], "note": None,
                     "lines": [{"sku": "p01", "qty": 2, "amount": p["t6_a"]}, {"sku": "p02", "qty": 1, "amount": p["t6_b"]}]})
    return d

def same(a, b):
    """Logical equality: decimals by numeric value; lists in order; maps by key set."""
    if isinstance(a, D) or isinstance(b, D):
        return isinstance(a, D) and isinstance(b, D) and a == b
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b

# ------------------------------------------------------------------ JSON <-> logical (with the common schema check)
class Bad(Exception):
    pass

_DEC = re.compile(r"-?\d+(\.\d+)?\Z"); _DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z"); _KW = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")

def to_json_obj(state):
    def f(v):
        if isinstance(v, D): return f"{v:.2f}" if v == v.quantize(D("0.01")) else format(v, "f")
        if isinstance(v, dict): return {k: f(x) for k, x in v.items()}
        if isinstance(v, list): return [f(x) for x in v]
        return v
    return f(state)

def to_json(state):
    o = to_json_obj(state)
    return '{"audit": ' + json.dumps(o["audit"]) + ', "orders": [\n' + ",\n".join(json.dumps(r, ensure_ascii=False) for r in o["orders"]) + "\n]}"

def check(kind, v, path):
    """Shared schema rules. `v` is in JSON representation; returns the logical value."""
    def need(c, msg):
        if not c: raise Bad(f"{path}: {msg}")
    if kind == "int":
        need(isinstance(v, int) and not isinstance(v, bool), f"expected an integer, got {json.dumps(v)[:40]}"); return v
    if kind == "dec":
        need(isinstance(v, str) and _DEC.match(v), f"expected a decimal written as a string like \"12.50\", got {json.dumps(v)[:40]}"); return D(v)
    if kind == "date":
        need(isinstance(v, str) and _DATE.match(v), f"expected a date string like \"2026-03-01\", got {json.dumps(v)[:40]}")
        try:
            import datetime; datetime.date(int(v[:4]), int(v[5:7]), int(v[8:10]))
        except ValueError:
            raise Bad(f"{path}: {v!r} is not a real calendar date")
        return v
    if kind == "kw":
        need(isinstance(v, str) and _KW.match(v), f"expected a keyword string like \"unpaid\", got {json.dumps(v)[:40]}"); return v
    if kind == "note":
        need(v is None or isinstance(v, str), f"expected a string or null, got {json.dumps(v)[:40]}"); return v
    raise AssertionError(kind)

def keys(o, want, path):
    if not isinstance(o, dict): raise Bad(f"{path}: expected an object")
    if set(o) != set(want):
        miss, extra = sorted(set(want) - set(o)), sorted(set(o) - set(want))
        raise Bad(f"{path}: " + (f"missing {miss} " if miss else "") + (f"unexpected {extra}" if extra else ""))

def from_json_obj(o):
    keys(o, ["audit", "orders"], "$")
    keys(o["audit"], ["unpaid", "paid", "shipped_total"], "$.audit")
    out = {"audit": {"unpaid": check("int", o["audit"]["unpaid"], "$.audit.unpaid"), "paid": check("int", o["audit"]["paid"], "$.audit.paid"),
                     "shipped_total": check("dec", o["audit"]["shipped_total"], "$.audit.shipped_total")}, "orders": []}
    if not isinstance(o["orders"], list): raise Bad("$.orders: expected a list")
    seen = set()
    for i, r in enumerate(o["orders"]):
        p = f"$.orders[{i}]"
        keys(r, ["id", "status", "due", "total", "qty", "tags", "note", "lines"], p)
        rid = check("int", r["id"], p + ".id")
        if rid in seen: raise Bad(f"{p}.id: duplicate id {rid}")
        seen.add(rid)
        if not isinstance(r["tags"], list): raise Bad(p + ".tags: expected a list")
        if not isinstance(r["lines"], list): raise Bad(p + ".lines: expected a list")
        lines = []
        for j, l in enumerate(r["lines"]):
            q = f"{p}.lines[{j}]"; keys(l, ["sku", "qty", "amount"], q)
            lines.append({"sku": check("kw", l["sku"], q + ".sku"), "qty": check("int", l["qty"], q + ".qty"), "amount": check("dec", l["amount"], q + ".amount")})
        out["orders"].append({"id": rid, "status": check("kw", r["status"], p + ".status"), "due": check("date", r["due"], p + ".due"),
                              "total": check("dec", r["total"], p + ".total"), "qty": check("int", r["qty"], p + ".qty"),
                              "tags": [check("kw", t, f"{p}.tags[{k}]") for k, t in enumerate(r["tags"])], "note": check("note", r["note"], p + ".note"), "lines": lines})
    return out

# ------------------------------------------------------------------ Weft <-> logical
def to_weft_value(state):
    def dec(v): return weft.Decimal(f"{v:.2f}" if v == v.quantize(D("0.01")) else format(v, "f"))
    def date(s): y, m, d = map(int, s.split("-")); return weft.WeftDate(y, m, d)
    return {"audit": {"unpaid": state["audit"]["unpaid"], "paid": state["audit"]["paid"], "shipped_total": dec(state["audit"]["shipped_total"])},
            "orders": [{"id": r["id"], "status": W.K(r["status"]), "due": date(r["due"]), "total": dec(r["total"]), "qty": r["qty"],
                        "tags": [W.K(t) for t in r["tags"]], "note": r["note"],
                        "lines": [{"sku": W.K(l["sku"]), "qty": l["qty"], "amount": dec(l["amount"])} for l in r["lines"]]} for r in state["orders"]]}

def weft_to_logical(v):
    """Weft value -> logical state. Every field is checked against the schema with its Weft type intact
    (a keyword is not a string, a decimal is not an integer), so no type information is lost before the check."""
    def t_int(x, p):
        if not isinstance(x, int) or isinstance(x, bool): raise Bad(f"{p}: expected an integer")
        return x
    def t_dec(x, p):
        if not isinstance(x, weft.Decimal): raise Bad(f"{p}: expected a decimal like 12.50m")
        return D(x.text)
    def t_kw(x, p):
        if not isinstance(x, W.K): raise Bad(f"{p}: expected a keyword like :unpaid")
        return x.name
    def t_date(x, p):
        if not isinstance(x, weft.WeftDate) or x.has_time: raise Bad(f"{p}: expected a date without time like #2026-03-01")
        return f"{x.year:04d}-{x.month:02d}-{x.day:02d}"
    def t_note(x, p):
        if x is not None and not isinstance(x, str): raise Bad(f"{p}: expected a string or nil")
        return x
    keys(v, ["audit", "orders"], "$")
    keys(v["audit"], ["unpaid", "paid", "shipped_total"], "$.audit")
    out = {"audit": {"unpaid": t_int(v["audit"]["unpaid"], "$.audit.unpaid"), "paid": t_int(v["audit"]["paid"], "$.audit.paid"),
                     "shipped_total": t_dec(v["audit"]["shipped_total"], "$.audit.shipped_total")}, "orders": []}
    if not isinstance(v["orders"], list): raise Bad("$.orders: expected a list")
    seen = set()
    for i, r in enumerate(v["orders"]):
        p = f"$.orders[{i}]"
        keys(r, ["id", "status", "due", "total", "qty", "tags", "note", "lines"], p)
        rid = t_int(r["id"], p + ".id")
        if rid in seen: raise Bad(f"{p}.id: duplicate id {rid}")
        seen.add(rid)
        if not isinstance(r["tags"], list): raise Bad(p + ".tags: expected a list")
        if not isinstance(r["lines"], list): raise Bad(p + ".lines: expected a list")
        lines = []
        for j, l in enumerate(r["lines"]):
            q = f"{p}.lines[{j}]"; keys(l, ["sku", "qty", "amount"], q)
            lines.append({"sku": t_kw(l["sku"], q + ".sku"), "qty": t_int(l["qty"], q + ".qty"), "amount": t_dec(l["amount"], q + ".amount")})
        out["orders"].append({"id": rid, "status": t_kw(r["status"], p + ".status"), "due": t_date(r["due"], p + ".due"), "total": t_dec(r["total"], p + ".total"),
                              "qty": t_int(r["qty"], p + ".qty"), "tags": [t_kw(t, f"{p}.tags[{k}]") for k, t in enumerate(r["tags"])],
                              "note": t_note(r["note"], p + ".note"), "lines": lines})
    return out

def to_weft(state):
    return W.emit_ai(to_weft_value(state))

# ------------------------------------------------------------------ cards and prompts
PROTOCOL = ("PROTOCOL: Do not use any tools. Each reply is EITHER exactly one fenced code block containing your submission and nothing else, "
            "OR the single word DONE. You have at most 6 replies. After each submission you receive the machine result: accepted, or the error "
            "(a failed submission changes nothing). You are never told whether the state is correct. Reply DONE when the state is as the task requires.")
CARD_J = """FORMAT: JSON. The state is one JSON object {"audit": {...}, "orders": [...]}.
Representation: decimals are strings with the digits ("12.50"); dates are strings "YYYY-MM-DD"; keywords are plain strings ("unpaid"); a missing note is null."""
CARD_JFULL = CARD_J + "\nSUBMISSION: the COMPLETE new state as JSON, in a ```json block. It replaces the whole state, so every order must be present, in the same order."
CARD_JPATCH = CARD_J + ("\nSUBMISSION: a JSON Patch (RFC 6902): a JSON array of operations, in a ```json block, applied to the current state. "
                        'Operations: {"op": "replace", "path": "/orders/0/status", "value": "hold"}, "add" (use path ".../-" to append to a list), "remove", "test", "move", "copy". '
                        "Paths are JSON Pointers; list positions are 0-based indexes (order 0 is the first row shown).")
def card_w():
    c = open(_R + "/wb1/cards/N4.md", encoding="utf-8").read().rstrip()
    return (c + "\n- date without time: `#2026-03-01`\n\nSUBMISSION: the COMPLETE new state in this format, in a ```weft block. It replaces the whole state, "
                "so every order must be present, in the same order. Keep the types: keywords `:unpaid`, decimals `12.50m`, dates `#2026-03-01`, a missing note `nil`.")
def card_s():
    return open(HERE + "/CARD-v6r10.md", encoding="utf-8").read().rstrip()   # the card frozen for C-1 (the top-level CARD.md has moved on)

def parse_cell(cell):
    arm, task, n, rep = cell.rsplit("-", 3)
    assert arm in ARMS and task in TASKS, cell
    return arm, task, int(n), int(rep)

def store_of(state):
    st = SH.Store(SH.Schema(SCHEMA_S)); st.load(to_weft_value(state)); return st

def prompt(cell):
    arm, task, n, rep = parse_cell(cell)
    state, p = gen(n, rep)
    if arm == "S":
        st = store_of(state)
        g = st.execute("show orders limit 2").split("\n", 1)[1] + "\n" + st.execute(f"show orders.lines where id={state['orders'][0]['id']}").split("\n", 1)[1]
        body = (card_s() + "\n\nSCHEMA:\n" + SCHEMA_S + f"\n\nCURRENT STATE (glimpse; version 0; {len(state['orders'])} orders, "
                f"{sum(len(r['lines']) for r in state['orders'])} lines):\n" + g + "\ndoc: " + W.emit_ai(st.doc).strip().replace("\n", " "))
    elif arm == "W-full":
        body = card_w() + "\n\n" + SCHEMA_TEXT + "\n\nCURRENT STATE:\n" + to_weft(state)
    else:
        body = (CARD_JFULL if arm == "J-full" else CARD_JPATCH) + "\n\n" + SCHEMA_TEXT + "\n\nCURRENT STATE:\n" + to_json(state)
    return PROTOCOL + "\n\n" + body + "\n\nTASK:\n" + task_text(task, p) + "\n"

# ------------------------------------------------------------------ sessions
def path(cell): return f"{RUN}/{cell}.json"
def load(cell):
    if os.path.exists(path(cell)):
        return json.load(open(path(cell), encoding="utf-8"))
    return {"cell": cell, "log": [], "accepted": [], "end": None}

_FENCE = re.compile(r"\s*```[A-Za-z]*[ \t]*\r?\n(.*?)\r?\n```\s*\Z", re.S)

def current_state(cell, rec):
    """Replay the accepted submissions (not timed)."""
    arm, task, n, rep = parse_cell(cell)
    state, p = gen(n, rep)
    if arm == "S":
        st = store_of(state)
        for m in rec["accepted"]:
            st.execute(m)
        return st, state, p
    if arm in ("J-full", "J-patch"):
        state = to_json_obj(state)                            # raw JSON object; never re-normalised (C4-03)
    for sub in rec["accepted"]:
        state = apply_submission(arm, state, sub)[0]
    return state, None, p

def apply_submission(arm, state, text):
    """`state` is the raw JSON object for the J arms and the logical state for W-full; the same kind is returned.
    Raises Bad with the error text (then nothing is applied)."""
    if arm == "J-full" or arm == "J-patch":
        try:
            o = json.loads(text)
        except json.JSONDecodeError as e:
            raise Bad(f"JSON syntax error at line {e.lineno} column {e.colno}: {e.msg}")
        if arm == "J-full":
            new = from_json_obj(o)                           # schema check only; the stored state is `o` itself
            return o, f"accepted: {len(new['orders'])} orders, {sum(len(r['lines']) for r in new['orders'])} lines"
        if not isinstance(o, list):
            raise Bad("a JSON Patch is a JSON array of operations")
        try:
            patched = jsonpatch.apply_patch(state, o)
        except (jsonpatch.JsonPatchException, jsonpatch.JsonPointerException, KeyError, IndexError, TypeError) as e:
            raise Bad(f"patch could not be applied: {type(e).__name__}: {str(e)[:200]}")
        from_json_obj(patched)                               # schema check only
        return patched, f"applied: {len(o)} operations"
    if arm == "W-full":
        try:
            v = W.parse_ai(text + "\n")
        except W.WeftNextError as e:
            raise Bad(f"Weft syntax error: {str(e)[:200]}")
        new = weft_to_logical(v)
        return new, f"accepted: {len(new['orders'])} orders, {sum(len(r['lines']) for r in new['orders'])} lines"
    raise AssertionError(arm)

def step(cell, reply, model_ms, finish_reason=None):
    """One solver reply. `model_ms` is the environment-reported time of that reply; `finish_reason` is the
    environment's stop reason if it reports one (None = not available)."""
    arm, task, n, rep = parse_cell(cell)
    rec = load(cell)
    if rec["end"]:
        return f"(session already ended: {rec['end']})"
    prior = sum(e["model_ms"] / 1000 + e["machine_s"] for e in rec["log"])
    entry = {"reply": reply, "model_ms": model_ms, "finish_reason": finish_reason}
    if prior + model_ms / 1000 >= MAX_SECONDS:                # C4-02: the reply arrived after the budget -> discarded unprocessed
        entry.update(kind="late_discarded", machine_s=0.0, feedback=None)
        rec["log"].append(entry); rec["end"] = "time_limit"; rec["seconds"] = float(MAX_SECONDS)
        os.makedirs(RUN, exist_ok=True)
        json.dump(rec, open(path(cell), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        return "(session ended: time_limit; the last reply arrived after the time budget and was not processed)"
    cur, _, p = current_state(cell, rec)                      # not timed (replay)
    t0 = time.perf_counter()
    if reply.strip() == "DONE":
        entry["kind"] = "done"; fb = None; rec["end"] = "done"
    else:
        m = _FENCE.match(reply)
        if not m or "```" in m.group(1) or not m.group(1).strip():
            if reply.count("```") == 1:                       # C4-04: cause is recorded only if the environment reports it
                entry["kind"] = "truncated_by_output_limit" if finish_reason in ("length", "max_tokens") else "unterminated_cause_unknown"
                fb = "Your reply opened a code block but did not close it. Nothing was submitted."
            else:
                entry["kind"] = "format_error"
                fb = "FORMAT: reply with exactly one fenced code block and nothing else, or the single word DONE. Nothing was submitted."
        else:
            sub = m.group(1)
            if arm == "S":
                r = cur.execute(sub)
                ok = not r.startswith("fail")
                fb = r
                if ok:                                        # apply the common schema check to the resulting state (C4-01)
                    try:
                        weft_to_logical(cur.materialize())
                    except Bad as e:
                        ok = False; fb = f"rejected: the state would violate the schema: {e}\n(nothing applied)"
            else:
                try:
                    _, summary = apply_submission(arm, cur, sub); ok = True; fb = summary
                except Bad as e:
                    ok = False; fb = f"rejected: {e}\n(nothing applied)"
            entry["kind"] = "accepted" if ok else "rejected"
            if ok:
                rec["accepted"].append(sub)
    entry["machine_s"] = time.perf_counter() - t0
    entry["feedback"] = fb
    rec["log"].append(entry)
    total = prior + model_ms / 1000 + entry["machine_s"]
    if not rec["end"]:
        if total >= MAX_SECONDS: rec["end"] = "time_limit"    # processing started before the budget ran out: its result stands
        elif len(rec["log"]) >= MAX_REPLIES: rec["end"] = "reply_limit"
    rec["seconds"] = total
    os.makedirs(RUN, exist_ok=True)
    json.dump(rec, open(path(cell), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    if rec["end"] == "done":
        return "(session ended: DONE)"
    return "MACHINE RESULT:\n" + fb + ("" if not rec["end"] else f"\n(session ended: {rec['end']})") + \
           ("" if rec["end"] else f"\n\nReply with your next submission (one fenced code block) or DONE. Replies used: {len(rec['log'])} of {MAX_REPLIES}.")

def final_state(cell):
    arm, task, n, rep = parse_cell(cell)
    rec = load(cell)
    cur, _, p = current_state(cell, rec)
    if arm == "S":
        cur = weft_to_logical(cur.materialize())
    elif arm in ("J-full", "J-patch"):
        cur = from_json_obj(cur)
    return cur, rec, p

def grade(cell):
    arm, task, n, rep = parse_cell(cell)
    cur, rec, p = final_state(cell)
    exp = expected(gen(n, rep)[0], task, p)
    return {"cell": cell, "arm": arm, "task": task, "n": n, "rep": rep, "complete": same(cur, exp), "end": rec["end"],
            "replies": len(rec["log"]), "seconds": rec.get("seconds"), "model_s": sum(e["model_ms"] for e in rec["log"]) / 1000,
            "machine_s": sum(e["machine_s"] for e in rec["log"]), "kinds": [e["kind"] for e in rec["log"]]}

# ------------------------------------------------------------------ self-test with reference submissions
def reference(arm, task, state, p):
    exp = expected(state, task, p)
    if arm == "J-full": return "```json\n" + to_json(exp) + "\n```"
    if arm == "W-full": return "```weft\n" + to_weft(exp).rstrip("\n") + "\n```"
    if arm == "J-patch": return "```json\n" + json.dumps(jsonpatch.make_patch(to_json_obj(state), to_json_obj(exp)).patch) + "\n```"
    m = {"T1": f"set? orders where id={p['t1_id']} and status!=:shipped : qty+=2",
         "T2": f"set? orders where status=:unpaid and due<#{p['t2_cutoff']} : status=:hold, tags+=:late",
         "T3": "put audit.unpaid = count orders where status=:unpaid\nput audit.paid = count orders where status=:paid\nput audit.shipped_total = sum total of orders where status=:shipped",
         "T4": "set? orders.lines where status=:unpaid and sku=:p03 : qty=0\nset? orders where status=:unpaid and any lines where sku=:p03 : tags+=:p03-cancelled",
         "T5": 'set orders where status=:unpaid order total desc limit 1 : status=:review, note="top"',
         "T6": f"add orders : id={p['t6_id']}, status=:unpaid, due=#{p['t6_due']}, total={p['t6_a'] + p['t6_b']:.2f}m, qty=1, tags=[], note=nil, "
               f"lines=[{{sku: :p01, qty: 2, amount: {p['t6_a']:.2f}m}}, {{sku: :p02, qty: 1, amount: {p['t6_b']:.2f}m}}]"}[task]
    return "```shuttle\n" + m + "\n```"

def selftest(sizes=(50, 500)):
    global RUN
    import tempfile; RUN = tempfile.mkdtemp()
    ok = bad = 0
    for n in sizes:
        for rep in (1, 2):
            state, p = gen(n, rep)
            assert same(from_json_obj(json.loads(to_json(state))), state) and same(weft_to_logical(W.parse_ai(to_weft(state))), state)
            assert same(weft_to_logical(store_of(state).materialize()), state)
            for task in TASKS:
                assert not same(expected(state, task, p), state) or task == "T1", (task, "no-op task")
                for arm in ARMS:
                    cell = f"{arm}-{task}-{n}-{rep}"
                    prompt(cell)
                    fb = step(cell, reference(arm, task, state, p), 1000)
                    g0 = grade(cell)["complete"]
                    step(cell, "DONE", 1000)
                    g = grade(cell)
                    if g["complete"] and g0 and g["end"] == "done": ok += 1
                    else: bad += 1; print("FAIL", cell, fb[:200])
                    # negative controls: untouched state must not be complete (unless the task is a no-op)
                    c2 = f"{arm}-{task}-{n}-{rep}"; RUN2 = RUN; RUN = tempfile.mkdtemp()
                    step(c2, "DONE", 1); neg = grade(c2)["complete"]; RUN = RUN2
                    if neg and not same(expected(state, task, p), state): bad += 1; print("FAIL negative", cell)
    # rejection paths
    RUN = tempfile.mkdtemp()
    r = [step("J-full-T1-50-1", '```json\n{"audit": {}}\n```', 1), step("J-patch-T1-50-1", '```json\n[{"op":"replace","path":"/orders/0/total","value":12.5}]\n```', 1),
         step("W-full-T1-50-1", "```weft\naudit: {unpaid: 0, paid: 0, shipped_total: 0}\norders: []\n```", 1), step("S-T1-50-1", "```shuttle\nset orders where id=1 : qty+=1\n```", 1),
         step("S-T2-50-1", "```sql\nx\n", 1)]
    for x in r: print("  ", x.split("\n")[1][:110] if "\n" in x else x[:110])
    if not all("rejected" in x or "fail" in x or "did not close" in x for x in r): bad += 1; print("FAIL rejection paths")
    bad += regressions()
    print(f"selftest: {ok} reference cells complete, {bad} failures")
    return bad == 0

def regressions():
    """Reproductions from the independent review of d4 (C4-01..04)."""
    global RUN
    import tempfile
    bad = 0
    def chk(name, cond, info=""):
        nonlocal bad
        if not cond: bad += 1; print("FAIL", name, str(info)[:200])
    state, p = gen(50, 1)
    # C4-01 S: wrong type inside audit is rejected, not applied, and grading does not crash
    RUN = tempfile.mkdtemp()
    fb = step("S-T3-50-1", '```shuttle\nput audit.unpaid = "wrong"\n```', 1)
    chk("C4-01 S audit type rejected", "rejected" in fb and "$.audit.unpaid" in fb, fb)
    step("S-T3-50-1", "DONE", 1); g = grade("S-T3-50-1"); chk("C4-01 S grading runs, not complete", g["complete"] is False, g)
    # C4-01 W: keyword where a string belongs
    RUN = tempfile.mkdtemp()
    exp = expected(state, "T5", p); v = to_weft_value(exp)
    for r in v["orders"]:
        if r["note"] == "top": r["note"] = W.K("top")
    fb = step("W-full-T5-50-1", "```weft\n" + W.emit_ai(v).rstrip("\n") + "\n```", 1)
    chk("C4-01 W keyword note rejected", "rejected" in fb and ".note" in fb, fb)
    step("W-full-T5-50-1", "DONE", 1); chk("C4-01 W not complete", grade("W-full-T5-50-1")["complete"] is False)
    # C4-01 J: impossible date
    RUN = tempfile.mkdtemp()
    fb = step("J-patch-T1-50-1", '```json\n[{"op":"replace","path":"/orders/0/due","value":"2026-99-99"}]\n```', 1)
    chk("C4-01 J impossible date rejected", "rejected" in fb and "calendar date" in fb, fb)
    # C4-02: a correct submission arriving after the budget is discarded
    RUN = tempfile.mkdtemp()
    fb = step("S-T5-50-1", reference("S", "T5", state, p), 610000); g = grade("S-T5-50-1")
    chk("C4-02 late reply discarded", g["complete"] is False and g["end"] == "time_limit" and g["seconds"] == MAX_SECONDS and g["kinds"] == ["late_discarded"], g)
    RUN = tempfile.mkdtemp()
    step("S-T5-50-1", reference("S", "T5", state, p), 599999); g = grade("S-T5-50-1")
    chk("C4-02 reply inside the budget is processed to the end", g["complete"] is True and g["kinds"] == ["accepted"], g)
    # C4-03: patch state is kept verbatim between submissions
    RUN = tempfile.mkdtemp()
    f1 = step("J-patch-T1-50-1", '```json\n[{"op":"replace","path":"/orders/0/total","value":"1.0"}]\n```', 1)
    f2 = step("J-patch-T1-50-1", '```json\n[{"op":"test","path":"/orders/0/total","value":"1.0"}]\n```', 1)
    chk("C4-03 replace then test with the same string", "applied" in f1 and "applied" in f2, f2)
    # C4-04: unterminated block is not called an output limit unless the environment says so
    RUN = tempfile.mkdtemp()
    step("S-T2-50-1", "```shuttle\nset", 1); step("S-T2-50-2", "```shuttle\nset", 1, "length")
    chk("C4-04 cause unknown", grade("S-T2-50-1")["kinds"] == ["unterminated_cause_unknown"]); chk("C4-04 cause reported", grade("S-T2-50-2")["kinds"] == ["truncated_by_output_limit"])
    print(f"regressions: {bad} failures")
    return bad

# ------------------------------------------------------------------ file-based exchange with the solver (frozen procedure)
SOLVER_RULES = ("You are the solver in an experiment. You may use ONLY the Read tool and the Write tool. No shell, no scripts, "
                "no code execution, no other tools: you must produce the submission text yourself.")
def launch_text(cell):
    f = f"{RUN}/{cell}.prompt.txt"
    os.makedirs(RUN, exist_ok=True); open(f, "w", encoding="utf-8").write(prompt(cell))
    return (SOLVER_RULES + f"\n\n1. Read the file {f} completely (if it is long, keep reading with offset until you have reached the end).\n"
            f"2. Do what it says. Write your reply — exactly in the form its PROTOCOL describes (one fenced code block, or the single word DONE) — "
            f"to the file {RUN}/{cell}.reply1.txt with the Write tool.\n3. Then answer with the single word WROTE.")

def next_turn(cell, model_ms, tool_uses, finish_reason=None):
    """Process reply k (the file the solver was told to write) and return the text to send back, or END."""
    rec = load(cell); k = len(rec["log"]) + 1
    rf = f"{RUN}/{cell}.reply{k}.txt"
    reply = open(rf, encoding="utf-8").read() if os.path.exists(rf) else "(no reply file was written)"
    fb = step(cell, reply, model_ms, finish_reason)
    rec = load(cell); rec["log"][-1]["tool_uses"] = tool_uses; rec["log"][-1]["reply_file_written"] = os.path.exists(rf)
    json.dump(rec, open(path(cell), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    if rec["end"]:
        return "END " + rec["end"]
    ff = f"{RUN}/{cell}.feedback{k}.txt"; open(ff, "w", encoding="utf-8").write(fb)
    return turn_text(cell)

def turn_text(cell):
    """Later turns are run by a FRESH solver call that reads the task file and the transcript so far
    (amendment A1: only fresh calls report their response time in this environment)."""
    rec = load(cell); k = len(rec["log"])
    tf = f"{RUN}/{cell}.transcript{k}.txt"
    parts = []
    for i, e in enumerate(rec["log"], 1):
        parts.append(f"===== YOUR REPLY {i} =====\n{e['reply'].rstrip()}\n\n===== MACHINE RESULT {i} =====\n{(e['feedback'] or '').rstrip()}\n")
    open(tf, "w", encoding="utf-8").write("\n".join(parts))
    return (SOLVER_RULES + f"\n\nYou are continuing a session. 1. Read the task file {RUN}/{cell}.prompt.txt completely (if it is long, keep reading with offset until the end).\n"
            f"2. Read the file {tf}: it holds your previous replies in this session and the machine result of each.\n"
            f"3. Write your next reply — one fenced code block, or the single word DONE, exactly as the PROTOCOL in the task file describes — "
            f"to the file {RUN}/{cell}.reply{k + 1}.txt with the Write tool. Replies used so far: {k} of {MAX_REPLIES}.\n4. Then answer with the single word WROTE.")

def cells_main():
    """All cells of the main run, in the frozen pseudo-random order."""
    cs = [f"{a}-{t}-{n}-{r}" for n in (50, 500) for a in ARMS for t in TASKS for r in (1, 2)]
    cs += [f"{a}-{t}-5000-{r}" for a in ("W-full", "S") for t in TASKS for r in (1, 2)]
    random.Random(20261111).shuffle(cs)
    return cs

if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "prompt": sys.stdout.write(prompt(sys.argv[2]))
    elif cmd == "promptfile":
        os.makedirs(RUN, exist_ok=True); f = f"{RUN}/{sys.argv[2]}.prompt.txt"; open(f, "w", encoding="utf-8").write(prompt(sys.argv[2])); print(f, os.path.getsize(f), "bytes,", open(f).read().count("\n"), "lines")
    elif cmd == "step": print(step(sys.argv[2], open(sys.argv[3], encoding="utf-8").read(), float(sys.argv[4]), sys.argv[5] if len(sys.argv) > 5 else None))
    elif cmd == "launch": print(launch_text(sys.argv[2]))
    elif cmd == "next": print(next_turn(sys.argv[2], float(sys.argv[3]), int(sys.argv[4]), sys.argv[5] if len(sys.argv) > 5 else None))
    elif cmd == "turn": print(turn_text(sys.argv[2]))
    elif cmd == "pre":            # guard before launching reply k+1: the transcript must exist and hold all k replies and results
        rec = load(sys.argv[2]); k = len(rec["log"]); tf = f"{RUN}/{sys.argv[2]}.transcript{k}.txt"
        expected = "\n".join(
            f"===== YOUR REPLY {i} =====\n{e['reply'].rstrip()}\n\n===== MACHINE RESULT {i} =====\n{(e['feedback'] or '').rstrip()}\n"
            for i, e in enumerate(rec["log"], 1)
        )
        ok = not rec["end"]
        if ok and k:
            try:
                with open(tf, encoding="utf-8") as f:
                    ok = f.read() == expected
            except (OSError, UnicodeError):
                ok = False
        print(("OK " if ok else "MISSING_OR_MISMATCH_OR_ENDED ") + sys.argv[2] + f" (replies so far: {k})"); sys.exit(0 if ok else 1)
    elif cmd == "cells": print("\n".join(cells_main()))
    elif cmd == "grade": print(json.dumps(grade(sys.argv[2]), indent=1))
    elif cmd == "selftest": sys.exit(0 if selftest() else 1)
