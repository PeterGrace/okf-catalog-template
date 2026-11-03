#!/usr/bin/env python3
"""okf: bookkeeping CLI for the OKF knowledge catalog.

Handles the mechanical parts of updating the catalog reliably: frontmatter
stamps (generated, verified, reviewed, open_questions, sources), the root
log.md, folder index.md listings, link and freshness reports, linting, and
publishing (commit, pull --rebase, push). Body prose is not its job; edit
that with ordinary file-editing tools.

Every timestamp it writes is the current UTC time; none can be passed in.
Frontmatter edits are textual: only the key being written changes, and every
other byte of the file is preserved.

Standard library only. Run from anywhere:
    python3 {{CATALOG}}/tools/okf.py <command> --help

To write, a session works in its own worktree (`session start --id ID`
prints the path) and runs that worktree's copy of this file, so sessions
never share a working tree.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ACTOR = os.environ.get("OKF_ACTOR") or "claude-code/claude-opus-5-5"
CO_AUTHOR = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"

NON_CONCEPTS = {"index.md", "log.md", "AGENTS.md", "CLAUDE.md", "README.md"}
RESERVED = {"index.md", "log.md"}
SKIP_DIRS = {".git", ".claude", "install"}  # install/ is the template's setup machinery
SKIP_TOP = {"docs", "tests"}  # the template's own development docs and tests, at the root only
STATUSES = {"draft", "stable", "deprecated"}
OUTCOMES = ["verified", "updated", "partial", "unverifiable"]
LOG_KINDS = ["Update", "Creation", "Change", "Import"]
TS_FMT = "%Y-%m-%dT%H:%M:%SZ"
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
FUTURE_SLACK = timedelta(minutes=2)

# Preferred position of top-level frontmatter keys, used only when a key has
# to be created. Existing keys are never moved.
KEY_ORDER = ["type", "title", "description", "resource", "aliases", "tags", "status",
             "generated", "stale_after", "verified", "reviewed", "open_questions", "sources"]


def now_utc():
    return datetime.now(timezone.utc)


def now_stamp():
    return now_utc().strftime(TS_FMT)


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def die(msg, code=1):
    sys.stdout.flush()
    print(f"okf: {msg}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# A small YAML-subset parser covering what OKF frontmatter uses: plain,
# single- and double-quoted scalars, flow maps and lists, block maps and
# lists (nested), comments, and |/> block scalars. Scalars stay strings.
# ---------------------------------------------------------------------------

class YamlError(Exception):
    def __init__(self, msg, line=None):
        super().__init__(msg)
        self.line = line


def _indent(t):
    return len(t) - len(t.lstrip(" "))


class _Inline:
    """Parser for one line's worth of inline YAML (scalar or flow collection)."""

    def __init__(self, s, line):
        self.s, self.i, self.line = s, 0, line

    def err(self, msg):
        raise YamlError(f"{msg} in {self.s!r}", self.line)

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \t":
            self.i += 1

    def peek(self):
        return self.s[self.i] if self.i < len(self.s) else ""

    def node(self, flow):
        self.ws()
        c = self.peek()
        if c == "{":
            return self.fmap()
        if c == "[":
            return self.fseq()
        if c == '"':
            return self.dq()
        if c == "'":
            return self.sq()
        if c in ("&", "*", "!", "|", ">", "%", "@", "`"):
            self.err(f"unsupported YAML indicator {c!r}")
        return self.plain(flow)

    def dq(self):
        self.i += 1
        out = []
        esc = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/", "0": "\0",
               " ": " ", "b": "\b", "f": "\f", "e": "\x1b", "a": "\x07", "v": "\v", "N": "\x85",
               "_": "\xa0", "L": " ", "P": " "}
        while True:
            if self.i >= len(self.s):
                self.err("unterminated double-quoted string")
            c = self.s[self.i]
            if c == '"':
                self.i += 1
                return "".join(out)
            if c == "\\":
                n = self.s[self.i + 1:self.i + 2]
                if n in esc:
                    out.append(esc[n])
                    self.i += 2
                elif n in ("x", "u", "U"):
                    width = {"x": 2, "u": 4, "U": 8}[n]
                    hx = self.s[self.i + 2:self.i + 2 + width]
                    if not re.fullmatch(r"[0-9a-fA-F]{%d}" % width, hx):
                        self.err("bad escape")
                    out.append(chr(int(hx, 16)))
                    self.i += 2 + width
                else:
                    self.err(f"invalid escape \\{n}")
            else:
                out.append(c)
                self.i += 1

    def sq(self):
        self.i += 1
        out = []
        while True:
            if self.i >= len(self.s):
                self.err("unterminated single-quoted string")
            c = self.s[self.i]
            if c == "'":
                if self.s[self.i + 1:self.i + 2] == "'":
                    out.append("'")
                    self.i += 2
                    continue
                self.i += 1
                return "".join(out)
            out.append(c)
            self.i += 1

    def plain(self, flow):
        start = self.i
        while self.i < len(self.s):
            c = self.s[self.i]
            nxt = self.s[self.i + 1:self.i + 2]
            if c == "#" and self.i > start and self.s[self.i - 1] in " \t":
                break
            if flow and c in ",]}":
                break
            if c == ":" and (nxt in ("", " ", "\t") or (flow and nxt in ",]}")):
                break
            self.i += 1
        val = self.s[start:self.i].rstrip()
        return None if val in ("", "~", "null", "Null", "NULL") else val

    def key(self):
        self.ws()
        c = self.peek()
        k = self.dq() if c == '"' else self.sq() if c == "'" else self.plain(True)
        self.ws()
        if self.peek() != ":":
            self.err("expected ':' after key")
        self.i += 1
        return k

    def fmap(self):
        self.i += 1
        d = {}
        while True:
            self.ws()
            if self.peek() == "}":
                self.i += 1
                return d
            k = self.key()
            if k in d:
                self.err(f"duplicate key {k!r}")
            self.ws()
            d[k] = None if self.peek() in (",", "}") else self.node(True)
            self.ws()
            c = self.peek()
            if c == ",":
                self.i += 1
            elif c != "}":
                self.err("expected ',' or '}' in flow map")

    def fseq(self):
        self.i += 1
        out = []
        while True:
            self.ws()
            if self.peek() == "]":
                self.i += 1
                return out
            out.append(self.node(True))
            self.ws()
            c = self.peek()
            if c == ",":
                self.i += 1
            elif c != "]":
                self.err("expected ',' or ']' in flow list")

    def finish(self):
        self.ws()
        if self.i < len(self.s) and self.s[self.i] != "#":
            self.err("unexpected trailing text")


def parse_inline(s, line=None):
    p = _Inline(s, line)
    v = p.node(False)
    if p.peek() == ":":
        raise YamlError(f"unquoted ': ' inside a plain value {s!r}; quote it", line)
    p.finish()
    return v


def _strip_comment(s):
    """Strip a trailing comment from an inline value only when it starts the value."""
    t = s.strip()
    return "" if t.startswith("#") else t


MAP_KEY_RE = re.compile(r"^([A-Za-z0-9_][\w.\-/ ]*?|\"(?:[^\"\\]|\\.)*\"|'(?:[^']|'')*')[ \t]*:(?:[ \t]+(.*)|[ \t]*)$")


def _content(lines):
    return [(n, t) for n, t in lines if t.strip() and not t.strip().startswith("#")]


def parse_value(inline, children, line):
    """Parse a key's value: the text after 'key:' plus its indented child lines."""
    s = _strip_comment(inline)
    if s[:1] in ("|", ">"):
        texts = [t for _, t in children]
        ind = min((_indent(t) for t in texts if t.strip()), default=0)
        body = [t[ind:] for t in texts]
        return ("\n" if s[0] == "|" else " ").join(body).rstrip("\n") + "\n"
    if s:
        if s[0] in "[{" and _content(children):
            s = " ".join([s] + [t.strip() for _, t in children])
        elif _content(children):
            raise YamlError("value on the key line and indented lines below it", line)
        return parse_inline(s, line)
    content = _content(children)
    return parse_node(content) if content else None


def parse_node(content):
    ind = _indent(content[0][1])
    first = content[0][1][ind:]
    if first == "-" or first.startswith("- "):
        return parse_seq(content, ind)
    return parse_map(content, ind)


def _split_items(content, ind, is_start):
    i = 0
    while i < len(content):
        n, t = content[i]
        if _indent(t) != ind or not is_start(t[ind:]):
            raise YamlError(f"bad indentation or structure: {t.strip()!r}", n)
        j = i + 1
        while j < len(content) and _indent(content[j][1]) > ind:
            j += 1
        yield content[i], content[i + 1:j]
        i = j


def _seq_start(t):
    return t == "-" or t.startswith("- ")


def parse_seq(content, ind):
    items = []
    for (n, t), kids in _split_items(content, ind, _seq_start):
        rest = t[ind + 1:]
        r = rest.strip()
        if not r or r.startswith("#"):
            items.append(parse_node(kids) if kids else None)
            continue
        off = ind + 1 + _indent(rest)
        if r[0] not in "[{\"'" and MAP_KEY_RE.match(r):
            items.append(parse_map([(n, " " * off + r)] + kids, off))
        else:
            items.append(parse_value(r, kids, n))
    return items


def parse_map(content, ind):
    d = {}
    i = 0
    while i < len(content):
        n, t = content[i]
        if _indent(t) != ind:
            raise YamlError(f"bad indentation: {t.strip()!r}", n)
        m = MAP_KEY_RE.match(t[ind:])
        if not m:
            raise YamlError(f"expected 'key: value', got {t.strip()!r}", n)
        j = i + 1
        # Children are more indented, or a block list at the same indent.
        while j < len(content) and (_indent(content[j][1]) > ind or
                                    (_indent(content[j][1]) == ind and _seq_start(content[j][1][ind:])
                                     and not (m.group(2) or "").strip())):
            j += 1
        k = m.group(1)
        if k[0] in "\"'":
            k = parse_inline(k, n)
        if k in d:
            raise YamlError(f"duplicate key {k!r}", n)
        d[k] = parse_value(m.group(2) or "", content[i + 1:j], n)
        i = j
    return d


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

PLAIN_SAFE = re.compile(r"^[A-Za-z0-9_./~+()][^\n\t]*$")
RESERVED_WORDS = {"true", "false", "yes", "no", "on", "off", "null", "~", "y", "n"}


def needs_quote(s, flow=False):
    if s == "" or s != s.strip() or not PLAIN_SAFE.match(s):
        return True
    if s.lower() in RESERVED_WORDS or ": " in s or " #" in s or s.endswith(":"):
        return True
    if flow and any(c in s for c in ",[]{}"):
        return True
    if re.fullmatch(r"[-+]?(\d[\d_]*)?\.?\d*([eE][-+]?\d+)?", s):
        return True
    return False


def dquote(s):
    out = ['"']
    for c in s:
        if c == '"':
            out.append('\\"')
        elif c == "\\":
            out.append("\\\\")
        elif c == "\n":
            out.append("\\n")
        elif c == "\t":
            out.append("\\t")
        elif ord(c) < 0x20 or ord(c) == 0x7f:
            out.append("\\x%02x" % ord(c))
        else:
            out.append(c)
    out.append('"')
    return "".join(out)


def scalar(s, flow=False, force=False):
    s = str(s)
    return dquote(s) if force or needs_quote(s, flow) else s


def flow_value(v):
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{scalar(k, True)}: {flow_value(x)}" for k, x in v.items()) + " }"
    if isinstance(v, list):
        return "[" + ", ".join(flow_value(x) for x in v) + "]"
    if v is None:
        return "null"
    return scalar(v, True)


def block_item(v, ind):
    """Render one block-list item as lines (no trailing newline)."""
    pad = " " * ind
    if isinstance(v, dict) and v and all(not isinstance(x, (dict, list)) for x in v.values()):
        lines = []
        for i, (k, x) in enumerate(v.items()):
            lead = pad + "- " if i == 0 else pad + "  "
            lines.append(f"{lead}{scalar(k)}: {scalar(x) if x is not None else ''}".rstrip())
        return lines
    if isinstance(v, (dict, list)):
        return [pad + "- " + flow_value(v)]
    return [pad + "- " + scalar(v)]


