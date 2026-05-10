#import requests
import httpx
from telegram import Update
from telegram.ext import ContextTypes
from telegraph.aio import Telegraph
from bs4 import BeautifulSoup
from bs4 import BeautifulSoup as BS
from urllib.parse import urljoin

telegraph = Telegraph(access_token="522e083178bb4d7511cc1784c3f849b9e71164cdac06d08812181c1945dc")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


NOISE_TEXTS = {
    "table of contents",
    "sign in with google to post a comment",
    "no comments yet. be the first!",
    "write a comment",
    "post comment",
}



ALLOWED_TAGS = {
    "p", "a", "b", "strong", "i", "em", "u",
    "s", "blockquote", "code", "pre",
    "ul", "ol", "li", "br", "img"
}


# CSS selectors za sections zisizohitajika - zitafutwa kabisa
UNWANTED_SELECTORS = [
    # Share buttons
    ".sharedaddy",
    ".jp-relatedposts",
    ".sd-sharing",
    "[class*='share']",
    
    # Related posts
    "[class*='related']",
    ".related-posts",
    
    # Navigation prev/next
    ".post-navigation",
    ".nav-links",
    ".navigation",
    "[class*='navigation']",
    
    # Sidebar / widgets
    ".widget",
    ".sidebar",
    
    # Elementor extras
    ".elementor-share-btn",
    "[class*='social']",
    
    # Copy button area (firqatunnajia specific)
    ".wp-block-buttons",
    ".wp-block-button",
    
    # Comments
    "#comments",
    ".comments-area",
]



def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


def detect_platform(soup: BeautifulSoup, url: str):
    """Gundua platform kutoka kwa meta tags au URL."""
    generator = soup.find("meta", attrs={"name": "generator"})
    gen_content = (generator.get("content", "") if generator else "").lower()

    if "wordpress" in gen_content or "elementor" in gen_content:
        return "wordpress"
    if soup.find("link", attrs={"rel": "https://api.w.org/"}):
        return "wordpress"
    if "blogger" in gen_content:
        return "blogger"
    if "drupal" in gen_content:
        return "drupal"
    if "medium.com" in url:
        return "medium"
    if "substack.com" in url:
        return "substack"
    return "generic"


def get_content_selectors(platform: str):
    selectors = {
        "wordpress": [".elementor-widget-theme-post-content .elementor-widget-container", ".entry-content", ".post-content", "article .content", "article"],
        "blogger":   [".post-body", ".entry-content", "#post-body", "article"],
        "drupal":    [".field-items", ".field-item", ".node__content", "#main-content", ".region-content"],
        "medium":    ["article", ".meteredContent", "section"],
        "substack":  [".body.markup", ".available-content", "article"],
        "generic":   [
            "article", ".entry-content", ".post-content", ".article-content",
            "main article", ".single-content", "#content article",
            ".content-area article", ".site-content article", "main",
        ],
    }
    return selectors.get(platform, selectors["generic"])


def find_content_element(soup: BeautifulSoup, selectors: list):
    for selector in selectors:
        el = soup.select_one(selector)
        if el:
            return el
    return soup.find("body")


import re

