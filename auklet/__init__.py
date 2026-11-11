"""Auklet — a browser engine written from scratch.

Public API::

    from auklet import Browser
    b = Browser(viewport=(1280, 800))
    b.load_html("<h1>Hello</h1>")
    b.screenshot("out.png")
"""

from .browser import Browser, FrameStats, ResourceLoader
from .css import StyleEngine, parse_stylesheet
from .dom import Comment, Document, Element, Node, Text
from .html_parser import parse_html
from .layout import Box, layout_document
from .paint import Painter

__version__ = "1.0.0"
__all__ = [
    "Browser", "FrameStats", "ResourceLoader", "StyleEngine", "parse_stylesheet",
    "Comment", "Document", "Element", "Node", "Text", "parse_html", "Box",
    "layout_document", "Painter", "__version__",
]