# ---------------------------------------------------------------------------
# Documents and frontmatter editing
# ---------------------------------------------------------------------------

class Doc:
    """A markdown file split into frontmatter lines and everything else."""

    def __init__(self, path):
        self.path = path
        with open(path, encoding="utf-8", newline="") as fh:
            self.text = fh.read()
        lines = self.text.splitlines(keepends=True)
        self.has_fm = False
        self.fm = []
        self.head, self.tail = [], lines
        if lines and lines[0].rstrip("\r\n") == "---":
            for j in range(1, len(lines)):
                if lines[j].rstrip("\r\n").rstrip() in ("---", "..."):
                    self.has_fm = True
                    self.head = lines[:1]
                    self.fm = [l.rstrip("\r\n") for l in lines[1:j]]
                    self.tail = lines[j:]
                    break
        self.nl = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"

    def blocks(self):
        """[(key, start, end)] with fm[start] the 'key:' line, fm[start+1:end] its continuation."""
        out = []
        n = len(self.fm)
        i = 0
        while i < n:
            m = re.match(r"^([A-Za-z_][\w.\-]*)[ \t]*:(?:[ \t]|$)", self.fm[i])
            if not m:
                i += 1
                continue
            last = i
            j = i + 1
            while j < n:
                t = self.fm[j]
                if not t.strip():
                    j += 1
                    continue
                if t[0] in " \t" or t == "-" or t.startswith("- "):
                    last = j
                    j += 1
                    continue
                break
            out.append((m.group(1), i, last + 1))
            i = last + 1
        return out

    def block(self, key):
        for k, s, e in self.blocks():
            if k == key:
                return s, e
        return None

    def parse(self):
        """Return the frontmatter as a dict; raise YamlError on anything unreadable."""
        data = {}
        covered = set()
        for k, s, e in self.blocks():
            if k in data:
                raise YamlError(f"duplicate key {k!r}", s + 2)
            inline = self.fm[s].split(":", 1)[1]
            children = [(s + 2 + i, t) for i, t in enumerate(self.fm[s + 1:e])]
            data[k] = parse_value(inline, children, s + 2)
            covered.update(range(s, e))
        for i, t in enumerate(self.fm):
            if i not in covered and t.strip() and not t.lstrip().startswith("#"):
                raise YamlError(f"line is not part of any key: {t.strip()!r}", i + 2)
        return data

    def key_line(self, key):
        b = self.block(key)
        return b[0] + 2 if b else 1

    def render(self):
        body = "".join(l + self.nl for l in self.fm)
        return "".join(self.head) + body + "".join(self.tail)

    def set_block(self, key, new_lines):
        """Replace (or insert) a top-level key's lines."""
        b = self.block(key)
        if b:
            s, e = b
            self.fm[s:e] = new_lines
            return
        blocks = self.blocks()
        pos = len(self.fm)
        # Trailing blank lines at the end of the frontmatter stay at the end.
        while pos > 0 and not self.fm[pos - 1].strip():
            pos -= 1
        if key in KEY_ORDER:
            rank = KEY_ORDER.index(key)
            before = [e for k, s, e in blocks if k in KEY_ORDER and KEY_ORDER.index(k) < rank]
            after = [s for k, s, e in blocks if k in KEY_ORDER and KEY_ORDER.index(k) > rank]
            if before:
                pos = max(before)
            elif after:
                pos = min(after)
        self.fm[pos:pos] = new_lines

    def delete_block(self, key):
        b = self.block(key)
        if b:
            del self.fm[b[0]:b[1]]

    def seq_items(self, key):
        """For a block-list key: (item_indent, [(start, end)]) spans in self.fm, else None."""
        b = self.block(key)
        if not b:
            return None
        s, e = b
        if _strip_comment(self.fm[s].split(":", 1)[1]):
            return None
        spans, ind = [], None
        for i in range(s + 1, e):
            t = self.fm[i]
            if not t.strip() or t.strip().startswith("#"):
                continue
            if ind is None:
                ind = _indent(t)
                if not _seq_start(t[ind:]):
                    return None
            if _indent(t) == ind and _seq_start(t[ind:]):
                spans.append([i, i + 1])
            elif _indent(t) > ind and spans:
                spans[-1][1] = i + 1
            else:
                return None
        return (ind if ind is not None else 2), [tuple(x) for x in spans]

    def save(self):
        new = self.render()
        check = Doc.__new__(Doc)
        check.fm = self.fm
        try:
            check.parse()
        except YamlError as ex:
            die(f"refusing to write {self.path}: edited frontmatter would not parse ({ex})")
        with open(self.path, "w", encoding="utf-8", newline="") as fh:
            fh.write(new)


def append_seq_item(doc, key, item_lines_fn, value, render=block_item):
    """Append an item to a list-valued key, creating or normalising the key as needed.

    item_lines_fn(indent) returns the new item's lines; render(value, indent) renders
    existing items when a flow list has to be rewritten as a block list.
    """
    b = doc.block(key)
    if b is None or value is None:
        doc.set_block(key, [f"{key}:"] + item_lines_fn(2))
        return
    s, e = b
    seq = doc.seq_items(key)
    if seq and isinstance(value, list):
        ind, spans = seq
        end = spans[-1][1] if spans else e
        doc.fm[end:end] = item_lines_fn(ind)
        return
    inline = _strip_comment(doc.fm[s].split(":", 1)[1])
    if isinstance(value, dict):
        if inline:  # bare flow mapping: keep its text as the first item
            lines = [f"{key}:", f"  - {inline}"]
        else:  # bare block mapping: indent it under '- '
            kids = [t for t in doc.fm[s + 1:e]]
            ind = min(_indent(t) for t in kids if t.strip())
            lines = [f"{key}:"]
            first = True
            for t in kids:
                if not t.strip():
                    lines.append(t)
                elif first and _indent(t) == ind:
                    lines.append(" " * ind + "- " + t[ind:])
                    first = False
                else:
                    lines.append("  " + t)
        doc.fm[s:e] = lines + item_lines_fn(2 if inline else ind)
        return
    if isinstance(value, list):  # flow list: re-render as a block list
        lines = [f"{key}:"]
        for v in value:
            lines += render(v, 2)
        doc.fm[s:e] = lines + item_lines_fn(2)
        return
    die(f"{key} has an unexpected shape ({type(value).__name__}); fix it by hand")


# ---------------------------------------------------------------------------
# Catalog paths
# ---------------------------------------------------------------------------

def walk_md(root):
    for dirpath, dirnames, filenames in os.walk(root):
        top = os.path.normpath(dirpath) == os.path.normpath(root)
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
                             and not (top and d in SKIP_TOP))
        for f in sorted(filenames):
            if f.endswith(".md"):
                yield os.path.relpath(os.path.join(dirpath, f), root)


def is_concept(rel):
    return os.path.basename(rel) not in NON_CONCEPTS


def concepts(root):
    return [p for p in walk_md(root) if is_concept(p)]


def resolve_concept(root, arg):
    """Accept /dir/x.md, dir/x, /dir/x, or a filesystem path; return the bundle-relative path."""
    cand = []
    if os.path.isabs(arg) and os.path.exists(arg):
        cand.append(os.path.relpath(os.path.realpath(arg), os.path.realpath(root)))
    if os.path.exists(arg) and not os.path.isabs(arg):
        cand.append(os.path.relpath(os.path.realpath(arg), os.path.realpath(root)))
    a = arg.lstrip("/")
    cand += [a, a + ".md"]
    for c in cand:
        c = os.path.normpath(c)
        if c.startswith(".."):
            continue
        if os.path.isfile(os.path.join(root, c)) and c.endswith(".md"):
            if not is_concept(c):
                die(f"{c} is not a concept document")
            return c
    die(f"no concept {arg!r} in {root}")


def load_concept(root, arg):
    rel = resolve_concept(root, arg)
    doc = Doc(os.path.join(root, rel))
    if not doc.has_fm:
        die(f"{rel} has no frontmatter; add it with your editor first")
    try:
        data = doc.parse()
    except YamlError as ex:
        die(f"{rel}: frontmatter does not parse (line {ex.line}: {ex}); fix it by hand first")
    return rel, doc, data


# ---------------------------------------------------------------------------
# stamp / review / unquestion / source
# ---------------------------------------------------------------------------

def cmd_stamp(a):
    rel, doc, data = load_concept(a.root, a.concept)
    item = {"by": a.by, "at": now_stamp()}
    if a.field == "generated":
        doc.set_block("generated", [f"generated: {flow_value(item)}"])
    else:
        append_seq_item(doc, "verified", lambda ind: [" " * ind + "- " + flow_value(item)],
                        data.get("verified"))
    doc.save()
    print(f"{rel}: {a.field} {flow_value(item)}")


def cmd_review(a):
    rel, doc, data = load_concept(a.root, a.concept)
    ts = now_stamp()
    doc.set_block("reviewed", ["reviewed:", f"  by: {scalar(a.by)}", f"  at: {ts}",
                               f"  outcome: {a.outcome}", f"  note: {scalar(a.note, force=True)}"])
    added = []
    existing = data.get("open_questions")
    have = list(existing) if isinstance(existing, list) else []
    for q in a.question or []:
        if q in have or q in added:
            print(f"{rel}: open question already queued: {q}")
            continue
        current = doc.parse().get("open_questions")
        append_seq_item(doc, "open_questions",
                        lambda ind, q=q: [" " * ind + "- " + scalar(q, force=True)], current,
                        render=lambda v, ind: [" " * ind + "- " + scalar(v, force=True)])
        added.append(q)
    doc.save()
    print(f"{rel}: reviewed {a.outcome} at {ts}" + (f"; queued {len(added)} question(s)" if added else ""))


def cmd_unquestion(a):
    rel, doc, data = load_concept(a.root, a.concept)
    qs = data.get("open_questions")
    if not isinstance(qs, list) or not qs:
        die(f"{rel} has no open_questions")
    if a.question.isdigit():
        idx = int(a.question) - 1
        if not 0 <= idx < len(qs):
            die(f"{rel} has {len(qs)} open question(s); index {a.question} is out of range (1-based)")
    elif a.question in qs:
        idx = qs.index(a.question)
    else:
        die(f"no open question in {rel} exactly matches {a.question!r}")
    removed = qs[idx]
    if len(qs) == 1:
        doc.delete_block("open_questions")
    else:
        seq = doc.seq_items("open_questions")
        if seq and len(seq[1]) == len(qs):
            s, e = seq[1][idx]
            del doc.fm[s:e]
        else:
            rest = qs[:idx] + qs[idx + 1:]
            doc.set_block("open_questions", ["open_questions:"] +
                          [f"  - {scalar(q, force=True)}" for q in rest])
    doc.save()
    left = len(qs) - 1
    print(f"{rel}: removed open question: {removed}" + ("" if left else " (key deleted, none left)"))


def cmd_question(a):
    rel, doc, data = load_concept(a.root, a.concept)
    existing = data.get("open_questions")
    if existing is not None and not isinstance(existing, list):
        die(f"{rel}: open_questions is not a list; fix it by hand")
    if a.question in (existing or []):
        print(f"{rel}: open question already queued: {a.question}")
        return
    append_seq_item(doc, "open_questions", lambda ind: [" " * ind + "- " + scalar(a.question, force=True)],
                    existing, render=lambda v, ind: [" " * ind + "- " + scalar(v, force=True)])
    doc.save()
    print(f"{rel}: queued open question: {a.question}")


def cmd_source(a):
    rel, doc, data = load_concept(a.root, a.concept)
    srcs = data.get("sources")
    if srcs is not None and not isinstance(srcs, list):
        die(f"{rel}: sources is not a list; fix it by hand")
    for s in srcs or []:
        if isinstance(s, dict) and s.get("id") == a.id:
            die(f"{rel} already has a source with id {a.id!r}")
    entry = {"id": a.id, "resource": a.resource}
    if a.title:
        entry["title"] = a.title
    if a.author:
        entry["author"] = a.author
    append_seq_item(doc, "sources", lambda ind: block_item(entry, ind), srcs)
    doc.save()
    print(f"{rel}: added source {a.id}")


