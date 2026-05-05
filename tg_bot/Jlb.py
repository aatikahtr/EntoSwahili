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


def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


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
        title = h1.text.strip() if h1 else "Habari"

        # Paragraphs — plain text tu ndani ya <p> tags
        paragraphs = soup.find_all("p")
        lines = []
        for p in paragraphs:
            text = p.get_text(separator=" ", strip=True)  # text tu, bila tags ndani
            if text and text.lower() not in NOISE_TEXTS and len(text) > 30:
                lines.append(f"<p>{text}</p>")

        if not lines:
            await original_message.reply_text("⚠️ Imeshindwa kupata content.")
            return

        html_content = "".join(lines)

        # Telegraph ina limit ya 64KB
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
