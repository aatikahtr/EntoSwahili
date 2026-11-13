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
import logging
import posixpath
from html import escape, unescape
from urllib.parse import urljoin, urlparse

from bs4 import NavigableString, Tag

from .sites import NOISE_TEXTS, GLOBAL_PROMO

logger = logging.getLogger(__name__)

# ── Tags zinazofutwa pamoja na ndani yake ─────────────────────
DROP = {
    "script", "style", "noscript", "template", "head", "meta", "link", "title",
    "nav", "footer", "aside", "button", "input", "select",
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

INLINE = set(WRAP) | INLINE_UNWRAP | {"a", "br", "img", "amp-img"}

HEADINGS = {"h1": "h3", "h2": "h3", "h3": "h3", "h4": "h4", "h5": "h4", "h6": "h4"}

STOP_MIN_WORDS = 40     # "Soma zaidi" inakata makala tu baada ya maneno haya
PROMO_MAX_LEN = 140     # matangazo ni mistari mifupi tu
FORM_MIN_CHARS = 400    # <form> yenye maandishi mengi ni container (mf. ASP.NET), si fomu halisi
PROMO = [re.compile(p, re.I) for p in GLOBAL_PROMO]

# ═════════ MBINU YA PICHA: mnyororo wa vyanzo (wa kwanza unaofaa unashinda) ═════════
#  1. attributes za "full/large" (Jetpack/WordPress)
#  2. srcset / data-srcset  → picha KUBWA kuliko zote
#  3. attributes za lazy-load (data-src, data-original, ...)
#  4. src ya kawaida
#  5. <picture><source>  (bila avif)
#  6. <noscript><img> iliyo jirani (lazy-load plugins huficha picha halisi hapa)
#  7. <a href="photo.jpg"> inayozunguka picha ndogo (thumbnail → full-size)
# Zaidi: background-image (style / data-bg), picha ndani ya <header>, <li>, <table>,
# na picha ya kichwa (og:image / twitter:image / JSON-LD) kama haipo ndani ya makala.
FULL_ATTRS = ("data-large-file", "data-full-url")
SRCSET_ATTRS = ("data-srcset", "data-lazy-srcset", "srcset")
LAZY_ATTRS = (
    "data-src", "data-lazy-src", "data-original", "data-lazy", "data-img-src",
    "data-actualsrc", "data-echo", "data-pagespeed-lazy-src", "data-url", "data-image",
)
BG_ATTRS = ("data-bg", "data-bg-src", "data-background", "data-background-image")
IMG_EXT = re.compile(r"\.(?:jpe?g|png|gif|webp|bmp)(?:$|[?#])", re.I)
PLACEHOLDER_STEMS = {
    "placeholder", "blank", "spacer", "transparent", "loading", "loader", "lazy",
    "lazyload", "pixel", "1x1", "empty", "noimage", "no-image", "grey", "gray",
}
BG_SKIP_CLASS = re.compile(r"icon|logo|avatar|sprite|badge|emoji|arrow|bullet", re.I)
HEADER_SKIP = re.compile(r"logo|avatar|icon|sprite|favicon", re.I)
BG_URL = re.compile(r"url\(\s*['\"]?([^'\")]+?)['\"]?\s*\)", re.I)
BAD_IMG = re.compile(
    r"(gravatar\.com|/emoji/|(?:^|/)(?:pixel|spacer|blank|transparent|loading|loader|placeholder)\.(?:gif|png))",
    re.I,
)
BAD_LINK = ("javascript:", "mailto:", "tel:", "#", "data:")

ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"), None)


def _is_small_form(tag) -> bool:
    """Fomu ndogo (search, comment, newsletter) → futa. Kubwa → ni ukurasa uliofungwa ndani ya form."""
    return tag.name == "form" and len(tag.get_text(strip=True)) < FORM_MIN_CHARS


def _usable(url) -> bool:
    """URL halisi ya picha (si data:, si placeholder)."""
    if not url:
        return False
    url = str(url).strip()
    if not url or url.startswith(("data:", "blob:", "javascript:", "about:")):
        return False
    stem = posixpath.splitext(posixpath.basename(urlparse(url).path))[0].lower()
    return stem not in PLACEHOLDER_STEMS


def _srcset_best(value) -> str | None:
    """Picha kubwa kuliko zote kwenye srcset ('url 300w, url2 800w'); inastahimili comma ndani ya URL."""
    value = (value or "").strip()
    if not value:
        return None
    pairs = [
        (u, float(n))
        for u, n in re.findall(r"(\S+?),?\s+(\d+(?:\.\d+)?)[wx]\b", value)
        if _usable(u)
    ]
    if pairs:
        return max(pairs, key=lambda p: p[1])[0]
    first = value.split()[0].rstrip(",")
    return first if _usable(first) else None


def img_key(url: str) -> str:
    """Ufunguo wa kutambua picha ile ile ya ukubwa tofauti (photo-300x200.jpg == photo.jpg)."""
    p = urlparse(url)
    path = re.sub(r"(?:-scaled|-\d{2,4}x\d{2,4})+(?=\.\w+$)", "", p.path.lower())
    return f"{p.netloc.lower()}{path}"


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
        lead_image: str | None = None,
    ):
        self.base_url = base_url
        self.title = _norm(title)
        self.images = images
        self.stop_at = stop_at
        self.drop_text = [re.compile(p, re.I) for p in (drop_text or [])]
        self.out: list[str] = []
        self.seen_texts: set[str] = set()
        self.seen_imgs: set[str] = set()
        self.words = 0
        self.lead_image = lead_image
        self.img_found = 0
        self.img_unresolved = 0
        self._li_imgs: list[str] = []

    # ═════════════ PUBLIC ═════════════
    def run(self, root: Tag) -> list[str]:
        try:
            self._container(root)
        except _Stop:
            pass

        # Picha ya kichwa (og:image n.k.) kama haipo ndani ya makala → iwe ya kwanza
        if self.images and self.lead_image:
            stem = posixpath.basename(urlparse(self.lead_image).path)
            if img_key(self.lead_image) not in self.seen_imgs and not HEADER_SKIP.search(stem):
                self.seen_imgs.add(img_key(self.lead_image))
                self.out.insert(0, f'<img src="{escape(self.lead_image)}"/>')

        if self.images:
            logger.info(
                "picha: zilizoonekana=%d, hazikupata URL=%d, zilizowekwa=%d",
                self.img_found, self.img_unresolved,
                sum(1 for b in self.out if b.startswith("<img")),
            )
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
            if name in DROP or _is_small_form(child):
                continue
            if name == "header":
                # maandishi ya <header> (title/meta) yanaondolewa, lakini picha zake zinabaki
                self._flush("p", buf)
                buf = []
                self._header_images(child)
                continue
            bg = self._bg_url(child)
            if bg:
                self._flush("p", buf)
                buf = []
                self._emit_img(bg)
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
        if name in DROP or name == "header" or _is_small_form(node):
            return []
        if name in ("img", "amp-img"):
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
        if "emoji" in classes:
            alt = (node.get("alt") or "").strip()
            return [("t", _esc(alt))] if alt else []
        if not self.images:
            return []

        self.img_found += 1
        for dim in ("width", "height"):
            raw = str(node.get(dim) or "").strip()
            if raw.isdigit() and int(raw) <= 50:
                return []

        src = self._resolve(node)
        if not src:
            self.img_unresolved += 1
            logger.info("picha bila URL inayoeleweka: %s", str(node)[:200])
            return []
        return self._img_token(src)

    def _img_token(self, src: str) -> list[tuple]:
        low = src.lower().split("?")[0]
        if low.endswith(".svg") or BAD_IMG.search(src):
            return []
        key = img_key(src)
        if key in self.seen_imgs:
            return []
        self.seen_imgs.add(key)
        return [("img", f'<img src="{escape(src)}"/>')]

    def _emit_img(self, src: str) -> None:
        for tok in self._img_token(src):
            self.out.append(tok[1])

    def _resolve(self, node: Tag) -> str | None:
        """Mnyororo wa vyanzo — chagua URL bora ya picha (angalia maelezo juu ya faili)."""
        cands: list = [node.get(a) for a in FULL_ATTRS]
        cands += [_srcset_best(node.get(a)) for a in SRCSET_ATTRS]
        cands += [node.get(a) for a in LAZY_ATTRS]
        cands.append(node.get("src"))

        parent = node.parent
        if parent is not None and parent.name == "picture":
            for source in parent.find_all("source"):
                if "avif" in (source.get("type") or "").lower():
                    continue
                cands.append(_srcset_best(source.get("data-srcset") or source.get("srcset")))

        ns = node.find_next_sibling("noscript")
        if ns is not None:
            inner = ns.find("img")
            if inner is not None:
                cands.append(inner.get("src"))

        chosen = next((str(c).strip() for c in cands if _usable(c)), None)
        anchor = node.find_parent("a")
        anchor_href = None
        if anchor is not None and anchor.get("href"):
            href = urljoin(self.base_url, anchor["href"].strip())
            if IMG_EXT.search(href):
                anchor_href = href

        if chosen is None:
            chosen = anchor_href
        if chosen is None:
            return None
        absolute = urljoin(self.base_url, chosen)

        # picha ndogo (thumbnail) iliyozungukwa na link ya picha kubwa ile ile → tumia kubwa
        if anchor_href and anchor_href != absolute and img_key(anchor_href) == img_key(absolute):
            absolute = anchor_href

        return absolute if absolute.lower().startswith(("http://", "https://")) else None

    def _bg_url(self, node: Tag) -> str | None:
        """Picha ya background (style/data-bg) kwenye element isiyo na maandishi wala <img>."""
        if not self.images:
            return None
        style = node.get("style") or ""
        data_bg = next((node.get(a) for a in BG_ATTRS if node.get(a)), None)
        if "url(" not in style and not data_bg:
            return None
        if BG_SKIP_CLASS.search(" ".join(node.get("class") or [])):
            return None
        if node.get_text(strip=True) or node.find(["img", "amp-img", "picture"]):
            return None
        url = data_bg
        if not url:
            m = BG_URL.search(style)
            url = m.group(1) if m else None
        if not _usable(url):
            return None
        url = urljoin(self.base_url, url.strip())
        return url if url.lower().startswith(("http://", "https://")) else None

    def _header_images(self, node: Tag) -> None:
        for img in node.find_all(["img", "amp-img"]):
            src = self._resolve(img) if self.images else None
            if src and HEADER_SKIP.search(posixpath.basename(urlparse(src).path)):
                continue  # logo/avatar ya tovuti, si picha ya makala
            for tok in self._img(img):
                self.out.append(tok[1])

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

        # "Soma zaidi", "ZILIZOPENDEKEZWA" → kata makala hapa (ikiwa tayari tuna maneno ya kutosha;
        # vinginevyo ni mstari wa juu tu — uondoe na uendelee)
        if len(plain) <= 80:
            head = re.sub(r"^\W+", "", low)
            if any(head.startswith(w) for w in self.stop_at):
                if self.words >= STOP_MIN_WORDS:
                    raise _Stop
                return

        # Mistari mifupi ya matangazo ("Bonyeza hapa kujiunga...") → ondoa block hiyo tu
        if len(plain) <= PROMO_MAX_LEN and any(p.search(plain) for p in PROMO):
            return

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

        self.words += len(plain.split())
        self.out.append(f"<{tag}>{html}</{tag}>")

    # ═════════════ LISTS ═════════════
    def _list(self, node: Tag, name: str) -> None:
        self._li_imgs = []
        items = self._list_items(node)
        imgs, self._li_imgs = self._li_imgs, []
        if not items:
            self.out.extend(imgs)
            return
        joined = "".join(items)
        # Orodha ya links tu (menu, related posts) → futa
        if len(items) >= 3 and _link_ratio(joined) >= 0.8:
            return
        self.words += len(_visible(joined).split())
        self.out.append(f"<{name}>{joined}</{name}>")
        self.out.extend(imgs)  # picha za ndani ya <li> zinakuja baada ya orodha

    def _list_items(self, node: Tag) -> list[str]:
        items: list[str] = []
        for child in node.children:
            if not isinstance(child, Tag):
                continue
            cname = (child.name or "").lower()
            if cname in DROP:
                continue
            if cname == "li":
                all_tokens = self._children(child, skip={"ul", "ol", "li"})
                self._li_imgs.extend(t[1] for t in all_tokens if t[0] == "img")
                tokens = [t for t in all_tokens if t[0] != "img"]
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
            for cell in cells:
                for img in cell.find_all(["img", "amp-img"]):
                    for tok in self._img(img):
                        self.out.append(tok[1])
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
            self.words += len(_visible(html).split())
            self.out.append(f"<{tag}>{html}</{tag}>")


class _Wrap:
    """Msaidizi mdogo: tibu <li> iliyo nested kama container ya items."""
    def __init__(self, li: Tag):
        self.children = [li]