# ---------------------------------------------------------------------------
# log / index
# ---------------------------------------------------------------------------

def cmd_log(a):
    path = os.path.join(a.root, "log.md")
    if not os.path.exists(path):
        die(f"no log.md at {a.root}")
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    today = now_utc().strftime("%Y-%m-%d")
    bullet = f"* **{a.kind}:** {' '.join(a.text.split())}"
    heading = f"## {today}"
    if heading in lines:
        h = lines.index(heading)
        i = h + 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        j = i
        while j < len(lines) and not lines[j].startswith("## "):
            if lines[j] == bullet:
                print(f"log.md: already logged under {today}")
                return
            j += 1
        if i < len(lines) and lines[i].startswith("* "):
            lines.insert(i, bullet)
        else:
            lines[h + 1:i] = ["", bullet, ""]
    else:
        first = next((i for i, l in enumerate(lines) if l.startswith("## ")), None)
        if first is not None:
            lines[first:first] = [heading, "", bullet, ""]
        else:
            t = next((i for i, l in enumerate(lines) if l.startswith("# ")), -1)
            while lines and lines[-1] == "":
                lines.pop()
            ins = len(lines) if t == -1 else t + 1
            block = ["", heading, "", bullet]
            if ins < len(lines):
                block.append("")
            lines[ins:ins] = block
            lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"log.md: {heading}: {bullet}")


def cmd_index(a):
    rel, doc, data = load_concept(a.root, a.concept)
    title = a.title or data.get("title")
    if not title:
        die(f"{rel} has no title; pass --title")
    folder = os.path.dirname(rel)
    ipath = os.path.join(a.root, folder, "index.md")
    if not os.path.exists(ipath):
        die(f"no index.md in /{folder}; create it first")
    with open(ipath, encoding="utf-8") as fh:
        text = fh.read()
    for m in LINK_RE.finditer(text):
        tgt, _ = resolve_link(m.group(2), os.path.join(folder, "index.md"), a.root)
        if tgt == rel:
            print(f"{os.path.join(folder, 'index.md')}: already lists {rel}")
            return
    name = os.path.basename(rel)
    label = title.replace("[", "\\[").replace("]", "\\]")
    bullet = f"* [{label}]({name}) - {' '.join(a.summary.split())}"
    insert_index_bullet(ipath, bullet, section=a.section)
    print(f"{os.path.join(folder, 'index.md')}: {bullet}")


# ---------------------------------------------------------------------------
# links (port of .claude/skills/okf-link-check/scripts/link_report.py)
# ---------------------------------------------------------------------------

MIN_NAME_LEN = 4
LINK_RE = re.compile(r"(?<!!)\[((?:[^\]\\]|\\.)*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def split_frontmatter(text):
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            body_start = text.find("\n", end + 4)
            body_start = len(text) if body_start == -1 else body_start + 1
            return text[4:end], text[body_start:], text[:body_start].count("\n")
    return "", text, 0


# ---------------------------------------------------------------------------
# Markdown structure: headings, GitHub-style anchors, footnotes
# ---------------------------------------------------------------------------

HEADING_RE = re.compile(r"^(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")
FOOTDEF_RE = re.compile(r"^\[\^([^\]]+)\]:")
FOOTREF_RE = re.compile(r"\[\^([^\]]+)\](?!:)")
HTML_ANCHOR_RE = re.compile(r"<a\s[^>]*(?:name|id)=[\"']([^\"']+)[\"']", re.I)


def headings(lines):
    """[(index, level, text)] for the ATX headings in lines, skipping fenced code."""
    out, fence = [], None
    for i, line in enumerate(lines):
        f = FENCE_RE.match(line)
        if f:
            fence = None if fence == f.group(1) else (fence or f.group(1))
            continue
        if fence:
            continue
        m = HEADING_RE.match(line)
        if m:
            out.append((i, len(m.group(1)), (m.group(2) or "").strip()))
    return out


def slugify(text):
    """GitHub's heading anchor: rendered text, lowercased, punctuation dropped, spaces to '-'."""
    t = re.sub(r"!?\[((?:[^\]\\]|\\.)*)\]\([^)]*\)", r"\1", text)  # links and images -> their text
    t = re.sub(r"<[^>]+>", "", t).replace("`", "")
    t = re.sub(r"\*+|(?<!\w)_+|_+(?!\w)", "", t)  # emphasis markers, not snake_case
    t = re.sub(r"[^\w\- ]", "", t.strip().lower())
    return t.replace(" ", "-")


def heading_slugs(lines):
    """[(index, level, text, slug)], numbering repeats the way GitHub does (x, x-1, x-2)."""
    seen, out = {}, []
    for i, level, text in headings(lines):
        base = slugify(text)
        slug = base if base not in seen else f"{base}-{seen[base]}"
        seen[base] = seen.get(base, 0) + 1
        seen.setdefault(slug, 1)
        out.append((i, level, text, slug))
    return out


def anchors_in(text):
    """Every fragment a link may target in a markdown document: heading slugs plus HTML anchors."""
    _, body, _ = split_frontmatter(text)
    found = {s for _, _, _, s in heading_slugs(body.split("\n"))}
    return found | set(HTML_ANCHOR_RE.findall(body))


def norm_fragment(frag):
    from urllib.parse import unquote
    return unquote(frag).lower()


def body_split(text):
    """(frontmatter-and-delimiter lines, body lines) of a document's text, split on '\\n'."""
    lines = text.split("\n")
    if lines and lines[0].rstrip("\r") == "---":
        for j in range(1, len(lines)):
            if lines[j].rstrip("\r").rstrip() in ("---", "..."):
                return lines[:j + 1], lines[j + 1:]
    return [], lines


def footnote_defs(lines):
    """{label: [line indexes]} for footnote definitions and their indented continuation lines."""
    defs, cur = {}, None
    for i, line in enumerate(lines):
        m = FOOTDEF_RE.match(line)
        if m:
            cur = m.group(1)
            defs.setdefault(cur, []).append(i)
        elif cur is not None and line.startswith(("    ", "\t")) and line.strip():
            defs[cur].append(i)
        else:
            cur = None
    return defs


def resolve_link(link, src, root):
    """Return (bundle-relative target path or None for external, is_absolute)."""
    target = link.split("#", 1)[0]
    if not target or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
        return None, None
    absolute = target.startswith("/")
    if absolute:
        path = target.lstrip("/")
    else:
        path = os.path.normpath(os.path.join(os.path.dirname(src), target))
    if target.endswith("/") or os.path.isdir(os.path.join(root, path)):
        path = os.path.join(path, "index.md")
    return os.path.normpath(path), absolute


def prose_lines(body, body_offset):
    """Yield (line_no, masked, original) of body prose with code, links and footnotes masked."""
    in_fence = False
    for i, line in enumerate(body.split("\n")):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or re.match(r"^\[\^[^\]]+\]:", line):
            continue
        masked = re.sub(r"`[^`]*`", " ", line)
        masked = LINK_RE.sub(" ", masked)
        masked = re.sub(r"https?://\S+", " ", masked)
        yield body_offset + i + 1, masked, line


def _fm_fallback(fm, key, as_list):
    if not as_list:
        m = re.search(rf"^{key}:\s*(.+?)\s*$", fm, re.M)
        return m.group(1).strip().strip("\"'") if m else None
    m = re.search(rf"^{key}:\s*\[(.*?)\]\s*$", fm, re.M)
    if m:
        return [v.strip().strip("\"'") for v in m.group(1).split(",") if v.strip()]
    m = re.search(rf"^{key}:\s*\n((?:\s+-\s+.+\n?)+)", fm, re.M)
    if m:
        return [v.strip().strip("\"'") for v in re.findall(r"^\s+-\s+(.+)$", m.group(1), re.M)]
    return []


def build_docs(root):
    docs = {}
    for f in walk_md(root):
        if os.path.basename(f) in NON_CONCEPTS - RESERVED and not os.path.dirname(f):
            continue
        with open(os.path.join(root, f), encoding="utf-8") as fh:
            text = fh.read()
        fm, body, offset = split_frontmatter(text)
        base = os.path.basename(f)
        kind = "index" if base == "index.md" else "log" if base == "log.md" else \
            "concept" if is_concept(f) else "machinery"
        try:
            data = Doc(os.path.join(root, f)).parse()
            title = data.get("title") if isinstance(data.get("title"), str) else None
            aliases = data.get("aliases") or []
            aliases = [x for x in (aliases if isinstance(aliases, list) else [aliases]) if isinstance(x, str)]
        except YamlError:
            title, aliases = _fm_fallback(fm, "title", False), _fm_fallback(fm, "aliases", True)
        docs[f] = {"path": f, "kind": kind, "fm": fm, "body": body, "offset": offset,
                   "title": title, "aliases": aliases, "links": []}
        for n, line in enumerate(text.split("\n"), 1):
            for m in LINK_RE.finditer(line):
                raw = m.group(2)
                frag = raw.split("#", 1)[1] if "#" in raw else None
                if raw.startswith("#"):  # in-page anchor: only its fragment needs checking
                    docs[f]["links"].append({"line": n, "raw": raw, "target": f, "absolute": True,
                                             "fragment": frag, "self": True})
                    continue
                target, absolute = resolve_link(raw, f, root)
                if target is not None:
                    docs[f]["links"].append({"line": n, "raw": raw, "target": target, "absolute": absolute,
                                             "fragment": frag})
    return docs


def names_for(doc):
    stem = os.path.basename(doc["path"])[:-3]
    names = {stem}
    if doc["title"]:
        names.add(doc["title"])
    names.update(doc["aliases"])
    return sorted(n for n in names if len(n) >= MIN_NAME_LEN)


def link_analysis(root, docs=None, mentions=True):
    docs = docs or build_docs(root)
    concepts_ = {p: d for p, d in docs.items() if d["kind"] == "concept"}
    report = {"broken": [], "broken_anchors": [], "relative": [], "orphans": [], "dead_ends": [],
              "index_drift": [], "unlinked_mentions": []}

    anchors = {}
    inbound = {p: set() for p in concepts_}
    for p, d in docs.items():
        for l in d["links"]:
            tpath = os.path.join(root, l["target"])
            if not os.path.exists(tpath):
                report["broken"].append({"file": p, "line": l["line"], "link": l["raw"]})
                continue
            if l.get("fragment") and l["target"].endswith(".md") and os.path.isfile(tpath):
                if l["target"] not in anchors:
                    with open(tpath, encoding="utf-8") as fh:
                        anchors[l["target"]] = {a.lower() for a in anchors_in(fh.read())}
                if norm_fragment(l["fragment"]) not in anchors[l["target"]]:
                    report["broken_anchors"].append({"file": p, "line": l["line"], "link": l["raw"]})
            if d["kind"] == "concept" and not l["absolute"]:
                report["relative"].append({"file": p, "line": l["line"], "link": l["raw"]})
            if d["kind"] == "concept" and l["target"] in inbound and l["target"] != p:
                inbound[l["target"]].add(p)

    for p, d in concepts_.items():
        outbound = {l["target"] for l in d["links"] if l["target"] in concepts_ and l["target"] != p}
        if not inbound[p]:
            report["orphans"].append(p)
        if not outbound:
            report["dead_ends"].append(p)

    # Every concept should be listed by its directory's index.md, and every
    # directory with an index by its parent's index.
    for p, d in docs.items():
        if d["kind"] in ("log", "machinery") or p == "index.md":
            continue
        if d["kind"] == "index":
            listed_in = os.path.join(os.path.dirname(os.path.dirname(p)), "index.md")
        else:
            listed_in = os.path.join(os.path.dirname(p), "index.md")
        listed_in = os.path.normpath(listed_in)
        idx = docs.get(listed_in)
        if idx is None:
            report["index_drift"].append({"file": p, "problem": f"no {listed_in} to list it"})
        elif p not in {l["target"] for l in idx["links"]}:
            report["index_drift"].append({"file": p, "problem": f"not listed in {listed_in}"})

    # `# Sections` lists sub-folders; a concept bullet there was misfiled (it belongs in `# Concepts`).
    for p, d in docs.items():
        if d["kind"] != "index":
            continue
        with open(os.path.join(root, p), encoding="utf-8") as fh:
            heading = None
            for n, line in enumerate(fh.read().split("\n"), 1):
                if INDEX_HEADING_RE.match(line):
                    heading = line.lstrip("#").strip().lower()
                elif heading == "sections" and _index_bullet(line):
                    for m in LINK_RE.finditer(line):
                        tgt, _ = resolve_link(m.group(2), p, root)
                        if tgt in concepts_:
                            report["index_drift"].append(
                                {"file": p, "problem": f"line {n}: concept /{tgt} is listed under # Sections "
                                                       "(which lists folders); move it to # Concepts"})

    if mentions:
        patterns = {}
        for p, d in concepts_.items():
            for name in names_for(d):
                patterns.setdefault(p, []).append(
                    (name, re.compile(rf"(?<![\w/-]){re.escape(name)}(?![\w-])", re.I)))
        for src, d in concepts_.items():
            linked = {l["target"] for l in d["links"]}
            for tgt, pats in patterns.items():
                if tgt == src or tgt in linked:
                    continue
                hits = []
                for line_no, masked, original in prose_lines(d["body"], d["offset"]):
                    for name, pat in pats:
                        if pat.search(masked):
                            hits.append({"line": line_no, "name": name, "text": original.strip()[:160]})
                            break
                if hits:
                    report["unlinked_mentions"].append({"file": src, "target": tgt, "hits": hits})

    report["summary"] = {"concepts": len(concepts_), **{k: len(v) for k, v in report.items()}}
    return report


def print_links(r):
    s = r["summary"]
    print(f"# OKF link report ({s['concepts']} concepts)\n")

    def section(title, items, fmt, note=""):
        print(f"## {title} ({len(items)})")
        if note:
            print(note)
        for it in items:
            print(fmt(it))
        print()

    section("Broken links", r["broken"], lambda i: f"- {i['file']}:{i['line']} -> {i['link']}")
    section("Broken anchors (no heading in the target has that slug)", r["broken_anchors"],
            lambda i: f"- {i['file']}:{i['line']} -> {i['link']}")
    section("Relative links in concepts", r["relative"], lambda i: f"- {i['file']}:{i['line']} -> {i['link']}",
            "Prefer bundle-root absolute paths (/dir/concept.md).")
    section("Orphans (no inbound link from another concept)", r["orphans"], lambda p: f"- /{p}")
    section("Dead ends (no outbound link to another concept)", r["dead_ends"], lambda p: f"- /{p}")
    section("Index drift", r["index_drift"], lambda i: f"- /{i['file']}: {i['problem']}")
    print(f"## Unlinked mentions ({len(r['unlinked_mentions'])})")
    print("Candidates only: confirm each is a real reference to the target before linking.")
    for m in r["unlinked_mentions"]:
        print(f"- /{m['file']} mentions /{m['target']}")
        for h in m["hits"][:3]:
            print(f"    L{h['line']} [{h['name']}]: {h['text']}")
        if len(m["hits"]) > 3:
            print(f"    ... {len(m['hits']) - 3} more")


def cmd_links(a):
    r = link_analysis(a.root)
    if a.check:
        for b in r["broken"]:
            print(f"broken link: {b['file']}:{b['line']} -> {b['link']}")
        for b in r["broken_anchors"]:
            print(f"broken anchor: {b['file']}:{b['line']} -> {b['link']}")
        sys.exit(1 if r["broken"] or r["broken_anchors"] else 0)
    if a.json:
        json.dump(r, sys.stdout, indent=2)
        print()
    else:
        print_links(r)


# ---------------------------------------------------------------------------
# oldest (port of .claude/skills/okf-review-oldest/scripts/oldest.py)
# ---------------------------------------------------------------------------

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
AT_RE = re.compile(r"\bat:\s*['\"]?(\d{4}-\d{2}-\d{2}T[0-9:.]+(?:Z|[+-]\d{2}:?\d{2}))")


def _ats(v):
    """Timestamps found under the 'at' keys of a mapping or list of mappings."""
    items = v if isinstance(v, list) else [v]
    out = []
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("at"), str):
            try:
                out.append(parse_ts(it["at"]))
            except ValueError:
                pass
    return out


