"""Shuttle v6 r10 — an operation language and executor over Weft next values (prototype).

The state is a log of transactions over a typed, schema-declared store. The AI writes one
transaction per message: a few lines of operations addressed by conditions, never a document.
The executor type-checks, evaluates, applies all-or-nothing, checks expectations, and returns a
short receipt. Documents are derived views (materialize()).

Grammar (one statement per line; `;` starts a comment):

  tx <id> [at <version>]                     transaction header (optional; one per message)
  set <path> where <cond> : <col>=<v>, ...   update every matching row (one row or thousands)
  set <path> where <cond> : <col>+=<v>       relative: numbers add/subtract, lists append/remove (also -=)
  set <path> where <cond> : <col>|=<v>       lists: add only elements not present (repeat-safe)
  set/del <path> where <cond> order <col> [asc|desc] limit n : ...   affect only the first n rows in that order (ties are an error)
  add <path> [after where <cond>] : <v>, <v>, ...   append (or insert after a match) a row, values in column order
  add <path> [after where <cond>] : <col>=<v>, ...  same, by name (missing columns take defaults)
  del <path> where <cond>                    delete matching rows
  set? / del?                                same, but matching no row is not an error (receipt shows set:0)
  <value> may be an aggregate: count <path> [where ..] | sum <col> of <path> [where ..]  (computed when the statement runs;
      sum needs an int or dec column, skips nil, and returns 0 / 0m of the column's type for an empty selection)
  conditions on a parent: any <child> where <cond> | none <child> where <cond>
  sum <col> of <path> [where <cond>]       query
  put <doc-field> = <v>                      set a scalar field of the document (non-tabular part)
  expect <agg> <cmp> <v>                     postcondition, checked after the whole transaction
  count <path> [where <cond>]                query (allowed in a read-only message)
  show <path> [where <cond>] [limit n] [cols a,b] [order <col> [asc|desc]]
  get <path> where <cond>                    exactly one row

  <path>  = table | table.child            (child rows are addressed through their parent:
                                            `set orders.lines where id=7006 and sku=:p03 : qty=3`
                                            where `id` is a column of orders and `sku` of lines)
  <cond>  = <term> (and|or <term>)* | not <term> | ( <cond> )
  <term>  = <col> (= | != | < | <= | > | >=) <v> | <col> in [v, v] | <col> has <v> | missing <col>
  <agg>   = count <path> [where <cond>] | sum <col> of <path> [where <cond>] | <path>.<col> where <cond>
  <v>     = any Weft next scalar: 42  1.50m  "text"  :kw  #2026-11-05  true  nil  [a, b]
"""
import sys, re, hashlib
import os as _os; _R = _os.path.dirname(_os.path.abspath(__file__)); sys.path.insert(0, _R)
import weft
import weftnext as W
from weftnext import K, S

# ------------------------------------------------------------------ schema
class Col:
    def __init__(self, name, typ, default=None, has_default=False):
        self.name, self.typ, self.default, self.has_default = name, typ, default, has_default

class Agg:
    """An aggregate used where a value is expected; resolved by the store when the statement runs."""
    __slots__ = ("kind", "col", "path", "cond")
    def __init__(self, kind, col, path, cond):
        self.kind, self.col, self.path, self.cond = kind, col, path, cond
    def text(self):
        return f"count {self.path}" if self.kind == "count" else f"sum {self.col} of {self.path}"

class Table:
    def __init__(self, name, cols, key, parent=None):
        self.name, self.cols, self.key, self.parent = name, cols, key, parent    # key: list of col names
        self.children = {}
    def col(self, n):
        for c in self.cols:
            if c.name == n:
                return c
        return None

TYPES = {"int": int, "dec": weft.Decimal, "str": str, "bool": bool, "kw": K, "dt": weft.WeftDate, "sym": S, "map": dict}

def type_ok(typ, v):
    if typ.startswith("list<"):
        inner = typ[5:-1]
        return isinstance(v, list) and all(type_ok(inner, x) for x in v)
    if typ.endswith("?"):
        return v is None or type_ok(typ[:-1], v)
    t = TYPES[typ]
    if t is int:
        return isinstance(v, int) and not isinstance(v, bool)
    return isinstance(v, t)

class Schema:
    """doc: scalar fields {name: type}; tables: {name: Table}. Declared in a small text form:
         doc service:str version:str debug:bool
         table orders key id : id:int placed:dt status:kw priority:int tags:list<kw>
         table orders.lines : sku:kw qty:int unit_price:dec
    """
    def __init__(self, text):
        self.doc, self.tables = {}, {}
        for raw in text.splitlines():
            line = raw.split(";")[0].strip()
            if not line:
                continue
            head, _, body = line.partition(":")
            parts = head.split()
            if parts[0] == "doc":
                for spec in (head[3:] + ":" + body).strip().split():
                    n, t = spec.split(":")
                    self.doc[n] = t
                continue
            if parts[0] != "table":
                raise ValueError(f"schema: {line}")
            name = parts[1]
            key = []
            if "key" in parts:
                key = parts[parts.index("key") + 1].split(",")
            cols = []
            for spec in body.split():
                n, t = spec.split(":", 1)
                dflt, hd = None, False
                if "=" in t:
                    t, d = t.split("=", 1)
                    dflt, hd = _scalar(d, 0, line), True
                cols.append(Col(n, t, dflt, hd))
            if "." in name:
                pname, cname = name.split(".", 1)
                p = self.tables[pname]
                t = Table(cname, cols, key, parent=p)
                p.children[cname] = t
                self.tables[name] = t
            else:
                self.tables[name] = Table(name, cols, key)

# ------------------------------------------------------------------ lexer
_TOK = re.compile(r'''\s*(?:(?P<str>"(?:\\.|[^"\\])*")|(?P<dt>#\d{4}-\d\d-\d\d(?:T\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)?)?)|(?P<kw>:[^\s:,(){}\[\]"=<>!]+)|(?P<op>\+=|-=|\|=|<=|>=|!=|=|<|>|:|,|\(|\)|\[|\]|\{|\})|(?P<atom>[^\s:,(){}\[\]"=<>!]+(?:\[\d+\][^\s:,(){}\[\]"=<>!]*)*(?:=(?=[^=]))?))''')

def _lex(line):
    out, i = [], 0
    s = line.rstrip()
    while i < len(s):
        m = _TOK.match(s, i)
        if not m or m.end() == i:
            if s[i:].lstrip().startswith('"'):
                raise ShuttleError("unterminated string (missing closing quote)")
            raise ShuttleError(f"cannot read {s[i:i+12]!r}")
        i = m.end()
        if m.group("str"):
            out.append(("str", m.group("str")))
        elif m.group("dt"):
            out.append(("atom", m.group("dt")))
        elif m.group("kw"):
            out.append(("atom", m.group("kw")))
        elif m.group("op"):
            out.append(("op", m.group("op")))
        else:
            a = m.group("atom")
            if a.endswith(("+=", "-=", "|=")):       # `col+=` glued
                out.append(("atom", a[:-2])); out.append(("op", a[-2:]))
            elif a.endswith("="):                    # `col=` glued
                out.append(("atom", a[:-1])); out.append(("op", "="))
            else:
                out.append(("atom", a))
    return out

def _strip_comment(s):
    """Remove a `;` comment that is outside string quotes."""
    out, inq, i = [], False, 0
    while i < len(s):
        c = s[i]
        if inq:
            out.append(c)
            if c == "\\" and i + 1 < len(s):
                out.append(s[i + 1]); i += 2; continue
            if c == '"':
                inq = False
        else:
            if c == ";":
                break
            if c == '"':
                inq = True
            out.append(c)
        i += 1
    return "".join(out)


