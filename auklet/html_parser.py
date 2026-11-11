"""A real HTML tokenizer + tree constructor.

This follows the shape of the HTML5 parsing algorithm: a state-machine tokenizer
and an insertion-mode tree builder with implied end tags, void elements, raw
text elements and the common auto-closing rules.  It is not a byte-for-byte
implementation of every corner of the spec (no foster parenting, no full
adoption agency), but it parses real-world documents correctly.
"""

from __future__ import annotations

import re
from typing import Optional

from .dom import Comment, Document, Element, Text

VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}

RAW_TEXT = {"script", "style", "xmp", "iframe", "noembed", "noframes"}
RCDATA = {"textarea", "title"}

# Elements that close an open <p> when they start.
CLOSES_P = {
    "address", "article", "aside", "blockquote", "details", "div", "dl",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hgroup", "hr", "main", "menu", "nav", "ol",
    "p", "pre", "section", "table", "ul",
}

HEAD_ELEMENTS = {"base", "basefont", "bgsound", "link", "meta", "title", "style", "script", "noscript"}

# Named character references (the ones that actually show up in documents).
ENTITIES = {
    "amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": "\u00a0",
    "copy": "\u00a9", "reg": "\u00ae", "trade": "\u2122", "hellip": "\u2026",
    "mdash": "\u2014", "ndash": "\u2013", "lsquo": "\u2018", "rsquo": "\u2019",
    "ldquo": "\u201c", "rdquo": "\u201d", "laquo": "\u00ab", "raquo": "\u00bb",
    "bull": "\u2022", "middot": "\u00b7", "deg": "\u00b0", "plusmn": "\u00b1",
    "times": "\u00d7", "divide": "\u00f7", "frac12": "\u00bd", "frac14": "\u00bc",
    "frac34": "\u00be", "sup2": "\u00b2", "sup3": "\u00b3", "micro": "\u00b5",
    "para": "\u00b6", "sect": "\u00a7", "dagger": "\u2020", "Dagger": "\u2021",
    "euro": "\u20ac", "pound": "\u00a3", "yen": "\u00a5", "cent": "\u00a2",
    "larr": "\u2190", "rarr": "\u2192", "uarr": "\u2191", "darr": "\u2193",
    "harr": "\u2194", "infin": "\u221e", "ne": "\u2260", "le": "\u2264",
    "ge": "\u2265", "asymp": "\u2248", "sum": "\u2211", "prod": "\u220f",
    "radic": "\u221a", "int": "\u222b", "part": "\u2202", "nabla": "\u2207",
    "alpha": "\u03b1", "beta": "\u03b2", "gamma": "\u03b3", "delta": "\u03b4",
    "epsilon": "\u03b5", "lambda": "\u03bb", "mu": "\u03bc", "pi": "\u03c0",
    "sigma": "\u03c3", "omega": "\u03c9", "Omega": "\u03a9", "Delta": "\u0394",
    "check": "\u2713", "cross": "\u2717", "star": "\u2605", "hearts": "\u2665",
    "spades": "\u2660", "clubs": "\u2663", "diams": "\u2666", "loz": "\u25ca",
    "shy": "\u00ad", "ensp": "\u2002", "emsp": "\u2003", "thinsp": "\u2009",
    "zwnj": "\u200c", "zwj": "\u200d", "lrm": "\u200e", "rlm": "\u200f",
}

_ENTITY_RE = re.compile(r"&(#[0-9]+|#[xX][0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);?")


def decode_entities(text: str) -> str:
    if "&" not in text:
        return text

    def repl(m: re.Match) -> str:
        body = m.group(1)
        if body.startswith("#"):
            try:
                if body[1] in "xX":
                    cp = int(body[2:], 16)
                else:
                    cp = int(body[1:])
                if 0 < cp <= 0x10FFFF:
                    return chr(cp)
            except ValueError:
                return m.group(0)
            return m.group(0)
        return ENTITIES.get(body, m.group(0))

    return _ENTITY_RE.sub(repl, text)


class Token:
    __slots__ = ("kind", "name", "attrs", "data", "self_closing")

    def __init__(self, kind, name="", attrs=None, data="", self_closing=False):
        self.kind = kind
        self.name = name
        self.attrs = attrs or {}
        self.data = data
        self.self_closing = self_closing

    def __repr__(self):  # pragma: no cover
        return f"Token({self.kind},{self.name!r},{self.data!r})"


