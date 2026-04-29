from telegram import Update
from telegram.ext import ContextTypes
from .media import (
    handle_media_group,
    translate_single_media
)

LOG_CHAT_ID = -1002158955567


async def trslate_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main message router (hupokea updates zote)"""
    try:
        message = update.effective_message
        if not message:
            return

        # Kama ni reply, tumia ule ujumbe ulioreply badala ya wa sasa
        target_message = message.reply_to_message if message.reply_to_message else message

        # Kama ni media group (album)
        if target_message.media_group_id:
            await handle_media_group(update, context, target_message)
            return

        # Kama ni maandishi
        if target_message.text:
            from .text import translate_text
            await translate_text(update, context, target_message)
            return

        # Media ya single (picha/video yenye caption)
        await translate_single_media(update, context, target_message)

    except Exception as e:
        await context.bot.send_message(
            LOG_CHAT_ID,
            f"❌ handle_message error:\n{e}"
        )