def _statements(text):
    """Yield (first line number, statement text). A statement continues onto the next line while a
    string quote is open, so a multi-line string may be written with real line breaks."""
    buf, start, inq = [], None, False
    for no, raw in enumerate(text.splitlines(), 1):
        if start is None:
            start = no
        buf.append(raw)
        j = 0
        line = raw if inq else _strip_comment(raw)
        while j < len(line):
            c = line[j]
            if inq and c == "\\":
                j += 2; continue
            if c == '"':
                inq = not inq
            j += 1
        if not inq:
            yield start, "\n".join(buf)
            buf, start = [], None
    if buf:
        yield start, "\n".join(buf) + "\x00"       # unterminated string: the lexer reports it


class ShuttleError(Exception):
    def __init__(self, msg, line=None, hint=None):
        super().__init__(msg)
        self.msg, self.line, self.hint = msg, line, hint

def _scalar(text, line, src):
    if text == "nil" or text == "null":
        return None
    try:
        if text.startswith(("[", "{")):
            return W.parse_ai(text + "\n")
        return W._atom(text, line, src)
    except W.WeftNextError as e:
        hint = None
        if ":" in text[1:] and not text.startswith((":", "#", "\"")):
            a, b = text.split(":", 1)
            hint = f"did you mean `{a}={b}`? (column=value uses `=`; a colon only starts a keyword like :paid)"
        raise ShuttleError(f"not a value: {text!r}", line, hint=hint)

# ------------------------------------------------------------------ parser
KEYWORDS = {"where", "and", "or", "not", "in", "has", "missing", "after", "limit", "cols", "of", "at"}

class P:
    def __init__(self, toks, line, src):
        self.t, self.i, self.line, self.src = toks, 0, line, src
    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else (None, None)
    def take(self, kind=None, text=None):
        k, v = self.peek()
        if k is None or (kind and k != kind) or (text and v != text):
            raise ShuttleError(f"expected {text or kind}, got {v!r}", self.line)
        self.i += 1
        return v
    def at_end(self):
        return self.i >= len(self.t)
    def embedded_query(self):
        """After a statement has FAILED: does it look like `<col> = get <table> ...` (a query written
        where a value belongs)? `get`/`show` alone are legal symbol values, so this is never used to reject."""
        for i in range(1, len(self.t) - 1):
            k, v = self.t[i]
            pk, pv = self.t[i - 1]
            nk, nv = self.t[i + 1]
            if (k == "atom" and v in ("get", "show") and nk == "atom" and nv not in KEYWORDS and nv not in ("order", "asc", "desc")
                    and ((pk == "op" and pv in ("=", "!=", "<", "<=", ">", ">=")) or (pk == "atom" and pv == "in"))):
                return v
        return None
    def colon(self):
        """The `:` that starts the values of set/add. A glued `:qty=0` (no space) is only whitespace
        away from `: qty=0`, so it is accepted: the colon is consumed and `qty` stays as the column."""
        k, v = self.peek()
        if k == "op" and v == ":":
            self.i += 1
            return
        if k == "atom" and v.startswith(":") and len(v) > 2 and v[-1] in "+-|" and self.peek(1) == ("op", "="):
            self.t[self.i] = ("atom", v[1:-1]); self.t[self.i + 1] = ("op", v[-1] + "=")     # glued `:tags+=`
            return
        if k == "atom" and v.startswith(":") and len(v) > 1 and self.peek(1)[0] == "op" and self.peek(1)[1] in ("=", "+=", "-=", "|="):
            self.t[self.i] = ("atom", v[1:])
            return
        raise ShuttleError(f"expected `:` before the values, got {v!r}", self.line,
                           hint="write `where <cond> : col=value, ...` (a space-separated colon, then the assignments)")
    def column(self):
        """A column name in an assignment. Keywords are values, so a `:name` here is a mistake."""
        k, v = self.peek()
        if k == "atom" and v.startswith(":"):
            name = v[1:].rstrip("+-|")
            raise ShuttleError(f"{v!r} is a keyword value; a column name has no colon", self.line,
                               hint=f"write `{name}=...` (column names: plain names; keyword values: :name)")
        if k == "op" and v == ":":
            raise ShuttleError("expected a column name, got ':'", self.line,
                               hint="separate the assignments of one row with commas, in ONE statement: `: status=:review, note=\"top\"` "
                                    "(a second statement would select its rows again, so a `limit 1` could pick a different row)")
        if k != "atom":
            raise ShuttleError(f"expected a column name, got {v!r}", self.line)
        self.i += 1
        return v
    def value(self):
        k, v = self.peek()
        if k == "op" and v == "{":
            self.i += 1
            m = {}
            while not (self.peek()[0] == "op" and self.peek()[1] == "}"):
                key = self.take("atom")
                if key.startswith(":"):
                    key = key[1:]
                if not W._name_ok("kw", key):
                    raise ShuttleError(f"{key!r} is not a valid map key (a key is a name like total or x-y, not a number or punctuation)", self.line)
                nk, nv = self.peek()
                if nk == "atom" and nv.startswith(":") and len(nv) > 1:
                    raise ShuttleError(f"in a map write a space after the colon: `{key}: {nv[1:]}`", self.line)
                self.take("op", ":")
                if key in m:
                    raise ShuttleError(f"duplicate key {key!r} in map", self.line)
                m[key] = self.value()
                if self.peek() == ("op", ","):
                    self.i += 1
                elif self.peek()[0] is None:
                    raise ShuttleError("unterminated map", self.line)
            self.i += 1
            return m
        if k == "op" and v == "[":
            self.i += 1
            xs = []
            while not (self.peek()[0] == "op" and self.peek()[1] == "]"):
                if self.peek()[0] is None:
                    raise ShuttleError("unterminated list", self.line)
                xs.append(self.value())
                if self.peek() == ("op", ","):
                    self.i += 1
            self.i += 1
            return xs
        if k == "str":
            self.i += 1
            # a string written across lines: real line breaks become the newline character
            return _scalar(v.replace("\n", "\\n").replace("\t", "\\t"), self.line, self.src)
        if k == "atom" and v in ("count", "sum") and self.peek(1)[0] == "atom":
            return self.aggregate()
        if k == "atom":
            self.i += 1
            return _scalar(v, self.line, self.src)
        if k == "op" and v == ":":
            raise ShuttleError("expected a value, got ':'", self.line,
                               hint="in a map write `key: value` with one colon and a space; a keyword value keeps its own colon: `sku: :p01`")
        raise ShuttleError(f"expected a value, got {v!r}", self.line)
    def aggregate(self):
        """`count <path> [where <cond>]` or `sum <col> of <path> [where <cond>]` used as a value:
        the executor computes it when the statement runs (v6)."""
        kind = self.take("atom")
        if kind == "count":
            path = self.take("atom")
            return Agg("count", None, path, self.where_opt())
        col = self.take("atom"); self.take("atom", "of"); path = self.take("atom")
        return Agg("sum", col, path, self.where_opt())
    # conditions
    def cond(self):
        left = self.term_or_not()
        while self.peek() == ("atom", "and") or self.peek() == ("atom", "or"):
            op = self.take()[0:3]
            right = self.term_or_not()
            left = (op.strip(), left, right)
        return left
    def term_or_not(self):
        if self.peek() == ("atom", "not"):
            self.i += 1
            return ("not", self.term_or_not())
        if self.peek() == ("op", "("):
            self.i += 1
            c = self.cond()
            self.take("op", ")")
            return c
        if self.peek() == ("atom", "missing"):
            self.i += 1
            return ("missing", self.take("atom"))
        if self.peek()[1] in ("any", "none") and self.peek(1)[0] == "atom" and self.peek(2) == ("atom", "where"):
            q = self.take("atom"); child = self.take("atom"); self.take("atom", "where")
            return (q, child, self.cond())                    # `any lines where sku=:p03` (v6)
        col = self.take("atom")
        k, v = self.peek()
        if col == "true" and not (k == "op" and v in ("=", "!=", "<", "<=", ">", ">=")) and not (k == "atom" and v in ("in", "has")):
            return ("true",)                                  # `where true`: every row
        if k == "op" and v in ("=", "!=", "<", "<=", ">", ">="):
            self.i += 1
            return (v, col, self.value())
        if k == "atom" and v in ("in", "has"):
            self.i += 1
            return (v, col, self.value())
        raise ShuttleError(f"expected a comparison after {col!r}", self.line)
    def where_opt(self):
        if self.peek() == ("atom", "where"):
            self.i += 1
            return self.cond()
        return None

