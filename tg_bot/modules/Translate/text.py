import asyncio
from telegram import Update, Message
from telegram.ext import ContextTypes
from .translator import translator_service


async def translate_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target: Message = None,
    force: bool = False,
):
    """Translate text messages. force=True -> /tr ilipotumika (jibu hata kama hakuna tofauti)"""
    msg = target or update.message
    text = msg.text or ""

    # Skip commands (isipokuwa /tr imetumika kwa makusudi)
    if text.startswith("/") and not force:
        return

    # Translate (kwenye thread ili bot isizuiwe)
    translated = await asyncio.to_thread(translator_service.translate_long, text)

    # Only reply if translation is different
    if not translator_service.should_translate(text, translated):
        if force:
            await update.effective_message.reply_text(
                "ℹ️ Maandishi haya tayari ni Kiswahili (au hayana tofauti baada ya tafsiri)."
            )
        return

    reply_to = update.effective_message

    # Telegram inaruhusu herufi 4096 kwa ujumbe
    for i in range(0, len(translated), 4096):
        await reply_to.reply_text(
            translated[i:i + 4096],
            message_thread_id=msg.message_thread_id
        )
