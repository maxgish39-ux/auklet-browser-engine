"""Auklet DOM: a small but real document object model.

Nodes are plain Python objects with parent/child links.  The tree is the single
source of truth for the HTML parser, the CSS engine, layout and the JS bindings.
"""

from __future__ import annotations

from typing import Iterator, Optional


class Node:
    __slots__ = ("parent", "children", "owner_document")

    node_type = 0

    def __init__(self, owner_document: Optional["Document"] = None):
        self.parent: Optional[Node] = None
        self.children: list[Node] = []
        self.owner_document = owner_document

    # -- tree mutation -------------------------------------------------
    def append_child(self, child: "Node") -> "Node":
        if child.parent is not None:
            child.parent.remove_child(child)
        child.parent = self
        child.owner_document = self.owner_document
        self.children.append(child)
        return child

    def insert_before(self, child: "Node", ref: Optional["Node"]) -> "Node":
        if ref is None:
            return self.append_child(child)
        if child.parent is not None:
            child.parent.remove_child(child)
        idx = self.children.index(ref)
        child.parent = self
        child.owner_document = self.owner_document
        self.children.insert(idx, child)
        return child

    def remove_child(self, child: "Node") -> "Node":
        self.children.remove(child)
        child.parent = None
        return child

    def replace_child(self, new: "Node", old: "Node") -> "Node":
        idx = self.children.index(old)
        if new.parent is not None:
            new.parent.remove_child(new)
        self.children[idx] = new
        new.parent = self
        old.parent = None
        return old

    # -- traversal -----------------------------------------------------
    def walk(self) -> Iterator["Node"]:
        yield self
        for c in list(self.children):
            yield from c.walk()

    def ancestors(self) -> Iterator["Node"]:
        n = self.parent
        while n is not None:
            yield n
            n = n.parent

    def previous_sibling(self) -> Optional["Node"]:
        if self.parent is None:
            return None
        sibs = self.parent.children
        i = sibs.index(self)
        return sibs[i - 1] if i > 0 else None

    def next_sibling(self) -> Optional["Node"]:
        if self.parent is None:
            return None
        sibs = self.parent.children
        i = sibs.index(self)
        return sibs[i + 1] if i + 1 < len(sibs) else None

    def element_children(self) -> list["Element"]:
        return [c for c in self.children if isinstance(c, Element)]

    def text_content(self) -> str:
        out = []
        for n in self.walk():
            if isinstance(n, Text):
                out.append(n.data)
        return "".join(out)

    def set_text_content(self, value: str) -> None:
        for c in self.children:
            c.parent = None
        self.children = []
        if value:
            self.append_child(Text(value, self.owner_document))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} {getattr(self, 'tag', '')}>"


class Text(Node):
    __slots__ = ("data",)
    node_type = 3

    def __init__(self, data: str, owner_document: Optional["Document"] = None):
        super().__init__(owner_document)
        self.data = data

    def text_content(self) -> str:
        return self.data


class Comment(Node):
    __slots__ = ("data",)
    node_type = 8

    def __init__(self, data: str, owner_document: Optional["Document"] = None):
        super().__init__(owner_document)
        self.data = data

    def text_content(self) -> str:
        return ""


class Element(Node):
    __slots__ = ("tag", "attributes", "style_attr", "dataset")
    node_type = 1

    def __init__(self, tag: str, attrs: Optional[dict] = None,
                 owner_document: Optional["Document"] = None):
        super().__init__(owner_document)
        self.tag = tag.lower()
        self.attributes: dict[str, str] = dict(attrs or {})
        self.style_attr: Optional[str] = self.attributes.get("style")

    # -- attributes ----------------------------------------------------
    def get_attribute(self, name: str) -> Optional[str]:
        return self.attributes.get(name.lower())

    def set_attribute(self, name: str, value: str) -> None:
        name = name.lower()
        self.attributes[name] = value
        if name == "style":
            self.style_attr = value

    def remove_attribute(self, name: str) -> None:
        name = name.lower()
        self.attributes.pop(name, None)
        if name == "style":
            self.style_attr = None

    def has_attribute(self, name: str) -> bool:
        return name.lower() in self.attributes

    @property
    def id(self) -> str:
        return self.attributes.get("id", "")

    @property
    def classes(self) -> list[str]:
        return self.attributes.get("class", "").split()

    def matches_class(self, name: str) -> bool:
        return name in self.classes

    # -- serialization -------------------------------------------------
    def inner_html(self) -> str:
        return "".join(serialize(c) for c in self.children)

    def outer_html(self) -> str:
        return serialize(self)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Element {self.tag} {self.attributes}>"


class Document(Node):
    __slots__ = ("doctype", "quirks", "base_url", "title")
    node_type = 9

    def __init__(self, base_url: str = ""):
        super().__init__(None)
        self.owner_document = self
        self.doctype: Optional[str] = None
        self.quirks = False
        self.base_url = base_url
        self.title = ""

    @property
    def document_element(self) -> Optional[Element]:
        for c in self.children:
            if isinstance(c, Element) and c.tag == "html":
                return c
        return None

    @property
    def head(self) -> Optional[Element]:
        root = self.document_element
        if root:
            for c in root.children:
                if isinstance(c, Element) and c.tag == "head":
                    return c
        return None

    @property
    def body(self) -> Optional[Element]:
        root = self.document_element
        if root:
            for c in root.children:
                if isinstance(c, Element) and c.tag == "body":
                    return c
        return None

    def get_element_by_id(self, ident: str) -> Optional[Element]:
        for n in self.walk():
            if isinstance(n, Element) and n.attributes.get("id") == ident:
                return n
        return None

    def elements(self) -> Iterator[Element]:
        for n in self.walk():
            if isinstance(n, Element):
                yield n


def serialize(node: Node) -> str:
    if isinstance(node, Text):
        return escape_text(node.data)
    if isinstance(node, Comment):
        return f"<!--{node.data}-->"
    if isinstance(node, Document):
        return "".join(serialize(c) for c in node.children)
    if isinstance(node, Element):
        attrs = "".join(
            f' {k}="{escape_attr(v)}"' if v != "" else f" {k}"
            for k, v in node.attributes.items()
        )
        if node.tag in VOID_ELEMENTS:
            return f"<{node.tag}{attrs}>"
        return f"<{node.tag}{attrs}>" + "".join(serialize(c) for c in node.children) + f"</{node.tag}>"
    return ""


VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


def escape_text(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def escape_attr(s: str) -> str:
    return s.replace("&", "&amp;").replace('"', "&quot;")
