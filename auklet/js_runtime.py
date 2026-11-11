"""JavaScript runtime for Auklet.

A real ECMAScript engine (QuickJS) is embedded and given a DOM binding layer:
``document``, ``window``, element wrappers with ``querySelector``,
``createElement``, ``classList``, ``style``, ``addEventListener``, timers and
``console``.  Scripts run to completion, then the engine re-styles, re-lays out
and re-paints \u2014 so JS-driven pages actually change what is on screen.
"""

from __future__ import annotations

import json
import re
from typing import Callable, Optional

import quickjs

from .css import ComputedStyle, parse_declarations, parse_stylesheet
from .dom import Comment, Document, Element, Node, Text

# ---------------------------------------------------------------------------
# JS prelude: DOM wrapper classes implemented in JS on top of native hooks.
# ---------------------------------------------------------------------------

PRELUDE = r"""
(function(global){
  "use strict";

  function NodeList(arr){ this._items = arr || []; }
  NodeList.prototype = {
    get length(){ return this._items.length; },
    item: function(i){ return this._items[i] || null; },
    forEach: function(fn, thisArg){ this._items.forEach(fn, thisArg); },
    map: function(fn, thisArg){ return this._items.map(fn, thisArg); },
    filter: function(fn, thisArg){ return this._items.filter(fn, thisArg); },
    indexOf: function(x){ return this._items.indexOf(x); },
    [Symbol.iterator]: function(){ return this._items[Symbol.iterator](); }
  };
  Object.defineProperty(NodeList.prototype, "0", { get: function(){ return this._items[0]; } });

  function makeList(arr){ return new NodeList(arr); }

  function Style(el){
    this._el = el;
  }
  Style.prototype = {
    getPropertyValue: function(name){ return __getStyle(this._el, name) || ""; },
    setProperty: function(name, value){ __setStyle(this._el, name, String(value)); },
    removeProperty: function(name){ __setStyle(this._el, name, ""); },
    get cssText(){ return __getStyleAttr(this._el) || ""; },
    set cssText(v){ __setStyleAttr(this._el, String(v)); }
  };
  var STYLE_PROPS = ["color","background","backgroundColor","backgroundImage","display","width","height",
    "margin","marginTop","marginRight","marginBottom","marginLeft","padding","paddingTop","paddingRight",
    "paddingBottom","paddingLeft","border","borderWidth","borderColor","borderStyle","borderRadius",
    "fontSize","fontFamily","fontWeight","fontStyle","lineHeight","textAlign","textDecoration",
    "position","top","right","bottom","left","opacity","flexDirection","justifyContent","alignItems",
    "gap","flex","flexGrow","flexShrink","flexBasis","boxShadow","transform","overflow","zIndex",
    "letterSpacing","whiteSpace","textTransform","visibility","cursor","maxWidth","minWidth",
    "maxHeight","minHeight","float","clear","listStyleType","objectFit","transition","filter"];
  STYLE_PROPS.forEach(function(p){
    var css = p.replace(/[A-Z]/g, function(m){ return "-" + m.toLowerCase(); });
    Object.defineProperty(Style.prototype, p, {
      get: function(){ return __getStyle(this._el, css) || ""; },
      set: function(v){ __setStyle(this._el, css, String(v)); }
    });
  });

  function ClassList(el){
    this._el = el;
  }
  ClassList.prototype = {
    _get: function(){ var c = __getAttr(this._el, "class"); return c ? c.split(/\s+/).filter(Boolean) : []; },
    _set: function(list){ __setAttr(this._el, "class", list.join(" ")); },
    add: function(){ for (var i=0;i<arguments.length;i++){ var l=this._get(); if(l.indexOf(arguments[i])<0){ l.push(arguments[i]); this._set(l);} } },
    remove: function(){ for (var i=0;i<arguments.length;i++){ var l=this._get().filter(function(x){return x!==arguments[i];}.bind(this)); this._set(l); } },
    contains: function(c){ return this._get().indexOf(c) >= 0; },
    toggle: function(c, force){
      var has = this.contains(c);
      if (force === true) { if(!has) this.add(c); return true; }
      if (force === false) { if(has) this.remove(c); return false; }
      if (has) { this.remove(c); return false; } else { this.add(c); return true; }
    },
    replace: function(a,b){ var l=this._get(); var i=l.indexOf(a); if(i<0) return false; l[i]=b; this._set(l); return true; },
    get length(){ return this._get().length; },
    item: function(i){ return this._get()[i] || null; },
    toString: function(){ return this._get().join(" "); }
  };

  function ElementWrap(handle){
    this.__h = handle;
  }

  function wrap(handle){
    if (handle === null || handle === undefined) return null;
    var kind = __kind(handle);
    if (kind === "text") return new TextWrap(handle);
    if (kind === "document") return document;
    return new ElementWrap(handle);
  }

  function TextWrap(handle){ this.__h = handle; }
  Object.defineProperty(TextWrap.prototype, "data", {
    get: function(){ return __getText(this.__h); },
    set: function(v){ __setText(this.__h, String(v)); }
  });
  Object.defineProperty(TextWrap.prototype, "nodeValue", {
    get: function(){ return __getText(this.__h); },
    set: function(v){ __setText(this.__h, String(v)); }
  });
  Object.defineProperty(TextWrap.prototype, "textContent", {
    get: function(){ return __getText(this.__h); },
    set: function(v){ __setText(this.__h, String(v)); }
  });
  TextWrap.prototype.nodeType = 3;

  var EP = ElementWrap.prototype;

  Object.defineProperty(EP, "tagName", { get: function(){ return __tag(this.__h).toUpperCase(); } });
  Object.defineProperty(EP, "nodeName", { get: function(){ return __tag(this.__h).toUpperCase(); } });
  Object.defineProperty(EP, "nodeType", { get: function(){ return 1; } });
  Object.defineProperty(EP, "id", {
    get: function(){ return __getAttr(this.__h, "id") || ""; },
    set: function(v){ __setAttr(this.__h, "id", String(v)); }
  });
  Object.defineProperty(EP, "className", {
    get: function(){ return __getAttr(this.__h, "class") || ""; },
    set: function(v){ __setAttr(this.__h, "class", String(v)); }
  });
  Object.defineProperty(EP, "classList", { get: function(){ return new ClassList(this.__h); } });
  Object.defineProperty(EP, "style", { get: function(){ return new Style(this.__h); } });
  Object.defineProperty(EP, "dataset", {
    get: function(){
      var self = this, out = {};
      var names = __attrNames(this.__h);
      names.forEach(function(n){
        if (n.indexOf("data-") === 0) {
          var key = n.slice(5).replace(/-([a-z])/g, function(m,c){ return c.toUpperCase(); });
          out[key] = __getAttr(self.__h, n);
        }
      });
      return out;
    }
  });
  Object.defineProperty(EP, "children", {
    get: function(){ return makeList(__children(this.__h).map(wrap)); }
  });
  Object.defineProperty(EP, "childNodes", {
    get: function(){ return makeList(__childNodes(this.__h).map(wrap)); }
  });
  Object.defineProperty(EP, "parentNode", { get: function(){ return wrap(__parent(this.__h)); } });
  Object.defineProperty(EP, "parentElement", { get: function(){ return wrap(__parent(this.__h)); } });
  Object.defineProperty(EP, "firstChild", { get: function(){ var c=__childNodes(this.__h); return c.length?wrap(c[0]):null; } });
  Object.defineProperty(EP, "lastChild", { get: function(){ var c=__childNodes(this.__h); return c.length?wrap(c[c.length-1]):null; } });
  Object.defineProperty(EP, "firstElementChild", { get: function(){ var c=__children(this.__h); return c.length?wrap(c[0]):null; } });
  Object.defineProperty(EP, "lastElementChild", { get: function(){ var c=__children(this.__h); return c.length?wrap(c[c.length-1]):null; } });
  Object.defineProperty(EP, "nextSibling", { get: function(){ return wrap(__nextSibling(this.__h)); } });
  Object.defineProperty(EP, "previousSibling", { get: function(){ return wrap(__prevSibling(this.__h)); } });
  Object.defineProperty(EP, "nextElementSibling", { get: function(){ return wrap(__nextElement(this.__h)); } });
  Object.defineProperty(EP, "previousElementSibling", { get: function(){ return wrap(__prevElement(this.__h)); } });
  Object.defineProperty(EP, "textContent", {
    get: function(){ return __textContent(this.__h); },
    set: function(v){ __setTextContent(this.__h, String(v)); }
  });
  Object.defineProperty(EP, "innerHTML", {
    get: function(){ return __innerHTML(this.__h); },
    set: function(v){ __setInnerHTML(this.__h, String(v)); }
  });
  Object.defineProperty(EP, "outerHTML", { get: function(){ return __outerHTML(this.__h); } });
  Object.defineProperty(EP, "innerText", {
    get: function(){ return __textContent(this.__h); },
    set: function(v){ __setTextContent(this.__h, String(v)); }
  });
  Object.defineProperty(EP, "value", {
    get: function(){ return __getAttr(this.__h, "value") || ""; },
    set: function(v){ __setAttr(this.__h, "value", String(v)); }
  });
  Object.defineProperty(EP, "checked", {
    get: function(){ return __hasAttr(this.__h, "checked"); },
    set: function(v){ if (v) __setAttr(this.__h, "checked", ""); else __removeAttr(this.__h, "checked"); }
  });
  Object.defineProperty(EP, "href", {
    get: function(){ return __getAttr(this.__h, "href") || ""; },
    set: function(v){ __setAttr(this.__h, "href", String(v)); }
  });
  Object.defineProperty(EP, "src", {
    get: function(){ return __getAttr(this.__h, "src") || ""; },
    set: function(v){ __setAttr(this.__h, "src", String(v)); }
  });
  Object.defineProperty(EP, "offsetWidth", { get: function(){ return __boxMetric(this.__h, "w"); } });
  Object.defineProperty(EP, "offsetHeight", { get: function(){ return __boxMetric(this.__h, "h"); } });
  Object.defineProperty(EP, "offsetTop", { get: function(){ return __boxMetric(this.__h, "y"); } });
  Object.defineProperty(EP, "offsetLeft", { get: function(){ return __boxMetric(this.__h, "x"); } });
  Object.defineProperty(EP, "clientWidth", { get: function(){ return __boxMetric(this.__h, "cw"); } });
  Object.defineProperty(EP, "clientHeight", { get: function(){ return __boxMetric(this.__h, "ch"); } });

  EP.getAttribute = function(n){ var v = __getAttr(this.__h, String(n).toLowerCase()); return v === null ? null : v; };
  EP.setAttribute = function(n, v){ __setAttr(this.__h, String(n).toLowerCase(), String(v)); };
  EP.removeAttribute = function(n){ __removeAttr(this.__h, String(n).toLowerCase()); };
  EP.hasAttribute = function(n){ return __hasAttr(this.__h, String(n).toLowerCase()); };
  EP.getAttributeNames = function(){ return __attrNames(this.__h); };
  EP.appendChild = function(child){ if(!child) return child; __appendChild(this.__h, child.__h); return child; };
  EP.append = function(){ for(var i=0;i<arguments.length;i++){ var a=arguments[i]; if(typeof a==="string"){ __appendText(this.__h, a); } else if(a && a.__h!==undefined){ __appendChild(this.__h, a.__h); } } };
  EP.prepend = function(){ for(var i=arguments.length-1;i>=0;i--){ var a=arguments[i]; if(typeof a==="string"){ __prependText(this.__h, a); } else if(a && a.__h!==undefined){ __prependChild(this.__h, a.__h); } } };
  EP.removeChild = function(child){ __removeChild(this.__h, child.__h); return child; };
  EP.replaceChild = function(nu, old){ __replaceChild(this.__h, nu.__h, old.__h); return old; };
  EP.insertBefore = function(nu, ref){ __insertBefore(this.__h, nu.__h, ref ? ref.__h : null); return nu; };
  EP.remove = function(){ __removeNode(this.__h); };
  EP.cloneNode = function(deep){ return wrap(__cloneNode(this.__h, !!deep)); };
  EP.contains = function(other){ return other && other.__h !== undefined ? __contains(this.__h, other.__h) : false; };
  EP.querySelector = function(sel){ return wrap(__querySelector(this.__h, String(sel))); };
  EP.querySelectorAll = function(sel){ return makeList(__querySelectorAll(this.__h, String(sel)).map(wrap)); };
  EP.getElementsByTagName = function(t){ return makeList(__getElementsByTagName(this.__h, String(t)).map(wrap)); };
  EP.getElementsByClassName = function(c){ return makeList(__getElementsByClassName(this.__h, String(c)).map(wrap)); };
  EP.closest = function(sel){ return wrap(__closest(this.__h, String(sel))); };
  EP.matches = function(sel){ return __matches(this.__h, String(sel)); };
  EP.addEventListener = function(type, fn, opts){ __addEventListener(this.__h, String(type), fn, opts); };
  EP.removeEventListener = function(type, fn){ __removeEventListener(this.__h, String(type), fn); };
  EP.dispatchEvent = function(ev){ return __dispatchEvent(this.__h, ev); };
  EP.click = function(){ __dispatchEvent(this.__h, {type:"click", target:this, bubbles:true}); };
  EP.focus = function(){ __dispatchEvent(this.__h, {type:"focus", target:this, bubbles:false}); };
  EP.blur = function(){ __dispatchEvent(this.__h, {type:"blur", target:this, bubbles:false}); };
  EP.getBoundingClientRect = function(){
    var r = __rect(this.__h);
    return {x:r[0], y:r[1], left:r[0], top:r[1], width:r[2], height:r[3], right:r[0]+r[2], bottom:r[1]+r[3]};
  };
  EP.getComputedStyle = function(){ return __computedStyle(this.__h); };
  EP.toString = function(){ return "[object HTML" + (__tag(this.__h)[0]||"?").toUpperCase() + __tag(this.__h).slice(1) + "Element]"; };

  var document = {
    __h: __documentHandle(),
    nodeType: 9,
    get documentElement(){ return wrap(__documentElement()); },
    get head(){ return wrap(__documentHead()); },
    get body(){ return wrap(__documentBody()); },
    get title(){ return __documentTitle(); },
    set title(v){ __setDocumentTitle(String(v)); },
    get readyState(){ return "complete"; },
    getElementById: function(id){ return wrap(__getElementById(String(id))); },
    querySelector: function(sel){ return wrap(__querySelector(this.__h, String(sel))); },
    querySelectorAll: function(sel){ return makeList(__querySelectorAll(this.__h, String(sel)).map(wrap)); },
    getElementsByTagName: function(t){ return makeList(__getElementsByTagName(this.__h, String(t)).map(wrap)); },
    getElementsByClassName: function(c){ return makeList(__getElementsByClassName(this.__h, String(c)).map(wrap)); },
    createElement: function(tag){ return wrap(__createElement(String(tag))); },
    createTextNode: function(t){ return wrap(__createTextNode(String(t))); },
    createComment: function(t){ return wrap(__createComment(String(t))); },
    addEventListener: function(type, fn, opts){ __addEventListener(this.__h, String(type), fn, opts); },
    removeEventListener: function(type, fn){ __removeEventListener(this.__h, String(type), fn); },
    dispatchEvent: function(ev){ return __dispatchEvent(this.__h, ev); },
    write: function(){ for(var i=0;i<arguments.length;i++){ __documentWrite(String(arguments[i])); } },
    get cookie(){ return ""; },
    set cookie(v){}
  };
  Object.defineProperty(document, "children", { get: function(){ return makeList(__children(this.__h).map(wrap)); } });
  Object.defineProperty(document, "childNodes", { get: function(){ return makeList(__childNodes(this.__h).map(wrap)); } });

  global.document = document;
  global.NodeList = NodeList;
  global.HTMLElement = ElementWrap;
  global.Element = ElementWrap;
  global.Node = ElementWrap;
  global.Text = TextWrap;
  global.__wrap = wrap;
  global.__makeList = makeList;
})(this);
"""


