import asyncio
import httpx
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ContextTypes

from modules.Instant_view.IslamSite.constants import telegraph, HEADERS
from modules.Instant_view.IslamSite.html_cleaner import clean_html
from .platform_handler import detect_platform, get_selectors, find_content, cleanup_platform

# Import browser manager kutoka get_command.py yako
from modules.Instant_view.IslamSite.get_command import get_browser, block_resources

SEMAPHORE = asyncio.Semaphore(5)

_client: httpx.AsyncClient | None = None

# Domains zinazohitaji JS — ongeza kadri unavyogundua
JS_REQUIRED_DOMAINS = {
    "trtafrika.com",
    "trtworld.com",
    # ongeza hapa...
}


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            headers=HEADERS,
            follow_redirects=True,
            timeout=httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=5.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _client


def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


def needs_js(url: str) -> bool:
    """Angalia kama URL inahitaji JS."""
    from urllib.parse import urlparse
    domain = urlparse(url).netloc.replace("www.", "")
    return domain in JS_REQUIRED_DOMAINS


# ============================================
# FETCH — httpx (haraka, bila JS)
# ============================================

async def fetch_with_httpx(url: str) -> BeautifulSoup:
    client = await get_client()
    response = await client.get(url)
    response.raise_for_status()
    encoding = response.encoding or "utf-8"
    return BeautifulSoup(response.content, "lxml", from_encoding=encoding)


# ============================================
# FETCH — Playwright (polepole, na JS)
# ============================================

async def fetch_with_playwright(url: str) -> BeautifulSoup:
    browser = await get_browser()

    ctx = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        java_script_enabled=True,
        bypass_csp=True,
        viewport={"width": 1280, "height": 720},
    )

    # Block image/font/media — lakini ACHA stylesheet kwa JS sites
    await ctx.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in {"image", "media", "font"}
        else route.continue_(),
    )

    try:
        page = await ctx.new_page()
        page.set_default_timeout(20000)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            # Subiri JS ikamilishe kazi yake
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            await page.goto(url, wait_until="load", timeout=30000)

        full_html = await page.content()
        return BeautifulSoup(full_html, "lxml")

    finally:
        await ctx.close()


# ============================================
# MAIN COMMAND
# ============================================

async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with SEMAPHORE:
        original_message = update.message

        if not context.args:
            await original_message.reply_text(
                "⚠️ Toa URL 🔗\n\nMfano:\n/get https://example.com"
            )
            return

        url = context.args[0].strip()

        if not is_url(url):
            await original_message.reply_text(
                "⚠️ URL si sahihi.\n\nLazima ianze na:\n- http://\n- https://"
            )
            return

        try:
            # ====================================
            # CHAGUA FETCH METHOD
            # ====================================

            if needs_js(url):
                soup = await fetch_with_playwright(url)
            else:
                soup = await fetch_with_httpx(url)

            # ====================================
            # TITLE
            # ====================================

            title = "Habari"
            h1 = soup.find("h1")
            if h1 and h1.get_text(strip=True):
                title = h1.get_text(strip=True)
            else:
                og_title = soup.find("meta", property="og:title")
                if og_title and og_title.get("content", "").strip():
                    title = og_title["content"].strip()
                else:
                    page_title = soup.find("title")
                    if page_title and page_title.get_text(strip=True):
                        title = page_title.get_text(strip=True)

            # ====================================
            # PLATFORM + CONTENT
            # ====================================

            platform = detect_platform(url, soup)
            selectors = get_selectors(platform)
            content_el = find_content(soup, selectors)

            if not content_el:
                await original_message.reply_text("⚠️ Imeshindwa kupata content.")
                return

            cleanup_platform(platform, content_el)
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
            code = e.response.status_code
            msgs = {
                403: "❌ Tovuti imekataa ufikiaji (403 Forbidden).",
                404: "❌ Ukurasa haupatikani (404 Not Found).",
                429: "❌ Maombi mengi sana. Jaribu tena baadaye (429).",
                500: "❌ Hitilafu ya server ya tovuti (500).",
            }
            await original_message.reply_text(msgs.get(code, f"❌ Server ilikataa ombi: {code}"))

        except httpx.TimeoutException:
            await original_message.reply_text("❌ Muda umekwisha. Tovuti haikujibu kwa wakati.")

        except httpx.RequestError as e:
            await original_message.reply_text(f"❌ Hitilafu ya mtandao:\n{e}")

        except Exception as e:
            await original_message.reply_text(f"❌ Hitilafu kwenye send_command.py:\n{e}")
