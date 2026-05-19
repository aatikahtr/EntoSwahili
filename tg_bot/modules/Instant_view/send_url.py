import httpx
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ContextTypes

from modules.Instant_view.IslamSite.constants import telegraph
from modules.Instant_view.IslamSite.html_cleaner import clean_html
from modules.Instant_view.IslamSite.constants import HEADERS


def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


def detect_platform(url: str, soup: BeautifulSoup) -> str:
    """Gundua platform kutoka URL na meta tags."""
    if "trtafrika.com" in url:
        return "trtafrika"
    if "firqatunnajia.com" in url:
        return "firqatunnajia"
    if "gsmarena.com" in url:
        return "gsmarena"
    if "medium.com" in url:
        return "medium"
    if "substack.com" in url:
        return "substack"

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

    return "generic"


def get_selectors(platform: str) -> list[str]:
    """Rudisha selectors kulingana na platform."""
    selectors_map = {
        # TRT Afrika — chagua article body moja kwa moja (ProseMirror editor)
        "trtafrika": [
            
            #".tiptap.ProseMirror",
            #".ProseMirror",
            #"[class*='trt-article-body']",
            "article",
        ],
        "firqatunnajia": [
            ".elementor-widget-theme-post-content .elementor-widget-container",
        ],
        "gsmarena": [
            "#specs-list",
            ".specs-cp-wrapper",
            ".review-body",
            "article",
        ],
        "wordpress": [
            ".entry-content",
            ".post-content",
            "article .content",
            "article",
        ],
        "blogger": [
            ".post-body",
            ".entry-content",
            "#post-body",
            "article",
        ],
        "drupal": [
            ".field-name-body .field-item",
            ".field-items",
            ".field-item",
            ".node__content",
            "#main-content",
            ".region-content",
        ],
        "medium": [
            "article",
            ".meteredContent",
            "section",
        ],
        "substack": [
            ".body.markup",
            ".available-content",
            "article",
        ],
        "generic": [
            "article",
            ".entry-content",
            ".post-content",
            ".article-content",
            "main article",
            ".single-content",
            "#content article",
            ".content-area article",
            ".site-content article",
            "main",
        ],
    }
    return selectors_map.get(platform, selectors_map["generic"])


def find_content(soup: BeautifulSoup, selectors: list[str]):
    """Tafuta element ya kwanza inayopatikana kutoka selectors."""
    for selector in selectors:
        el = soup.select_one(selector)
        if el:
            return el
    return soup.find("body")


async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    original_message = update.message

    if not context.args:
        await original_message.reply_text(
            "⚠️ Toa URL 🔗. Mfano: /get https://example.com"
        )
        return

    url = context.args[0]

    if not is_url(url):
        await original_message.reply_text(
            "⚠️ URL si sahihi. Lazima ianze na http:// au https://"
        )
        return

    try:
        async with httpx.AsyncClient(
            headers=HEADERS,
            follow_redirects=True,
            timeout=30,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Title
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else "Habari"

        # Gundua platform na pata selectors
        platform = detect_platform(url, soup)
        selectors = get_selectors(platform)

        # Pata content element
        content_el = find_content(soup, selectors)

        if not content_el:
            await original_message.reply_text("⚠️ Imeshindwa kupata content.")
            return

        body_html = content_el.decode_contents()
        html_content = clean_html(body_html, base_url=url)

        if not html_content.strip():
            await original_message.reply_text("⚠️ Imeshindwa kupata content.")
            return

        if len(html_content.encode("utf-8")) > 64000:
            html_content = html_content[:60000] + "<p>... (imekatwa)</p>"

        page_data = await telegraph.create_page(
            title=title,
            html_content=html_content,
        )

        telegraph_url = f"https://telegra.ph/{page_data['path']}"

        await original_message.reply_text(
            f"📄 <b>{title}</b>\n\n"
            f"🔗 <a href='{telegraph_url}'>Soma hapa (Instant View)</a>",
            parse_mode="HTML",
            disable_web_page_preview=False,
        )

    except httpx.HTTPStatusError as e:
        await original_message.reply_text(
            f"❌ Server ilikataa ombi: {e.response.status_code}"
        )
    except httpx.RequestError as e:
        await original_message.reply_text(
            f"❌ Hitilafu ya mtandao:\n{e}"
        )
    except Exception as e:
        await original_message.reply_text(
            f"❌ Hitilafu kwenye send_url.py:\n{e}"
        )
