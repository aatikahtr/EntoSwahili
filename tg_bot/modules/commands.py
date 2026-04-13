from telegram import Update
from telegram.ext import ContextTypes


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    text = (
        "👋 *Maasha Allah Karibu kwenye Mtranslator Bot!*\n\n"
        "📌 Tuma maandishi au Picha, Video zenye caption — nitaifasiri kwenda *Kiswahili*.\n\n"
        "💬 Usitumie `/` kama si command.\n\n"
        "🚀 Jaribu sasa!"
    )
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        message_thread_id=update.message.message_thread_id
    )
