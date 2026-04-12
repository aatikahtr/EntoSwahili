from telegram import Update
from telegram.ext import ContextTypes
from config import LOG_CHAT_ID
from handlers.media import (
    handle_media_group,
    translate_single_media
)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main message router (hupokea updates zote)"""
    try:
        message = update.effective_message
        if not message:
            return

        # Kama ni media group (album)
        if message.media_group_id:
            await handle_media_group(update, context)
            return

        # Kama ni maandishi
        if message.text:
            from handlers.text import translate_text
            await translate_text(update, context)
            return

        # Media ya single (picha/video yenye caption)
        await translate_single_media(update, context)

    except Exception as e:
        await context.bot.send_message(
            LOG_CHAT_ID,
            f"❌ handle_message error:\n{e}"
        )