class JSRuntime:
    """Owns a QuickJS context and the DOM bridge."""

    def __init__(self, document: Document, viewport=(1280, 800),
                 on_mutation: Optional[Callable[[], None]] = None,
                 on_console: Optional[Callable[[str, str], None]] = None):
        self.doc = document
        self.viewport = viewport
        self.on_mutation = on_mutation
        self.on_console = on_console
        self.ctx = quickjs.Context()
        self.handles: dict[int, Node] = {}
        self._next_handle = 1
        self._handle_of: dict[int, int] = {}
        self.listeners: dict[tuple[int, str], list] = {}
        self.timers: list[tuple[float, object, list]] = []
        self._now = 0.0
        self.errors: list[str] = []
        self._install()

    # -- handle management ---------------------------------------------
    def handle(self, node: Optional[Node]) -> Optional[int]:
        if node is None:
            return None
        key = id(node)
        h = self._handle_of.get(key)
        if h is None:
            h = self._next_handle
            self._next_handle += 1
            self._handle_of[key] = h
            self.handles[h] = node
        return h

    def node(self, h) -> Optional[Node]:
        try:
            return self.handles.get(int(h))
        except (TypeError, ValueError):
            return None

    def _mutated(self) -> None:
        if self.on_mutation is not None:
            self.on_mutation()

    # -- installation ---------------------------------------------------
    def _install(self) -> None:
        ctx = self.ctx
        rt = self

        def _log(level):
            def fn(*args):
                msg = " ".join(_js_str(a) for a in args)
                if rt.on_console:
                    rt.on_console(level, msg)
            return fn

        for level in ("log", "info", "warn", "error", "debug"):
            ctx.add_callable(f"__console_{level}", _log(level))
        ctx.eval(
            "var console = {log: __console_log, info: __console_info, warn: __console_warn,"
            " error: __console_error, debug: __console_debug};"
        )

        # --- node accessors
        ctx.add_callable("__kind", lambda h: _kind(rt.node(h)))
        ctx.add_callable("__tag", lambda h: getattr(rt.node(h), "tag", ""))
        ctx.add_callable("__getAttr", lambda h, n: _get_attr(rt.node(h), n))
        ctx.add_callable("__setAttr", lambda h, n, v: _set_attr(rt, rt.node(h), n, v))
        ctx.add_callable("__removeAttr", lambda h, n: _remove_attr(rt, rt.node(h), n))
        ctx.add_callable("__hasAttr", lambda h, n: _has_attr(rt.node(h), n))
        ctx.add_callable("__attrNames", lambda h: _attr_names(rt.node(h)))
        ctx.add_callable("__getText", lambda h: getattr(rt.node(h), "data", ""))
        ctx.add_callable("__setText", lambda h, v: _set_text(rt, rt.node(h), v))
        ctx.add_callable("__textContent", lambda h: _text_content(rt.node(h)))
        ctx.add_callable("__setTextContent", lambda h, v: _set_text_content(rt, rt.node(h), v))
        ctx.add_callable("__innerHTML", lambda h: _inner_html(rt.node(h)))
        ctx.add_callable("__setInnerHTML", lambda h, v: _set_inner_html(rt, rt.node(h), v))
        ctx.add_callable("__outerHTML", lambda h: _outer_html(rt.node(h)))
        ctx.add_callable("__children", lambda h: [rt.handle(c) for c in _children(rt.node(h))])
        ctx.add_callable("__childNodes", lambda h: [rt.handle(c) for c in _child_nodes(rt.node(h))])
        ctx.add_callable("__parent", lambda h: rt.handle(_parent(rt.node(h))))
        ctx.add_callable("__nextSibling", lambda h: rt.handle(_sibling(rt.node(h), 1)))
        ctx.add_callable("__prevSibling", lambda h: rt.handle(_sibling(rt.node(h), -1)))
        ctx.add_callable("__nextElement", lambda h: rt.handle(_element_sibling(rt.node(h), 1)))
        ctx.add_callable("__prevElement", lambda h: rt.handle(_element_sibling(rt.node(h), -1)))

        # --- style
        ctx.add_callable("__getStyle", lambda h, p: _get_style(rt.node(h), p))
        ctx.add_callable("__setStyle", lambda h, p, v: _set_style(rt, rt.node(h), p, v))
        ctx.add_callable("__getStyleAttr", lambda h: getattr(rt.node(h), "style_attr", "") or "")
        ctx.add_callable("__setStyleAttr", lambda h, v: _set_style_attr(rt, rt.node(h), v))
        ctx.add_callable("__computedStyle", lambda h: _computed_style(rt, rt.node(h)))

        # --- tree mutation
        ctx.add_callable("__appendChild", lambda p, c: _append(rt, rt.node(p), rt.node(c)))
        ctx.add_callable("__prependChild", lambda p, c: _prepend(rt, rt.node(p), rt.node(c)))
        ctx.add_callable("__appendText", lambda p, t: _append_text(rt, rt.node(p), t))
        ctx.add_callable("__prependText", lambda p, t: _prepend_text(rt, rt.node(p), t))
        ctx.add_callable("__removeChild", lambda p, c: _remove_child(rt, rt.node(p), rt.node(c)))
        ctx.add_callable("__replaceChild", lambda p, n, o: _replace_child(rt, rt.node(p), rt.node(n), rt.node(o)))
        ctx.add_callable("__insertBefore", lambda p, n, r: _insert_before(rt, rt.node(p), rt.node(n), rt.node(r)))
        ctx.add_callable("__removeNode", lambda h: _remove_node(rt, rt.node(h)))
        ctx.add_callable("__cloneNode", lambda h, deep: rt.handle(_clone(rt.node(h), bool(deep))))
        ctx.add_callable("__contains", lambda a, b: _contains(rt.node(a), rt.node(b)))

        # --- queries
        ctx.add_callable("__querySelector", lambda h, s: rt.handle(_query_one(rt.node(h), s)))
        ctx.add_callable("__querySelectorAll", lambda h, s: [rt.handle(n) for n in _query_all(rt.node(h), s)])
        ctx.add_callable("__getElementsByTagName", lambda h, t: [rt.handle(n) for n in _by_tag(rt.node(h), t)])
        ctx.add_callable("__getElementsByClassName", lambda h, c: [rt.handle(n) for n in _by_class(rt.node(h), c)])
        ctx.add_callable("__closest", lambda h, s: rt.handle(_closest(rt.node(h), s)))
        ctx.add_callable("__matches", lambda h, s: _matches(rt.node(h), s))

        # --- document
        ctx.add_callable("__documentHandle", lambda: rt.handle(rt.doc))
        ctx.add_callable("__documentElement", lambda: rt.handle(rt.doc.document_element))
        ctx.add_callable("__documentHead", lambda: rt.handle(rt.doc.head))
        ctx.add_callable("__documentBody", lambda: rt.handle(rt.doc.body))
        ctx.add_callable("__documentTitle", lambda: rt.doc.title)
        ctx.add_callable("__setDocumentTitle", lambda v: setattr(rt.doc, "title", v))
        ctx.add_callable("__getElementById", lambda i: rt.handle(rt.doc.get_element_by_id(i)))
        ctx.add_callable("__createElement", lambda t: rt.handle(Element(t, owner_document=rt.doc)))
        ctx.add_callable("__createTextNode", lambda t: rt.handle(Text(t, rt.doc)))
        ctx.add_callable("__createComment", lambda t: rt.handle(Comment(t, rt.doc)))
        ctx.add_callable("__documentWrite", lambda t: _document_write(rt, t))

        # --- events
        ctx.add_callable("__addEventListener", lambda h, t, fn, o: _add_listener(rt, h, t, fn))
        ctx.add_callable("__removeEventListener", lambda h, t, fn: _remove_listener(rt, h, t, fn))
        ctx.add_callable("__dispatchEvent", lambda h, ev: _dispatch(rt, h, ev))

        # --- geometry
        ctx.add_callable("__boxMetric", lambda h, k: _box_metric(rt, rt.node(h), k))
        ctx.add_callable("__rect", lambda h: _rect(rt, rt.node(h)))

        # --- timers
        ctx.add_callable("__setTimeout", lambda fn, ms: _add_timer(rt, fn, ms, False))
        ctx.add_callable("__setInterval", lambda fn, ms: _add_timer(rt, fn, ms, True))
        ctx.add_callable("__clearTimer", lambda i: _clear_timer(rt, i))
        ctx.add_callable("__now", lambda: rt._now)

        # --- window
        ctx.eval(PRELUDE)
        ctx.eval(
            "var window = this;"
            "window.innerWidth = %d; window.innerHeight = %d; window.devicePixelRatio = 1;"
            "window.setTimeout = __setTimeout; window.setInterval = __setInterval;"
            "window.clearTimeout = __clearTimer; window.clearInterval = __clearTimer;"
            "window.requestAnimationFrame = function(fn){ return __setTimeout(fn, 16); };"
            "window.alert = __console_log;"
            "window.location = {href: %s, pathname: '/', search: '', hash: ''};"
            "window.navigator = {userAgent: 'Auklet/1.0', language: 'en-US'};"
            "window.addEventListener = function(t, fn){ __addEventListener(__documentHandle(), t, fn); };"
            "window.self = window; window.top = window; window.parent = window;"
            % (int(self.viewport[0]), int(self.viewport[1]), json.dumps(self.doc.base_url or ""))
        )

    # -- execution ------------------------------------------------------
    def run(self, code: str, filename: str = "<script>") -> None:
        try:
            self.ctx.eval(code)
        except Exception as exc:  # quickjs.JSException
            msg = f"{filename}: {exc}"
            self.errors.append(msg)
            if self.on_console:
                self.on_console("error", msg)

    def run_timers(self, budget: float = 2.0, max_steps: int = 2000) -> None:
        """Run queued timers in virtual time until the queue drains."""
        steps = 0
        while self.timers and steps < max_steps:
            steps += 1
            self.timers.sort(key=lambda t: t[0])
            when, fn, args = self.timers.pop(0)
            self._now = max(self._now, when)
            try:
                if callable(fn):
                    fn()
                else:
                    self.ctx.eval(f"({fn})()")
            except Exception as exc:
                self.errors.append(f"timer: {exc}")
                if self.on_console:
                    self.on_console("error", f"timer: {exc}")
            if self._now > budget:
                break

    def fire_event(self, node: Node, event_type: str, extra: Optional[dict] = None) -> bool:
        h = self.handle(node)
        ev = {"type": event_type, "bubbles": True, "target": None}
        if extra:
            ev.update(extra)
        try:
            return bool(_dispatch(self, h, ev))
        except Exception as exc:
            self.errors.append(f"event {event_type}: {exc}")
            return False


