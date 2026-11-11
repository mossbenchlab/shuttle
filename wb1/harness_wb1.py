"""WB-1 harness (PROCEDURE-WB1-d3 §1, §3, §5).

prompt(task, arm) -> str            frozen prompt text
document(value, arm) -> str         an arm's standard emitter (used for E documents and verification)
read(text, arm) -> value            an arm's parser (raises ArmParseError / TableNotAllowed)
grade(task, arm, reply) -> dict     {"status": format|parse|mismatch|pass, "feedback": str, ...}
"""
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_sys.path.insert(0, _os.path.join(_HERE, "lib")); _sys.path.insert(0, _HERE)

import base64, json, re, sys
import weft
import weftnext as W

ARMS = ["J", "W1", "N3", "N4"]
CARD_DIR = _os.path.join(_HERE, "cards")


class ArmParseError(Exception):
    pass


class FormatViolation(Exception):
    pass


# ------------------------------------------------------------------ J: JSON with type wrappers
_WRAP = {"$dec", "$dt", "$kw"}


def _to_j(v):
    if isinstance(v, dict):
        return {k: _to_j(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_to_j(x) for x in v]
    if isinstance(v, weft.Decimal):
        return {"$dec": v.text}
    if isinstance(v, weft.WeftDate):
        return {"$dt": W.canonical_text(v).strip()[1:]}
    if isinstance(v, weft.Keyword):
        return {"$kw": v.name}
    return v


def _no_float(s):
    raise ArmParseError(f"numbers with a fraction or exponent are not allowed: {s}")


def _pairs(ps):
    seen = {}
    for k, v in ps:
        if k in seen:
            raise ArmParseError(f"duplicate key {k!r}")
        seen[k] = v
    if any(k.startswith("$") for k in seen):
        if len(seen) != 1 or next(iter(seen)) not in _WRAP:
            raise ArmParseError(f"bad type wrapper {json.dumps(list(seen))}: a wrapper is exactly one of "
                                "{\"$dec\": ...}, {\"$dt\": ...}, {\"$kw\": ...}")
        (k, s), = seen.items()
        if not isinstance(s, str):
            raise ArmParseError(f"{k} needs a string value")
        # WBPF-01: the wrapper string must be exactly the canonical spelling of one scalar
        # (nothing may be dropped, e.g. a trailing "; comment").
        try:
            if k == "$dec":
                x = weft.Decimal(s)
                ok = isinstance(x, weft.Decimal) and W.canonical_text(x).strip() == s + "m"
            elif k == "$dt":
                x = weft.parse("#" + s)
                ok = isinstance(x, weft.WeftDate) and W.canonical_text(x).strip() == "#" + s
            else:
                x = weft.parse(":" + s)
                ok = isinstance(x, weft.Keyword) and x.name == s and W.canonical_text(x).strip() == ":" + s
        except (ValueError, weft.WeftError):
            ok = False
        if not ok:
            raise ArmParseError(f"not a valid {k} value: {s!r}")
        return x
    return seen


def _j_read(text):
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_float=_no_float,
                          parse_constant=lambda c: _no_float(c))
    except ArmParseError:
        raise
    except json.JSONDecodeError as e:
        raise ArmParseError(f"line {e.lineno}, column {e.colno}: {e.msg}")


# ------------------------------------------------------------------ per arm
def document(v, arm):
    if arm == "J":
        return json.dumps(_to_j(v), indent=2, ensure_ascii=False) + "\n"
    if arm == "W1":
        return weft.format_value(v) + ("" if weft.format_value(v).endswith("\n") else "\n")
    if arm == "N3":
        return W.emit_ai(v, tables=False)
    if arm == "N4":
        return W.emit_ai(v)
    raise KeyError(arm)


def read(text, arm):
    if arm == "J":
        return _j_read(text)
    if arm == "W1":
        try:
            return W.from_v1(weft.parse(text))
        except weft.WeftError as e:
            raise ArmParseError(str(e))
    try:
        return W.parse_ai(text, allow_tables=(arm == "N4"))
    except W.WeftNextTableNotAllowed as e:
        raise FormatViolation(f"table syntax is not allowed in this format ({e})")
    except W.WeftNextError as e:
        raise ArmParseError(str(e))