class Tokenizer:
    """Character-level HTML tokenizer."""

    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.n = len(text)

    def tokens(self):
        text = self.text
        n = self.n
        while self.pos < n:
            lt = text.find("<", self.pos)
            if lt < 0:
                yield Token("text", data=decode_entities(text[self.pos:]))
                self.pos = n
                return
            if lt > self.pos:
                yield Token("text", data=decode_entities(text[self.pos:lt]))
                self.pos = lt
            if text.startswith("<!--", self.pos):
                end = text.find("-->", self.pos + 4)
                if end < 0:
                    yield Token("comment", data=text[self.pos + 4:])
                    self.pos = n
                    return
                yield Token("comment", data=text[self.pos + 4:end])
                self.pos = end + 3
                continue
            if text.startswith("<!", self.pos):
                end = text.find(">", self.pos)
                if end < 0:
                    self.pos = n
                    return
                body = text[self.pos + 2:end].strip()
                if body.lower().startswith("doctype"):
                    yield Token("doctype", data=body[7:].strip())
                self.pos = end + 1
                continue
            if text.startswith("</", self.pos):
                end = text.find(">", self.pos)
                if end < 0:
                    self.pos = n
                    return
                name = text[self.pos + 2:end].strip().split()[0].lower() if text[self.pos + 2:end].strip() else ""
                yield Token("end", name=name)
                self.pos = end + 1
                continue
            if text.startswith("<?", self.pos):
                end = text.find(">", self.pos)
                self.pos = n if end < 0 else end + 1
                continue
            # start tag
            m = re.match(r"<([a-zA-Z][^\s/>]*)", text[self.pos:])
            if not m:
                yield Token("text", data="<")
                self.pos += 1
                continue
            name = m.group(1).lower()
            i = self.pos + m.end()
            attrs: dict[str, str] = {}
            self_closing = False
            while i < n:
                while i < n and text[i] in " \t\r\n\f":
                    i += 1
                if i >= n:
                    break
                if text[i] == ">":
                    i += 1
                    break
                if text[i] == "/" and i + 1 < n and text[i + 1] == ">":
                    self_closing = True
                    i += 2
                    break
                if text[i] == "/":
                    i += 1
                    continue
                # attribute name
                start = i
                while i < n and text[i] not in " \t\r\n\f=/>":
                    i += 1
                aname = text[start:i].lower()
                while i < n and text[i] in " \t\r\n\f":
                    i += 1
                aval = ""
                if i < n and text[i] == "=":
                    i += 1
                    while i < n and text[i] in " \t\r\n\f":
                        i += 1
                    if i < n and text[i] in "\"'":
                        q = text[i]
                        i += 1
                        vstart = i
                        while i < n and text[i] != q:
                            i += 1
                        aval = text[vstart:i]
                        i += 1
                    else:
                        vstart = i
                        while i < n and text[i] not in " \t\r\n\f>":
                            i += 1
                        aval = text[vstart:i]
                if aname:
                    attrs[aname] = decode_entities(aval)
            self.pos = i
            yield Token("start", name=name, attrs=attrs, self_closing=self_closing)
            if name in RAW_TEXT or name in RCDATA:
                close = re.compile(r"</" + re.escape(name) + r"\s*>", re.I)
                cm = close.search(text, self.pos)
                end = cm.start() if cm else n
                raw = text[self.pos:end]
                if name in RCDATA:
                    raw = decode_entities(raw)
                if raw:
                    yield Token("text", data=raw)
                self.pos = cm.end() if cm else n
                yield Token("end", name=name)


