from telegram import Update, Message
from telegram.ext import ContextTypes
from .translator import translator_service


async def translate_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target: Message = None
):
    """Translate text messages"""
    # target = reply_to_message au message ya kawaida
    msg = target or update.message
    text = msg.text

    # Skip commands
    if text.startswith("/"):
        return

    # Translate
    translated = translator_service.translate(text)

    # Only reply if translation is different
    if not translator_service.should_translate(text, translated):
        return

    # Jibu kwenye ujumbe wa mtumiaji (si target)
    reply_to = update.effective_message

    await reply_to.reply_text(
        translated,
        message_thread_id=msg.message_thread_id
    )
