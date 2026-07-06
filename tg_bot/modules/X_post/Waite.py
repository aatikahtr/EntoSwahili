import re
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from .New_update import x_update

URL_REGEX = re.compile(r'(https?://[^\s]+)')
Knowledge_translate = [-1004358606228, -1002029795026]
ERROR_CHAT_ID = -1003754038608

# -----------------------------------
# BLOCK WORDS
# -----------------------------------
BLOCK_WORDS = {
    "MillardAyoMagazetiTz&Kenya",
    "#Magazetiyaleo",
    "list@rss",
    "Your subscriptions:",
    "@rss2tg_bot",
    "Removed:",
    "⚠️",
    "Added:",
    "latest record:",
}

BLOCK_PREFIXES = (
    "/",
    "/settings@rss",
)



async def textzote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

        urls = URL_REGEX.findall(text)
        if not urls:
            return

        new_url = urls[-1]

        if chat_id in Knowledge_translate:
            asyncio.create_task(x_update(update, context, new_url, chat_id))
            if chat_id == -1002029795026:
                    await context.bot.delete_message(chat_id=chat_id, message_id=msg.message_id
                    )
            return

    except Exception as e:
        error_msg = f"Kosa limetokea kwenye function ya TEXT: {e}"
        asyncio.create_task(
            context.bot.send_message(
                chat_id=ERROR_CHAT_ID,
                text=error_msg
            )
        )
