import aiohttp
from html import escape
from urllib.parse import urljoin
from bs4 import BeautifulSoup, Tag, NavigableString


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


def sanitize(node, base_url: str) -> str:
    if isinstance(node, NavigableString):
        return escape(str(node))

    if not isinstance(node, Tag):
        return ""

    name = node.name.lower()

    # TEXT TAGS ONLY
    if name in ALLOWED_TAGS:
        attrs = ""
        for k, v in node.attrs.items():
            if k in ALLOWED_ATTRS.get(name, []):
                if name == "a" and k == "href":
                    v = urljoin(base_url, v)
                attrs += f' {k}="{escape(str(v))}"'

        inner = "".join(sanitize(c, base_url) for c in node.contents)
        return f"<{name}{attrs}>{inner}</{name}>"

    return "".join(sanitize(c, base_url) for c in node.contents)


# ======================
# CUTTER
# ======================
def kata(title: str, blocks: list[Tag], base_url: str) -> tuple[str, str]:
    title = title.split("|")[0].strip()
    parts = []

    for block in blocks:
        text = block.get_text(" ", strip=True)

        if "Tarjama:" in text or "Bonyeza" in text:
            break

        html = sanitize(block, base_url)
        html = html.replace("Alhidaaya.com", "")
        html = html.replace("Search form", "")

        parts.append(html)

    return title, "".join(parts)


# ======================
# CORE FUNCTION
# ======================
async def islam_content(url: str) -> tuple[str, str]:
    session = await get_session()
    async with session.get(url) as resp:
        if resp.status != 200:
            raise ValueError("Siwezi kufikia link")
        html = await resp.text()

    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.string.strip() if soup.title else "Hakuna title"

    article = soup.find("article") or soup.find("main") or soup.body
    if not article:
        raise ValueError("Hakuna content")

    for tag in article(["script", "style", "nav", "footer", "aside", "noscript"]):
        tag.decompose()

    blocks: list[Tag] = []
    seen_texts: set[str] = set()

    for el in article.find_all(
        ["p", "li", "blockquote", "h2", "h3"],
        recursive=True
    ):
        if el.name == "p" and el.find_parent("li"):
            continue

        text = el.get_text(" ", strip=True)
        if not text or text in seen_texts:
            continue

        seen_texts.add(text)
        blocks.append(el)

    title, html_content = kata(title, blocks, url)
    return title, html_content
