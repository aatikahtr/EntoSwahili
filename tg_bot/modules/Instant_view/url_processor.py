import aiohttp
from html import escape
from urllib.parse import urljoin
from bs4 import BeautifulSoup, Tag, NavigableString

MAX_HTML_LENGTH = 60000

# ======================
# AIOHTTP SESSION
# ======================
_aiohttp_session: aiohttp.ClientSession | None = None


async def get_session() -> aiohttp.ClientSession:
    global _aiohttp_session
    if _aiohttp_session is None or _aiohttp_session.closed:
        _aiohttp_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
            headers={"User-Agent": "Mozilla/5.0"},
        )
    return _aiohttp_session


# ======================
# SANITIZER
# ======================
ALLOWED_TAGS = {
    "p", "a", "b", "strong", "i", "em", "u",
    "s", "blockquote", "code", "pre",
    "ul", "ol", "li", "br"
}
ALLOWED_ATTRS = {"a": ["href", "title", "target", "rel"]}


def sanitize(node, base_url: str, allow_media: bool) -> str:
    if isinstance(node, NavigableString):
        return escape(str(node))

    if not isinstance(node, Tag):
        return ""

    name = node.name.lower()

    # FIGURE
    if name == "figure":
        return "".join(sanitize(c, base_url, allow_media) for c in node.contents)

    # IMAGE
    if allow_media and name == "img":
        src = (
            node.get("src")
            or node.get("data-src")
            or node.get("data-lazy-src")
        )
        if src:
            return f'<img src="{escape(urljoin(base_url, src))}"/>'
        return ""

    # TEXT TAGS
    if name in ALLOWED_TAGS:
        attrs = ""
        for k, v in node.attrs.items():
            if k in ALLOWED_ATTRS.get(name, []):
                if name == "a" and k == "href":
                    v = urljoin(base_url, v)
                attrs += f' {k}="{escape(str(v))}"'

        inner = "".join(sanitize(c, base_url, allow_media) for c in node.contents)
        return f"<{name}{attrs}>{inner}</{name}>"

    return "".join(sanitize(c, base_url, allow_media) for c in node.contents)


# ======================
# CUTTER
# ======================
def kata(title: str, blocks: list[Tag], base_url: str) -> tuple[str, str]:
    STOP_WORDS = {
        "bonyeza",
        "soma zaidi",
        "endelea kusoma",
        "read more",
        "continue reading",
    }

    # Safisha title
    title = title.split("|")[0].strip()
    parts = []

    for block in blocks:
        text = block.get_text(" ", strip=True).lower()

        # Kata content ukikutana na stop words (kwa text tu)
        if text and any(w in text for w in STOP_WORDS):
            break

        parts.append(sanitize(block, base_url, allow_media=True))

    return title, "".join(parts)


# ======================
# CORE FUNCTION (FINAL)
# ======================
async def extract_content(
    url: str,
    allow_media: bool = True,
) -> tuple[str, str]:

    session = await get_session()
    async with session.get(url) as resp:
        if resp.status != 200:
            raise ValueError("Siwezi kufikia link")
        html = await resp.text()

    soup = BeautifulSoup(html, "html.parser")

    # ===== TITLE =====
    title = soup.title.string.strip() if soup.title else "Hakuna title"

    # ===== ARTICLE ROOT =====
    article = (
        soup.find("article")
        or soup.find("main")
        or soup.body
    )

    if not article:
        raise ValueError("Hakuna content")

    # ===== CLEAN UNWANTED TAGS =====
    for tag in article(["script", "style", "nav", "footer", "aside", "noscript"]):
        tag.decompose()

    blocks: list[Tag] = []
    seen_texts: set[str] = set()

    # ===== CONTENT EXTRACTION =====
    for el in article.find_all(
        ["p", "li", "blockquote", "h2", "h3", "figure", "img"],
        recursive=True
    ):

        # MEDIA (IMG / FIGURE) → ruhusu zote
        if el.name in {"img", "figure"}:
            blocks.append(el)
            continue

        # Skip <p> ndani ya <li>
        if el.name == "p" and el.find_parent("li"):
            continue

        text = el.get_text(" ", strip=True)

        if not text:
            continue

        # Skip noise fupi sana
        if el.name in {"p", "li", "blockquote"} and len(text) < 30:
            continue

        # Zuia kurudia text
        if text in seen_texts:
            continue

        seen_texts.add(text)
        blocks.append(el)

    # ===== CUT CONTENT (SOMA ZAIDI) =====
    title, html_content = kata(title, blocks, url)

    return title, html_content[:MAX_HTML_LENGTH]