# ---------------------------------------------------------------------------
# Bridge helpers
# ---------------------------------------------------------------------------


def _js_str(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return f"{v:g}" if isinstance(v, float) else str(v)
    return str(v)


def _kind(node) -> str:
    if node is None:
        return "null"
    if isinstance(node, Document):
        return "document"
    if isinstance(node, Text):
        return "text"
    if isinstance(node, Element):
        return "element"
    return "other"


def _get_attr(node, name):
    if isinstance(node, Element):
        return node.attributes.get(str(name).lower())
    return None


def _set_attr(rt, node, name, value):
    if isinstance(node, Element):
        node.set_attribute(str(name), str(value))
        rt._mutated()


def _remove_attr(rt, node, name):
    if isinstance(node, Element):
        node.remove_attribute(str(name))
        rt._mutated()


def _has_attr(node, name) -> bool:
    return isinstance(node, Element) and str(name).lower() in node.attributes


def _attr_names(node) -> list:
    return list(node.attributes.keys()) if isinstance(node, Element) else []


def _set_text(rt, node, value):
    if isinstance(node, Text):
        node.data = str(value)
        rt._mutated()


def _text_content(node) -> str:
    if node is None:
        return ""
    return node.text_content()


def _set_text_content(rt, node, value):
    if node is None:
        return
    node.set_text_content(str(value))
    rt._mutated()


def _inner_html(node) -> str:
    if isinstance(node, Element):
        return node.inner_html()
    return ""


def _set_inner_html(rt, node, value):
    if not isinstance(node, Element):
        return
    from .html_parser import parse_html
    frag = parse_html(f"<body>{value}</body>")
    body = frag.body
    node.set_text_content("")
    if body is not None:
        for c in list(body.children):
            node.append_child(c)
    rt._mutated()


def _outer_html(node) -> str:
    from .dom import serialize
    return serialize(node) if node is not None else ""


def _children(node) -> list:
    if node is None:
        return []
    return [c for c in node.children if isinstance(c, Element)]


def _child_nodes(node) -> list:
    return list(node.children) if node is not None else []


def _parent(node):
    return node.parent if node is not None else None


def _sibling(node, direction):
    if node is None:
        return None
    return node.next_sibling() if direction > 0 else node.previous_sibling()


def _element_sibling(node, direction):
    if node is None:
        return None
    s = node.next_sibling() if direction > 0 else node.previous_sibling()
    while s is not None and not isinstance(s, Element):
        s = s.next_sibling() if direction > 0 else s.previous_sibling()
    return s


def _get_style(node, prop):
    if not isinstance(node, Element):
        return ""
    from .css import parse_declarations
    for d in parse_declarations(node.style_attr or ""):
        if d.prop == str(prop).lower():
            return d.value
    return ""


def _set_style(rt, node, prop, value):
    if not isinstance(node, Element):
        return
    from .css import parse_declarations
    decls = parse_declarations(node.style_attr or "")
    prop = str(prop).lower()
    out = []
    found = False
    for d in decls:
        if d.prop == prop:
            found = True
            if str(value).strip():
                out.append(f"{prop}: {value}")
        else:
            out.append(f"{d.prop}: {d.value}")
    if not found and str(value).strip():
        out.append(f"{prop}: {value}")
    node.set_attribute("style", "; ".join(out))
    rt._mutated()


def _set_style_attr(rt, node, value):
    if isinstance(node, Element):
        node.set_attribute("style", str(value))
        rt._mutated()


def _computed_style(rt, node):
    if not isinstance(node, Element):
        return {}
    st = getattr(rt, "styles", {}).get(id(node)) if hasattr(rt, "styles") else None
    if st is None:
        return {}
    return {k: v for k, v in st.props.items()}


def _append(rt, parent, child):
    if parent is None or child is None:
        return
    parent.append_child(child)
    rt._mutated()


def _prepend(rt, parent, child):
    if parent is None or child is None:
        return
    ref = parent.children[0] if parent.children else None
    parent.insert_before(child, ref)
    rt._mutated()


def _append_text(rt, parent, text):
    if parent is None:
        return
    parent.append_child(Text(str(text), parent.owner_document))
    rt._mutated()


def _prepend_text(rt, parent, text):
    if parent is None:
        return
    ref = parent.children[0] if parent.children else None
    parent.insert_before(Text(str(text), parent.owner_document), ref)
    rt._mutated()


def _remove_child(rt, parent, child):
    if parent is None or child is None:
        return
    if child in parent.children:
        parent.remove_child(child)
        rt._mutated()


def _replace_child(rt, parent, new, old):
    if parent is None or new is None or old is None:
        return
    parent.replace_child(new, old)
    rt._mutated()


def _insert_before(rt, parent, new, ref):
    if parent is None or new is None:
        return
    parent.insert_before(new, ref)
    rt._mutated()


def _remove_node(rt, node):
    if node is not None and node.parent is not None:
        node.parent.remove_child(node)
        rt._mutated()


def _clone(node, deep):
    if isinstance(node, Text):
        return Text(node.data, node.owner_document)
    if isinstance(node, Comment):
        return Comment(node.data, node.owner_document)
    if isinstance(node, Element):
        el = Element(node.tag, dict(node.attributes), node.owner_document)
        if deep:
            for c in node.children:
                el.append_child(_clone(c, True))
        return el
    return None


def _contains(a, b) -> bool:
    if a is None or b is None:
        return False
    n = b
    while n is not None:
        if n is a:
            return True
        n = n.parent
    return False


def _query_one(root, selector):
    from .css import matches, parse_selector
    sel = parse_selector(selector)
    if sel is None or root is None:
        return None
    for n in root.walk():
        if isinstance(n, Element) and matches(n, sel):
            return n
    return None


def _query_all(root, selector) -> list:
    from .css import matches, parse_selector
    sel = parse_selector(selector)
    if sel is None or root is None:
        return []
    return [n for n in root.walk() if isinstance(n, Element) and matches(n, sel)]


def _by_tag(root, tag) -> list:
    tag = str(tag).lower()
    if root is None:
        return []
    return [n for n in root.walk() if isinstance(n, Element) and (tag == "*" or n.tag == tag)]


def _by_class(root, cls) -> list:
    if root is None:
        return []
    return [n for n in root.walk() if isinstance(n, Element) and str(cls) in n.classes]


def _closest(node, selector):
    from .css import matches, parse_selector
    sel = parse_selector(selector)
    if sel is None:
        return None
    n = node
    while n is not None:
        if isinstance(n, Element) and matches(n, sel):
            return n
        n = n.parent
    return None


def _matches(node, selector) -> bool:
    from .css import matches, parse_selector
    sel = parse_selector(selector)
    return bool(sel and isinstance(node, Element) and matches(node, sel))


def _document_write(rt, text):
    body = rt.doc.body
    if body is None:
        return
    from .html_parser import parse_html
    frag = parse_html(f"<body>{text}</body>")
    if frag.body is not None:
        for c in list(frag.body.children):
            body.append_child(c)
    rt._mutated()


def _add_listener(rt, handle, event_type, fn):
    try:
        h = int(handle)
    except (TypeError, ValueError):
        return
    rt.listeners.setdefault((h, str(event_type)), []).append(fn)


def _remove_listener(rt, handle, event_type, fn):
    try:
        h = int(handle)
    except (TypeError, ValueError):
        return
    lst = rt.listeners.get((h, str(event_type)), [])
    rt.listeners[(h, str(event_type))] = [f for f in lst if f is not fn]


def _dispatch(rt, handle, ev) -> bool:
    try:
        h = int(handle)
    except (TypeError, ValueError):
        return False
    node = rt.node(h)
    if node is None:
        return False
    etype = ev.get("type") if isinstance(ev, dict) else getattr(ev, "type", "")
    if not etype:
        return False
    target = node
    # build event object in JS
    try:
        rt.ctx.eval(
            "globalThis.__ev = {type: %s, bubbles: %s, defaultPrevented: false, "
            "preventDefault: function(){ this.defaultPrevented = true; }, "
            "stopPropagation: function(){ this._stopped = true; }};"
            % (json.dumps(str(etype)), "true" if (isinstance(ev, dict) and ev.get("bubbles", True)) else "false")
        )
    except Exception:
        return False
    ev_obj = rt.ctx.get("__ev")
    # capture/bubble path
    path = []
    n = target
    while n is not None:
        path.append(n)
        n = n.parent
    handled = False
    for n in path:
        nh = rt.handle(n)
        for fn in list(rt.listeners.get((nh, str(etype)), [])):
            try:
                fn(ev_obj)
                handled = True
            except Exception as exc:
                rt.errors.append(f"listener {etype}: {exc}")
                if rt.on_console:
                    rt.on_console("error", f"listener {etype}: {exc}")
        if not (isinstance(ev, dict) and ev.get("bubbles", True)):
            break
    return handled


def _box_metric(rt, node, key) -> float:
    box = getattr(rt, "box_index", {}).get(id(node)) if hasattr(rt, "box_index") else None
    if box is None:
        return 0.0
    if key == "w":
        return round(box.w, 2)
    if key == "h":
        return round(box.h, 2)
    if key == "x":
        return round(box.x, 2)
    if key == "y":
        return round(box.y, 2)
    if key == "cw":
        return round(box.content_w, 2)
    if key == "ch":
        return round(box.content_h, 2)
    return 0.0


def _rect(rt, node):
    box = getattr(rt, "box_index", {}).get(id(node)) if hasattr(rt, "box_index") else None
    if box is None:
        return [0.0, 0.0, 0.0, 0.0]
    return [round(box.x, 2), round(box.y, 2), round(box.w, 2), round(box.h, 2)]


def _add_timer(rt, fn, ms, repeat) -> int:
    try:
        delay = float(ms) / 1000.0
    except (TypeError, ValueError):
        delay = 0.0
    tid = len(rt.timers) + 1
    rt.timers.append((rt._now + max(0.0, delay), fn, []))
    return tid


def _clear_timer(rt, tid) -> None:
    pass
