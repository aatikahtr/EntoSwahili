import asyncio
import httpx
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ContextTypes

from modules.Instant_view.IslamSite.constants import telegraph, HEADERS
from modules.Instant_view.IslamSite.html_cleaner import clean_html
from .platform_handler import (
    detect_platform,
    get_selectors,
    find_content,
    cleanup_platform,
)

# ============================================
# SEMAPHORE - Zuia requests nyingi sana
# ============================================

SEMAPHORE = asyncio.Semaphore(5)

# httpx client moja inayoendelea (connection pooling)
_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            headers=HEADERS,
            follow_redirects=True,
            timeout=httpx.Timeout(
                connect=10.0,   # Muda wa kuunganika
                read=20.0,      # Muda wa kusoma response
                write=10.0,
                pool=5.0,
            ),
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
            ),
        )
    return _client


# ============================================
# HELPERS
# ============================================

def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


# ============================================
# MAIN COMMAND
# ============================================

async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with SEMAPHORE:
        original_message = update.message

        # ====================================
        # CHECK URL
        # ====================================

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
            # FETCH PAGE
            # ====================================

            client = await get_client()
            response = await client.get(url)
            response.raise_for_status()

            # Chunguza encoding ili maandishi yasichafuke
            encoding = response.encoding or "utf-8"
            soup = BeautifulSoup(
                response.content,   # bytes (bora kuliko .text)
                "lxml",
                from_encoding=encoding,
            )

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
                await original_message.reply_text(
                    "⚠️ Imeshindwa kupata content."
                )
                return

            cleanup_platform(platform, content_el)

            body_html = content_el.decode_contents()
            html_content = clean_html(body_html, base_url=url)

            if not html_content.strip():
                await original_message.reply_text(
                    "⚠️ Imeshindwa kupata content."
                )
                return

            # ====================================
            # TELEGRAPH LIMIT
            # ====================================

            if len(html_content.encode("utf-8")) > 64000:
                html_content = html_content[:60000] + "<p>... (imekatwa)</p>"

            # ====================================
            # CREATE TELEGRAPH PAGE
            # ====================================

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

        # ====================================
        # ERROR HANDLING
        # ====================================

        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            msgs = {
                403: "❌ Tovuti imekataa ufikiaji (403 Forbidden).",
                404: "❌ Ukurasa haupatikani (404 Not Found).",
                429: "❌ Maombi mengi sana. Jaribu tena baadaye (429).",
                500: "❌ Hitilafu ya server ya tovuti (500).",
            }
            await original_message.reply_text(
                msgs.get(code, f"❌ Server ilikataa ombi: {code}")
            )

        except httpx.TimeoutException:
            await original_message.reply_text(
                "❌ Muda umekwisha. Tovuti haikujibu kwa wakati."
            )

        except httpx.RequestError as e:
            await original_message.reply_text(
                f"❌ Hitilafu ya mtandao:\n{e}"
            )

        except Exception as e:
            await original_message.reply_text(
                f"❌ Hitilafu kwenye send_command.py:\n{e}"
            )
