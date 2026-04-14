import re
from urllib.parse import urlparse
from telegram import Update
from telegram.ext import ContextTypes

from .url_processor import extract_content
from .Islamic_url import islam_content
from .instant_view import create_instant_view


# Domains ambazo HAZIRUHUSIWI picha
NO_MEDIA_DOMAINS = {
    "alhidaaya.com",
    "firqatunnajia.com",
}


def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


def normalize_domain(url: str) -> str:
    domain = urlparse(url).netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain



async def instant_view_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    original_message = update.message
    replied = update.message.reply_to_message

    if not replied or not replied.text:
        await original_message.reply_text("⚠️ Tumia command hii kwa ku-reply message yenye URL.")
        return

    text = replied.text.strip()

    # Kagua kama ni URL moja kwa moja, au tafuta ndani ya text
    if is_url(text):
        url = text
    else:
        match = re.search(r'https?://\S+', text)
        if not match:
            await original_message.reply_text(
                f"⚠️ Sijapata URL kwenye message uliyoreply:\n\n{text[:200]}"
            )
            return
        url = match.group(0)

    try:
        domain = normalize_domain(url)

        if domain in NO_MEDIA_DOMAINS:
            title, html = await islam_content(url)
        else:
            title, html = await extract_content(url)

        link = await create_instant_view(
            title=title,
            html=html,
            tg_user=update.effective_user,
        )

        await original_message.reply_text(f"{title}\n{link}")

    except Exception as e:
        await original_message.reply_text(f"❌ Hitilafu: {e}")


