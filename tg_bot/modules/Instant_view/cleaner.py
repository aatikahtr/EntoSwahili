"""
cleaner.py — INJINI YA KUSAFISHA HTML (maandishi + picha tu).

Inapokea element ya makala (BeautifulSoup) na kurudisha LIST ya "blocks"
tayari kwa Telegraph. Kila block ni mojawapo ya:

    <p>  <h3>  <h4>  <blockquote>  <pre>  <ul>/<ol> (na <li>)  <img/>

Ndani ya blocks za maandishi zinaruhusiwa tu:  a  b  i  u  s  code  br
Kila tag nyingine (script, iframe, video, audio, form, div, span, table...)
ama inafutwa, ama inafunguliwa (unwrap) au kubadilishwa kuwa maandishi.

Ili kuzuia tag mpya isiyofaa: ongeza kwenye DROP.
Ili kuruhusu tag mpya: ongeza kwenye WRAP / INLINE_UNWRAP.
"""

import re
from html import escape, unescape
from urllib.parse import urljoin

from bs4 import NavigableString, Tag

from .sites import NOISE_TEXTS

# ── Tags zinazofutwa pamoja na ndani yake ─────────────────────
DROP = {
    "script", "style", "noscript", "template", "head", "meta", "link", "title",
    "nav", "footer", "aside", "header", "form", "button", "input", "select",
    "textarea", "option", "label", "fieldset", "svg", "canvas", "iframe",
    "video", "audio", "source", "track", "object", "embed", "map", "area",
    "dialog", "menu", "hr",
}

# ── Inline tags zinazobaki (zimebadilishwa jina) ──────────────
WRAP = {
    "b": "b", "strong": "b",
    "i": "i", "em": "i", "cite": "i",
    "u": "u", "ins": "u",
    "s": "s", "strike": "s", "del": "s",
    "code": "code", "kbd": "code", "samp": "code", "tt": "code",
}

# ── Inline tags zinazofunguliwa (maandishi yanabaki, tag inaondoka) ──
INLINE_UNWRAP = {
    "span", "small", "big", "mark", "abbr", "sup", "sub", "font", "time",
    "bdi", "bdo", "q", "var", "dfn", "wbr", "data", "ruby", "rt", "rp",
}

INLINE = set(WRAP) | INLINE_UNWRAP | {"a", "br", "img"}

HEADINGS = {"h1": "h3", "h2": "h3", "h3": "h3", "h4": "h4", "h5": "h4", "h6": "h4"}

LAZY_ATTRS = ("data-src", "data-lazy-src", "data-original", "data-lazy", "src")
BAD_IMG = re.compile(
    r"(gravatar\.com|/emoji/|(?:^|/)(?:pixel|spacer|blank|transparent|loading|loader|placeholder)\.(?:gif|png))",
    re.I,
)
BAD_LINK = ("javascript:", "mailto:", "tel:", "#", "data:")

ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"), None)


class _Stop(Exception):
    """Inatupwa tukifika kwenye 'Soma zaidi' n.k. — kila kitu baada yake kinaachwa."""


def _esc(text: str) -> str:
    return escape(text, quote=False)


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(ZERO_WIDTH))


def _visible(html: str) -> str:
    """Maandishi yanayoonekana kutoka kwa HTML ya block."""
    return unescape(re.sub(r"<[^>]+>", "", html)).strip()


def _trim(html: str) -> str:
    html = re.sub(r"(?:<br/>\s*){2,}", "<br/>", html)
    return re.sub(r"^(?:\s|<br/>)+|(?:\s|<br/>)+$", "", html)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _link_ratio(html: str) -> float:
    total = len(_visible(html))
    if not total:
        return 0.0
    linked = sum(len(_visible(m)) for m in re.findall(r"<a\b[^>]*>(.*?)</a>", html, re.S))
    return linked / total


def _wrap(tokens: list[tuple], open_: str, close: str) -> list[tuple]:
    """Funika text tokens kwa tag; picha zinabaki nje (hazifungwi ndani ya tag)."""
    out: list[tuple] = []
    run: list[str] = []

    def flush():
        s = "".join(run)
        run.clear()
        if _visible(s):
            out.append(("t", f"{open_}{s}{close}"))
        elif s:
            out.append(("t", s))

    for tok in tokens:
        if tok[0] == "t":
            run.append(tok[1])
        elif tok[0] == "br":
            run.append("<br/>")
        else:
            flush()
            out.append(tok)
    flush()
    return out


