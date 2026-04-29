from telegram import Update
from telegram.ext import ContextTypes
from .media import (
    handle_media_group,
    translate_single_media
)

LOG_CHAT_ID = -1002158955567


async def trslate_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main message router - inashughulikia MessageHandler NA reply_to"""
    try:
        message = update.effective_message
        if not message:
            return

        # Chagua ujumbe wa kutafsiri:
        # - Kama mtumiaji alireply ujumbe → tafsiri ule ujumbe wa asili
        # - Kama ni ujumbe wa kawaida → tafsiri ujumbe huu huu
        target = message.reply_to_message or message

        # Zuia kujitafsiri (bot haireplyi yenyewe)
        if target.from_user and target.from_user.is_bot:
            return

        # Kama ni media group (album)
        if target.media_group_id:
            await handle_media_group(update, context, target)
            return

        # Kama ni maandishi
        if target.text:
            from .text import translate_text
            await translate_text(update, context, target)
            return

        # Media ya single (picha/video yenye caption)
        await translate_single_media(update, context, target)

    except Exception as e:
        await context.bot.send_message(
            LOG_CHAT_ID,
            f"❌ handle_message error:\n{e}"
        )
