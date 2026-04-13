import re
import logging
from telegram import Update
from telegram.ext import ContextTypes

from app.bot.services.url_processor import extract_content, publish_telegraph

logger = logging.getLogger(__name__)

TARGET_CHANNEL = -1001297333544
AUTHOR_NAME = "Teknolojia"
AUTHOR_URL = "https://t.me/Huduma"


async def Tech_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post
    if not message or not message.text:
        return

    match = re.search(r"(https?://\S+)", message.text)
    if not match:
        return

    url = match.group(1)

    try:
        title, html = await extract_content(
            url=url,
            allow_media=True,
            cut_content=False,
        )

        link = await publish_telegraph(
            title=title,
            html=html,
            author_name=AUTHOR_NAME,
            author_url=AUTHOR_URL,
        )

        await context.bot.send_message(
            chat_id=TARGET_CHANNEL,
            text=f"<a href='{link}'>{title}</a>",
            parse_mode="HTML",
        )

    except Exception:
        logger.exception("Tech_link error")
