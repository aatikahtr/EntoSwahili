from telegram import Update
from telegram.ext import ContextTypes
from services.translator import translator_service


async def translate_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Translate text messages"""
    msg = update.message
    text = msg.text

    # Skip commands
    if text.startswith("/"):
        return

    # Translate
    translated = translator_service.translate(text)

    # Only reply if translation is different
    if not translator_service.should_translate(text, translated):
        return

    await msg.reply_text(
        translated,
        message_thread_id=msg.message_thread_id
    )