def clean_html(html: str, base_url: str) -> str:
    # Futa XML kwanza kabla BeautifulSoup haijasoma
    html = re.sub(r'<\?xml[^>]*\?>', '', html)
    html = re.sub(r'<xml[^>]*>.*?</xml>', '', html, flags=re.DOTALL)
    
    soup = BeautifulSoup(html, "html.parser")
    
    # 1. Futa sections zote zisizohitajika kwanza
    for selector in UNWANTED_SELECTORS:
        for tag in soup.select(selector):
            tag.decompose()

    # 2. Ondoa tags zisizohitajika
    for tag in soup.find_all(True):
        if tag.name and tag.name.lower() in {
            "script", "style", "nav", "footer", "aside",
            "form", "button", "input", "xml", "svg", "meta",
            "link", "head", "noscript", "iframe", "canvas",
            "select", "textarea", "label", "header", "figure",
            "picture", "source", "video", "audio", "map", "area",
        }:
            tag.decompose()

    def process_node(tag):
        from bs4 import NavigableString, Tag

        if isinstance(tag, NavigableString):
            return str(tag)
        if not isinstance(tag, Tag):
            return ""

        name = tag.name.lower() if tag.name else ""

        if name == "img":
            src = tag.get("src", "").strip()
            if not src:
                return ""
            src = urljoin(base_url, src)
            return f'<img src="{src}"/>' if src.startswith("http") else ""

        if name == "a":
            href = tag.get("href", "").strip()
            inner = "".join(process_node(child) for child in tag.children)
            if href:
                href = urljoin(base_url, href)
            if href.startswith("http") and inner.strip():
                return f'<a href="{href}">{inner}</a>'
            return inner

        inner = "".join(process_node(child) for child in tag.children)
        if not inner.strip():
            return ""

        tag_map = {"strong": "b", "em": "i", "h1": "h3", "h2": "h3", "h5": "h4", "h6": "h4"}
        mapped = tag_map.get(name, name)

        if not mapped or mapped not in ALLOWED_TAGS:
            return inner

        return f"<{mapped}>{inner}</{mapped}>"

    parts = []
    TOP_LEVEL_TAGS = {"p", "h2", "h3", "h4", "ul", "ol", "blockquote", "pre"}

    for tag in soup.find_all(list(TOP_LEVEL_TAGS) + ["img"], recursive=True):
        if tag.name == "img":
            src = tag.get("src", "").strip()
            if src:
                src = urljoin(base_url, src)
                if src.startswith("http"):
                    parts.append(f'<img src="{src}"/>')
            continue

        if any(parent.name in TOP_LEVEL_TAGS for parent in tag.parents):
            continue

        cleaned = process_node(tag)
        if cleaned.strip():
            plain = BeautifulSoup(cleaned, "html.parser").get_text().strip().lower()
            if plain and plain not in NOISE_TEXTS and len(plain) > 10:
                parts.append(cleaned)

    return "".join(parts)


#=======
# Commmand
#=======

async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    original_message = update.message

    if not context.args:
        await original_message.reply_text("⚠️ Toa URL 🔗. Mfano: /get https://example.com")
        return

    url = context.args[0]

    if not is_url(url):
        await original_message.reply_text("⚠️ URL si sahihi. Lazima ianze na http:// au https://")
        return

    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
            #response = requests.get(url, headers=HEADERS, timeout=30)
            response = await client.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            

        # Pata title
        h1 = soup.find("h1")
        title = h1.get_text().strip() if h1 else "Habari"

        # Gundua platform na pata content
        platform = detect_platform(soup, url)
        selectors = get_content_selectors(platform)
        content_el = find_content_element(soup, selectors)

        if not content_el:
            await original_message.reply_text("⚠️ Imeshindwa kupata content.")
            return


        html_content = clean_html(str(content_el), base_url=url)

        if not html_content.strip():
            await original_message.reply_text("⚠️ Imeshindwa kupata content.")
            return

        html_content = str(BS(html_content, "html.parser"))
        
        if len(html_content.encode("utf-8")) > 64000:
            html_content = html_content[:60000] + "<p>... (imekatwa)</p>"

        page_data = await telegraph.create_page(title=title, html_content=html_content)
        telegraph_url = f"https://telegra.ph/{page_data['path']}"

        await original_message.reply_text(
            f"📄 <b>{title}</b>\n\n"
            f"🔗 <a href='{telegraph_url}'>Soma hapa (Instant View)</a>",
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
    
    
    except httpx.HTTPError as e:
        await original_message.reply_text(f"❌ Hitilafu ya mtandao: {e}")
    except Exception as e:
        await original_message.reply_text(f"❌ Hitilafu: {e}")
        