# ------------------------------------------------------------------ value comparison
def _days_from_civil(y, m, d):
    y -= m <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468

def _dkey(d):
    """Ordering key of a date: the instant (UTC when an offset is given; otherwise as written).
    Dates without time and dates with time are never ordered against each other (see _ord_fn)."""
    mins = (_days_from_civil(d.year, d.month, d.day) * 24 + d.hour) * 60 + d.minute - (d.tz_offset_minutes or 0)
    return (mins * 60 + d.second, d.nano)

def _dsame(a, b):
    return (a.year, a.month, a.day, a.has_time, a.hour, a.minute, a.second, a.nano, a.tz_offset_minutes) == \
           (b.year, b.month, b.day, b.has_time, b.hour, b.minute, b.second, b.nano, b.tz_offset_minutes)

def _sort_key(col, line):
    """Sort key for `order <col>`: nil counts as the smallest value (first in asc, last in desc);
    numbers / dates / strings / keywords compare within their kind; a column mixing kinds is an error."""
    from decimal import Decimal as D
    seen = []
    def key(v):
        if v is None:
            return (0, 0)
        if isinstance(v, bool):
            k = (1, int(v))
        elif isinstance(v, int):
            k = (2, v)
        elif isinstance(v, weft.Decimal):
            k = (2, D(v.text))
        elif isinstance(v, weft.WeftDate):
            k = (3 if not v.has_time else 6, _dkey(v))       # dates and times are different kinds for ordering
        elif isinstance(v, str):
            k = (4, v)
        elif isinstance(v, (K, S)):
            k = (5, v.name)
        else:
            raise ShuttleError(f"cannot order by {col!r}: lists and maps have no order", line)
        if seen and seen[0] != k[0]:
            raise ShuttleError(f"cannot order by {col!r}: it mixes kinds of values", line)
        if not seen:
            seen.append(k[0])
        return k
    return key

def _dec_add(*terms):
    """Exact sum of ints / weft Decimals: the precision is set from the operands so nothing is
    rounded; an inexact result (impossible for addition at that precision) is an error, never a
    silently changed value. Returns a Python Decimal."""
    import decimal
    ds = [decimal.Decimal(t.text if isinstance(t, weft.Decimal) else str(t)) for t in terms]
    digits = sum(len(d.as_tuple().digits) + abs(d.as_tuple().exponent) for d in ds) + 2
    with decimal.localcontext() as ctx:
        ctx.prec = max(28, digits)
        ctx.traps[decimal.Inexact] = True
        ctx.traps[decimal.Rounded] = True
        tot = decimal.Decimal(0)
        for d in ds:
            tot = tot + d
    return tot

def _dec_text(d):
    """Plain (non-scientific) text of a Python Decimal, as Weft writes decimals."""
    s = format(d, "f")
    return s

def _eq_fn(const):
    """Equality against a constant with the same result as W.same (canonical-binary identity), but
    with the constant normalised once and a native comparison per row."""
    if const is None:
        return lambda v: v is None
    if isinstance(const, bool):
        return lambda v: isinstance(v, bool) and v == const
    if isinstance(const, int):
        return lambda v: isinstance(v, int) and not isinstance(v, bool) and v == const
    if isinstance(const, str):
        return lambda v: isinstance(v, str) and v == const
    if isinstance(const, K):
        name = const.name
        return lambda v: isinstance(v, K) and v.name == name
    if isinstance(const, S):
        name = const.name
        return lambda v: isinstance(v, S) and v.name == name
    if isinstance(const, weft.Decimal):
        txt = const.text
        return lambda v: isinstance(v, weft.Decimal) and v.text == txt
    if isinstance(const, weft.WeftDate):
        return lambda v: isinstance(v, weft.WeftDate) and _dsame(v, const)
    enc = W._encode(const)                              # lists, maps, anything else: canonical bytes
    return lambda v: W._encode(v) == enc

def _ord_fn(op, const, line):
    """Ordering comparison `v <op> const`. A nil row value satisfies no ordering comparison (the row is
    simply not matched); a nil constant (`x < nil`) is an error. Mixed int/dec compare numerically;
    dates compare as instants (UTC when an offset is given); a kind mismatch is an error."""
    from decimal import Decimal as D
    import operator
    f = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}[op]
    if const is None:                                   # SV5-03 r2: rejected when the condition is compiled
        raise ShuttleError(f"cannot use `{op} nil`; to test for nil write `missing <col>` or `<col> != nil`", line)
    if isinstance(const, bool):
        raise ShuttleError(f"cannot use `{op}` with true/false", line)
    if isinstance(const, int):
        def cmp(v):
            if v is None:
                return False
            if isinstance(v, int) and not isinstance(v, bool):
                return f(v, const)
            if isinstance(v, weft.Decimal):
                return f(D(v.text), const)
            raise ShuttleError(f"cannot compare {type(v).__name__} with int", line)
        return cmp
    if isinstance(const, weft.Decimal):
        dc = D(const.text)
        def cmp(v):
            if v is None:
                return False
            if isinstance(v, weft.Decimal):
                return f(D(v.text), dc)
            if isinstance(v, int) and not isinstance(v, bool):
                return f(v, dc)
            raise ShuttleError(f"cannot compare {type(v).__name__} with Decimal", line)
        return cmp
    if isinstance(const, weft.WeftDate):
        k = _dkey(const)
        def cmp(v):
            if v is None:
                return False
            if isinstance(v, weft.WeftDate):
                if v.has_time != const.has_time:            # found by a small-model solver (L6.h): mixing silently misplaced the boundary days
                    raise ShuttleError(("a date without time cannot be ordered against a time: the column holds " +
                                        ("dates like #2026-03-01; write the bound as a date too" if not v.has_time else
                                         "times like #2026-03-01T09:00:00Z; write the bound with a time too")), line)
                return f(_dkey(v), k)
            raise ShuttleError(f"cannot compare {type(v).__name__} with WeftDate", line)
        return cmp
    if isinstance(const, str):
        def cmp(v):
            if v is None:
                return False
            if isinstance(v, str):
                return f(v, const)
            raise ShuttleError(f"cannot compare {type(v).__name__} with str", line)
        return cmp
    raise ShuttleError(f"cannot use `{op}` with a {type(const).__name__} (lists, maps and symbols have no order)", line)