def describe(root, path, now):
    doc = Doc(os.path.join(root, path))
    try:
        data = doc.parse() if doc.has_fm else {}
    except YamlError:
        data = None
    stamps = {}
    if data is not None:
        for field in ("generated", "verified", "reviewed"):
            found = _ats(data.get(field))
            if found:
                stamps[field] = max(found)
        get = lambda k: data.get(k) if isinstance(data.get(k), str) else None
        oq = data.get("open_questions")
        questions = [str(q) for q in oq] if isinstance(oq, list) else []
    else:  # unparseable frontmatter: fall back to the old regex scan
        raw = "\n".join(doc.fm)
        for field in ("generated", "verified", "reviewed"):
            b = doc.block(field)
            txt = "\n".join(doc.fm[b[0]:b[1]]) if b else ""
            found = [parse_ts(t) for t in AT_RE.findall(txt)]
            if found:
                stamps[field] = max(found)
        get = lambda k: _fm_fallback(raw, k, False)
        questions = []
    if stamps:
        field, fresh = max(stamps.items(), key=lambda kv: kv[1])
    else:
        field, fresh = None, EPOCH
    stale_after = get("stale_after")
    try:
        stale = bool(stale_after) and now >= parse_ts(stale_after)
    except ValueError:
        stale = False
    return {
        "path": "/" + path,
        "title": get("title"),
        "status": get("status") or "stable",
        "last_touched": None if field is None else fresh.isoformat().replace("+00:00", "Z"),
        "last_touched_by": field,
        "age_days": None if field is None else round((now - fresh).total_seconds() / 86400, 1),
        "stale": stale,
        "open_questions": questions,
        "_sort": fresh,
    }


def cmd_oldest(a):
    now = now_utc()
    rows = [describe(a.root, p, now) for p in concepts(a.root)]
    rows = [r for r in rows if r["status"] != "deprecated"]
    rows.sort(key=lambda r: (r["_sort"], r["path"]))
    if a.open_questions:
        rows = [r for r in rows if r["open_questions"]]
    else:
        rows = rows[: a.n]
    for r in rows:
        del r["_sort"]
    if a.json:
        print(json.dumps(rows, indent=2))
        return
    for r in rows:
        when = r["last_touched"] or "never"
        flags = (" STALE" if r["stale"] else "") + (f" ?{len(r['open_questions'])}" if r["open_questions"] else "")
        print(f"{when:22} {r['last_touched_by'] or '-':9} {r['path']}{flags}")
        if a.open_questions:
            for i, q in enumerate(r["open_questions"], 1):
                print(f"    {i}. {q}")


# ---------------------------------------------------------------------------
# sprawl: which concepts should be split for progressive disclosure
# ---------------------------------------------------------------------------

# Words that mark a section or bold lead-in as volatile: a dated snapshot, an
# incident, a procedure or a change log rather than what the thing *is*.
VOLATILE_RE = re.compile(
    r"(?i)\b(as of|current state|status|outage|incident|investigation|post-?mortem|change ?log|"
    r"changes since|changed|open (?:items|questions)|traps?|gotchas?|fix(?:ed|es)?|workaround|"
    r"stuck|broken|to ?do|snapshot|history|timeline|procedure|runbook|to check)\b")
DATE_RE = re.compile(r"\b(?:19|20)\d{2}-[01]\d(?:-[0-3]\d)?\b|"
                     r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? (?:\d{1,2},? )?(?:19|20)\d{2}\b",
                     re.I)
LEADIN_RE = re.compile(r"^\*\*([^*]{2,80}?)\*\*")
# score = lines/20 + sections/2 + sources/3 + 1.5 per volatile heading or lead-in + dates/5
SPRAWL_WEIGHTS = {"lines": 1 / 20, "sections": 1 / 2, "sources": 1 / 3, "volatile": 1.5, "dates": 1 / 5}
SPRAWL_WARN = 16  # lint warns above this; on 2026-10-24 the four sprawling hubs scored 18.8-30.7, the next 13.4
# Concept types that grow by design (a list of entries, not a hub), so sprawl doesn't apply.
SPRAWL_EXEMPT_TYPES = {"backlog"}


def volatile_reason(text):
    m = VOLATILE_RE.search(text)
    if m:
        return m.group(1).lower()
    d = DATE_RE.search(text)
    return d.group(0) if d else None


