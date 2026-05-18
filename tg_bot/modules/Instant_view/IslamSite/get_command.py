
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import ContextTypes
from telegraph.aio import Telegraph

# Local module
from .html_cleaner import clean_html



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

            # Tumia "domcontentloaded" — haraka zaidi, haingoji ads/trackers
            # Kama ikishindwa, jaribu tena bila kusubiri sana
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # Subiri kidogo content ipakiwe (JS rendering)
                await page.wait_for_timeout(2000)
            except Exception:
                # Fallback: "load" event tu
                await page.goto(url, wait_until="load", timeout=45000)

            # Title
            h1 = await page.query_selector("h1")
            title = (await h1.inner_text()).strip() if h1 else "Habari"

            # Gundua platform
            is_firqatunnajia = "firqatunnajia.com" in url
            is_gsmarena = "gsmarena.com" in url
            is_wordpress = await page.query_selector(
                "meta[name='generator'][content*='WordPress'], "
                "meta[name='generator'][content*='Elementor'], "
                "link[rel='https://api.w.org/']"
            )
            is_blogger = await page.query_selector(
                "meta[name='generator'][content*='Blogger']"
            )
            is_drupal = await page.query_selector(
                "meta[name='generator'][content*='Drupal'], "
                "meta[name='Generator'][content*='Drupal']"
            )
            is_medium = "medium.com" in url
            is_substack = "substack.com" in url

            # Selectors kulingana na platform
            if is_firqatunnajia:
                content_selectors = [
                    ".elementor-widget-theme-post-content .elementor-widget-container",
                ]
            elif is_gsmarena:
                content_selectors = [
                    "#specs-list",          # Specs table yenyewe
                    ".specs-cp-wrapper",
                    ".review-body",         # Kwa review pages
                    "article",
                ]
            elif is_wordpress:
                content_selectors = [
                    ".entry-content",
                    ".post-content",
                    "article .content",
                    "article",
                ]
            elif is_blogger:
                content_selectors = [
                    ".post-body",
                    ".entry-content",
                    "#post-body",
                    "article",
                ]
            elif is_drupal:
                content_selectors = [
                    ".field-name-body .field-item",
                    ".field-items",
                    ".field-item",
                    ".node__content",
                    "#main-content",
                    ".region-content",
                ]
            elif is_medium:
                content_selectors = [
                    "article",
                    ".meteredContent",
                    "section",
                ]
            elif is_substack:
                content_selectors = [
                    ".body.markup",
                    ".available-content",
                    "article",
                ]
            else:
                content_selectors = [
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
                ]

            # Pata content element
            content_el = None
            for selector in content_selectors:
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
        await original_message.reply_text(f"❌ Hitilafu: {e}")
