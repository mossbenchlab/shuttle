"""Weft next — prototype (design draft d3).

Value model: Weft 1.x values with Int/BigInt unified (Python int) and
TypedValue removed (migrated to the Tagged node `weft1-typed`).

    parse_ai(text)  -> value      AI surface (indentation blocks + inline flow), many-to-one
    emit_ai(value)  -> text       deterministic AI-surface rendering
    canonical_text(value) -> str  Weft 1.x strict-canonical restricted to the next model
    encode(value) -> bytes        canonical binary (with WFT2 header)
    decode(bytes) -> value
    digest(value) -> hex          SHA-256 of the canonical binary
    from_v1(value) -> value       Weft 1.x value -> next value model
"""
import hashlib
import re
import struct

import weft

S, K, X = weft.Symbol, weft.Keyword, weft.Sexpr
STRICT = weft.FormatOptions(strict_canonical=True)
MAGIC = b"WFT2" + bytes([1])


class WeftNextError(ValueError):
    def __init__(self, msg, line=None, text=None):
        self.line, self.text = line, text
        where = f"[line {line}] " if line is not None else ""
        shown = f"  | {text}" if text is not None else ""
        super().__init__(f"{where}{msg}{shown}")


# --------------------------------------------------------------- value model
class WeftNextLimitError(WeftNextError):
    """A resource limit (d5) was exceeded."""


import dataclasses as _dc
import weft.limits as _wl

DEFAULT_MAX_VALUE_BYTES = 64 * 1024 * 1024
HARD_MAX_VALUE_BYTES = 1 << 30
PROTOTYPE_MAX_DEPTH = 200     # this prototype is recursive; d5 itself allows up to the 1.x hard max


@_dc.dataclass(frozen=True)
class Limits:
    """d5: the Weft 1.x §9 limits (same defaults, hard maximums, no 'unlimited')
    plus max_value_bytes, the size of the value as a canonical binary document."""
    max_depth: int = _wl.DEFAULT_MAX_DEPTH
    max_size_bytes: int = _wl.DEFAULT_MAX_SIZE_BYTES
    max_items_per_coll: int = _wl.DEFAULT_MAX_ITEMS_PER_COLL
    max_string_bytes: int = _wl.DEFAULT_MAX_STRING_BYTES
    max_int_digits: int = _wl.DEFAULT_MAX_INT_DIGITS
    max_total_items: int = _wl.DEFAULT_MAX_TOTAL_ITEMS
    max_value_bytes: int = DEFAULT_MAX_VALUE_BYTES

    def __post_init__(self):
        object.__setattr__(self, "_v1", weft.Limits(
            max_depth=self.max_depth, max_size_bytes=self.max_size_bytes,
            max_items_per_coll=self.max_items_per_coll, max_string_bytes=self.max_string_bytes,
            max_int_digits=self.max_int_digits, max_total_items=self.max_total_items))   # 1.x validation
        v = self.max_value_bytes
        if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= HARD_MAX_VALUE_BYTES:
            raise ValueError(f"max_value_bytes={v!r} must be an int in 1..{HARD_MAX_VALUE_BYTES}")
        if self.max_depth > PROTOTYPE_MAX_DEPTH:
            raise ValueError(f"this prototype supports max_depth <= {PROTOTYPE_MAX_DEPTH}")

    def v1(self):
        return self._v1

    def v1_canonical(self):
        """1.x limits for reading a canonical text (d6 r3): the 1.x parser counts each Map key
        as a value, which the next model does not (§7.1). A Map entry is one key and one value,
        so the 1.x count is at most 2 x (next count) + 1; the exact count is then checked by
        check_value."""
        return weft.Limits(max_depth=self.max_depth, max_size_bytes=self.max_size_bytes,
                           max_items_per_coll=self.max_items_per_coll, max_string_bytes=self.max_string_bytes,
                           max_int_digits=self.max_int_digits,
                           max_total_items=min(_wl.HARD_MAX_TOTAL_ITEMS, 2 * self.max_total_items + 1))

    def v1_scalar(self):
        """1.x limits for checking one scalar taken from a binary document (D6-02): the text
        input-size limit does not apply there (the payload is bounded by max_value_bytes)."""
        return weft.Limits(max_depth=self.max_depth, max_size_bytes=_wl.HARD_MAX_SIZE_BYTES,
                           max_items_per_coll=self.max_items_per_coll, max_string_bytes=self.max_string_bytes,
                           max_int_digits=self.max_int_digits, max_total_items=self.max_total_items)


DEFAULT_LIMITS = Limits()
_POW10 = {}


def _uvlen(n):
    k = 1
    while n >= 0x80:
        n >>= 7; k += 1
    return k


def _too_many_digits(n, digits):
    p = _POW10.get(digits)
    if p is None:
        p = _POW10[digits] = 10 ** digits
    return abs(n) >= p


_NAME_OK = {}


def _name_ok(kind, name):
    r = _NAME_OK.get((kind, name))
    if r is None:
        try:
            x = K(name) if kind == "kw" else S(name)
            y = weft.parse(weft.format_value(x, weft.FormatOptions(strict_canonical=True)))
            r = type(y) is type(x) and y.name == name
        except Exception:
            r = False
        if len(_NAME_OK) < 100_000:
            _NAME_OK[(kind, name)] = r
    return r