# ------------------------------------------------------------------ store
class Store:
    def __init__(self, schema: Schema):
        self.schema = schema
        self.doc = {}
        self.rows = {name: [] for name, t in schema.tables.items() if t.parent is None}
        self.version = 0
        self.vid = "0" * 12                # version identifier: chained hash of committed transactions
        self.log = []                      # committed transactions
        self.receipts = {}                 # tx id -> receipt (idempotency)
        self.index = {}                    # table name -> {key tuple: row} (top-level tables with a key)
        self._undo = None                  # list of callables that revert mutations, newest last

    # ---- load / materialize (documents are derived views)
    def load(self, value):
        """Load a Weft value shaped like {doc fields..., table: [rows...]}."""
        for k, v in value.items():
            if k in self.schema.doc:
                self.doc[k] = v
            elif k in self.rows:
                self.rows[k] = [self._row_in(self.schema.tables[k], r) for r in v]
            else:
                raise ShuttleError(f"load: unknown field {k!r}")
        self._reindex()
    def _key_of(self, t, row):
        return tuple(W._encode(row[c]) for c in t.key)
    def _reindex(self):
        self.index = {}
        for name, rows in self.rows.items():
            t = self.schema.tables[name]
            if t.key:
                idx = {}
                for r in rows:
                    k = self._key_of(t, r)
                    if k in idx:
                        raise ShuttleError(f"load: duplicate key in {name}")
                    idx[k] = r
                self.index[name] = idx
    # ---- mutation primitives (every change goes through these so it can be undone)
    def _mut_set(self, container, key, value):
        had, old = (key in container) if isinstance(container, dict) else True, container[key] if (isinstance(container, list) or key in container) else None
        container[key] = value
        self._undo.append((container, key, had, old))      # undone by _rollback without a closure
    def _mut_cell(self, row, col, value):
        """Hot path of bulk `set`: the column exists in the row."""
        self._undo.append((row, col, True, row[col]))
        row[col] = value
    def _mut_insert(self, lst, i, row):
        lst.insert(i, row)
        self._undo.append(lambda: lst.pop(i))
    def _mut_delete(self, lst, i):
        row = lst[i]
        del lst[i]
        self._undo.append(lambda: lst.insert(i, row))
        return row
    def _idx_add(self, name, t, row):
        if t.key and name in self.index:
            k = self._key_of(t, row)
            self.index[name][k] = row
            self._undo.append(lambda: self.index[name].pop(k, None))
    def _idx_del(self, name, t, row):
        if t.key and name in self.index:
            k = self._key_of(t, row)
            self.index[name].pop(k, None)
            self._undo.append(lambda: self.index[name].__setitem__(k, row))
    def _row_in(self, t, r):
        row = {}
        for c in t.cols:
            if c.name in t.children:
                row[c.name] = [self._row_in(t.children[c.name], x) for x in r.get(c.name, [])]
            else:
                row[c.name] = r.get(c.name, c.default)
        return row
    def materialize(self):
        out = dict(self.doc)
        for name, rows in self.rows.items():
            out[name] = [self._row_out(self.schema.tables[name], r) for r in rows]
        return out
    def _row_out(self, t, r):
        o = {}
        for c in t.cols:
            if c.name in t.children:
                o[c.name] = [self._row_out(t.children[c.name], x) for x in r[c.name]]
            else:
                o[c.name] = r[c.name]
        return o
    def digest(self):
        return hashlib.sha256(W._encode(self.materialize())).hexdigest()[:12]

    # ---- evaluation
    def _eval(self, c, row, parent_row, t, line):
        return self._compile(c, t, line)(row, parent_row)

    # ---- condition compiler: a condition is turned into one Python closure per statement, so the
    # per-row work is a few dict lookups and native comparisons (no re-encoding of either side).
    def _compile(self, c, t, line):
        op = c[0]
        if op == "true":
            return lambda row, pr: True
        if op in ("and", "or"):
            l, r = self._compile(c[1], t, line), self._compile(c[2], t, line)
            if op == "and":
                return lambda row, pr: l(row, pr) and r(row, pr)
            return lambda row, pr: l(row, pr) or r(row, pr)
        if op == "not":
            f = self._compile(c[1], t, line)
            return lambda row, pr: not f(row, pr)
        if op in ("any", "none"):
            child = c[1]
            if child not in t.children:
                raise ShuttleError(f"`{op} {child} where ...`: {t.name} has no child table {child!r}", line,
                                   hint=("children: " + ", ".join(t.children)) if t.children else f"{t.name} has no child tables")
            f = self._compile(c[2], t.children[child], line)
            if op == "any":
                return lambda row, pr: any(f(ch, row) for ch in row[child])
            return lambda row, pr: not any(f(ch, row) for ch in row[child])
        col = c[1]
        if col in t.children:
            raise ShuttleError(f"{col!r} is a child table; test its rows with `any {col} where <cond>` (or `none {col} where ...`)", line)
        if len(c) > 2 and isinstance(c[2], Agg):
            raise ShuttleError(f"an aggregate ({c[2].text()}) cannot be used inside a condition", line)
        if op == "in" and any(isinstance(x, Agg) for x in c[2]):
            raise ShuttleError("an aggregate cannot be used inside a condition", line)
        in_row = t.col(col) is not None
        par = t.parent if isinstance(t.parent, Table) else (self.schema.tables.get(t.parent) if t.parent else None)
        in_parent = par is not None and par.col(col) is not None
        if not in_row and not in_parent:
            if par is not None:
                plain = col.split(".")[-1]
                if "." in col and par.col(plain) is not None and t.col(plain) is not None:
                    fix = (f"`{plain}` here means the {t.name} column (it hides the parent's `{plain}`); the parent's `{plain}` cannot be "
                           f"tested from {t.name} — select the parent rows first (e.g. `set {par.name} where {plain}=... : ...`) or use another parent column")
                elif "." in col and (par.col(plain) is not None or t.col(plain) is not None):
                    fix = f"write `{plain}` (parent columns are used by their plain name)"
                else:
                    fix = "parent columns are used by their plain name, e.g. `status=:unpaid`"
                raise ShuttleError(f"no column {col!r} in {t.name} or its parent", line,
                                   hint=f"{t.name} columns: " + ", ".join(x.name for x in t.cols) +
                                        f"; parent {par.name} columns: " + ", ".join(x.name for x in par.cols if x.name not in par.children) + f". {fix}")
            raise ShuttleError(f"no column {col!r} in {t.name}", line, hint="columns: " + ", ".join(x.name for x in t.cols))
        if in_row:
            getv = lambda row, pr: row[col]
        else:
            getv = lambda row, pr: pr[col]
        if op == "missing":
            return lambda row, pr: getv(row, pr) is None
        if op == "in":
            eqs = [_eq_fn(x) for x in c[2]]
            return lambda row, pr: any(e(getv(row, pr)) for e in eqs)
        if op == "has":
            e = _eq_fn(c[2])
            return lambda row, pr: (lambda v: isinstance(v, list) and any(e(x) for x in v))(getv(row, pr))
        if op == "=":
            e = _eq_fn(c[2])
            return lambda row, pr: e(getv(row, pr))
        if op == "!=":
            e = _eq_fn(c[2])
            return lambda row, pr: not e(getv(row, pr))
        cmp = _ord_fn(op, c[2], line)
        return lambda row, pr: cmp(getv(row, pr))

    def _select(self, path, cond, line, need_pos=True):
        """Yield (container_list, index, row, parent_row, table) for matching rows.
        With need_pos=False the index may be None for rows found through the key index."""
        name = path.split(".")
        if name[0] not in self.rows:
            raise ShuttleError(f"no table {name[0]!r}", line, hint="tables: " + ", ".join(self.rows))
        t = self.schema.tables[name[0]]
        if len(name) == 1:
            f = self._compile(cond, t, line) if cond is not None else None
            pinned = self._pinned_key(t, cond)
            if pinned is not None:
                r = self.index[name[0]].get(pinned)
                if r is not None and (f is None or f(r, None)):
                    yield self.rows[name[0]], (self._position(name[0], r) if need_pos else None), r, None, t
                return
            lst = self.rows[name[0]]
            if f is None:
                for i, r in enumerate(lst):
                    yield lst, i, r, None, t
            else:
                for i, r in enumerate(lst):
                    if f(r, None):
                        yield lst, i, r, None, t
            return
        if len(name) != 2 or name[1] not in t.children:
            raise ShuttleError(f"no child table {path!r}", line, hint="children of " + name[0] + ": " + ", ".join(t.children) if t.children else "none")
        ct = t.children[name[1]]
        f = self._compile(cond, ct, line) if cond is not None else None
        shadow = {c.name for c in ct.cols}
        pinned = None if any(k in shadow for k in t.key) else self._pinned_key(t, cond)
        parents = [self.index[name[0]][pinned]] if pinned is not None and pinned in self.index.get(name[0], {}) else ([] if pinned is not None else self.rows[name[0]])
        for pr in parents:
            for i, r in enumerate(pr[name[1]]):
                if f is None or f(r, pr):
                    yield pr[name[1]], i, r, pr, ct

    def _order_limit(self, p, no):
        """Optional `order <col> [asc|desc] limit n` after the condition of set/del: only the first n rows
        in that order are affected (`limit 1` = the top row). Returns (col, desc, n) or None."""
        if p.peek() != ("atom", "order") and p.peek() != ("atom", "limit"):
            return None
        col, desc = None, False
        if p.peek() == ("atom", "order"):
            p.i += 1
            col = p.take("atom")
            if p.peek()[0] == "atom" and p.peek()[1] in ("asc", "desc"):
                desc = p.take("atom") == "desc"
        if p.peek() != ("atom", "limit"):
            raise ShuttleError("`order` in set/del needs `limit n` (which rows to affect)", no)
        p.i += 1
        lt = p.take("atom")
        if not lt.isdigit() or int(lt) < 1:
            raise ShuttleError(f"limit needs a positive number, got {lt!r}", no)
        return (col, desc, int(lt))
    def _top(self, hits, topn, path, no):
        if topn is None:
            return hits
        col, desc, n = topn
        if col is not None:
            t = self._table_of(path, no)
            if t.col(col) is None:
                raise ShuttleError(f"no column {col!r} in {t.name}", no, hint="columns: " + ", ".join(x.name for x in t.cols))
            keyf = _sort_key(col, no)
            hits = sorted(hits, key=lambda h: keyf(h[2][col]), reverse=desc)
            if len(hits) > n and keyf(hits[n - 1][2][col]) == keyf(hits[n][2][col]):
                raise ShuttleError(f"limit {n}: rows {n} and {n + 1} tie on {col!r}; add a second condition or order by a key", no)
        return hits[:n]
    def _table_of(self, path, line):
        name = path.split(".")
        if name[0] not in self.rows:
            raise ShuttleError(f"no table {name[0]!r}", line, hint="tables: " + ", ".join(self.rows))
        t = self.schema.tables[name[0]]
        if len(name) == 1:
            return t
        if len(name) != 2 or name[1] not in t.children:
            raise ShuttleError(f"no child table {path!r}", line, hint="children of " + name[0] + ": " + ", ".join(t.children) if t.children else "none")
        return t.children[name[1]]
    def _pinned_key(self, t, cond):
        """If the condition is a conjunction containing `key = v` for every key column of t, return the key tuple."""
        if cond is None or not t.key or t.name not in self.index:
            return None
        eqs = {}
        def walk(c):
            if c[0] == "and":
                walk(c[1]); walk(c[2])
            elif c[0] == "=" and isinstance(c[1], str):
                eqs.setdefault(c[1], c[2])
        walk(cond)
        if all(k in eqs for k in t.key):
            try:
                return tuple(W._encode(eqs[k]) for k in t.key)
            except W.WeftNextError:
                return None
        return None
    def _position(self, name, row):
        # position of a row object in its table (only needed for `after` and deletes; O(n) but rare)
        lst = self.rows[name]
        for i, r in enumerate(lst):
            if r is row:
                return i
        raise ShuttleError("internal: row not in table")

    def _relative_fn(self, t, col, aop, v, line):
        """Compile `col += v` / `col -= v` for one statement into a function of the current value.
        The result is type-checked against the column's declared type once per row (cheaply)."""
        c = t.col(col)
        typ = c.typ
        base = typ[:-1] if typ.endswith("?") else typ
        def bad(cur):
            if cur is None:
                return ShuttleError(f"{t.name}.{col} is nil; `{aop}` needs a current value (use `=`)", line)
            return ShuttleError(f"`{aop}` works on numbers and lists; {t.name}.{col} is {typ}, got {W._canonical_text(v).strip()}", line)
        if base.startswith("list<"):
            items = v if isinstance(v, list) else [v]
            if not type_ok(base, items):
                raise ShuttleError(f"{t.name}.{col} is {typ}, got {W._canonical_text(v).strip()}", line)
            if aop == "+=":
                def f(cur):
                    if not isinstance(cur, list):
                        raise bad(cur)
                    return cur + items
                return f
            if aop == "|=":                                   # add only what is not there yet (safe to repeat)
                def f(cur):
                    if not isinstance(cur, list):
                        raise bad(cur)
                    out = list(cur)
                    for y in items:
                        e = _eq_fn(y)
                        if not any(e(x) for x in out):
                            out.append(y)
                    return out
                return f
            eqs = [_eq_fn(y) for y in items]
            def f(cur):
                if not isinstance(cur, list):
                    raise bad(cur)
                out = [x for x in cur if not any(e(x) for e in eqs)]
                if len(out) == len(cur):
                    raise ShuttleError(f"{t.name}.{col} does not contain {W._canonical_text(v).strip()}", line)
                return out
            return f
        if aop == "|=":
            raise ShuttleError(f"`|=` works on lists only; {t.name}.{col} is {typ}", line)
        if base == "int":
            if not isinstance(v, int) or isinstance(v, bool):
                raise ShuttleError(f"{t.name}.{col} is {typ}, got {W._canonical_text(v).strip()}", line)
            d = v if aop == "+=" else -v
            def f(cur):
                if not isinstance(cur, int) or isinstance(cur, bool):
                    raise bad(cur)
                return cur + d
            return f
        if base == "dec":
            if not isinstance(v, (int, weft.Decimal)) or isinstance(v, bool):
                raise ShuttleError(f"{t.name}.{col} is {typ}, got {W._canonical_text(v).strip()}", line)
            from decimal import Decimal as D
            d = D(v.text if isinstance(v, weft.Decimal) else str(v))
            if aop == "-=":
                d = d.copy_negate()                             # SV5-01 r2: unary minus rounds at context precision
            def f(cur):
                if not isinstance(cur, weft.Decimal):
                    raise bad(cur)
                try:
                    return weft.Decimal(_dec_text(_dec_add(cur, d)))
                except ArithmeticError as e:                    # SV5-01: never round silently
                    raise ShuttleError(f"{t.name}.{col}: decimal arithmetic could not be done exactly ({type(e).__name__})", line)
            return f
        raise ShuttleError(f"`{aop}` works on numbers and lists; {t.name}.{col} is {typ}", line)

    def _check_type(self, t, col, v, line):
        c = t.col(col)
        if c is None:
            raise ShuttleError(f"no column {col!r} in {t.name}", line, hint="columns: " + ", ".join(x.name for x in t.cols))
        if col in t.children:
            raise ShuttleError(f"{col!r} is a child table; address it as {t.name}.{col}", line)
        if not type_ok(c.typ, v):
            raise ShuttleError(f"{t.name}.{col} is {c.typ}, got {W._canonical_text(v).strip()}", line)

    def _new_row(self, t, values, line, named=None):
        row = {}
        if named is None:
            named = bool(values) and isinstance(values[0], tuple)
        if named:                                             # by name
            given = dict(values)
            for c in t.cols:
                if c.name in t.children:
                    ch = given.pop(c.name, [])
                    ct = t.children[c.name]
                    if not isinstance(ch, list) or not all(isinstance(x, dict) for x in ch):
                        raise ShuttleError(f"{t.name}.{c.name} must be a list of maps (child rows), e.g. [{{{', '.join(x.name + ': ...' for x in ct.cols[:2])}}}]", line)
                    rows = []
                    for x in ch:
                        r = self._new_row(ct, list(x.items()), line, named=True)
                        self._check_key(ct, rows, r, line)
                        rows.append(r)
                    row[c.name] = rows
                    continue
                if c.name in given:
                    v = given.pop(c.name)
                    self._check_type(t, c.name, v, line)
                    row[c.name] = v
                elif c.has_default:
                    row[c.name] = c.default
                else:
                    ex = {"int": "0", "dec": "0m", "str": '""', "kw": ":x", "bool": "false", "dt": "#2026-01-01"}.get(c.typ.rstrip("?"), "nil" if c.typ.endswith("?") else "<value>")
                    raise ShuttleError(f"missing {t.name}.{c.name} (no default)", line,
                                       hint=f"every column without a default must be in the add: write `{c.name}={ex}` in this line "
                                            f"(a later line of the same message may update it, e.g. with an aggregate)")
            if given:
                raise ShuttleError(f"unknown column(s) {', '.join(given)}", line)
        else:                                                   # positional, non-child columns in order
            cols = [c for c in t.cols if c.name not in t.children]
            if len(values) != len(cols):
                raise ShuttleError(f"{t.name} has {len(cols)} columns ({', '.join(c.name for c in cols)}), got {len(values)} values", line)
            for c, v in zip(cols, values):
                self._check_type(t, c.name, v, line)
                row[c.name] = v
            for ch in t.children:
                row[ch] = []
        return row

    # ---- transactions
    def execute(self, text):
        """Run one message (one transaction). Returns the receipt text. All-or-nothing."""
        tx_id, at = None, None
        body = text.strip()
        stmts = []
        try:
            for no, raw in _statements(text):
                s = _strip_comment(raw).strip()
                if not s:
                    continue
                toks = _lex(s)
                p = P(toks, no, raw)
                kind = p.take("atom")
                if kind == "tx":
                    tx_id = p.take("atom")
                    if p.peek() == ("atom", "at"):
                        p.i += 1
                        vtxt = p.take("atom")
                        if not vtxt.isdigit():
                            raise ShuttleError(f"`at` needs a version number, got {vtxt!r}", no)
                        at = int(vtxt)
                    if not p.at_end():
                        raise ShuttleError(f"unexpected {p.peek()[1]!r} after the tx header", no,
                                           hint="the tx header is a line of its own: `tx <id> at <version>`, then the operations on the next lines")
                    if at is None and tx_id.isdigit():
                        raise ShuttleError(f"`tx {tx_id}`: a tx id is a name; to pin the version write `tx <id> at {tx_id}`", no)
                    continue
                zero_ok = kind in ("set?", "del?")
                if zero_ok:
                    kind = kind[:-1]
                stmts.append((no, kind, p, raw, zero_ok))
        except ShuttleError as e:
            return f"fail line {e.line}: {e.msg}" + (f"\n  hint: {e.hint}" if e.hint else "") + "\n  (nothing applied)"
        except Exception as e:
            return f"fail: internal error {type(e).__name__}: {str(e)[:120]}\n  (nothing applied)"
        if tx_id is not None and tx_id in self.receipts:
            prev_body, prev_receipt = self.receipts[tx_id]
            if prev_body == body:
                return prev_receipt + "  ; (replay)"
            return (f"fail: tx id {tx_id!r} was already used for a different message; a tx id names one message "
                    f"(reuse it only to re-send the same message). Pick a new id.\n  (nothing applied)")
        if at is not None and at != self.version:
            r = (f"fail stale: you assumed version {at}, current is {self.version}\n"
                 f"  hint: another writer changed the store. Read again before writing (the rows you chose may differ now), "
                 f"and guard the write with the condition you relied on (e.g. `and status=:unpaid`)")
            return r
        self._undo = []
        counts = {"set": 0, "add": 0, "del": 0, "put": 0}
        expects, outputs, shown_zero = [], [], set()
        try:
            for no, kind, p, raw, zero_ok in stmts:
                if kind == "set":
                    path = p.take("atom")
                    cond = p.where_opt()
                    if cond is None:
                        raise ShuttleError("set needs `where` (to update every row write `where true`)", no)
                    topn = self._order_limit(p, no)
                    p.colon()
                    assigns = []
                    while not p.at_end():
                        col = p.column()
                        aop = p.take("op")
                        if aop not in ("=", "+=", "-=", "|="):
                            raise ShuttleError(f"expected =, +=, -= or |= after {col!r}, got {aop!r}", no)
                        assigns.append((col, aop, p.value()))
                        if p.peek() == ("op", ","):
                            p.i += 1
                    n = 0
                    tname = path.split(".")[0]
                    t = self._table_of(path, no)
                    assigns = [(col, aop, self._resolve(v, no, outputs)) for col, aop, v in assigns]
                    for col, aop, v in assigns:                    # resolve columns once per statement
                        if aop == "=":
                            self._check_type(t, col, v, no)        # constant: checked once, not per row
                        elif t.col(col) is None:
                            raise ShuttleError(f"no column {col!r} in {t.name}", no, hint="columns: " + ", ".join(x.name for x in t.cols))
                    if len({c for c, _, _ in assigns}) != len(assigns):
                        raise ShuttleError("the same column is assigned twice in one set", no)
                    key_changes = bool(t.key) and any(col in t.key for col, _, _ in assigns)
                    simple = not key_changes and all(aop == "=" for _, aop, _ in assigns)
                    plan = [(col, None if aop == "=" else self._relative_fn(t, col, aop, v, no), v) for col, aop, v in assigns]
                    for lst, i, row, pr, t in self._top(list(self._select(path, cond, no, need_pos=False)), topn, path, no):
                        if simple:
                            for col, _, v in plan:
                                self._mut_cell(row, col, v)
                            n += 1
                            continue
                        if key_changes and pr is None:
                            self._idx_del(tname, t, row)
                        for col, rel, v in plan:
                            if rel is not None:
                                v = rel(row[col])
                            self._mut_cell(row, col, v)
                        if key_changes:
                            if pr is None:
                                k = self._key_of(t, row)
                                if k in self.index.get(tname, {}):
                                    raise ShuttleError(f"set would create a duplicate key {','.join(t.key)}={','.join(W._canonical_text(row[c]).strip() for c in t.key)} in {t.name}", no)
                                self._idx_add(tname, t, row)
                            else:
                                self._check_key(t, [x for x in lst if x is not row], row, no)
                        n += 1
                    if n == 0 and not zero_ok:
                        raise ShuttleError(f"set matched no rows in {path}", no, hint=self._hint_nomatch(path, cond, no, "set"))
                    counts["set"] += n
                elif kind == "add":
                    path = p.take("atom")
                    name = path.split(".")
                    parent_cond = after = None
                    if p.peek() == ("atom", "where"):
                        p.i += 1
                        parent_cond = p.cond()
                    if p.peek() == ("atom", "after"):
                        p.i += 1
                        p.take("atom", "where")
                        after = p.cond()
                    p.colon()
                    vals = []
                    while not p.at_end():
                        if p.peek(1) == ("op", "=") and p.peek()[0] == "atom":
                            col = p.column(); p.take("op", "=")
                            vals.append((col, self._resolve(p.value(), no, outputs)))
                        elif p.peek()[0] == "atom" and not p.peek()[1].startswith(":") and (
                                p.peek(1) == ("op", ":") or
                                (p.peek(1)[0] == "atom" and p.peek(1)[1].startswith(":") and not W._name_ok("kw", p.peek(1)[1][1:]))):
                            nxt = p.peek(1)[1] if p.peek(1)[0] == "atom" else "value"
                            raise ShuttleError(f"`{p.peek()[1]}:` — in a named add write `{p.peek()[1]}={nxt.lstrip(':')}` (use `=`, not `:`)", no)
                        else:
                            vals.append(self._resolve(p.value(), no, outputs))
                        if p.peek() == ("op", ","):
                            p.i += 1
                    if re.split(r"[.\[]", path)[0] in self.schema.doc:
                        # document list: `add flags : :beta`  /  `add changes[1].affects : "2.3.2"`
                        cont, key = self._doc_ref(path, no)
                        lst = cont[key] if (isinstance(cont, dict) and key in cont) or isinstance(cont, list) else None
                        if not isinstance(lst, list):
                            raise ShuttleError(f"{path!r} is not a list", no)
                        if len(vals) != 1 or isinstance(vals[0], tuple):
                            raise ShuttleError("add to a document list takes exactly one value", no)
                        self._check_doc_type(path, vals[0], no, element=True)
                        self._mut_insert(lst, len(lst), vals[0])
                        counts["add"] += 1
                        continue
                    if len(name) == 1:
                        t = self.schema.tables.get(name[0])
                        if t is None or t.parent is not None:
                            raise ShuttleError(f"no table {path!r}", no, hint="tables: " + ", ".join(self.rows))
                        if parent_cond is not None:
                            raise ShuttleError("`add <table> where ...` is not allowed; use `after where` to place the row, or omit", no)
                        target = self.rows[name[0]]
                    else:
                        if len(name) != 2 or name[1] not in self.schema.tables.get(name[0], Table("", [], [])).children:
                            raise ShuttleError(f"no child table {path!r}", no)
                        if parent_cond is None:
                            raise ShuttleError(f"add {path} needs `where <parent condition>` to pick the parent row", no)
                        parents = list(self._select(name[0], parent_cond, no))
                        if len(parents) != 1:
                            raise ShuttleError(f"parent condition matched {len(parents)} rows of {name[0]} (need exactly one)", no)
                        t = self.schema.tables[path]
                        target = parents[0][2][name[1]]
                    row = self._new_row(t, vals, no, named=(not vals) or isinstance(vals[0], tuple))
                    if len(name) == 1 and t.key and name[0] in self.index:
                        if self._key_of(t, row) in self.index[name[0]]:
                            raise ShuttleError(f"duplicate key {','.join(t.key)}={','.join(W._canonical_text(row[c]).strip() for c in t.key)} in {t.name}", no)
                    else:
                        self._check_key(t, target, row, no)
                    if after is None:
                        self._mut_insert(target, len(target), row)
                    else:
                        pr = None if len(name) == 1 else parents[0][2]
                        fa = self._compile(after, t, no)
                        hits = [i for i, r in enumerate(target) if fa(r, pr)]
                        if len(hits) != 1:
                            raise ShuttleError(f"`after where` must match exactly one row, matched {len(hits)}", no)
                        self._mut_insert(target, hits[0] + 1, row)
                    if len(name) == 1:
                        self._idx_add(name[0], t, row)
                    counts["add"] += 1
                elif kind == "del":
                    path = p.take("atom")
                    cond = p.where_opt()
                    if cond is None:
                        raise ShuttleError("del needs `where`", no)
                    topn = self._order_limit(p, no)
                    hits = self._top(list(self._select(path, cond, no)), topn, path, no)
                    if not hits and not zero_ok:
                        raise ShuttleError(f"del matched no rows in {path}", no, hint=self._hint_nomatch(path, cond, no, "del"))
                    tname = path.split(".")[0]
                    for lst, i, row, pr, t in sorted(hits, key=lambda h: -h[1]):
                        self._mut_delete(lst, i)
                        if pr is None:
                            self._idx_del(tname, t, row)
                    counts["del"] += len(hits)
                elif kind == "put":
                    field = p.take("atom"); p.take("op", "=")
                    v = self._resolve(p.value(), no, outputs)
                    cont, key = self._doc_ref(field, no)
                    if cont is self.doc and not type_ok(self.schema.doc[key], v):
                        raise ShuttleError(f"{key} is {self.schema.doc[key]}", no)
                    if isinstance(cont, list) and not (0 <= key < len(cont)):
                        raise ShuttleError(f"index {key} out of range", no)
                    if isinstance(cont, dict) and key not in cont and cont is not self.doc:
                        raise ShuttleError(f"{field!r}: no such key {key!r} (put changes existing fields; use add for lists)", no, hint="keys: " + ", ".join(cont))
                    if cont is not self.doc:
                        self._check_doc_type(field, v, no, element=False)
                    self._mut_set(cont, key, v)
                    counts["put"] += 1
                elif kind == "expect":
                    expects.append((no, p))
                elif kind in ("count", "sum", "show", "get"):
                    outputs.append(self._query(kind, p, no))
                else:
                    raise ShuttleError(f"unknown statement {kind!r}", no, hint="set, add, del, put, expect, count, sum, show, get")
                if kind != "expect" and not p.at_end():
                    raise ShuttleError(f"unexpected {p.peek()[1]!r} after the end of the statement", no)
            # postconditions
            for no, p in expects:
                got = self._agg(p, no)
                op = p.take("op")
                want = self._resolve(p.value(), no, outputs)
                if not p.at_end():
                    raise ShuttleError(f"unexpected {p.peek()[1]!r} after the end of the statement", no)
                if op == "=":
                    ok_ = _eq_fn(want)(got)
                elif op == "!=":
                    ok_ = not _eq_fn(want)(got)
                else:
                    ok_ = _ord_fn(op, want, no)(got)
                if not ok_:
                    raise ShuttleError(f"expectation failed: got {W._canonical_text(got).strip()}, wanted {op} {W._canonical_text(want).strip()}", no)
        except ShuttleError as e:
            self._rollback()
            hint = e.hint
            for st_ in stmts:                        # R8-01: query guidance only after a real failure of that statement
                if st_[0] == e.line and not st_[2].at_end() and st_[2].embedded_query():   # only when parsing stopped mid-statement
                    hint = (f"a `{st_[2].embedded_query()}` query cannot be used as a value or inside a condition. To change the top row directly write "
                            "`set <table> where <cond> order <col> desc limit 1 : col=value, ...`; otherwise run the query in its own message and use the id from the receipt")
            r = f"fail line {e.line}: {e.msg}" + (f"\n  hint: {hint}" if hint else "") + "\n  (nothing applied)"
            return r                                 # a failed message reserves no tx id (v6 r4): fix it and re-send with the same id
        except Exception as e:                       # anything unexpected: still all-or-nothing
            self._rollback()
            r = f"fail: internal error {type(e).__name__}: {str(e)[:120]}\n  (nothing applied)"
            return r
        self._undo = None
        changed = any(counts.values())
        for k in ("set", "del"):
            if counts[k] == 0 and any(kind == k and zero_ok for _, kind, _, _, zero_ok in stmts):
                counts[k] = 0; shown_zero.add(k)
        if changed:
            self.version += 1
            self.vid = hashlib.sha256((self.vid + "\n" + text).encode("utf-8")).hexdigest()[:12]
            self.log.append((tx_id, text))
        r = f"ok v={self.version} " + " ".join(f"{k}:{v}" for k, v in counts.items() if v or k in shown_zero) + (f" expect:{len(expects)}" if expects else "") + f" vid={self.vid}"
        if outputs:
            r += "\n" + "\n".join(outputs)
        if tx_id is not None and changed:            # only a message that changed the store owns its id
            self.receipts[tx_id] = (body, r)
        return r

    def _doc_ref(self, path, line, create=False):
        """Resolve `a.b[2].c` inside the document part. Returns (container, key)."""
        parts = re.findall(r"[^.\[\]]+|\[\d+\]", path)
        if not parts or parts[0] not in self.schema.doc:
            raise ShuttleError(f"no document field {parts[0] if parts else path!r}", line, hint="fields: " + ", ".join(self.schema.doc))
        cur, key = self.doc, parts[0]
        for part in parts[1:]:
            if isinstance(cur, dict) and key not in cur or isinstance(cur, list) and not (isinstance(key, int) and 0 <= key < len(cur)):
                raise ShuttleError(f"no such path {path!r} (stopped at {key!r})", line)
            cur = cur[key]
            if part.startswith("["):
                if not isinstance(cur, list):
                    raise ShuttleError(f"{path!r}: index into a non-list", line)
                key = int(part[1:-1])
            else:
                if not isinstance(cur, dict):
                    raise ShuttleError(f"{path!r}: field of a non-map", line)
                key = part
        return cur, key

    def _rollback(self):
        for undo in reversed(self._undo or []):
            if isinstance(undo, tuple):
                container, key, had, old = undo
                if had:
                    container[key] = old
                else:
                    del container[key]
            else:
                undo()
        self._undo = None

    def _doc_type_at(self, path):
        """Declared type at a document path, or None once the path enters an undeclared part (a map)."""
        parts = re.findall(r"[^.\[\]]+|\[\d+\]", path)
        typ = self.schema.doc.get(parts[0])
        for part in parts[1:]:
            if typ is None:
                return None
            if part.startswith("["):
                typ = typ[5:-1] if typ.startswith("list<") else None
            else:
                typ = None                      # fields inside a `map` are not declared
        return typ

    def _check_doc_type(self, path, v, line, element):
        """put: v must have the type declared at the path. add: v must have the element type of the
        list declared at the path."""
        typ = self._doc_type_at(path)
        if element:
            typ = typ[5:-1] if typ and typ.startswith("list<") else None
        if typ and not type_ok(typ, v):
            raise ShuttleError(f"{path} expects {typ}, got {W._canonical_text(v).strip()}", line)

    def _check_key(self, t, rows, row, line):
        if t.key:
            k = tuple(W._encode(row[c]) for c in t.key)
            for r in rows:
                if tuple(W._encode(r[c]) for c in t.key) == k:
                    raise ShuttleError(f"duplicate key {','.join(t.key)}={','.join(W._canonical_text(row[c]).strip() for c in t.key)} in {t.name}", line)

    def _hint_nomatch(self, path, cond, line, verb):
        try:
            n = sum(1 for _ in self._select(path, None, line))
            return (f"{path} has {n} rows; check the condition's values and types. "
                    f"If matching nothing is acceptable here (e.g. a guard like `and status!=:shipped`), write `{verb}?` instead of `{verb}`")
        except ShuttleError:
            return None

    # ---- queries
    def _resolve(self, v, no, outputs):
        """Replace an aggregate placeholder by its value, computed now (after earlier statements of
        this message); the computed value is echoed in the receipt so the caller can audit it."""
        if isinstance(v, Agg):
            val = self._agg_eval(v.kind, v.col, v.path, v.cond, no)
            outputs.append(f"computed {v.text()} = {W.emit_ai(val).strip()}")
            return val
        if isinstance(v, list):
            return [self._resolve(x, no, outputs) for x in v]
        if isinstance(v, dict):
            return {k: self._resolve(x, no, outputs) for k, x in v.items()}
        return v
    def _agg_eval(self, kind, col, path, cond, no):
        if kind == "count":
            return sum(1 for _ in self._select(path, cond, no, need_pos=False))
        t = self._table_of(path, no)
        c = t.col(col)
        if c is None:
            raise ShuttleError(f"sum: no column {col!r} in {t.name}", no, hint="columns: " + ", ".join(x.name for x in t.cols))
        base = c.typ[:-1] if c.typ.endswith("?") else c.typ
        if base not in ("int", "dec"):                       # SV6-01: the result type comes from the declared column type
            raise ShuttleError(f"sum: {t.name}.{col} is {c.typ}; only int and dec columns can be summed", no)
        terms = [r[col] for lst, i, r, pr, tt in self._select(path, cond, no, need_pos=False) if r.get(col) is not None]   # nil is skipped
        if base == "int":
            return sum(terms)                                 # 0 for an empty selection
        try:                                                  # SV6-02: dec column -> Decimal even when empty
            return weft.Decimal(_dec_text(_dec_add(*terms))) if terms else weft.Decimal("0")
        except ArithmeticError as e:
            raise ShuttleError(f"sum {col}: decimal arithmetic could not be done exactly ({type(e).__name__})", no)
    def _agg(self, p, no):
        kind = p.take("atom")
        if kind == "count":
            path = p.take("atom")
            cond = p.where_opt()
            return self._agg_eval("count", None, path, cond, no)
        if kind == "sum":
            col = p.take("atom"); p.take("atom", "of"); path = p.take("atom")
            cond = p.where_opt()
            return self._agg_eval("sum", col, path, cond, no)
        # <path>.<col> where <cond>  (exactly one row)
        path, _, col = kind.rpartition(".")
        cond = p.where_opt()
        hits = list(self._select(path, cond, no, need_pos=False))
        if len(hits) != 1:
            raise ShuttleError(f"{kind} must match exactly one row, matched {len(hits)}", no)
        return hits[0][2][col]
    def _query(self, kind, p, no):
        if kind == "count":
            path = p.take("atom"); cond = p.where_opt()
            return f"count {path} = {self._agg_eval('count', None, path, cond, no)}"
        if kind == "sum":
            col = p.take("atom"); p.take("atom", "of"); path = p.take("atom"); cond = p.where_opt()
            return f"sum {col} of {path} = {W.emit_ai(self._agg_eval('sum', col, path, cond, no)).strip()}"
        path = p.take("atom"); cond = p.where_opt()
        limit, cols, order = (1 if kind == "get" else 20), None, None
        while not p.at_end():
            w = p.take("atom")
            if w == "limit":
                lt = p.take("atom")
                if not lt.isdigit():
                    raise ShuttleError(f"limit needs a number, got {lt!r}", no)
                limit = int(lt)
            elif w == "cols":
                cols = []
                while not p.at_end() and p.peek()[0] == "atom" and p.peek()[1] not in ("limit", "order"):
                    cols.append(p.take("atom"))
                    if p.peek() == ("op", ","):
                        p.i += 1
            elif w == "order":
                ocol = p.take("atom")
                desc = False
                if p.peek()[0] == "atom" and p.peek()[1] in ("asc", "desc"):
                    desc = p.take("atom") == "desc"
                order = (ocol, desc)
            else:
                raise ShuttleError(f"unexpected {w!r} in {kind} (allowed: limit n, cols a,b, order col [asc|desc])", no)
        t = self._table_of(path, no)
        for c in (cols or []) + ([order[0]] if order else []):
            if t.col(c) is None and not (t.parent is not None and (t.parent if isinstance(t.parent, Table) else self.schema.tables[t.parent]).col(c) is not None):
                raise ShuttleError(f"no column {c!r} in {t.name}", no, hint="columns: " + ", ".join(x.name for x in t.cols))
        hits = list(self._select(path, cond, no, need_pos=False))
        if kind == "get" and len(hits) != 1:
            raise ShuttleError(f"get matched {len(hits)} rows (need exactly one)", no)
        if order is not None:
            ocol, desc = order
            keyf = _sort_key(ocol, no)
            hits.sort(key=lambda h: keyf(h[2][ocol] if ocol in h[2] else h[3][ocol]), reverse=desc)
        out = [f"{kind} {path}: {len(hits)} row(s)" + (f", showing {min(limit, len(hits))}" if len(hits) > limit else "")]
        for lst, i, r, pr, t in hits[:limit]:
            o = {c: (r[c] if c in r else pr[c]) for c in (cols or [c.name for c in t.cols if c.name not in t.children])}
            out.append("  {" + ", ".join(f"{k}: {W.emit_ai(v).strip().replace(chr(10), ' ')}" for k, v in o.items()) + "}")
        return "\n".join(out)