class TreeBuilder:
    def __init__(self, document: Document):
        self.doc = document
        self.stack: list[Element] = []
        self.html: Optional[Element] = None
        self.head: Optional[Element] = None
        self.body: Optional[Element] = None
        self.mode = "initial"

    # -- helpers -------------------------------------------------------
    @property
    def current(self) -> Optional[Element]:
        return self.stack[-1] if self.stack else None

    def _ensure_html(self) -> Element:
        if self.html is None:
            self.html = Element("html", owner_document=self.doc)
            self.doc.append_child(self.html)
            self.stack.append(self.html)
        return self.html

    def _ensure_head(self) -> Element:
        self._ensure_html()
        if self.head is None:
            self.head = Element("head", owner_document=self.doc)
            self.html.append_child(self.head)
        return self.head

    def _ensure_body(self) -> Element:
        self._ensure_head()
        if self.body is None:
            self.body = Element("body", owner_document=self.doc)
            self.html.append_child(self.body)
            # body is the default insertion point
            while self.stack and self.stack[-1] is not self.html:
                self.stack.pop()
            self.stack.append(self.body)
        return self.body

    def _insert(self, el: Element) -> Element:
        parent = self.current
        if parent is None:
            parent = self._ensure_body()
        parent.append_child(el)
        return el

    def _in_stack(self, tag: str) -> bool:
        return any(e.tag == tag for e in self.stack)

    def _pop_until(self, tag: str) -> None:
        while self.stack:
            e = self.stack.pop()
            if e.tag == tag:
                return

    def _close_p(self) -> None:
        if self._in_stack("p"):
            self._pop_until("p")

    # -- main ----------------------------------------------------------
    def run(self, tokens) -> Document:
        for tok in tokens:
            self.process(tok)
        # close everything
        self._ensure_body()
        return self.doc

    def process(self, tok: Token) -> None:
        if tok.kind == "doctype":
            self.doc.doctype = tok.data
            self.doc.quirks = "html" not in tok.data.lower()
            return
        if tok.kind == "comment":
            target = self.current or self._ensure_html()
            target.append_child(Comment(tok.data, self.doc))
            return
        if tok.kind == "text":
            self._text(tok.data)
            return
        if tok.kind == "start":
            self._start(tok)
            return
        if tok.kind == "end":
            self._end(tok.name)
            return

    def _text(self, data: str) -> None:
        if not data:
            return
        cur = self.current
        # raw text / RCDATA content belongs to its element verbatim
        if cur is not None and cur.tag in RAW_TEXT | RCDATA:
            if cur.children and isinstance(cur.children[-1], Text):
                cur.children[-1].data += data
            else:
                cur.append_child(Text(data, self.doc))
            return
        if self.mode in ("initial", "head"):
            if not data.strip():
                return
            self._ensure_body()
            self.mode = "body"
        cur = self.current
        if cur is None:
            cur = self._ensure_body()
        # merge with previous text node
        if cur.children and isinstance(cur.children[-1], Text):
            cur.children[-1].data += data
        else:
            cur.append_child(Text(data, self.doc))

    def _start(self, tok: Token) -> None:
        name = tok.name
        if name == "html":
            el = self._ensure_html()
            for k, v in tok.attrs.items():
                el.attributes.setdefault(k, v)
            return
        if name == "head":
            self._ensure_html()
            if self.head is None:
                self.head = Element("head", tok.attrs, self.doc)
                self.html.append_child(self.head)
            self.stack = [self.html, self.head]
            self.mode = "head"
            return
        if name == "body":
            self._ensure_head()
            if self.body is None:
                self.body = Element("body", tok.attrs, self.doc)
                self.html.append_child(self.body)
            self.stack = [self.html, self.body]
            self.mode = "body"
            return

        if self.mode in ("initial", "head") and name in HEAD_ELEMENTS and self.body is None:
            head = self._ensure_head()
            el = Element(name, tok.attrs, self.doc)
            head.append_child(el)
            self.mode = "head"
            if name not in VOID_ELEMENTS and not tok.self_closing:
                self.stack = [self.html, head, el]
            return

        if self.body is None:
            self._ensure_body()
            self.mode = "body"

        # auto-closing rules
        if name in CLOSES_P:
            self._close_p()
        if name == "li":
            self._close_list_item("li")
        if name in ("dd", "dt"):
            self._close_list_item("dd")
            self._close_list_item("dt")
        if name == "option":
            if self.current is not None and self.current.tag == "option":
                self.stack.pop()
        if name == "tr":
            self._close_table_row()
        if name in ("td", "th"):
            self._close_cell()
        if name in ("thead", "tbody", "tfoot"):
            self._close_table_row()
        if name == "a" and self._in_stack("a"):
            self._pop_until("a")

        el = Element(name, tok.attrs, self.doc)
        self._insert(el)
        if name in VOID_ELEMENTS or tok.self_closing:
            return
        self.stack.append(el)

    def _close_list_item(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, -1, -1):
            t = self.stack[i].tag
            if t == tag:
                del self.stack[i:]
                return
            if t in ("ul", "ol", "dl", "menu"):
                return

    def _close_table_row(self) -> None:
        for i in range(len(self.stack) - 1, -1, -1):
            t = self.stack[i].tag
            if t == "tr":
                del self.stack[i:]
                return
            if t in ("table", "thead", "tbody", "tfoot"):
                return

    def _close_cell(self) -> None:
        for i in range(len(self.stack) - 1, -1, -1):
            t = self.stack[i].tag
            if t in ("td", "th"):
                del self.stack[i:]
                return
            if t in ("tr", "table"):
                return

    def _end(self, name: str) -> None:
        if name in ("html", "body"):
            return
        if name == "head":
            self.stack = [self.html] if self.html else []
            return
        if name == "p" and not self._in_stack("p"):
            # stray </p> creates an empty paragraph
            self._ensure_body()
            self._insert(Element("p", owner_document=self.doc))
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i].tag == name:
                del self.stack[i:]
                return


def parse_html(text: str, base_url: str = "") -> Document:
    doc = Document(base_url)
    builder = TreeBuilder(doc)
    builder.run(Tokenizer(text).tokens())
    # document title
    if doc.head is not None:
        for c in doc.head.children:
            if isinstance(c, Element) and c.tag == "title":
                doc.title = c.text_content().strip()
    return doc