def sprawl_of(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as fh:
        text = fh.read()
    _, body = body_split(text)
    try:
        data = Doc(os.path.join(root, rel)).parse()
    except YamlError:
        data = {}
    srcs = data.get("sources")
    nsrc = len(srcs) if isinstance(srcs, list) else 0
    ctype = data.get("type")
    exempt = ctype if isinstance(ctype, str) and ctype.strip().lower() in SPRAWL_EXEMPT_TYPES else None
    hs = headings(body)
    code = set()
    fence = None
    for i, line in enumerate(body):
        f = FENCE_RE.match(line)
        if f or fence:
            code.add(i)
        if f:
            fence = None if fence == f.group(1) else (fence or f.group(1))
    lines = sum(1 for l in body if l.strip())
    dates = {d.lower() for i, l in enumerate(body) if i not in code for d in DATE_RE.findall(l)}

    sections, volatile = [], []
    for k, (i, level, title) in enumerate(hs):
        end = next((j for j, lv, _ in hs[k + 1:] if lv <= level), len(body))
        size = sum(1 for l in body[i + 1:end] if l.strip())
        why = volatile_reason(title)
        sections.append({"heading": title, "level": level, "line": i, "lines": size, "volatile": why})
        if why:
            volatile.append({"kind": "heading", "text": title, "line": i, "why": why})
    for i, l in enumerate(body):
        m = LEADIN_RE.match(l)
        if m and i not in code:
            why = volatile_reason(m.group(1))
            if why:
                volatile.append({"kind": "lead-in", "text": m.group(1).strip(), "line": i, "why": why})

    parts = {"lines": lines, "sections": len(hs), "sources": nsrc, "volatile": len(volatile), "dates": len(dates)}
    score = round(sum(SPRAWL_WEIGHTS[k] * v for k, v in parts.items()), 1)
    offset = text.count("\n", 0, len(text) - len("\n".join(body)))
    for x in sections + volatile:
        x["line"] += offset + 1
    # Split candidates: volatile sections, and any section holding a fifth of the body (min 12 lines).
    cands = [s for s in sections if s["volatile"] or s["lines"] >= max(12, lines // 5)]
    cands.sort(key=lambda s: (-bool(s["volatile"]), -s["lines"]))
    return {"path": "/" + rel, "score": score, "exempt": exempt, **parts, "sections_detail": sections,
            "volatile_detail": volatile, "candidates": cands}


def cmd_sprawl(a):
    rows = sorted((sprawl_of(a.root, p) for p in concepts(a.root)), key=lambda r: (-r["score"], r["path"]))
    if a.concept:
        want = "/" + resolve_concept(a.root, a.concept)
        rows = [r for r in rows if r["path"] == want]
    else:
        rows = [r for r in rows if not r["exempt"]][: a.n]
    if a.json:
        print(json.dumps(rows, indent=2))
        return
    print(f"score = lines/20 + sections/2 + sources/3 + 1.5 x volatile + dates/5  (lint warns above {SPRAWL_WARN})\n")
    for r in rows:
        print(f"{r['score']:5.1f}  {r['path']}  [{r['lines']} lines, {r['sections']} sections, "
              f"{r['sources']} sources, {r['volatile']} volatile, {r['dates']} dates]")
        if r["exempt"]:
            print(f"         exempt: type {r['exempt']} grows by design; lint doesn't warn\n")
            continue
        for s in r["candidates"]:
            tag = f"volatile: {s['volatile']}" if s["volatile"] else "large"
            print(f"         L{s['line']:<4} {'#' * s['level']} {s['heading']}  ({s['lines']} lines; {tag})")
        for v in r["volatile_detail"]:
            if v["kind"] == "lead-in":
                print(f"         L{v['line']:<4} **{v['text']}**  (lead-in paragraph; volatile: {v['why']})")
        print()


# ---------------------------------------------------------------------------
# Restructuring: link rewriting, index listings, mv, split
# ---------------------------------------------------------------------------

def rewrite_links(root, fn, moved=None):
    """Rewrite links across the bundle and return the files changed.

    fn(target, fragment) returns a new (target, fragment), or None to leave the link
    pointing where it did. moved maps a file's current path to the path its relative
    and in-page links were written against (a file that has just been moved or created
    from another file's text). A link keeps its style: in-page (#x), bundle-absolute
    (/dir/x.md) or relative (x.md).
    """
    moved = moved or {}
    changed = []
    for f in walk_md(root):
        if os.path.basename(f) in NON_CONCEPTS - RESERVED and not os.path.dirname(f):
            continue
        base = moved.get(f, f)
        path = os.path.join(root, f)
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()

        def repl(m):
            raw = m.group(2)
            target_part, _, frag = raw.partition("#")
            frag = frag if "#" in raw else None
            if raw.startswith("#"):
                tgt, absolute, own = base, True, True
            else:
                tgt, absolute = resolve_link(raw, base, root)
                own = False
                if tgt is None:
                    return m.group(0)
            res = fn(tgt, frag)
            ntgt, nfrag = res if res else (tgt, frag)
            if (ntgt, nfrag) == (tgt, frag) and (base == f or absolute):
                if not own or ntgt == f:
                    return m.group(0)
            if own and ntgt == f:
                new = "#" + nfrag if nfrag else "/" + ntgt
            elif own or absolute or (base != f and is_concept(f)):
                # A concept that moved gets bundle-absolute links, the catalog's preferred style.
                new = "/" + ntgt
                if target_part.endswith("/") and ntgt.endswith("/index.md"):
                    new = "/" + ntgt[: -len("index.md")]
            else:
                if target_part.endswith("/") and ntgt.endswith("index.md"):
                    new = os.path.relpath(os.path.dirname(ntgt) or ".", os.path.dirname(f) or ".") + "/"
                else:
                    new = os.path.relpath(ntgt, os.path.dirname(f) or ".")
            if nfrag and not new.startswith("#"):
                new += "#" + nfrag
            s = m.start(2) - m.start()
            return m.group(0)[:s] + new + m.group(0)[s + len(raw):]

        new_text = "\n".join(LINK_RE.sub(repl, line) for line in text.split("\n"))
        if new_text != text:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(new_text)
            changed.append(f)
    return changed


INDEX_HEADING_RE = re.compile(r"^#+\s")


def _index_bullet(line):
    return line.startswith(("* ", "- "))


def insert_index_bullet(ipath, bullet, section=None, create_section=False):
    """Add a bullet to index.md: after the last bullet of its `section` heading, or, with no
    section, at the end of `# Concepts` (or after the last bullet outside `# Sections`),
    creating `# Concepts` ahead of `# Sections` when there's nowhere else to put it."""
    with open(ipath, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    hs = [(i, l.lstrip("#").strip().lower()) for i, l in enumerate(lines) if INDEX_HEADING_RE.match(l)]

    def span(i):
        return i + 1, next((j for j, _ in hs if j > i), len(lines))

    def named(want):
        return [i for i, h in hs if h == want]

    if section:
        want = section.strip().lstrip("#").strip()
        hit = named(want.lower())
        if not hit and not create_section:
            die(f"no heading {section!r} in {ipath}")
        if not hit:
            while lines and lines[-1] == "":
                lines.pop()
            lines += ["", f"# {want}", "", bullet, ""]
        else:
            start, stop = span(hit[0])
            bullets = [i for i in range(start, stop) if _index_bullet(lines[i])]
            if bullets:
                lines.insert(bullets[-1] + 1, bullet)
            else:
                lines[start:start] = ["", bullet] + ([""] if start < len(lines) and lines[start].strip() else [])
    else:
        # Concept bullets never go under `# Sections`, which lists sub-folders.
        if named("concepts"):
            start, stop = span(named("concepts")[0])
            allowed = range(start, stop)
        else:
            barred = set()
            for i in named("sections"):
                barred.update(range(*span(i)))
            allowed = [i for i in range(len(lines)) if i not in barred]
        bullets = [i for i in allowed if _index_bullet(lines[i])]
        if bullets:
            lines.insert(bullets[-1] + 1, bullet)
        elif named("concepts"):
            start = named("concepts")[0] + 1
            lines[start:start] = ["", bullet] + ([""] if start < len(lines) and lines[start].strip() else [])
        elif named("sections"):
            at = named("sections")[0]
            while at > 0 and lines[at - 1] == "":
                at -= 1
            lines[at:at] = ["", "# Concepts", "", bullet]
        else:
            while lines and lines[-1] == "":
                lines.pop()
            lines += ["", "# Concepts", "", bullet, ""]
    if lines[-1] != "":
        lines.append("")
    with open(ipath, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def ensure_index(root, folder, touched):
    """Make sure folder/index.md exists and is listed in its parent's index; record files written."""
    if not folder:
        return
    ipath = os.path.join(root, folder, "index.md")
    if os.path.exists(ipath):
        return
    name = os.path.basename(folder)
    heading = name.replace("-", " ").capitalize()
    with open(ipath, "w", encoding="utf-8") as fh:
        fh.write(f"# {heading}\n\nTODO: say what this folder holds.\n")
    touched.append(os.path.join(folder, "index.md"))
    parent = os.path.dirname(folder)
    ensure_index(root, parent, touched)
    pidx = os.path.join(root, parent, "index.md")
    with open(pidx, encoding="utf-8") as fh:
        absolute = any(l.startswith("* [") and "](/" in l for l in fh.read().split("\n"))
    href = f"/{folder}/" if absolute else f"{name}/"
    insert_index_bullet(pidx, f"* [{heading}]({href}) - TODO: describe this folder", section="Sections",
                        create_section=True)
    touched.append(os.path.join(parent, "index.md"))
    print(f"okf: created /{folder}/index.md; replace its TODO lines (and the parent's listing)", file=sys.stderr)


def new_concept_path(root, arg):
    p = arg.strip().lstrip("/")
    if not p.endswith(".md"):
        p += ".md"
    p = os.path.normpath(p)
    if p.startswith("..") or os.path.isabs(p):
        die(f"{arg}: not a path inside the catalog")
    parts = p.split(os.sep)
    if os.path.basename(p) in NON_CONCEPTS:
        die(f"{arg}: {os.path.basename(p)} is a reserved name, not a concept")
    if parts[0] in SKIP_DIRS | SKIP_TOP | {"tools"} or any(x.startswith(".") for x in parts):
        die(f"{arg}: that's repository machinery, not a place for concepts")
    if os.path.exists(os.path.join(root, p)):
        die(f"{p} already exists")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.md", os.path.basename(p)):
        print(f"okf: note: {os.path.basename(p)} isn't short, lowercase and hyphenated", file=sys.stderr)
    return p


def print_touched(touched):
    seen = []
    for t in touched:
        if t not in seen:
            seen.append(t)
    print("touched (pass these to publish):")
    for t in seen:
        print(f"  {t}")


def cmd_mv(a):
    root = a.root
    old = resolve_concept(root, a.old)
    new = new_concept_path(root, a.new)
    odir, ndir = os.path.dirname(old), os.path.dirname(new)
    touched = [old, new]
    os.makedirs(os.path.join(root, ndir), exist_ok=True)
    ensure_index(root, ndir, touched)

    # Take the old folder's listing (if any) so the summary travels with the concept.
    bullet = None
    if odir != ndir:
        oidx = os.path.join(root, odir, "index.md")
        if os.path.exists(oidx):
            with open(oidx, encoding="utf-8") as fh:
                lines = fh.read().split("\n")
            keep = []
            for line in lines:
                hit = any(resolve_link(m.group(2), os.path.join(odir, "index.md"), root)[0] == old
                          for m in LINK_RE.finditer(line))
                if hit and line.startswith(("* ", "- ")) and bullet is None:
                    bullet = line
                    continue
                keep.append(line)
            if bullet is not None:
                with open(oidx, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(keep))
                touched.append(os.path.join(odir, "index.md"))

    if git(root, "ls-files", "--error-unmatch", old).returncode == 0:
        r = git(root, "mv", old, new)
        if r.returncode:
            die("git mv failed:\n" + r.stderr)
    else:
        os.rename(os.path.join(root, old), os.path.join(root, new))

    if odir != ndir:
        if bullet is None:
            data = Doc(os.path.join(root, new)).parse()
            title = data.get("title") or os.path.basename(new)[:-3]
            bullet = f"* [{title}]({os.path.basename(new)}) - {' '.join(str(data.get('description') or '').split())}"
        else:
            bullet = LINK_RE.sub(lambda m: m.group(0).replace(
                f"({m.group(2)}", "(" + os.path.basename(new) + ("#" + m.group(2).split("#", 1)[1] if "#" in m.group(2) else ""), 1)
                if resolve_link(m.group(2), os.path.join(odir, "index.md"), root)[0] == old else m.group(0), bullet)
        insert_index_bullet(os.path.join(root, ndir, "index.md"), bullet, section=None)
        touched.append(os.path.join(ndir, "index.md"))

    touched += rewrite_links(root, lambda t, frag: (new, frag) if t == old else None, moved={new: old})
    print(f"moved /{old} -> /{new}")
    print_touched(touched)


def find_section(body, want):
    hs = heading_slugs(body)
    w = want.strip().lstrip("#").strip()
    hits = [h for h in hs if h[2].lower() == w.lower()] or [h for h in hs if h[3] == w.lower().lstrip("#")]
    if not hits:
        die(f"no heading {want!r}; headings are:\n  " + "\n  ".join("#" * h[1] + " " + h[2] for h in hs))
    if len(hits) > 1:
        die(f"{len(hits)} headings match {want!r}; pass the anchor slug instead: "
            + ", ".join(h[3] for h in hits))
    return hits[0], hs


def cmd_split(a):
    root = a.root
    parent, pdoc, pdata = load_concept(root, a.concept)
    new = new_concept_path(root, a.to)
    with open(os.path.join(root, parent), encoding="utf-8") as fh:
        text = fh.read()
    head, body = body_split(text)
    (s, level, heading, slug), hs = find_section(body, a.section)
    e = next((i for i, lv, _, _ in hs if i > s and lv <= level), len(body))

    defs = footnote_defs(body)
    def_lines = {i for idx in defs.values() for i in idx}
    section_idx = [i for i in range(s + 1, e) if i not in def_lines]
    while section_idx and not body[section_idx[-1]].strip():
        section_idx.pop()
    while section_idx and not body[section_idx[0]].strip():
        section_idx.pop(0)
    if not section_idx:
        die(f"section {heading!r} has no content to move")
    if e == len(body):
        print(f"okf: note: '{heading}' is the last section, so it runs to the end of the document; check "
              "that its closing paragraphs really belong to it and move any that don't back", file=sys.stderr)
    moved_set = set(range(s + 1, e))
    moved_text = "\n".join(body[i] for i in section_idx)
    rest_text = "\n".join(l for i, l in enumerate(body) if i not in moved_set and i not in def_lines)
    used_moved = set(FOOTREF_RE.findall(moved_text))
    used_rest = set(FOOTREF_RE.findall(rest_text))

    # Sources: --source wins; else those the section cites (a footnote label equal to the id,
    # or a footnote definition naming its id, title or resource); else all, to be pruned by hand.
    srcs = [x for x in (pdata.get("sources") or []) if isinstance(x, dict)]
    def_text = {lab: "\n".join(body[i] for i in defs.get(lab, [])) for lab in used_moved}
    if a.source:
        unknown = set(a.source) - {x.get("id") for x in srcs}
        if unknown:
            die(f"{parent} has no source with id(s): {', '.join(sorted(unknown))}")
        chosen, how = [x for x in srcs if x.get("id") in a.source], "named with --source"
    else:
        chosen = []
        for x in srcs:
            sid = str(x.get("id") or "")
            keys = [str(x.get(k)) for k in ("id", "title", "resource") if x.get(k)]
            if (sid and sid in used_moved) or any(k in t for k in keys for t in def_text.values()):
                chosen.append(x)
        how = "cited by the section's footnotes"
        if not chosen:
            chosen, how = srcs, "all of the parent's (none was cited by footnote; prune them)"

    # New concept body: the section's content with headings re-levelled so its
    # subsections start at '#', then the footnote definitions it uses.
    new_body = []
    for i in section_idx:
        line = body[i]
        m = HEADING_RE.match(line)
        if m and i in {h[0] for h in hs}:
            line = "#" * max(1, len(m.group(1)) - level) + " " + (m.group(2) or "")
        new_body.append(line)
    title = a.title or re.sub(r"`", "", heading)
    ptitle = pdata.get("title") or os.path.basename(parent)[:-3]
    description = a.description or f"{heading}, split out of {ptitle}."
    if not a.description:
        print("okf: note: no --description given; write a real one in the new concept and its index listing",
              file=sys.stderr)
    intro = f"Split out of [{ptitle}](/{parent}); see it for the surrounding context."
    foot = []
    for lab in sorted(used_moved, key=lambda x: min(defs.get(x, [10 ** 9]))):
        foot += [body[i] for i in defs.get(lab, [])]
    fm = ["---", f"type: {scalar(a.type)}", f"title: {scalar(title)}", f"description: {scalar(description)}"]
    if pdata.get("status"):
        fm.append(f"status: {scalar(pdata['status'])}")
    fm.append("generated: " + flow_value({"by": a.by, "at": now_stamp()}))
    if chosen:
        fm.append("sources:")
        for x in chosen:
            fm += block_item(x, 2)
    fm.append("---")
    content = "\n".join(fm + ["", intro, ""] + new_body + ([""] + foot if foot else [])) + "\n"
    check = Doc.__new__(Doc)
    check.fm = fm[1:-1]
    try:
        check.parse()
    except YamlError as ex:
        die(f"generated frontmatter would not parse ({ex}); nothing written")

    # Parent: keep the heading, replace its content with a stub; footnote definitions
    # stay only where something still cites them (orphans stay put).
    link = f"[{title.replace('[', chr(92) + '[').replace(']', chr(92) + ']')}](/{new})"
    stub = a.stub or (f"{link}: {description}" if a.description else f"See {link}.")
    if f"(/{new})" not in stub:
        stub = stub.rstrip() + f" See {link}."
    drop = set()
    keep_defs = []
    for lab, idx in defs.items():
        inside = all(s < i < e for i in idx)
        if lab in used_moved and lab not in used_rest:
            drop.update(idx)
        elif inside:
            keep_defs += [body[i] for i in idx]  # re-added at the end of the parent
            drop.update(idx)
    out = []
    for i, line in enumerate(body):
        if i == s:
            out += [line, "", stub, ""]
        elif s < i < e or i in drop:
            continue
        else:
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    if keep_defs:
        out += [""] + keep_defs
    new_parent = "\n".join(head + out) + "\n"
    with open(os.path.join(root, parent), "w", encoding="utf-8") as fh:
        fh.write(new_parent)
    os.makedirs(os.path.join(root, os.path.dirname(new)), exist_ok=True)
    with open(os.path.join(root, new), "w", encoding="utf-8") as fh:
        fh.write(content)

    touched = [parent, new]
    ensure_index(root, os.path.dirname(new), touched)
    with open(os.path.join(root, new), encoding="utf-8") as fh:
        _, nbody = body_split(fh.read())
    nslugs = [h[3] for h in heading_slugs(nbody)]
    sub = [h for h in hs if s < h[0] < e]
    amap = {slug: None}
    for h, ns in zip(sub, nslugs):
        amap[h[3]] = ns

    def fn(t, frag):
        if t == parent and frag is not None and norm_fragment(frag) in amap:
            return new, amap[norm_fragment(frag)]
        return None

    touched += rewrite_links(root, fn, moved={new: parent})
    idx = os.path.join(root, os.path.dirname(new), "index.md")
    insert_index_bullet(idx, f"* [{title}]({os.path.basename(new)}) - {' '.join(description.split())}")
    touched.append(os.path.join(os.path.dirname(new), "index.md"))
    print(f"split '{heading}' ({len(section_idx)} lines) out of /{parent} into /{new}")
    print(f"sources copied: {', '.join(str(x.get('id')) for x in chosen) or 'none'} ({how})")
    if foot:
        print(f"footnotes carried: {', '.join(sorted(used_moved & set(defs)))}")
    print_touched(touched)


# ---------------------------------------------------------------------------
# lint
# ---------------------------------------------------------------------------

SECRET_RULES = [
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"),
     "PEM private-key header"),
    ("github-token", re.compile(r"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{36,}"),
     "GitHub token prefix (ghp_/gho_/ghu_/ghs_/ghr_) followed by 36+ token characters"),
    ("github-pat", re.compile(r"(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{22,}"),
     "fine-grained GitHub PAT prefix github_pat_ followed by 22+ token characters"),
    ("slack-token", re.compile(r"(?<![A-Za-z0-9_-])xox[bpa]-[A-Za-z0-9-]{10,}"),
     "Slack token prefix xoxb-/xoxp-/xoxa- followed by 10+ token characters"),
    ("sk-key", re.compile(r"(?<![A-Za-z0-9_-])sk-(?:[A-Za-z0-9]+-)*[A-Za-z0-9_]{20,}"),
     "sk- API-key prefix (OpenAI/Anthropic/Stripe style) followed by 20+ key characters"),
    ("aws-key-id", re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])"),
     "AWS access key id (AKIA/ASIA + 16 uppercase alphanumerics)"),
]
ASSIGN_RE = re.compile(
    r"(?i)(?<![\w-])(password|passwd|passphrase|secret|client[_-]?secret|token|api[_-]?key|access[_-]?key)"
    r"[\"']?[ \t]*[:=][ \t]*([\"']?)([^\s\"'`,;<>]+)\2?")
PLACEHOLDER_RE = re.compile(r"(?i)^(?:x+|\*+|\.+|changeme|redacted|example\w*|placeholder|none|null|true|false|"
                            r"todo|tbd|your[_-].*|my[_-].*|<.*>|\$.*|\{\{.*|%.*|env|secret\w*|password\w*|token\w*)$")


def _literal_secret(value):
    """Does an assigned value look like a real credential rather than prose or a reference?"""
    if len(value) < 8 or PLACEHOLDER_RE.match(value):
        return None
    if value.startswith(("/", "~", "http:", "https:", "file:")) or re.match(r"^\w+\(", value):
        return None
    has_digit = bool(re.search(r"\d", value))
    has_alpha = bool(re.search(r"[A-Za-z]", value))
    mixed = bool(re.search(r"[a-z]", value)) and bool(re.search(r"[A-Z]", value))
    if has_digit and has_alpha:
        return "value mixes letters and digits"
    if mixed and len(value) >= 12:
        return "value is 12+ mixed-case characters"
    if len(value) >= 20 and not re.search(r"[-_.]", value):
        return "value is a 20+ character unbroken token"
    return None


def _mask(v):
    return v[:4] + "..." if len(v) > 4 else "..."


def scan_secrets(root, rel, text):
    hits = []
    for n, line in enumerate(text.split("\n"), 1):
        for rule, rx, why in SECRET_RULES:
            m = rx.search(line)
            if m:
                hits.append({"file": rel, "line": n, "rule": "secret:" + rule,
                             "message": f"possible secret {_mask(m.group(0))}: {why}"})
        for m in ASSIGN_RE.finditer(line):
            why = _literal_secret(m.group(3))
            if why:
                hits.append({"file": rel, "line": n, "rule": "secret:assignment",
                             "message": f"possible secret: '{m.group(1)}' followed by a literal value "
                                        f"{_mask(m.group(3))} ({why})"})
    return hits


def git(root, *args, check=False):
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, check=check)


def last_commit_times(root):
    """{path: datetime of the last commit touching it}, and the set of paths with uncommitted changes."""
    times = {}
    r = git(root, "log", "--format=%x00%cI", "--name-only", "--no-renames")
    if r.returncode != 0:
        return None, set()
    current = None
    for line in r.stdout.split("\n"):
        if line.startswith("\x00"):
            current = parse_ts(line[1:])
        elif line.strip() and current is not None:
            times.setdefault(line.strip(), current)
    st = git(root, "status", "--porcelain", "--untracked-files=all")
    dirty = {l[3:].split(" -> ")[-1].strip('"') for l in st.stdout.split("\n") if l.strip()}
    return times, dirty


def check_ts(value, where, rel, line, errs, warns, now, future_check):
    if not isinstance(value, str) or not ISO_RE.match(value):
        errs.append({"file": rel, "line": line, "rule": "timestamp",
                     "message": f"{where} is not an ISO 8601 timestamp: {value!r}"})
        return None
    try:
        ts = parse_ts(value)
    except ValueError:
        errs.append({"file": rel, "line": line, "rule": "timestamp",
                     "message": f"{where} is not a valid date/time: {value!r}"})
        return None
    if not value.endswith("Z") and not value.endswith("+00:00"):
        warns.append({"file": rel, "line": line, "rule": "timestamp-utc",
                      "message": f"{where} is not in UTC: {value!r}"})
    if future_check and ts > now + FUTURE_SLACK:
        errs.append({"file": rel, "line": line, "rule": "future-timestamp",
                     "message": f"{where} {value} is in the future (now {now.strftime(TS_FMT)})"})
    return ts


def lint(root):
    now = now_utc()
    errs, warns = [], []
    docs = build_docs(root)
    commit_times, dirty = last_commit_times(root)

    for rel in walk_md(root):
        path = os.path.join(root, rel)
        base = os.path.basename(rel)
        doc = Doc(path)
        if base == "index.md":
            if rel != "index.md" and doc.has_fm:
                errs.append({"file": rel, "line": 1, "rule": "index-frontmatter",
                             "message": "non-root index.md must not have frontmatter"})
            if rel == "index.md":
                try:
                    d = doc.parse() if doc.has_fm else {}
                    if d.get("okf_version") is None:
                        warns.append({"file": rel, "line": 1, "rule": "okf-version",
                                      "message": "root index.md does not declare okf_version"})
                except YamlError as ex:
                    errs.append({"file": rel, "line": ex.line or 1, "rule": "frontmatter-parse",
                                 "message": f"frontmatter does not parse: {ex}"})
            continue
        if not is_concept(rel):
            continue
        if not doc.has_fm:
            errs.append({"file": rel, "line": 1, "rule": "no-frontmatter",
                         "message": "concept has no YAML frontmatter block"})
            continue
        try:
            data = doc.parse()
        except YamlError as ex:
            errs.append({"file": rel, "line": ex.line or 1, "rule": "frontmatter-parse",
                         "message": f"frontmatter does not parse: {ex}"})
            continue
        ln = doc.key_line
        if not data.get("type"):
            errs.append({"file": rel, "line": 1, "rule": "no-type", "message": "frontmatter has no 'type'"})
        for k in ("title", "description"):
            if not data.get(k):
                warns.append({"file": rel, "line": 1, "rule": f"no-{k}", "message": f"frontmatter has no '{k}'"})
        status = data.get("status")
        if status is not None and status not in STATUSES:
            warns.append({"file": rel, "line": ln("status"), "rule": "status",
                          "message": f"status {status!r} is not draft, stable or deprecated"})
        gen_ts = None
        g = data.get("generated")
        if g is not None:
            if not isinstance(g, dict) or "at" not in g or "by" not in g:
                warns.append({"file": rel, "line": ln("generated"), "rule": "generated-shape",
                              "message": "generated should be a mapping with 'by' and 'at'"})
            if isinstance(g, dict) and "at" in g:
                gen_ts = check_ts(g["at"], "generated.at", rel, ln("generated"), errs, warns, now, True)
        v = data.get("verified")
        if v is not None:
            for i, it in enumerate(v if isinstance(v, list) else [v]):
                if isinstance(it, dict) and "at" in it:
                    check_ts(it["at"], f"verified[{i}].at", rel, ln("verified"), errs, warns, now, True)
                else:
                    warns.append({"file": rel, "line": ln("verified"), "rule": "verified-shape",
                                  "message": f"verified[{i}] should be a mapping with 'by' and 'at'"})
        r = data.get("reviewed")
        if r is not None:
            if isinstance(r, dict) and "at" in r:
                check_ts(r["at"], "reviewed.at", rel, ln("reviewed"), errs, warns, now, True)
                if r.get("outcome") not in OUTCOMES:
                    warns.append({"file": rel, "line": ln("reviewed"), "rule": "reviewed-outcome",
                                  "message": f"reviewed.outcome {r.get('outcome')!r} is not one of {', '.join(OUTCOMES)}"})
            else:
                warns.append({"file": rel, "line": ln("reviewed"), "rule": "reviewed-shape",
                              "message": "reviewed should be a mapping with by, at, outcome, note"})
        sa = data.get("stale_after")
        if sa is not None:
            ts = check_ts(sa, "stale_after", rel, ln("stale_after"), errs, warns, now, False)
            if ts and ts <= now:
                warns.append({"file": rel, "line": ln("stale_after"), "rule": "stale",
                              "message": f"stale_after {sa} has passed; re-check the concept"})
        srcs = data.get("sources")
        if srcs is not None:
            if not isinstance(srcs, list):
                warns.append({"file": rel, "line": ln("sources"), "rule": "sources-shape",
                              "message": "sources should be a list"})
            else:
                for i, s in enumerate(srcs):
                    if not isinstance(s, dict) or not s.get("resource"):
                        warns.append({"file": rel, "line": ln("sources"), "rule": "sources-shape",
                                      "message": f"sources[{i}] has no 'resource'"})
                    elif s.get("last_modified") is not None:
                        check_ts(s["last_modified"], f"sources[{i}].last_modified", rel, ln("sources"),
                                 errs, warns, now, False)
        if gen_ts and commit_times is not None and rel not in dirty and rel in commit_times:
            ct = commit_times[rel]
            if gen_ts > ct + FUTURE_SLACK:
                warns.append({"file": rel, "line": ln("generated"), "rule": "generated-after-commit",
                              "message": f"generated.at {gen_ts.strftime(TS_FMT)} is later than the file's last "
                                         f"commit {ct.astimezone(timezone.utc).strftime(TS_FMT)}"})

    links = link_analysis(root, docs, mentions=False)
    for b in links["broken"]:
        errs.append({"file": b["file"], "line": b["line"], "rule": "broken-link",
                     "message": f"link target does not exist: {b['link']}"})
    for b in links["broken_anchors"]:
        errs.append({"file": b["file"], "line": b["line"], "rule": "broken-anchor",
                     "message": f"no heading in the target matches the anchor: {b['link']}"})
    for b in links["relative"]:
        warns.append({"file": b["file"], "line": b["line"], "rule": "relative-link",
                      "message": f"relative link {b['link']}; prefer a bundle-root absolute path"})
    for p in links["orphans"]:
        warns.append({"file": p, "line": 1, "rule": "orphan",
                      "message": "no other concept links to this concept"})
    for d in links["index_drift"]:
        warns.append({"file": d["file"], "line": 1, "rule": "index-drift", "message": d["problem"]})
    for rel in concepts(root):
        sp = sprawl_of(root, rel)
        if sp["score"] > SPRAWL_WARN and not sp["exempt"]:
            warns.append({"file": rel, "line": 1, "rule": "sprawl",
                          "message": f"sprawl score {sp['score']} > {SPRAWL_WARN} ({sp['lines']} lines, "
                                     f"{sp['sections']} sections, {sp['volatile']} volatile); consider splitting "
                                     f"(okf.py sprawl {rel}, okf-reorganize skill)"})

    me = os.path.realpath(__file__)
    for dirpath, dirnames, filenames in os.walk(root):
        # Session worktrees are separate checkouts; each is linted from inside itself.
        dirnames[:] = sorted(d for d in dirnames if d not in (".git", ".worktrees"))
        for f in sorted(filenames):
            path = os.path.join(dirpath, f)
            if os.path.realpath(path) == me:
                continue
            try:
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
            except (UnicodeDecodeError, OSError):
                continue
            errs.extend(scan_secrets(root, os.path.relpath(path, root), text))

    key = lambda x: (x["file"], x["line"], x["rule"])
    return sorted(errs, key=key), sorted(warns, key=key)


def cmd_lint(a):
    errs, warns = lint(a.root)
    if a.json:
        print(json.dumps({"errors": errs, "warnings": warns}, indent=2))
    else:
        for level, items in (("ERROR", errs), ("WARN", warns)):
            for i in items:
                print(f"{level} {i['file']}:{i['line']}: [{i['rule']}] {i['message']}")
        print(f"{len(errs)} error(s), {len(warns)} warning(s)")
    sys.exit(1 if errs else 0)


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------

def publish_path(root, arg):
    """Normalize a path argument to a repo-relative path, refusing anything outside the catalog."""
    if os.path.isabs(arg) and (arg == root or arg.startswith(root + os.sep)):
        rel = os.path.relpath(arg, root)
    else:
        rel = os.path.normpath(arg.lstrip("/"))
    if rel == "." or rel.startswith(".."):
        die(f"{arg}: not a path inside the catalog")
    return rel


def covers(path, changed):
    """True if the named path is the changed file or a directory containing it."""
    return changed == path or changed.startswith(path.rstrip("/") + "/")


def changed_paths(root):
    """Repo-relative paths with uncommitted changes (modified, added, deleted, untracked)."""
    out = git(root, "status", "--porcelain", "-z", "--untracked-files=all").stdout
    paths, entries = [], out.split("\0")
    i = 0
    while i < len(entries):
        e = entries[i]
        if len(e) > 3:
            paths.append(e[3:])
            if e[0] in "RC":  # rename/copy: the next entry is the old path
                paths.append(entries[i + 1])
                i += 1
        i += 1
    return sorted(set(paths))


def cmd_publish(a):
    root = a.root
    if git(root, "rev-parse", "--git-dir").returncode != 0:
        die(f"{root} is not a git repository")
    gitdir = git(root, "rev-parse", "--absolute-git-dir").stdout.strip()
    if any(os.path.exists(os.path.join(gitdir, d)) for d in ("rebase-merge", "rebase-apply", "MERGE_HEAD")):
        die("a rebase or merge is in progress; finish or abort it first")
    unmerged = git(root, "diff", "--name-only", "--diff-filter=U").stdout.split()
    if unmerged:
        die("unmerged paths, resolve them first: " + ", ".join(unmerged))
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != "main" and not (branch == "HEAD" and is_linked_worktree(root)):
        die(f"on branch {branch!r}; publish from main or from a session worktree (okf.py session start)")

    # Several sessions can share this checkout, so commit only the paths this
    # session names; anything else in the tree belongs to someone else.
    if a.all and a.paths:
        die("pass either PATH... or --all, not both")
    paths = None if a.all else [publish_path(root, p) for p in a.paths]
    dirty = changed_paths(root)
    mine = dirty if paths is None else [d for d in dirty if any(covers(p, d) for p in paths)]
    others = [d for d in dirty if d not in mine]

    errs, _ = lint(root)
    blocking = [i for i in errs if i["file"] in mine or (not mine and paths is None)]
    for i in errs:
        level = "ERROR" if i in blocking else "WARN (not in this commit)"
        print(f"{level} {i['file']}:{i['line']}: [{i['rule']}] {i['message']}", file=sys.stderr)
    if blocking:
        die(f"lint found {len(blocking)} error(s) in the files being published; not publishing")

    git(root, "fetch", "--quiet", "origin", "main")
    ahead = git(root, "rev-list", "--count", "origin/main..HEAD").stdout.strip()
    ahead = int(ahead) if ahead.isdigit() else 0
    if dirty and paths is not None and not paths:
        die("name the files this session changed (okf.py publish -m MSG PATH...), or pass --all "
            "if nobody else is working in this checkout. Uncommitted changes:\n  "
            + "\n  ".join(dirty))
    if not mine and not ahead:
        print("nothing to publish: no changes in the named paths and no unpushed commits")
        if others:
            print("left uncommitted (not named):\n  " + "\n  ".join(others))
        return
    if mine:
        if not a.message:
            die("there are changes to commit; pass -m MESSAGE")
        r = git(root, "add", "-A", "--", *mine)
        if r.returncode:
            die("git add failed:\n" + r.stderr)
        # A pathspec commit takes only these paths, even if another session
        # has staged something else.
        r = git(root, "commit", "-q", "-m", f"{a.message}\n\n{CO_AUTHOR}", "--", *mine)
        if r.returncode:
            die("git commit failed:\n" + r.stdout + r.stderr)
        print("committed " + git(root, "rev-parse", "--short", "HEAD").stdout.strip()
              + ": " + ", ".join(mine))
    else:
        print(f"no new changes in the named paths; pushing {ahead} unpushed commit(s)")
    if others:
        print("left uncommitted (not named):\n  " + "\n  ".join(others))

    # --autostash: other sessions' uncommitted edits would otherwise stop the rebase.
    r = git(root, "pull", "--rebase", "--autostash", "--quiet", "origin", "main")
    if r.returncode:
        if any(os.path.exists(os.path.join(gitdir, d)) for d in ("rebase-merge", "rebase-apply")):
            git(root, "rebase", "--abort")
        die("git pull --rebase origin main failed; rebase aborted, your commit is still local and "
            "unpushed. Resolve by hand (git pull --rebase origin main, fix conflicts, "
            "git rebase --continue), then run publish again.\n" + r.stdout + r.stderr)
    r = git(root, "push", "--quiet", "origin", "HEAD:main")
    if r.returncode:
        die("git push failed; the commit is local:\n" + r.stdout + r.stderr)
    print("pushed " + git(root, "rev-parse", "HEAD").stdout.strip() + " to origin/main")


# ---------------------------------------------------------------------------
# Session worktrees
# ---------------------------------------------------------------------------

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")


def is_linked_worktree(root):
    gitdir = git(root, "rev-parse", "--absolute-git-dir").stdout.strip()
    common = git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    return bool(gitdir) and os.path.realpath(gitdir) != os.path.realpath(common)


def main_checkout(root):
    """The primary checkout that owns .worktrees/, even when called from a worktree."""
    common = git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    if not common:
        die(f"{root} is not a git repository")
    return os.path.dirname(os.path.realpath(common))


def session_dir(main, sid):
    if not SESSION_ID_RE.match(sid or ""):
        die(f"bad session id {sid!r}: use letters, digits, '-' and '_'")
    return os.path.join(main, ".worktrees", sid)


def worktree_state(path):
    """(dirty paths, number of commits not on origin/main)."""
    dirty = changed_paths(path)
    ahead = git(path, "rev-list", "--count", "origin/main..HEAD").stdout.strip()
    return dirty, int(ahead) if ahead.isdigit() else 0


def last_change(path):
    """Most recent mtime of any file or directory in a worktree."""
    return datetime.fromtimestamp(max(
        os.path.getmtime(os.path.join(dp, f))
        for dp, dns, fs in os.walk(path) for f in fs + ["."]
    ), timezone.utc)


def cmd_session(a):
    main = main_checkout(a.root)
    wt_root = os.path.join(main, ".worktrees")

    if a.action == "start":
        path = session_dir(main, a.id)
        git(main, "fetch", "--quiet", "origin", "main")
        if os.path.isdir(path):
            dirty, ahead = worktree_state(path)
            if not dirty and not ahead:
                # Idle worktree: move it up to the latest main.
                git(path, "checkout", "--quiet", "--detach", "origin/main")
            print(path)
            return
        os.makedirs(wt_root, exist_ok=True)
        r = git(main, "worktree", "add", "--quiet", "--detach", path, "origin/main")
        if r.returncode:
            die("git worktree add failed:\n" + r.stderr)
        print(path)
        # Sessions don't always run 'end'; tidy up clean, pushed, day-old ones.
        for sid in sorted(os.listdir(wt_root)):
            other = os.path.join(wt_root, sid)
            if other == path or not os.path.isdir(other):
                continue
            dirty, ahead = worktree_state(other)
            if not dirty and not ahead and last_change(other) < datetime.now(timezone.utc) - timedelta(hours=24):
                git(main, "worktree", "remove", other)

    elif a.action == "end":
        path = session_dir(main, a.id)
        if not os.path.isdir(path):
            print(f"no worktree for session {a.id}")
            return
        git(path, "fetch", "--quiet", "origin", "main")
        dirty, ahead = worktree_state(path)
        if dirty or ahead:
            die(f"{path} still has uncommitted changes ({len(dirty)}) or unpushed commits ({ahead}); "
                "publish or discard them first")
        r = git(main, "worktree", "remove", path)
        if r.returncode:
            die("git worktree remove failed:\n" + r.stderr)
        print(f"removed {path}")

    elif a.action in ("list", "prune"):
        git(main, "fetch", "--quiet", "origin", "main")
        cutoff = datetime.now(timezone.utc) - timedelta(hours=a.older_than)
        entries = sorted(os.listdir(wt_root)) if os.path.isdir(wt_root) else []
        for sid in entries:
            path = os.path.join(wt_root, sid)
            if not os.path.isdir(path):
                continue
            dirty, ahead = worktree_state(path)
            idle = last_change(path)
            status = "clean" if not dirty and not ahead else f"{len(dirty)} uncommitted, {ahead} unpushed"
            if a.action == "list":
                print(f"{sid}  last change {idle.strftime(TS_FMT)}  {status}")
            elif not dirty and not ahead and idle < cutoff:
                git(main, "worktree", "remove", path)
                print(f"removed {sid} (clean, idle since {idle.strftime(TS_FMT)})")
            elif dirty or ahead:
                print(f"kept {sid}: {status}")
        if a.action == "prune":
            git(main, "worktree", "prune")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=argparse.SUPPRESS,
                        help=f"catalog root (default: the directory above tools/, {DEFAULT_ROOT})")
    ap = argparse.ArgumentParser(prog="okf", description=__doc__, parents=[common],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="<command>")

    def add(name, fn, help_, desc=None):
        p = sub.add_parser(name, parents=[common], help=help_, description=desc or help_,
                           formatter_class=argparse.RawDescriptionHelpFormatter)
        p.set_defaults(fn=fn)
        return p

    concept_help = "concept path, e.g. /infra/time-server.md or infra/time-server"

    p = add("stamp", cmd_stamp, "set generated or append to verified, with the current UTC time",
            "generated: replace 'generated' with { by, at: now }.\n"
            "verified: append { by, at: now } to the 'verified' list (creating it, or turning a\n"
            "bare mapping into a list). Only stamp verified when the facts really were confirmed.")
    p.add_argument("concept", help=concept_help)
    p.add_argument("field", choices=["generated", "verified"])
    p.add_argument("--by", default=DEFAULT_ACTOR, help=f"actor (default {DEFAULT_ACTOR}; env OKF_ACTOR), e.g. human:{{OWNER}}")

    p = add("review", cmd_review, "record a review: replace 'reviewed', queue open questions",
            "Replace the 'reviewed' extension key with { by, at: now, outcome, note } and append\n"
            "each --question to 'open_questions' (exact duplicates are skipped).")
    p.add_argument("concept", help=concept_help)
    p.add_argument("--outcome", required=True, choices=OUTCOMES)
    p.add_argument("--note", required=True, help="what was and wasn't checked")
    p.add_argument("--question", action="append", metavar="TEXT", help="open question to queue (repeatable)")
    p.add_argument("--by", default=DEFAULT_ACTOR, help=f"actor (default {DEFAULT_ACTOR})")

    p = add("unquestion", cmd_unquestion, "remove one open question (deletes the key when none are left)")
    p.add_argument("concept", help=concept_help)
    p.add_argument("question", help="1-based index (as listed by 'oldest --open-questions') or exact text")

    p = add("question", cmd_question, "queue one open question without recording a review",
            "Append TEXT to the concept's open_questions list (exact duplicates are skipped).\n"
            "Unlike 'review', it leaves 'reviewed' alone, so it doesn't count as a re-check.")
    p.add_argument("concept", help=concept_help)
    p.add_argument("question", help="self-contained question for {{OWNER}}")

    p = add("source", cmd_source, "append an entry to 'sources' (refuses a duplicate id)")
    p.add_argument("concept", help=concept_help)
    p.add_argument("--id", required=True)
    p.add_argument("--resource", required=True, help="URI, path, or description of what was consulted")
    p.add_argument("--title")
    p.add_argument("--author", help="e.g. claude-code/claude-opus-5-5 or human:{{OWNER}}")

    p = add("log", cmd_log, "add an entry under today's (UTC) heading in the root log.md",
            "Adds '* **Kind:** TEXT' as the first bullet under '## YYYY-MM-DD' (today, UTC),\n"
            "creating the heading at the top if needed. Exact duplicates are skipped.")
    p.add_argument("text")
    p.add_argument("--kind", default="Update", choices=LOG_KINDS)

    p = add("index", cmd_index, "list a concept in its folder's index.md",
            "Adds '* [Title](file.md) - SUMMARY' at the end of the folder's '# Concepts' list (never\n"
            "under '# Sections', which lists sub-folders; '# Concepts' is created ahead of it if\n"
            "missing), or of --section, unless the concept is already linked there.")
    p.add_argument("concept", help=concept_help)
    p.add_argument("summary")
    p.add_argument("--title", help="link text (default: the concept's frontmatter title)")
    p.add_argument("--section", help="heading to list it under, e.g. 'Build infrastructure'")

    p = add("links", cmd_links, "report broken links, orphans, dead ends, index drift, unlinked mentions")
    p.add_argument("--json", action="store_true")
    p.add_argument("--check", action="store_true", help="print only broken links; exit 1 if any")

    p = add("oldest", cmd_oldest, "list concepts by when they were last touched (generated/verified/reviewed)",
            "Freshness is the latest of generated.at, verified[].at and reviewed.at; concepts\n"
            "with none sort first; deprecated concepts are skipped. STALE marks a passed\n"
            "stale_after; ?N counts queued open_questions.")
    p.add_argument("-n", type=int, default=5, help="how many to list (default 5)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--open-questions", action="store_true", help="list every concept with queued open_questions")

    p = add("sprawl", cmd_sprawl, "rank concepts by how much they need splitting, with candidate sections",
            "score = lines/20 + sections/2 + sources/3 + 1.5 per volatile heading or bold lead-in\n"
            "+ distinct dates/5. Lines are non-blank body lines; sections are headings; volatile\n"
            "means the heading or a '**Lead-in.**' paragraph names a snapshot, incident, procedure\n"
            "or change log (as of, current state, outage, change log, open items, trap, fix, ...).\n"
            f"Candidates are volatile sections and any section holding a fifth of the body. lint\n"
            f"warns above {SPRAWL_WARN}. Concepts of type {', '.join(sorted(t.title() for t in SPRAWL_EXEMPT_TYPES))}\n"
            "grow by design: they're left out of the ranking and lint, but shown when named.")
    p.add_argument("concept", nargs="?", help="show just this concept")
    p.add_argument("-n", type=int, default=5, help="how many to list (default 5)")
    p.add_argument("--json", action="store_true")

    p = add("mv", cmd_mv, "rename or move a concept and rewrite every link to it",
            "git mv OLD NEW, rewrite every inbound link in the bundle (anchors kept, link style\n"
            "kept: absolute, relative or index-relative), fix the moved file's own relative links,\n"
            "and move its index.md listing to the new folder (creating index.md, listed in the\n"
            "parent's index, for a new folder). Refuses if NEW exists or is a reserved name.\n"
            "Prints the files it touched, for publish.")
    p.add_argument("old", help=concept_help)
    p.add_argument("new", help="new concept path, e.g. /playbooks/build-server-stuck-deploys.md")

    p = add("split", cmd_split, "carve a section out of a concept into a new concept",
            "Moves the section's content (and its subsections) into NEW, whose frontmatter gets\n"
            "type, title (default: the heading), description, the parent's status, generated now,\n"
            "and sources: --source IDs if given, else those the section's footnotes cite (label\n"
            "equal to the id, or a definition naming its id/title/resource), else all of the\n"
            "parent's (prune them). verified is never copied: splitting isn't verification.\n"
            "The section's heading is dropped (it's the title) and its subsections are re-levelled\n"
            "to start at '#'. The parent keeps the heading with a stub paragraph linking to NEW.\n"
            "Footnotes go wherever they're cited (copied if both). Links to PARENT#section and\n"
            "its subsections are rewritten to NEW across the bundle. NEW is listed in its\n"
            "folder's index.md. Prints the files it touched, for publish.")
    p.add_argument("concept", help=concept_help)
    p.add_argument("--section", required=True, help="heading text (or its anchor slug) of the section to move")
    p.add_argument("--to", required=True, help="new concept path")
    p.add_argument("--title", help="default: the heading text")
    p.add_argument("--type", default="Note", help="new concept's type (default Note)")
    p.add_argument("--description", help="one-sentence description (also the index summary and default stub)")
    p.add_argument("--stub", help="paragraph left in the parent (a link to NEW is appended if missing)")
    p.add_argument("--source", action="append", metavar="ID", help="parent source id to copy (repeatable)")
    p.add_argument("--by", default=DEFAULT_ACTOR, help=f"actor for generated (default {DEFAULT_ACTOR})")

    p = add("lint", cmd_lint, "check the catalog; exit 1 on errors")
    p.add_argument("--json", action="store_true")

    p = add("publish", cmd_publish, "lint, commit the named paths, pull --rebase, push to origin main",
            "Commits only the PATHs you name (files or directories, e.g. infra/time-server.md\n"
            "log.md), because other sessions may have uncommitted work in the same checkout;\n"
            "everything else is left alone and listed. --all commits every change instead; use\n"
            "it only when nobody else is working in the checkout.\n\n"
            "Refuses on unmerged paths, an in-progress rebase/merge, a branch other than main\n"
            "(a detached session worktree is fine), or lint errors in the files being published (errors elsewhere are shown as\n"
            "warnings). Commits with MESSAGE plus a Co-Authored-By trailer, pulls with\n"
            "rebase (autostashing others' uncommitted edits), and pushes. On a rebase conflict\n"
            "it aborts the rebase, leaves the commit local and exits 1. With no changes in the\n"
            "named paths it still pushes any unpushed commits.")
    p.add_argument("-m", "--message")
    p.add_argument("paths", nargs="*", metavar="PATH", help="files or directories this session changed")
    p.add_argument("--all", action="store_true", help="commit every change in the working tree")

    p = add("session", cmd_session, "give a session its own git worktree to edit and publish from",
            "start --id ID: create (or reuse) .worktrees/ID in the main checkout, at the latest\n"
            "  origin/main with a detached HEAD, and print its path. Edit there and run that\n"
            "  worktree's tools/okf.py; its publish pushes HEAD to origin/main. An idle worktree\n"
            "  is moved up to the latest main.\n"
            "end --id ID: remove the worktree; refuses while it has uncommitted or unpushed work.\n"
            "list: show every session worktree, its last change and whether it's clean.\n"
            "prune [--older-than H]: remove clean, fully pushed worktrees idle for H hours\n"
            "  (default 24); report the ones with unfinished work.")
    p.add_argument("action", choices=["start", "end", "list", "prune"])
    p.add_argument("--id", help="session id (Claude Code's session_id; letters, digits, '-', '_')")
    p.add_argument("--older-than", type=float, default=24, metavar="HOURS")

    a = ap.parse_args(argv)
    if getattr(a, "action", None) in ("start", "end") and not a.id:
        ap.error("session start/end need --id")
    a.root = os.path.abspath(getattr(a, "root", DEFAULT_ROOT))
    a.fn(a)


if __name__ == "__main__":
    main()
