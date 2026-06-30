import os
import asyncio
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    filters,
)

from modules.X_post.Waite import textzote

#=========
#Jalibio
#==========
from modules.Instant_view.send_url import send_command
from modules.Instant_view.IslamSite import get_command

#===========
# Translate
#===========
from modules.Translate.trslate_update import trslate_message
from modules.commands import start

#==========
# Instant View 
#===============
from modules.Instant_view.instant_command import instant_view_command


#=========
# Moja moja
#==========
from modules.Mojamoja.moja1 import mojaone


#=========
#Check  Url
#=========
from modules.selectors import check_selectors


#============
#Website to rss
#=============

from modules.Rss.rss_command import rss_command
from modules.Rss.rss_scheduler import setup_scheduler



# Bot Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
URL = os.getenv("URL")
PORT = int(os.getenv("PORT", 10000))

# Groups zinazoruhusiwa
ALLOWED_GROUPS = [-1001668363178, -1001669440207]

# Global application instance
app = None


async def telegram_webhook(request: Request):
    """Handle incoming webhook requests"""
    data = await request.json()
    await app.update_queue.put(Update.de_json(data, app.bot))
    return Response()


async def main():
    """Initialize and run the bot"""
    global app
    
    # Build application
    app = Application.builder().token(BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("view", instant_view_command))

    # PRIVATE: command /tr + reply pekee
    app.add_handler(
        CommandHandler(
            "tr",
            trslate_message,
            filters=filters.ChatType.PRIVATE
        )
    )

    app.add_handler(
        CommandHandler(
            "get",
            get_command,
            filters=filters.ChatType.PRIVATE
        )
    )


    app.add_handler(
        CommandHandler(
            "link",
            send_command,
            filters=filters.ChatType.PRIVATE
        )
    )
    
    
    app.add_handler(CommandHandler("check", check_selectors))
    
        # ── Handlers ───────
    
    app.add_handler(
    CommandHandler(
        "rss",
        rss_command,
        filters=(
            filters.ChatType.CHANNEL |
            filters.ChatType.GROUPS |
            filters.ChatType.PRIVATE
        )
    )
)

    # ── Washa RSS Scheduler ──
    setup_scheduler(app, interval_minutes=10)
    
    
    # GROUP/SUPERGROUP: MessageHandler + filter ya group IDs zilizoruhusiwa
    allowed_chats = filters.Chat(chat_id=ALLOWED_GROUPS)
    app.add_handler(
        MessageHandler(
            (filters.ChatType.GROUP | filters.ChatType.SUPERGROUP) &
            allowed_chats &
            (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.AUDIO | filters.ANIMATION),
            trslate_message
        )
    )

    # CHANNEL handler
    app.add_handler(
        MessageHandler(
            filters.ChatType.CHANNEL &
            (filters.TEXT | filters.PHOTO | filters.VIDEO),
            mojaone
        )
    )
    
    
    app.add_handler(
        MessageHandler(
            filters.ChatType.CHANNEL,
            textzote
        )
    )
    
    
    
    # Setup webhook server
    starlette_app = Starlette(
        routes=[Route("/telegram", telegram_webhook, methods=["POST"])]
    )

    server = uvicorn.Server(
        uvicorn.Config(
            app=starlette_app,
            host="0.0.0.0",
            port=PORT,
            log_level="info"
        )
    )

    # Set webhook
    await app.bot.set_webhook(f"{URL}/telegram")

    # Run application
    async with app:
        await app.start()
        await server.serve()
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
