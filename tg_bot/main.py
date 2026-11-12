import os
import asyncio
import logging
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

from modules.msghandler import texttu
from modules.Rss.rss_cmd import rs, rmv, vw
from modules.Rss.rss_updt import start_rss_job




# ===========
# Translate
# ===========
from modules.Translate.trslate_update import trslate_message
from modules.commands import start

# ==========
# Instant View
# ==========
from modules.Instant_view.instant_command import instant_view_command

# ==========
# Handle (updates za channel → Instant View)
# ==========
from handle.msghandle import msg_handle, ROUTES

# =========
# Moja moja
# =========
from modules.Mojamoja.moja1 import mojaone



logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# Bot Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
URL = os.getenv("URL")
PORT = int(os.getenv("PORT", 10000))

# Groups zinazoruhusiwa
ALLOWED_GROUPS = [-1001668363178, -1001669440207]

# Channel maalum kwa textzote (X/Twitter URLs) - SASA NI LIST
X_TRANSLATE_CHANNELS = [-1004358606228, -1002029795026, -1003754038608]

# Global application instance
app: Application | None = None


async def telegram_webhook(request: Request) -> Response:
    """Handle incoming webhook requests"""
    try:
        data = await request.json()
        await app.update_queue.put(Update.de_json(data, app.bot))
    except Exception as e:
        logger.exception(f"Webhook error: {e}")
    return Response()


def register_handlers(application: Application) -> None:
    """Register all bot handlers"""

    # ── Commands ──────────────────────────
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("iv", instant_view_command))

    # /rs — RSS (private, groups, na channels)
    application.add_handler(
        CommandHandler(
            "rs",
            rs,
            filters=filters.UpdateType.MESSAGE | filters.UpdateType.CHANNEL_POST,
        )
    )

    # /rmv — futa RSS kutoka MongoDB (chat hii tu)
    application.add_handler(
        CommandHandler(
            "rmv",
            rmv,
            filters=filters.UpdateType.MESSAGE | filters.UpdateType.CHANNEL_POST,
        )
    )

    # /vw — muundo wa post za RSS (hidden | show)
    application.add_handler(
        CommandHandler(
            "vw",
            vw,
            filters=filters.UpdateType.MESSAGE | filters.UpdateType.CHANNEL_POST,
        )
    )

    # TEXT tu kwa X channels
    application.add_handler(
        MessageHandler(filters.TEXT & filters.Chat(chat_id=X_TRANSLATE_CHANNELS), texttu)
    )

    # /tr — private na kwenye groups zilizoruhusiwa (reply, maandishi, au PDF)
    application.add_handler(
        CommandHandler(
            "tr",
            trslate_message,
            filters=filters.ChatType.PRIVATE | filters.Chat(chat_id=ALLOWED_GROUPS),
        )
    )



    # ── GROUP/SUPERGROUP: allowed groups pekee ──────────────
    allowed_chats = filters.Chat(chat_id=ALLOWED_GROUPS)
    application.add_handler(
        MessageHandler(
            (filters.ChatType.GROUP | filters.ChatType.SUPERGROUP)
            & allowed_chats
            & (
                filters.TEXT
                | filters.PHOTO
                | filters.VIDEO
                | filters.Document.ALL
                | filters.AUDIO
                | filters.ANIMATION
            ),
            trslate_message,
        )
    )
    

    # ── CHANNEL ya jumla (zote isipokuwa X_TRANSLATE_CHANNELS) — group=1
    application.add_handler(
        MessageHandler(
            filters.ChatType.CHANNEL
            & ~filters.Chat(chat_id=X_TRANSLATE_CHANNELS)
            & (filters.TEXT | filters.PHOTO | filters.VIDEO),
            mojaone,
        ),
        group=1,
    )

    # ── HANDLE: channel posts zenye URL → Instant View (group=2, haiingiliani na zingine)
    application.add_handler(
        MessageHandler(
            filters.UpdateType.CHANNEL_POST
            & filters.Chat(chat_id=list(ROUTES))
            & (filters.TEXT | filters.CAPTION),
            msg_handle,
        ),
        group=2,
    )


async def main():
    """Initialize and run the bot"""
    global app

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN haijawekwa kwenye environment variables")
    if not URL:
        raise RuntimeError("URL haijawekwa kwenye environment variables")

    # Build application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Register handlers
    register_handlers(app)

    # Washa RSS job (inakagua kila INTERVAL)
    start_rss_job(app)

    # Setup webhook server
    starlette_app = Starlette(
        routes=[Route("/telegram", telegram_webhook, methods=["POST"])]
    )

    server = uvicorn.Server(
        uvicorn.Config(
            app=starlette_app,
            host="0.0.0.0",
            port=PORT,
            log_level="info",
        )
    )

    # Set webhook
    await app.bot.set_webhook(f"{URL}/telegram")

    # Run application
    async with app:
        await app.start()
        try:
            await server.serve()
        finally:
            await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