# ------------------------------------------------------------------ prompt
PREAMBLE = """You are taking part in a test of data formats. You will write one data document in the format described by the FORMAT CARD below. Follow the card exactly; do not use any other data format.

Reply with the complete document inside exactly one fenced code block (a line ``` before it and a line ``` after it). Write nothing else outside the code block.
"""


def card(arm):
    return open(f"{CARD_DIR}/{arm}.md", encoding="utf-8").read()


def expected(task):
    return W.decode(base64.b64decode(task["expected_wft2"]))


def base(task):
    return W.decode(base64.b64decode(task["base_wft2"]))


def prompt(task, arm):
    parts = [PREAMBLE, "=== FORMAT CARD ===\n" + card(arm).rstrip() + "\n=== END OF FORMAT CARD ===\n"]
    if task["kind"] == "G":
        parts.append("SOURCE DATA:\n\n" + task["source"].rstrip() + "\n")
        parts.append("TASK:\n\n" + task["instruction"] + "\n")
    else:
        parts.append("DOCUMENT (in the format of the card):\n\n```\n" + document(base(task), arm) + "```\n")
        parts.append("TASK:\n\n" + task["instruction"] + " Reply with the complete changed document.\n")
    return "\n".join(parts)


# ------------------------------------------------------------------ grading
_FENCE = re.compile(r"^```[^\n`]*$", re.M)


def extract(reply):
    marks = list(_FENCE.finditer(reply))
    if len(marks) != 2:
        raise FormatViolation(f"expected exactly one fenced code block, found {len(marks) // 2 if len(marks) % 2 == 0 else 'an unclosed'} block(s)")
    a, b = marks
    body = reply[a.end() + 1:b.start()]
    return body


FB_TAIL = "\n\nReply with the complete corrected document in exactly one fenced code block, and nothing else."
FB_MISMATCH = "The document parses, but its value is not the value the task asks for."


# Exceptions that a submission can cause while being read or checked (WBPF-02). Anything else
# raised by grade() is a harness fault: it propagates and the session is recorded as an infra event.
SUBMISSION_ERRORS = (W.WeftNextError, weft.WeftError, ValueError, RecursionError, UnicodeError,
                     OverflowError, TypeError)


def grade(task, arm, reply):
    try:
        body = extract(reply)
        v = read(body, arm)
        W.check_value(v)                              # d5 limits, the same for every arm
        b = W.encode(v)
    except FormatViolation as e:
        return {"status": "format", "detail": str(e), "feedback": f"FORMAT ERROR: {e}." + FB_TAIL}
    except ArmParseError as e:
        return {"status": "parse", "detail": str(e), "feedback": f"PARSE ERROR: {e}" + FB_TAIL}
    except SUBMISSION_ERRORS as e:
        msg = f"invalid document ({type(e).__name__}): {str(e)[:300]}"
        return {"status": "parse", "detail": msg, "feedback": f"PARSE ERROR: {msg}" + FB_TAIL}
    vb = base64.b64encode(b).decode()
    if b == W.encode(expected(task)):
        return {"status": "pass", "detail": "", "feedback": None, "value_b64": vb}
    return {"status": "mismatch", "detail": "", "feedback": FB_MISMATCH + FB_TAIL, "value_b64": vb}


def table_use(reply):
    """N4 reporting (§6, WBPF-05): {"used": table syntax met (also when the parse failed),
    "headers": outer table headers met, "lists": lists built from table syntax (outer tables and
    nested table cells; None unless the parse succeeded), "parsed": the submission parsed as N4}."""
    try:
        body = extract(reply)
    except FormatViolation:
        return {"used": False, "headers": 0, "lists": None, "parsed": False}
    try:
        W.parse_ai(body)
        parsed = True
    except SUBMISSION_ERRORS:
        parsed = False
    h = W.tables_used()
    return {"used": h > 0, "headers": h, "lists": W.table_lists() if parsed else None, "parsed": parsed}