def _digits_ok(text, limit):
    """Weft 1.x §9 digit budget for a decimal-notation number, applied to its canonical
    spelling: the mantissa digits (integer and fraction digits together, leading zeros
    included) and the exponent digits are each limited to max_int_digits (D6R2-01)."""
    t = text.lstrip("+-")
    if t in ("nan", "inf"):
        return
    mant, _, exp = t.lower().partition("e")
    nm = sum(1 for c in mant if c.isdigit())
    ne = sum(1 for c in exp if c.isdigit())
    if nm > limit or ne > limit:
        raise WeftNextLimitError(f"number has {max(nm, ne)} decimal digits in its "
                                 f"{'mantissa' if nm > limit else 'exponent'}, exceeds max_int_digits={limit}")


def check_value(v, limits=DEFAULT_LIMITS):
    """d5 value check, shared by all entry points. Iterative (no host stack),
    never encodes. Returns the size in bytes of the canonical binary document.
    Cost is linear in the number of nodes: name byte lengths are cached, so
    column names shared by table rows are measured once."""
    L = limits
    names = {}

    def nbytes(t, kind):
        """byte length of a name; also checks (once per distinct name) that it is a valid
        Keyword (map keys, keywords) or Symbol (tag names, symbols) name: one that reads back
        from its 1.x canonical spelling as the same name (d6 §1)."""
        key = (kind, t)
        n = names.get(key)
        if n is None:
            n = len(t.encode("utf-8"))
            if n > L.max_string_bytes:
                raise WeftNextLimitError(f"string of {n} bytes exceeds max_string_bytes={L.max_string_bytes}")
            if not _name_ok(kind, t):
                raise WeftNextError(f"not a valid {'Keyword' if kind == 'kw' else 'Symbol'} name: {t[:80]!r}")
            names[key] = n
        return n

    def fail_size(n):
        raise WeftNextLimitError(f"value exceeds max_value_bytes={L.max_value_bytes} "
                                 f"(at least {n} bytes as canonical binary)")

    total = 0
    frames = [[None, iter((v,)), 0, 0]]              # node, child iterator, payload bytes, depth
    while True:
        fr = frames[-1]
        child = next(fr[1], frames)                   # `frames` as the end sentinel
        if child is frames:
            frames.pop()
            if not frames:
                size = fr[2] + len(MAGIC)
                if size > L.max_value_bytes:
                    fail_size(size)
                return size
            sz = 1 + _uvlen(fr[2]) + fr[2]
            if sz > L.max_value_bytes:
                fail_size(sz)
            frames[-1][2] += sz
            continue
        total += 1
        if total > L.max_total_items:
            raise WeftNextLimitError(f"more than max_total_items={L.max_total_items} values")
        if isinstance(child, (list, dict, X)):
            d = fr[3] + 1
            if d > L.max_depth:
                raise WeftNextLimitError(f"tree depth {d} exceeds max_depth={L.max_depth}")
            if isinstance(child, list):
                n, it, acc = len(child), iter(child), 0
            elif isinstance(child, dict):
                n, it = len(child), iter(child.values())
                acc = 0
                for k in child:
                    if not isinstance(k, str):
                        raise WeftNextError(f"map key is not a name: {type(k).__name__}")
                    kb = nbytes(k, "kw"); acc += _uvlen(kb) + kb
            else:
                n, it = len(child.items), iter(child.items)
                kb = nbytes(child.tag.name, "sym"); acc = _uvlen(kb) + kb
            if n > L.max_items_per_coll:
                raise WeftNextLimitError(f"collection of {n} items exceeds max_items_per_coll={L.max_items_per_coll}")
            frames.append([child, it, acc, d])
            continue
        if child is None or child is True or child is False:
            p = 0
        elif isinstance(child, int):
            if _too_many_digits(child, L.max_int_digits):
                raise WeftNextLimitError(f"integer exceeds max_int_digits={L.max_int_digits}")
            p = 0 if child == 0 else (child + (child < 0)).bit_length() // 8 + 1
        elif isinstance(child, float):
            _digits_ok(_scalar_text(child), L.max_int_digits)       # D6R2-01 (same rule as 1.x)
            p = 8
        elif isinstance(child, str):
            p = len(child.encode("utf-8"))
            if p > L.max_string_bytes:
                raise WeftNextLimitError(f"string of {p} bytes exceeds max_string_bytes={L.max_string_bytes}")
        elif isinstance(child, weft.Binary):
            p = len(child.data)
            if p > L.max_string_bytes:
                raise WeftNextLimitError(f"binary of {p} bytes exceeds max_string_bytes={L.max_string_bytes}")
        elif isinstance(child, (S, K)):
            p = nbytes(child.name, "kw" if isinstance(child, K) else "sym")
        elif isinstance(child, weft.Decimal):
            t = _scalar_text(child)
            _digits_ok(t[:-1], L.max_int_digits)                      # D6R2-01 (same rule as 1.x)
            p = len(t) - 1
        elif isinstance(child, weft.WeftDate):
            p = len(_scalar_text(child)) - 1
        else:
            raise WeftNextError(f"not a Weft-next value: {type(child).__name__}")
        sz = 1 + _uvlen(p) + p
        if sz > L.max_value_bytes:
            fail_size(sz)
        fr[2] += sz


V1_PREFIX = "weft1-"


def from_v1(v):
    """1.x value -> next value (d6 §9). Injective: TypedValue v::T becomes weft1-typed(v, T),
    and a 1.x Sexpr whose tag starts with "weft1-" is wrapped as weft1-sexpr(tag, items...),
    so no two different 1.x values become the same next value."""
    if isinstance(v, weft.BigInt):
        return int(v.value)
    if isinstance(v, weft.Typed):
        return X(S("weft1-typed"), [from_v1(v.value), from_v1(v.type)])
    if isinstance(v, list):
        return [from_v1(x) for x in v]
    if isinstance(v, dict):
        return {k: from_v1(x) for k, x in v.items()}
    if isinstance(v, X):
        items = [from_v1(x) for x in v.items]
        if v.tag.name.startswith(V1_PREFIX):
            return X(S("weft1-sexpr"), [v.tag] + items)
        return X(v.tag, items)
    return v


