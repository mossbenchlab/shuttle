"""Exploratory: let the solver write Shuttle transactions for the WB-1 edit tasks."""
import sys, json, re, os, base64
import os as _os; _R = _os.path.dirname(_os.path.abspath(__file__)); sys.path.insert(0, _R); sys.path.insert(0, _R + "/wb1")
import shuttle as SH, weftnext as W, harness_wb1 as H
from schemas_wb1 import SCHEMAS
SH.TYPES["map"]=dict
SCHEMAS["release"]="doc version:str date:dt summary:str changes:list<map> contributors:list<str> signed:bool"
T={t["id"]:t for t in json.load(open(_R + "/wb1/tasks-wb1.json", encoding="utf-8"))["tasks"]}
HERE=_R

def store_for(tid):
    st=SH.Store(SH.Schema(SCHEMAS[tid.split("-")[1]])); st.load(H.base(T[tid])); return st

def prompt(tid):
    st=store_for(tid)
    sch=SCHEMAS[tid.split("-")[1]]
    # a glimpse of the data: 2 rows per table + doc fields (the AI does not get the whole document)
    glimpse=[]
    for name,rows in st.rows.items():
        t=st.schema.tables[name]
        glimpse.append(f"{name}: {len(rows)} rows, e.g.")
        for r in rows[:2]:
            glimpse.append("  "+W.emit_ai(st._row_out(t,r)).strip().replace("\n"," "))
    if st.doc:
        glimpse.append("doc: "+W.emit_ai(st.doc).strip().replace("\n"," ")[:600])
    return (open(f"{HERE}/CARD.md", encoding="utf-8").read()+"\nSCHEMA:\n"+sch+"\n\nCURRENT STATE (glimpse):\n"+"\n".join(glimpse)+
            "\n\nTASK:\n"+T[tid]["instruction"]+"\n")

def extract(reply):
    m=re.findall(r"^```[^\n]*\n(.*?)^```",reply,re.M|re.S)
    return m[0] if len(m)==1 else None

cmd=sys.argv[1]
if cmd=="prompt":
    tid=sys.argv[2]; p=prompt(tid)
    os.makedirs(f"{HERE}/run",exist_ok=True); open(f"{HERE}/run/{tid}.prompt.md","w", encoding="utf-8").write(p)
    print(f"Read the file {HERE}/run/{tid}.prompt.md with your Read tool once, in full, and follow it. Write your reply to the file {HERE}/run/{tid}.r1.md with your Write tool. Use no other tools. After writing, reply only: saved")
elif cmd=="grade":
    tid, r = sys.argv[2], int(sys.argv[3])
    st=store_for(tid)
    # replay earlier successful? no: each round is the whole corrected transaction on the base state
    reply=open(f"{HERE}/run/{tid}.r{r}.md", encoding="utf-8").read()
    body=extract(reply)
    if body is None:
        print("FORMAT: need exactly one fenced code block"); sys.exit()
    rec=st.execute(body)
    ok=W.same(st.materialize(), H.expected(T[tid]))
    json.dump({"task":tid,"round":r,"tx":body,"receipt":rec,"pass":ok,"tx_chars":len(body)}, open(f"{HERE}/run/{tid}.r{r}.json","w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(rec); print("PASS" if ok else "WRONG VALUE (state differs from expected)")
    if not ok:
        fb = rec if rec.startswith("fail") else "The transaction applied, but the resulting state is not what the task asks for. Re-read the task and reply with the whole corrected transaction."
        print("---- feedback to send:"); print(fb + f"\n\nWrite your whole corrected transaction to the file {HERE}/run/{tid}.r{r+1}.md with your Write tool, then reply only: saved")
