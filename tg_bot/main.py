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

from config import BOT_TOKEN, URL, PORT
from handlers.commands import start
from handlers.update import handle_message


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
    app.add_handler(
        MessageHandler(
            filters.ALL & (
                filters.ChatType.PRIVATE |
                filters.ChatType.GROUP |
                filters.ChatType.SUPERGROUP
            ),
            handle_message
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
