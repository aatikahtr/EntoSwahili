import asyncio
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

# ============================================
# GLOBALS
# ============================================

_browser = None
_playwright = None

# Zuia overload ya requests nyingi
SEMAPHORE = asyncio.Semaphore(3)


# ============================================
# BROWSER MANAGER
# ============================================

async def get_browser():
    global _browser, _playwright

    try:
        # Browser ipo tayari?
        if _browser:
            await _browser.version()
            return _browser

    except Exception:
        _browser = None

    _playwright = await async_playwright().start()

    _browser = await _playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-sync",
            "--no-first-run",
            "--disable-popup-blocking",
        ],
    )

    return _browser


# ============================================
# HELPERS
# ============================================

def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


async def block_resources(route):
    """
    Zuia resources zisizo muhimu
    ili kuongeza speed.
    """

    blocked = {
        "image",
        "media",
        "font",
        "stylesheet",
    }

    if route.request.resource_type in blocked:
        await route.abort()
    else:
        await route.continue_()


# ============================================
# MAIN COMMAND
# ============================================

async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

        ctx = None

        try:
            # ====================================
            # BROWSER
            # ====================================

            browser = await get_browser()

            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                java_script_enabled=True,
                bypass_csp=True,
                viewport={
                    "width": 1280,
                    "height": 720,
                },
            )

            await ctx.route("**/*", block_resources)

            page = await ctx.new_page()

            page.set_default_timeout(20000)

            # ====================================
            # OPEN URL
            # ====================================

            try:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=20000,
                )

                await page.wait_for_selector("body")

            except Exception:
                # fallback
                await page.goto(
                    url,
                    wait_until="load",
                    timeout=30000,
                )

            # ====================================
            # TITLE
            # ====================================

            title = "Habari"

            try:
                h1 = page.locator("h1").first
                text = await h1.text_content()

                if text and text.strip():
                    title = text.strip()

            except Exception:
                try:
                    page_title = await page.title()

                    if page_title.strip():
                        title = page_title.strip()

                except Exception:
                    pass

            # ====================================
            # PLATFORM DETECTION
            # ====================================

            full_html = await page.content()

            soup_detect = BeautifulSoup(
                full_html,
                "lxml",
            )

            platform = detect_platform(
                url,
                soup_detect,
            )

            selectors = get_selectors(platform)

            # ====================================
            # FIND CONTENT
            # ====================================

            content_el = None

            for selector in selectors:
                try:
                    el = await page.query_selector(selector)

                    if el:
                        content_el = el
                        break

                except Exception:
                    continue

            # fallback
            if not content_el:
                content_el = await page.query_selector("body")

            if not content_el:
                await original_message.reply_text(
                    "⚠️ Imeshindwa kupata content."
                )
                return

            # ====================================
            # GET HTML
            # ====================================

            body_html = await content_el.inner_html()

            # ====================================
            # CLEANUP
            # ====================================

            content_soup = BeautifulSoup(
                body_html,
                "lxml",
            )

            cleanup_platform(
                platform,
                content_soup,
            )

            body_html = content_soup.decode_contents()

            html_content = clean_html(
                body_html,
                base_url=url,
            )

            # ====================================
            # VALIDATE
            # ====================================

            if not html_content.strip():
                await original_message.reply_text(
                    "⚠️ Imeshindwa kupata content."
                )
                return

            # Telegraph limit
            if len(html_content.encode("utf-8")) > 64000:
                html_content = (
                    html_content[:60000]
                    + "<p>... (imekatwa)</p>"
                )

            # ====================================
            # CREATE TELEGRAPH PAGE
            # ====================================

            page_data = await telegraph.create_page(
                title=title,
                html_content=html_content,
            )

            telegraph_url = (
                f"https://telegra.ph/{page_data['path']}"
            )

            # ====================================
            # SEND MESSAGE
            # ====================================

            await original_message.reply_text(
                f"📄 <b>{title}</b>\n\n"
                f"🔗 <a href='{telegraph_url}'>"
                f"Soma hapa (Instant View)"
                f"</a>",
                parse_mode="HTML",
                disable_web_page_preview=False,
            )

        except Exception as e:

            await original_message.reply_text(
                f"❌ Hitilafu kwenye get_command.py:\n{e}"
            )

        finally:
            # Muhimu sana kuzuia memory leak
            if ctx:
                try:
                    await ctx.close()
                except Exception:
                    pass
