import asyncio
from telegram import Update
from telegram.ext import ContextTypes

from ID import error_chat_id
from utils import BLOCK_WORDS, BLOCK_PREFIXES
from modules.Twitte.Xupdate import x_update


async def textzotu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        msg = update.channel_post or update.edited_channel_post
        if not msg:
            return

        chat_id = msg.chat.id
        text = msg.text or ""

        if text.startswith(BLOCK_PREFIXES) or any(word in text for word in BLOCK_WORDS):
            return

        if any(word in text for word in ["R to @", "RT by @", "RT @"]):
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=msg.message_id
            )
            return

        asyncio.create_task(x_update(update, context))

    except Exception as e:
        error_msg = f"Kosa limetokea kwenye function ya TEXT: {e}"
        asyncio.create_task(
            context.bot.send_message(
                chat_id=error_chat_id,
                text=error_msg
            )
        )