def _from_text(v, line=None, src=None):
    """A value read by the 1.x parser from a next-format text (canonical text, AI-surface
    scalars). Not a migration: Tagged values stay as they are, and the 1.x TypedValue
    spelling v::T is not part of the next format (d6 §9)."""
    if isinstance(v, weft.BigInt):
        return int(v.value)
    if isinstance(v, weft.Typed):
        raise WeftNextError("v::T (a 1.x TypedValue) is not part of Weft next; migrate 1.x documents with from_v1",
                            line, src)
    if isinstance(v, list):
        return [_from_text(x, line, src) for x in v]
    if isinstance(v, dict):
        return {k: _from_text(x, line, src) for k, x in v.items()}
    if isinstance(v, X):
        return X(v.tag, [_from_text(x, line, src) for x in v.items])
    return v


def to_v1(v):
    """next value -> 1.x value, the inverse of from_v1 on its image (d6 §9). An Int outside the
    1.x Int range becomes a BigInt."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, int):
        return v if -(1 << 63) <= v < (1 << 63) else weft.BigInt(v)
    if isinstance(v, list):
        return [to_v1(x) for x in v]
    if isinstance(v, dict):
        return {k: to_v1(x) for k, x in v.items()}
    if isinstance(v, X):
        name = v.tag.name
        if name == "weft1-typed" and len(v.items) == 2:
            return weft.Typed(to_v1(v.items[0]), to_v1(v.items[1]))
        if name == "weft1-sexpr" and v.items and isinstance(v.items[0], S):
            return X(v.items[0], [to_v1(x) for x in v.items[1:]])
        return X(v.tag, [to_v1(x) for x in v.items])
    return v


def _fits(text, L):
    n = len(text.encode("utf-8"))
    if n > L.max_size_bytes:
        raise WeftNextLimitError(f"the text would be {n} bytes, over max_size_bytes={L.max_size_bytes}; "
                                 "it could not be read back with the same limits")
    return text


def canonical_text(v, limits=None):
    """d6 §2: only values that pass check_value are written, and only texts that the same
    limits can read back (D6-01)."""
    L = DEFAULT_LIMITS if limits is None else limits
    check_value(v, L)
    return _fits(_canonical_text(v), L)


def _canonical_text(v):
    return weft.format_value(v, STRICT)


# ------------------------------------------------------------ canonical binary
T_NIL, T_FALSE, T_TRUE, T_INT, T_FLOAT, T_DEC, T_STR, T_BIN, T_DT, T_SYM, T_KW, \
    T_LIST, T_MAP, T_TAG = range(14)
NAN_BITS = b"\x7f\xf8\x00\x00\x00\x00\x00\x00"


def _uvar(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _name(s):
    b = s.encode("utf-8")
    return _uvar(len(b)) + b


def _scalar_text(v):
    return _canonical_text(v)[:-1]          # strip the trailing "\n"


def _enc(v, out):
    if v is None:
        out += bytes([T_NIL, 0]); return
    if v is True or v is False:
        out += bytes([T_TRUE if v else T_FALSE, 0]); return
    if isinstance(v, int):
        if v == 0:
            p = b""
        else:
            p = v.to_bytes((v + (v < 0)).bit_length() // 8 + 1, "big", signed=True)
        tag = T_INT
    elif isinstance(v, float):
        p = NAN_BITS if v != v else struct.pack(">d", v); tag = T_FLOAT
    elif isinstance(v, weft.Decimal):
        p = _scalar_text(v)[:-1].encode(); tag = T_DEC          # drop "m"
    elif isinstance(v, str):
        p = v.encode("utf-8"); tag = T_STR
    elif isinstance(v, weft.Binary):
        p = bytes(v.data); tag = T_BIN
    elif isinstance(v, weft.WeftDate):
        p = _scalar_text(v)[1:].encode(); tag = T_DT              # drop "#"
    elif isinstance(v, S):
        p = v.name.encode("utf-8"); tag = T_SYM
    elif isinstance(v, K):
        p = v.name.encode("utf-8"); tag = T_KW
    elif isinstance(v, list):
        buf = bytearray()
        for x in v:
            _enc(x, buf)
        p = bytes(buf); tag = T_LIST
    elif isinstance(v, dict):
        buf = bytearray()
        for k in sorted(v, key=lambda k: k.encode("utf-8")):    # code-point order
            buf += _name(k)
            _enc(v[k], buf)
        p = bytes(buf); tag = T_MAP
    elif isinstance(v, X):
        buf = bytearray(_name(v.tag.name))
        for x in v.items:
            _enc(x, buf)
        p = bytes(buf); tag = T_TAG
    else:
        raise WeftNextError(f"not a Weft-next value: {type(v).__name__}")
    out.append(tag)
    out += _uvar(len(p))
    out += p


def encode(v, limits=None):
    """d6 §2: only values that pass check_value are encoded."""
    check_value(v, DEFAULT_LIMITS if limits is None else limits)
    return _encode(v)


def _encode(v):
    out = bytearray(MAGIC)
    _enc(v, out)
    return bytes(out)


def digest(v, limits=None):
    return hashlib.sha256(encode(v, limits)).hexdigest()


def _ruvar(b, i, lim):
    n = shift = 0
    while True:
        if i >= lim:
            raise WeftNextError("truncated length")
        c = b[i]; i += 1
        n |= (c & 0x7F) << shift
        if not c & 0x80:
            return n, i
        shift += 7
        if shift > 63:
            raise WeftNextError("length too long")


def _dec(b, i, lim, d, L):
    if i >= lim:
        raise WeftNextError("truncated value")
    tag = b[i]
    ln, j = _ruvar(b, i + 1, lim)
    end = j + ln
    if end > lim:
        raise WeftNextError("length runs past the enclosing value")
    p = b[j:end]
    if tag == T_NIL: return None, end
    if tag == T_FALSE: return False, end
    if tag == T_TRUE: return True, end
    if tag == T_INT: return int.from_bytes(p, "big", signed=True) if p else 0, end
    if tag == T_FLOAT:
        if ln != 8:
            raise WeftNextError("float payload must be 8 bytes")
        return struct.unpack(">d", p)[0], end
    if tag == T_DEC: return weft.parse(p.decode() + "m", limits=L.v1_scalar()), end
    if tag == T_STR: return p.decode("utf-8"), end
    if tag == T_BIN: return weft.Binary(bytes(p), "base64"), end
    if tag == T_DT: return weft.parse("#" + p.decode(), limits=L.v1_scalar()), end
    if tag == T_SYM: return S(p.decode("utf-8")), end
    if tag == T_KW: return K(p.decode("utf-8")), end
    if tag in (T_LIST, T_MAP, T_TAG):
        if d + 1 > L.max_depth:
            raise WeftNextLimitError(f"tree depth {d + 1} exceeds max_depth={L.max_depth}")
    if tag == T_LIST:
        xs, k = [], j
        while k < end:
            x, k = _dec(b, k, end, d + 1, L); xs.append(x)
        return xs, end
    if tag == T_MAP:
        m, k = {}, j
        while k < end:
            nl, k2 = _ruvar(b, k, end)
            if k2 + nl > end:
                raise WeftNextError("key runs past the map")
            name = b[k2:k2 + nl].decode("utf-8"); k = k2 + nl
            if name in m:
                raise WeftNextError(f"duplicate key {name!r}")
            m[name], k = _dec(b, k, end, d + 1, L)
        return m, end
    if tag == T_TAG:
        nl, k = _ruvar(b, j, end)
        if k + nl > end:
            raise WeftNextError("tag name runs past the value")
        name = b[k:k + nl].decode("utf-8"); k += nl
        xs = []
        while k < end:
            x, k = _dec(b, k, end, d + 1, L); xs.append(x)
        return X(S(name), xs), end
    raise WeftNextError(f"bad binary tag {tag}")


def decode(b, limits=DEFAULT_LIMITS):
    """Strict: accepts only the canonical binary document of some value (d5)."""
    b = bytes(b)
    if len(b) > limits.max_value_bytes:
        raise WeftNextLimitError(f"document of {len(b)} bytes exceeds max_value_bytes={limits.max_value_bytes}")
    if b[:5] != MAGIC:
        raise WeftNextError("not a WFT2 v1 document")
    try:
        v, i = _dec(b, 5, len(b), 0, limits)
    except WeftNextError:
        raise
    except (UnicodeDecodeError, weft.WeftError, ValueError, struct.error) as e:
        raise WeftNextError(f"malformed binary ({e.__class__.__name__})")
    if i != len(b):
        raise WeftNextError("trailing bytes")
    check_value(v, limits)
    if _encode(v) != b:
        raise WeftNextError("not the canonical binary of its value")
    return v


def parse_canonical(text, limits=DEFAULT_LIMITS):
    """Strict canonical text (d5): read with the 1.x limits, check the value,
    and require the input to be exactly its canonical text."""
    if len(text.encode("utf-8")) > limits.max_size_bytes:
        raise WeftNextLimitError(f"input exceeds max_size_bytes={limits.max_size_bytes}")
    try:
        v = _from_text(weft.parse(text, limits=limits.v1_canonical()))
    except weft.WeftLimitError as e:
        raise WeftNextLimitError(f"{e}")
    except weft.WeftError as e:
        raise WeftNextError(f"{e.__class__.__name__}: {e}")
    check_value(v, limits)
    if _canonical_text(v) != text:
        raise WeftNextError("not the canonical text of its value")
    return v


def same(a, b):
    """Value identity used for round-trip checks: canonical binary equality
    (NaN payloads are not preserved, as in Weft 1.x canonical text)."""
    return encode(a) == encode(b)


# ------------------------------------------------------------- inline (flow)
_DELIM = set(" \t,[]{}()")
_KWSTART = re.compile(r"[A-Za-z_*/<>=!?À-\U0010ffff]|[+-][^0-9\s,\[\]{}()]")


class _Tok:
    __slots__ = ("kind", "text", "start", "end")

    def __init__(self, kind, text, start, end):
        self.kind, self.text, self.start, self.end = kind, text, start, end


def _tokens(s, line):
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c in " \t,":
            i += 1; continue
        if c in "[]{}()":
            out.append(_Tok(c, c, i, i + 1)); i += 1; continue
        if c == '"' or (c == "b" and s[i + 1:i + 2] == '"'):
            j = i + (2 if c == "b" else 1)
            while j < n and s[j] != '"':
                j += 2 if s[j] == "\\" else 1
            if j >= n:
                raise WeftNextError("string not closed on this line", line, s)
            out.append(_Tok("str" if c == '"' else "atom", s[i:j + 1], i, j + 1)); i = j + 1; continue
        if c == ":":
            prev = out[-1] if out else None
            nxt = s[i + 1:i + 3]
            keyish = prev is not None and prev.kind in ("atom", "str") and prev.end == i
            if keyish or not _KWSTART.match(nxt):
                out.append(_Tok("colon", ":", i, i + 1)); i += 1; continue
        j = i + 1
        while j < n and s[j] not in _DELIM and not (
                s[j] == ":" and (j + 1 >= n or s[j + 1] in " \t,")):
            j += 1
        out.append(_Tok("atom", s[i:j], i, j)); i = j
    return out


def _depth_delta(toks):
    d = 0
    for t in toks:
        if t.kind in "[{(":
            d += 1
        elif t.kind in "]})":
            d -= 1
    return d


class _State:                    # limits and depth of the document being parsed (prototype: not thread-safe)
    L = DEFAULT_LIMITS
    depth = 0
    tables = True
    tables_used = 0                 # outer table headers met by the last parse_ai call (WB-1 §6)
    table_lists = 0                 # lists built from table syntax (outer tables + nested table cells)


class WeftNextTableNotAllowed(WeftNextError):
    """Table syntax was used while parse_ai(..., allow_tables=False)."""


def _enter(line, src):
    _State.depth += 1
    if _State.depth > _State.L.max_depth:
        raise WeftNextLimitError(f"nesting depth exceeds max_depth={_State.L.max_depth}", line, src)


def _leave():
    _State.depth -= 1


def _atom(text, line, src):
    if text == "null":
        return None
    if text.startswith("\\") and len(text) > 1:
        try:
            return S(text[1:])
        except (ValueError, TypeError) as e:
            raise WeftNextError(f"not a valid Symbol name after \\: {text[1:]!r} ({e})", line, src)
    try:
        v = weft.parse(text, limits=_State.L.v1())
    except weft.WeftLimitError as e:
        raise WeftNextLimitError(f"{e}", line, src)
    except weft.WeftError as e:
        raise WeftNextError(f"not a value: {text!r} ({e.__class__.__name__})", line, src)
    if isinstance(v, (list, dict, X)):
        raise WeftNextError(f"not a scalar: {text!r}", line, src)
    return _from_text(v, line, src)


def _v1parse(text, line, src):
    try:
        return weft.parse(text, limits=_State.L.v1())
    except weft.WeftLimitError as e:
        raise WeftNextLimitError(f"{e}", line, src)
    except weft.WeftError as e:
        raise WeftNextError(f"not a value: {text!r} ({e.__class__.__name__})", line, src)


def _key_name(tok, line, src):
    if tok.kind == "str":
        name = _v1parse(tok.text, line, src)
    elif tok.text.startswith(":"):
        name = tok.text[1:]
    else:
        name = tok.text
    try:
        weft.parse(":" + name, limits=_State.L.v1())
    except weft.WeftLimitError as e:
        raise WeftNextLimitError(f"{e}", line, src)
    except weft.WeftError:
        raise WeftNextError(f"not a valid key name: {name!r}", line, src)
    return name


class _Flow:
    def __init__(self, toks, line, src):
        self.t, self.i, self.line, self.src = toks, 0, line, src

    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else None

    def take(self, kind=None):
        t = self.peek()
        if t is None or (kind and t.kind != kind):
            want = kind or "a value"
            raise WeftNextError(f"expected {want!r}", self.line, self.src)
        self.i += 1
        return t

    def value(self):
        t, n = self.peek(), self.peek(1)
        cont = t is not None and (t.kind in ("[", "{", "(") or (
            t.kind == "atom" and n is not None and n.kind == "(" and n.start == t.end))
        if cont:
            _enter(self.line, self.src)
        v = self._value()
        if cont:
            _leave()
        return v

    def _value(self):
        t = self.peek()
        if t is None:
            raise WeftNextError("expected a value", self.line, self.src)
        if t.kind == "[":
            self.i += 1; xs = []
            while self.peek() is not None and self.peek().kind != "]":
                xs.append(self.value())
            self.take("]"); return xs
        if t.kind == "{":
            self.i += 1; m = {}
            while self.peek() is not None and self.peek().kind != "}":
                kt = self.take()
                if kt.kind not in ("atom", "str"):
                    raise WeftNextError("expected a key", self.line, self.src)
                name = _key_name(kt, self.line, self.src)
                if self.peek() is not None and self.peek().kind == "colon":
                    self.i += 1
                elif not (kt.kind == "atom" and kt.text.startswith(":")):
                    raise WeftNextError(f"expected ':' after key {name!r}", self.line, self.src)
                if name in m:
                    raise WeftNextError(f"duplicate key {name!r}", self.line, self.src)
                m[name] = self.value()
            self.take("}"); return m
        if t.kind == "(":                       # Weft 1.x Sexpr (tag ...)
            self.i += 1
            tag = self.take("atom")
            items = []
            while self.peek() is not None and self.peek().kind != ")":
                items.append(self.value())
            self.take(")")
            return X(_tag_symbol(tag.text, self.line, self.src), items)
        if t.kind == "atom":
            self.i += 1
            nx = self.peek()
            if nx is not None and nx.kind == "(" and nx.start == t.end:   # tag(a, b)
                if t.text == "table":
                    raise WeftNextError("table(...) is only allowed at the end of a `key:` line "
                                        "(for a tag named table write \\table(...))", self.line, self.src)
                self.i += 1; items = []
                while self.peek() is not None and self.peek().kind != ")":
                    items.append(self.value())
                self.take(")")
                return X(_tag_symbol(t.text, self.line, self.src), items)
            return _atom(t.text, self.line, self.src)
        if t.kind == "str":
            self.i += 1
            return _v1parse(t.text, self.line, self.src)
        raise WeftNextError(f"unexpected {t.text!r}", self.line, self.src)


def _tag_symbol(text, line, src):
    v = _atom(text, line, src)
    if not isinstance(v, S):
        raise WeftNextError(f"a tag must be a symbol: {text!r}", line, src)
    return v


# ------------------------------------------------------------ tables
def _is_table_head(body):
    return body.startswith("table(")


def _table_spec(f):
    """f is positioned on the `table` atom; returns [(name, subspec|None), ...]."""
    f.take("atom"); f.take("(")
    spec, seen = [], set()
    while f.peek() is not None and f.peek().kind != ")":
        kt = f.take()
        if kt.kind not in ("atom", "str"):
            raise WeftNextError("expected a column name", f.line, f.src)
        name = _key_name(kt, f.line, f.src)
        if name in seen:
            raise WeftNextError(f"duplicate column {name!r}", f.line, f.src)
        seen.add(name)
        sub = None
        if f.peek() is not None and f.peek().kind == "colon":
            f.i += 1
            nt = f.peek()
            if nt is None or nt.text != "table":
                raise WeftNextError(f"expected table(...) after column {name!r}:", f.line, f.src)
            sub = _table_spec(f)
        spec.append((name, sub))
    f.take(")")
    if not spec:
        raise WeftNextError("a table needs at least one column", f.line, f.src)
    return spec


def _record(spec, vals, line, src, omitted=None):
    _enter(line, src)
    try:
        return _record1(spec, vals, line, src, omitted)
    finally:
        _leave()


def _record1(spec, vals, line, src, omitted):
    if not isinstance(vals, list) or len(vals) != len(spec):
        got = len(vals) if isinstance(vals, list) else "not a row"
        raise WeftNextError(f"row has {got} values but the table has {len(spec)} columns "
                            f"({', '.join(n for n, _ in spec)})", line, src)
    m = {}
    if omitted is not None:
        omitted[0] += 2                               # map node: tag + length >= 2 bytes
    for (name, sub), v in zip(spec, vals):
        if omitted is not None:
            nb = len(name.encode("utf-8"))
            omitted[0] += _uvlen(nb) + nb + 2         # key prefix + key + value (>= 2 bytes)
        if sub is not None:
            if not isinstance(v, list):
                raise WeftNextError(f"column {name!r} is a table: write [[...], ...]", line, src)
            _enter(line, src)
            v = [_record(sub, r, line, src, omitted) for r in v]
            _leave()
            _State.table_lists += 1
        m[name] = v
    return m


# ------------------------------------------------------------ block parser
def _strip_comment(s):
    out, i, n, q = [], 0, len(s), False
    while i < n:
        c = s[i]
        if q:
            if c == "\\":
                out.append(s[i:i + 2]); i += 2; continue
            if c == '"':
                q = False
            out.append(c); i += 1; continue
        if c == '"':
            q = True; out.append(c); i += 1; continue
        if c == ";":
            break
        if c == "#" and (i + 1 >= n or s[i + 1] in " \t"):
            break
        out.append(c); i += 1
    return "".join(out).rstrip()


class _Line:
    __slots__ = ("no", "raw", "indent", "body", "tab")

    def __init__(self, no, raw):
        self.no, self.raw = no, raw
        lead = len(raw) - len(raw.lstrip(" "))
        self.indent = lead
        self.tab = raw[lead:lead + 1] == "\t" and raw.strip() != ""
        self.body = _strip_comment(raw[lead:]).strip()


def _is_entry(body, no):
    if body.startswith("- ") or body == "-":
        return False
    try:
        toks = _tokens(body, no)
    except WeftNextError:
        return False
    return (len(toks) >= 2 and toks[0].kind in ("atom", "str")
            and toks[1].kind == "colon" and toks[1].start == toks[0].end)


class _Doc:
    def __init__(self, text, max_value_bytes):
        self.limit = max_value_bytes
        self.omitted = [len(MAGIC)]                   # d5 §2.1: lower bound of the canonical binary size
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        self.raw = text.split("\n")
        self.lines = [_Line(i + 1, r) for i, r in enumerate(self.raw)]
        self.i = 0

    def skip_blank(self):
        while self.i < len(self.lines) and self.lines[self.i].body == "":
            self.i += 1

    def cur(self):
        self.skip_blank()
        if self.i >= len(self.lines):
            return None
        ln = self.lines[self.i]
        if ln.tab:
            raise WeftNextError("tab in indentation", ln.no, ln.raw)
        return ln

    def block(self, indent):
        ln = self.cur()
        if ln.body in ("|", "|-"):
            return self.text_block(indent, ln, ln.body)
        if ln.body.startswith("- ") or ln.body == "-":
            return self.seq(indent)
        if _is_entry(ln.body, ln.no):
            return self.mapping(indent)
        if _is_table_head(ln.body):
            return self.table(ln.body, indent, ln)
        v = self.flow(ln.body, ln)
        nx = self.cur()
        if nx is not None and nx.indent > indent:
            raise WeftNextError("unexpected indentation after a value", nx.no, nx.raw)
        return v

    def flow(self, body, ln):
        f = _Flow(self.flow_tokens(body, ln), ln.no, ln.raw)
        v = f.value()
        if f.peek() is not None:
            raise WeftNextError("more than one value here (quote text as a string?)", ln.no, ln.raw)
        return v

    def table(self, body, indent, ln):
        if not _State.tables:
            raise WeftNextTableNotAllowed("table syntax is not allowed in this mode", ln.no, ln.raw)
        _State.tables_used += 1             # counted when the header is met, even if the table then fails
        f = _Flow(_tokens(body, ln.no), ln.no, ln.raw)
        spec = _table_spec(f)
        if f.peek() is not None:
            raise WeftNextError("unexpected text after the table header", ln.no, ln.raw)
        self.i += 1
        rows, row_indent = [], None
        _enter(ln.no, ln.raw)
        while True:
            nx = self.cur()
            if nx is None or nx.indent <= indent:
                _leave()
                _State.table_lists += 1
                return rows
            if row_indent is None:
                row_indent = nx.indent
            elif nx.indent != row_indent:
                raise WeftNextError("table rows must share one indentation", nx.no, nx.raw)
            rf = _Flow(self.flow_tokens(nx.body, nx), nx.no, nx.raw)
            vals = []
            while rf.peek() is not None:
                vals.append(rf.value())
            rows.append(_record(spec, vals, nx.no, nx.raw, self.omitted))
            if self.omitted[0] > self.limit:
                raise WeftNextLimitError(f"tables expand beyond max_value_bytes={self.limit} "
                                    "(lower bound of the canonical binary size of the table rows so far)", nx.no, nx.raw)

    def flow_tokens(self, body, ln):
        toks = _tokens(body, ln.no)
        self.i += 1
        while _depth_delta(toks) > 0:            # JSON-style multi-line brackets
            if self.i >= len(self.lines):
                raise WeftNextError("bracket not closed", ln.no, ln.raw)
            more = self.lines[self.i]; self.i += 1
            if more.body:
                base = len(body) + 1
                body = body + " " + more.body
                toks += [_Tok(t.kind, t.text, t.start + base, t.end + base)
                         for t in _tokens(more.body, more.no)]
        return toks

    def child(self, indent, ln, under_key):
        self.i += 1
        nx = self.cur()
        if (under_key and nx is not None and nx.indent == indent
                and (nx.body.startswith("- ") or nx.body == "-")):
            return self.seq(indent)                # YAML: list at the key's indent
        if nx is None or nx.indent <= indent:
            return None                           # `key:` / `-` with nothing -> nil
        return self.block(nx.indent)

    def text_block(self, indent, ln, chomp):
        rows, base = [], None
        self.i += 1
        while self.i < len(self.lines):
            r = self.lines[self.i].raw
            if r.strip() == "":
                if r != "":
                    raise WeftNextError("whitespace-only line in a text block", self.i + 1, r)
                rows.append(None); self.i += 1; continue
            lead = len(r) - len(r.lstrip(" "))
            if lead <= indent:
                break
            if base is None:
                base = lead
            if lead < base:
                raise WeftNextError("text block line is less indented than its first line", self.i + 1, r)
            rows.append(r[base:]); self.i += 1
        while rows and rows[-1] is None:
            rows.pop(); self.i -= 1
        s = "\n".join("" if x is None else x for x in rows)
        return s + ("\n" if (chomp == "|" and rows) else "")

    def value_after(self, rest, indent, ln, col):
        rest = rest.strip()
        if rest == "":
            return self.child(indent, ln, col is None)
        if rest in ("|", "|-"):
            return self.text_block(indent, ln, rest)
        if col is None and _is_table_head(rest):
            return self.table(rest, indent, ln)
        if col is not None and (rest.startswith("- ") or rest == "-" or _is_entry(rest, ln.no)):
            ln.indent, ln.body = col, rest          # compact `- key: v` / `- - x` (list items only)
            return self.block(col)
        return self.flow(rest, ln)

    def mapping(self, indent):
        _enter(self.lines[self.i].no if self.i < len(self.lines) else None, None)
        try:
            return self._mapping(indent)
        finally:
            _leave()

    def seq(self, indent):
        _enter(self.lines[self.i].no if self.i < len(self.lines) else None, None)
        try:
            return self._seq(indent)
        finally:
            _leave()

    def _mapping(self, indent):
        m = {}
        while True:
            ln = self.cur()
            if ln is None or ln.indent < indent:
                return m
            if ln.indent > indent:
                raise WeftNextError("unexpected indentation", ln.no, ln.raw)
            if not _is_entry(ln.body, ln.no):
                raise WeftNextError("expected `key: value` here", ln.no, ln.raw)
            toks = _tokens(ln.body, ln.no)
            name = _key_name(toks[0], ln.no, ln.raw)
            if name in m:
                raise WeftNextError(f"duplicate key {name!r}", ln.no, ln.raw)
            rest = ln.body[toks[1].end:]
            if _is_entry(rest.strip(), ln.no):
                raise WeftNextError("a map cannot start on the same line as its key", ln.no, ln.raw)
            m[name] = self.value_after(rest, indent, ln, None)

    def _seq(self, indent):
        xs = []
        while True:
            ln = self.cur()
            if ln is None or ln.indent < indent:
                return xs
            if ln.indent > indent:
                raise WeftNextError("unexpected indentation", ln.no, ln.raw)
            if not (ln.body.startswith("- ") or ln.body == "-"):
                return xs if xs else self._bad(ln)
            rest = ln.body[1:]
            col = indent + 1 + (len(rest) - len(rest.lstrip(" ")))
            xs.append(self.value_after(rest, indent, ln, col))

    def _bad(self, ln):
        raise WeftNextError("expected `- item` here", ln.no, ln.raw)


def tables_used():
    """Outer table headers met by the last parse_ai call (also when the parse then failed)."""
    return _State.tables_used


def table_lists():
    """Lists the last parse_ai call built from table syntax: each outer table and each nested
    table cell (complete only when the parse succeeded)."""
    return _State.table_lists


def parse_ai(text, limits=DEFAULT_LIMITS, allow_tables=True):
    """AI surface -> value. d5 limits: input size, nesting depth while reading,
    1.x scalar limits, the table early check (a lower bound of the canonical
    binary size compared with limits.max_value_bytes), then check_value."""
    _State.tables_used = 0                    # WBPF2-01: reset before any check that can fail
    _State.table_lists = 0
    n = len(text.encode("utf-8"))
    if n > limits.max_size_bytes:
        raise WeftNextLimitError(f"input of {n} bytes exceeds max_size_bytes={limits.max_size_bytes}")
    saved = (_State.L, _State.depth, _State.tables)
    _State.L, _State.depth, _State.tables = limits, 0, allow_tables
    try:
        d = _Doc(text, limits.max_value_bytes)
        ln = d.cur()
        if ln is None:
            raise WeftNextError("empty document")
        v = d.block(ln.indent)
        rest = d.cur()
        if rest is not None:
            raise WeftNextError("unexpected content after the document", rest.no, rest.raw)
    finally:
        _State.L, _State.depth, _State.tables = saved
    check_value(v, limits)
    return v


# ------------------------------------------------------------ AI-surface emitter
_BIDI = set("‪‫‬‭‮⁦⁧⁨⁩")


def _inline(v):
    if isinstance(v, list):
        return "[" + ", ".join(_inline(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k}: {_inline(v[k])}"
                               for k in sorted(v, key=lambda k: k.encode())) + "}"
    if isinstance(v, X):
        return f"{_inline(v.tag)}(" + ", ".join(_inline(x) for x in v.items) + ")"
    if isinstance(v, S) and v.name in ("null", "-", "table"):
        return "\\" + v.name
    return _scalar_text(v)


def _shape(recs):
    """Column spec if recs (a list of dicts) can be written as a table, else None."""
    if not recs or not all(isinstance(r, dict) and r for r in recs):
        return None
    keys = sorted(recs[0], key=lambda k: k.encode())
    if any(sorted(r, key=lambda k: k.encode()) != keys for r in recs):
        return None
    spec = []
    for k in keys:
        col = [r[k] for r in recs]
        sub = None
        if all(isinstance(c, list) for c in col):
            inner = [x for c in col for x in c]
            sub = _shape(inner)
        spec.append((k, sub))
    return spec


_EMIT_TABLES = [True]


def _table_spec_ok(v):
    return _EMIT_TABLES[0] and isinstance(v, list) and len(v) >= 2 and _shape(v) is not None


def _head(spec):
    return "table(" + ", ".join(k if sub is None else f"{k}: {_head(sub)}"
                                for k, sub in spec) + ")"


def _cells(spec, r):
    return " ".join(_inline(r[k]) if sub is None
                    else "[" + " ".join("[" + _cells(sub, x) + "]" for x in r[k]) + "]"
                    for k, sub in spec)


def _table_lines(v, pad):
    spec = _shape(v)
    return _head(spec), [pad + _cells(spec, r) for r in v]


def _block_ok(s):
    if "\n" not in s or "\r" in s or s.endswith("\n\n"):
        return False
    body = s[:-1] if s.endswith("\n") else s
    rows = body.split("\n")
    if rows[0] == "" or rows[0][0] in " \t":
        return False
    for r in rows:
        if r != "" and r.strip() == "":
            return False
        if any((ord(c) < 32 and c != "\t") or 0x7F <= ord(c) <= 0x9F or c in _BIDI for c in r):
            return False
    return True


def _is_block(v):
    return (isinstance(v, (list, dict)) and len(v) > 0
            and (len(_inline(v)) > 60 or any(_is_block(x) or _is_text(x)
                                             for x in (v.values() if isinstance(v, dict) else v))))


def _is_text(v):
    return isinstance(v, str) and _block_ok(v)


def _text_lines(s, pad):
    chomp = "|" if s.endswith("\n") else "|-"
    body = s[:-1] if s.endswith("\n") else s
    return chomp, [(pad + r) if r else "" for r in body.split("\n")]


def _emit(v, indent, out):
    pad = " " * indent
    if isinstance(v, dict):
        for k in sorted(v, key=lambda k: k.encode()):
            x = v[k]
            if _is_text(x):
                chomp, rows = _text_lines(x, pad + "  ")
                out.append(f"{pad}{k}: {chomp}"); out += rows
            elif _is_block(x) and _table_spec_ok(x):              # D6-05: inline first
                head, rows = _table_lines(x, pad + "  ")
                out.append(f"{pad}{k}: {head}"); out += rows
            elif _is_block(x):
                out.append(f"{pad}{k}:"); _emit(x, indent + 2, out)
            else:
                out.append(f"{pad}{k}: {_inline(x)}")
    else:
        for x in v:
            if _is_text(x):
                chomp, rows = _text_lines(x, pad + "  ")
                out.append(f"{pad}- {chomp}"); out += rows
            elif _is_block(x) and isinstance(x, dict):
                sub = []
                _emit(x, indent + 2, sub)
                out.append(pad + "- " + sub[0][indent + 2:]); out += sub[1:]
            elif _is_block(x):
                out.append(f"{pad}-"); _emit(x, indent + 2, out)
            else:
                out.append(f"{pad}- {_inline(x)}")


def emit_ai(v, tables=True, limits=None):
    L = DEFAULT_LIMITS if limits is None else limits
    check_value(v, L)                                                # d6 §2
    saved = _EMIT_TABLES[0]
    _EMIT_TABLES[0] = tables
    try:
        return _fits(_emit_ai(v), L)                                 # D6-01
    finally:
        _EMIT_TABLES[0] = saved


def _emit_ai(v):
    if _is_block(v) and _table_spec_ok(v):
        head, rows = _table_lines(v, "  ")
        return "\n".join([head] + rows) + "\n"
    if _is_block(v):
        out = []
        _emit(v, 0, out)
        return "\n".join(out) + "\n"
    if _is_text(v):
        chomp, rows = _text_lines(v, "  ")
        return "\n".join([chomp] + rows) + "\n"
    return _inline(v) + "\n"
