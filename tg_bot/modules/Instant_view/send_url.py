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


def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


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

        # Cleanup maalum ya platform
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
        await original_message.reply_text(
            f"❌ Server ilikataa ombi: {e.response.status_code}"
        )
    except httpx.RequestError as e:
        await original_message.reply_text(
            f"❌ Hitilafu ya mtandao:\n{e}"
        )
    except Exception as e:
        await original_message.reply_text(
            f"❌ Hitilafu kwenye send_command.py:\n{e}"
        )