class Cleaner:
    def __init__(
        self,
        base_url: str,
        title: str = "",
        images: bool = True,
        stop_at: tuple = (),
        drop_text: list[str] | None = None,
    ):
        self.base_url = base_url
        self.title = _norm(title)
        self.images = images
        self.stop_at = stop_at
        self.drop_text = [re.compile(p, re.I) for p in (drop_text or [])]
        self.out: list[str] = []
        self.seen_texts: set[str] = set()
        self.seen_imgs: set[str] = set()

    # ═════════════ PUBLIC ═════════════
    def run(self, root: Tag) -> list[str]:
        try:
            self._container(root)
        except _Stop:
            pass
        return self.out

    # ═════════════ BLOCK LEVEL ═════════════
    def _container(self, node: Tag) -> None:
        """Pitia watoto; inline content inakusanywa kuwa <p>, blocks zinashughulikiwa."""
        buf: list[tuple] = []
        for child in node.children:
            if isinstance(child, NavigableString):
                if type(child) is NavigableString:  # si Comment/Doctype/CData
                    buf.append(("t", _esc(_collapse(str(child)))))
                continue
            if not isinstance(child, Tag):
                continue
            name = (child.name or "").lower()
            if name in DROP:
                continue
            if name in INLINE:
                buf.extend(self._inline(child))
            else:
                self._flush("p", buf)
                buf = []
                self._block(child, name)
        self._flush("p", buf)

    def _block(self, node: Tag, name: str) -> None:
        if name in HEADINGS:
            self._flush(HEADINGS[name], self._children(node))
        elif name in ("p", "figcaption", "caption", "dt", "dd", "address"):
            self._flush("p", self._children(node))
        elif name == "blockquote":
            self._flush("blockquote", self._children(node))
        elif name in ("ul", "ol"):
            self._list(node, name)
        elif name == "pre":
            text = node.get_text().translate(ZERO_WIDTH).strip("\n")
            if text.strip():
                self.out.append(f"<pre>{_esc(text)}</pre>")
        elif name == "table":
            self._table(node)
        else:
            # div, section, article, figure, picture, tr, td, na tag zisizojulikana
            self._container(node)

    # ═════════════ INLINE LEVEL ═════════════
    def _children(self, node: Tag, skip: set | None = None) -> list[tuple]:
        tokens: list[tuple] = []
        for child in node.children:
            if isinstance(child, NavigableString):
                if type(child) is NavigableString:
                    tokens.append(("t", _esc(_collapse(str(child)))))
            elif isinstance(child, Tag):
                if skip and (child.name or "").lower() in skip:
                    continue
                tokens.extend(self._inline(child))
        return tokens

    def _inline(self, node: Tag) -> list[tuple]:
        name = (node.name or "").lower()
        if name in DROP:
            return []
        if name == "img":
            return self._img(node)
        if name == "br":
            return [("br",)]

        children = self._children(node)

        if name == "a":
            href = (node.get("href") or "").strip()
            if not href or href.lower().startswith(BAD_LINK):
                return children
            href = urljoin(self.base_url, href)
            if not href.lower().startswith(("http://", "https://")):
                return children
            return _wrap(children, f'<a href="{escape(href)}">', "</a>")

        if name in WRAP:
            tag = WRAP[name]
            return _wrap(children, f"<{tag}>", f"</{tag}>")

        if name in INLINE_UNWRAP:
            return children

        # tag ya block ndani ya inline context (mf. <div> ndani ya <blockquote>)
        return [("br",)] + children + [("br",)]

    def _img(self, node: Tag) -> list[tuple]:
        # emoji ya WordPress ni <img> lakini ni maandishi — ibaki hata kwa text-only
        classes = " ".join(node.get("class") or [])
        if "emoji" in classes.split() or "emoji" in classes:
            alt = (node.get("alt") or "").strip()
            return [("t", _esc(alt))] if alt else []
        if not self.images:
            return []

        src = ""
        for attr in LAZY_ATTRS:
            val = (node.get(attr) or "").strip()
            if val and not val.startswith("data:"):
                src = val
                break
        if not src:
            srcset = (node.get("data-srcset") or node.get("srcset") or "").strip()
            if srcset:
                src = srcset.split(",")[-1].strip().split(" ")[0]
        if not src:
            return []

        for dim in ("width", "height"):
            raw = str(node.get(dim) or "").strip()
            if raw.isdigit() and int(raw) <= 50:
                return []

        src = urljoin(self.base_url, src)
        low = src.lower().split("?")[0]
        if (
            not src.lower().startswith(("http://", "https://"))
            or low.endswith(".svg")
            or BAD_IMG.search(src)
            or src in self.seen_imgs
        ):
            return []

        self.seen_imgs.add(src)
        return [("img", f'<img src="{escape(src)}"/>')]

    # ═════════════ EMIT ═════════════
    def _flush(self, tag: str, tokens: list[tuple]) -> None:
        """Geuza tokens kuwa blocks: maandishi → <tag>, picha → <img/> (kwa mpangilio)."""
        run: list[str] = []

        def emit():
            s = _trim("".join(run))
            run.clear()
            if _visible(s):
                self._emit_text(tag, s)

        for tok in tokens:
            if tok[0] == "t":
                run.append(tok[1])
            elif tok[0] == "br":
                run.append("<br/>")
            else:
                emit()
                self.out.append(tok[1])
        emit()

    def _emit_text(self, tag: str, html: str) -> None:
        plain = _visible(html)
        low = _norm(plain)

        if low in NOISE_TEXTS:
            return

        # "Soma zaidi", "Bonyeza", "ZILIZOPENDEKEZWA" → kata makala hapa
        if len(plain) <= 80 and any(w in low for w in self.stop_at):
            raise _Stop

        if any(p.search(plain) for p in self.drop_text):
            return

        # Mstari mfupi ambao ni link tu (mf. "Soma pia: ...") → noise
        if tag == "p" and len(plain) < 60 and _link_ratio(html) > 0.9:
            return

        # Kichwa kinachorudia title ya ukurasa
        if tag in ("h3", "h4") and low == self.title:
            return

        if low in self.seen_texts:
            return
        self.seen_texts.add(low)

        self.out.append(f"<{tag}>{html}</{tag}>")

    # ═════════════ LISTS ═════════════
    def _list(self, node: Tag, name: str) -> None:
        items = self._list_items(node)
        if not items:
            return
        joined = "".join(items)
        # Orodha ya links tu (menu, related posts) → futa
        if len(items) >= 3 and _link_ratio(joined) >= 0.8:
            return
        self.out.append(f"<{name}>{joined}</{name}>")

    def _list_items(self, node: Tag) -> list[str]:
        items: list[str] = []
        for child in node.children:
            if not isinstance(child, Tag):
                continue
            cname = (child.name or "").lower()
            if cname in DROP:
                continue
            if cname == "li":
                tokens = [t for t in self._children(child, skip={"ul", "ol", "li"}) if t[0] != "img"]
                s = _trim("".join(t[1] if t[0] == "t" else "<br/>" for t in tokens))
                plain = _visible(s)
                if plain and _norm(plain) not in NOISE_TEXTS and not any(
                    p.search(plain) for p in self.drop_text
                ):
                    items.append(f"<li>{s}</li>")
                # nested lists → items za ziada (Telegraph haipendi nesting)
                for sub in child.find_all(["ul", "ol", "li"], recursive=False):
                    items.extend(self._list_items(sub if sub.name != "li" else _Wrap(sub)))
            else:
                items.extend(self._list_items(child))
        return items

    # ═════════════ TABLES ═════════════
    def _table(self, node: Tag) -> None:
        rows = [tr for tr in node.find_all("tr") if tr.find_parent("table") is node]
        cells_per_row = [
            [c for c in tr.find_all(["td", "th"], recursive=False)] for tr in rows
        ]
        max_cols = max((len(c) for c in cells_per_row), default=0)

        # Table ya layout (safu moja) → itendewe kama container ya kawaida
        if max_cols <= 1:
            self._container(node)
            return

        category = None
        for cells in cells_per_row:
            texts = [_collapse(c.get_text(" ", strip=True)).strip() for c in cells]
            texts = [t for t in texts if t]
            if not texts:
                continue

            if len(cells) == 3 and cells[0].name == "th" and cells[0].get("rowspan"):
                # GSMArena: category | label | value
                if texts[0] != category:
                    category = texts[0]
                    self._raw("h4", f"▸ {_esc(texts[0])}")
                if len(texts) >= 3:
                    self._raw("p", f"<b>{_esc(texts[1])}</b>  {_esc(texts[2])}")
                continue

            if len(texts) == 1:
                self._raw("h4", _esc(texts[0]))
            elif any(c.name == "th" for c in cells):
                self._raw("h4", _esc("  ·  ".join(texts)))
            elif len(texts) == 2:
                self._raw("p", f"<b>{_esc(texts[0])}</b>  {_esc(texts[1])}")
            else:
                self._raw("p", _esc("  ·  ".join(texts)))

    def _raw(self, tag: str, html: str) -> None:
        if _visible(html) and _norm(_visible(html)) not in NOISE_TEXTS:
            self.out.append(f"<{tag}>{html}</{tag}>")


class _Wrap:
    """Msaidizi mdogo: tibu <li> iliyo nested kama container ya items."""
    def __init__(self, li: Tag):
        self.children = [li]
