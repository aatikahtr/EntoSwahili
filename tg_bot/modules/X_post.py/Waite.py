import re
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from.New_update import x_update

# -----------------------------------
# REGEX PATTERNS
# -----------------------------------
URL_REGEX = re.compile(r'(https?://[^\s]+)')
Knowledge_translate = -1004358606228

# -----------------------------------
# TEXT HANDLER
# -----------------------------------
async def textzote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        msg = update.channel_post or update.edited_channel_post
        if not msg:
            return
        
        chat_id = message.chat.id
        text = msg.text or ""
        
        if any(word in text for word in ["R to @", "RT by @",  "RT @"]):
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=message.message_id
            )
            return
        
        urls = URL_REGEX.findall(text)
        if not urls:
            return
        
        new_url = urls[-1]
        
        if chat_id == Knowledge_translate:
            asyncio.create_task(x_update(update, context, new_url, chat_id))
            return
        
        
        
    except Exception as e:
        error_msg = f"Kosa limetokea kwenye function ya TEXT: {e}"
        asyncio.create_task(
            context.bot.send_message(
                chat_id=error_id,
                text=error_msg
            )
        )
