from urllib.parse import urlparse
from telegram import Update
from telegram.ext import ContextTypes

from app.bot.services.url_processor import extract_content
from app.bot.services.Islamic_url import islam_content
from app.bot.services.instant_view import create_instant_view


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


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    text = message.text.strip()

    if not is_url(text):
        await message.reply_text("⚠️ Tafadhali tuma URL sahihi.")
        return

    try:
        domain = normalize_domain(text)

        # Chagua extractor kulingana na domain
        if domain in NO_MEDIA_DOMAINS:
            title, html = await islam_content(text)
        else:
            title, html = await extract_content(text)

        link = await create_instant_view(
            title=title,
            html=html,
            tg_user=update.effective_user,
        )

        await message.reply_text(f"{title}\n{link}")

    except Exception as e:
        await message.reply_text(f"❌ Hitilafu: {e}")
