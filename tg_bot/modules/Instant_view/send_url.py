import httpx
from telegram import Update
from telegram.ext import ContextTypes

from IslamSite.constants import telegraph

# Local module
#tg_bot/modules/Instant_view/send_url.py
from tg_bot.modules.Instant_view.IslamSite.html_cleaner import clean_html
from tg_bot.modules.Instant_view.IslamSite.constants import HEADERS



#=======
# Command
#=======

async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

        # ✅ TRT Afrika: kata sehemu za related posts na vitu vya ziada
        if platform == "trtafrika":
            html_content = cut_trtafrika_noise(html_content)

        if not html_content.strip():
            await original_message.reply_text("⚠️ Imeshindwa kupata content.")
            return

        # Funga tags zilizo wazi
        soup_fix = BS(html_content, "html.parser")
        html_content = soup_fix.decode_contents()

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
