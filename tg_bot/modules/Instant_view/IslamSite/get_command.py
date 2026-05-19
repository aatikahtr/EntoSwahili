from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ContextTypes

from .constants import telegraph
from .html_cleaner import clean_html
from modules.Instant_view.platform_handler import (
    detect_platform,
    get_selectors,
    cleanup_platform,
)


def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)
            except Exception:
                await page.goto(url, wait_until="load", timeout=45000)

            # Title
            h1 = await page.query_selector("h1")
            title = (await h1.inner_text()).strip() if h1 else "Habari"

            # Gundua platform kupitia platform_handler
            full_html = await page.content()
            soup_detect = BeautifulSoup(full_html, "html.parser")
            platform = detect_platform(url, soup_detect)
            selectors = get_selectors(platform)

            # Pata content element
            content_el = None
            for selector in selectors:
                el = await page.query_selector(selector)
                if el:
                    content_el = el
                    break

            if not content_el:
                content_el = await page.query_selector("body")

            if not content_el:
                await browser.close()
                await original_message.reply_text("⚠️ Imeshindwa kupata content.")
                return

            body_html = await content_el.inner_html()
            await browser.close()

        # Cleanup maalum ya platform
        content_soup = BeautifulSoup(body_html, "html.parser")
        cleanup_platform(platform, content_soup)
        body_html = content_soup.decode_contents()

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

    except Exception as e:
        await original_message.reply_text(
            f"❌ Hitilafu kwenye get_command.py:\n{e}"
        )
