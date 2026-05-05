import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ContextTypes
from telegraph.aio import Telegraph

NOISE_TEXTS = {
    "table of contents",
    "sign in with google to post a comment",
    "no comments yet. be the first!",
    "write a comment",
    "post comment",
}

telegraph = Telegraph(access_token="522e083178bb4d7511cc1784c3f849b9e71164cdac06d08812181c1945dc")

# Tags zinazoruhusiwa na Telegraph
ALLOWED_TAGS = {"b", "strong", "i", "em", "u", "s", "a", "img", "p", "br",
                "h3", "h4", "ul", "ol", "li", "blockquote", "pre", "code", "figure", "figcaption"}


def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


def clean_node(tag) -> str:
    """Badilisha BeautifulSoup node kuwa HTML safi inayokubalika na Telegraph."""
    from bs4 import NavigableString, Tag

    if isinstance(tag, NavigableString):
        return str(tag)

    if not isinstance(tag, Tag):
        return ""

    name = tag.name.lower() if tag.name else ""

    # Ruka tags zisizohusika
    if name in {"script", "style", "nav", "footer", "aside", "form", "button", "input"}:
        return ""

    # Picha
    if name == "img":
        src = tag.get("src", "")
        alt = tag.get("alt", "")
        if src and src.startswith("http"):
            return f'<img src="{src}" alt="{alt}"/>'
        return ""

    # Link
    if name == "a":
        href = tag.get("href", "")
        inner = "".join(clean_node(child) for child in tag.children)
        if href and href.startswith("http") and inner.strip():
            return f'<a href="{href}">{inner}</a>'
        return inner

    # Tags zinazobeba maandishi
    inner = "".join(clean_node(child) for child in tag.children)

    if not inner.strip():
        return ""

    # Map tags za HTML kwenda zinazoruhusiwa na Telegraph
    tag_map = {
        "strong": "b", "em": "i",
        "h1": "h3", "h2": "h3", "h5": "h4", "h6": "h4",
    }
    mapped = tag_map.get(name, name)

    if mapped in ALLOWED_TAGS:
        return f"<{mapped}>{inner}</{mapped}>"

    # Tags zisizojulikana — rudisha maandishi tu ndani yake
    return inner


def extract_content(soup: BeautifulSoup) -> str:
    """Toa content yote kutoka ukurasa."""

    # Jaribu kupata sehemu kuu ya makala
    main = (
        soup.find("article")
        or soup.find("main")
        or soup.find(class_=lambda c: c and any(
            x in str(c).lower() for x in ["content", "post-body", "entry", "article-body"]
        ))
        or soup.find("body")
    )

    if not main:
        return ""

    parts = []

    for tag in main.find_all(
        ["p", "h2", "h3", "h4", "ul", "ol", "blockquote", "pre", "figure", "img"],
        recursive=True
    ):
        # Epuka kurudia — ruka kama mzazi wake tayari amechakatwa
        if tag.find_parent(["figure"]) and tag.name == "img":
            continue

        cleaned = clean_node(tag)
        if cleaned.strip():
            # Angalia noise
            plain = BeautifulSoup(cleaned, "html.parser").get_text().strip().lower()
            if plain and plain not in NOISE_TEXTS and len(plain) > 10:
                parts.append(cleaned)

    return "".join(parts)


async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    original_message = update.message

    if not context.args:
        await original_message.reply_text("⚠️ Toa URL. Mfano: /get https://example.com")
        return

    url = context.args[0]

    if not is_url(url):
        await original_message.reply_text("⚠️ URL si sahihi. Lazima ianze na http:// au https://")
        return

    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Title
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else "Habari"

        # Content kamili na formatting
        html_content = extract_content(soup)

        if not html_content.strip():
            await original_message.reply_text("⚠️ Imeshindwa kupata content.")
            return

        # Telegraph limit ya 64KB
        if len(html_content.encode("utf-8")) > 64000:
            html_content = html_content[:60000] + "<p>... (imekatwa)</p>"

        # Chapisha ukurasa wa Telegraph
        page = await telegraph.create_page(
            title=title,
            html_content=html_content,
        )

        telegraph_url = f"https://telegra.ph/{page['path']}"

        await original_message.reply_text(
            f"📄 <b>{title}</b>\n\n"
            f"🔗 <a href='{telegraph_url}'>Soma hapa (Instant View)</a>",
            parse_mode="HTML",
            disable_web_page_preview=False,
        )

    except Exception as e:
        await original_message.reply_text(f"❌ Hitilafu: {e}")
