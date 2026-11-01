"""Rss/rss_cmd.py - Commands zote za RSS: /rs list | add url | stop url"""
import asyncio

import feedparser
from telegram import Update
from telegram.ext import ContextTypes

from .rss_updt import FEEDS_FILE, SEEN_FILE, entry_id, load_json, save_json

USAGE = "Tumia:\n/rs list\n/rs add url\n/rs stop url"


async def rs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.channel_post or update.message
    if not msg:
        return

    chat_id = str(msg.chat.id)
    args = context.args or []
    feeds = load_json(FEEDS_FILE)
    urls = feeds.get(chat_id, [])

    async def reply(text: str):
        await msg.reply_text(
            text,
            message_thread_id=msg.message_thread_id,
            disable_web_page_preview=True,
        )

    # /rs au /rs list
    if not args or args[0].lower() == "list":
        if not urls:
            return await reply("Hakuna RSS iliyoongezwa.\n/rs add url")
        lines = "\n".join(f"{i}. {u}" for i, u in enumerate(urls, 1))
        return await reply(f"📡 RSS zako:\n{lines}")

    if len(args) < 2:
        return await reply(USAGE)

    action, url = args[0].lower(), args[1]

    # /rs add url
    if action == "add":
        if url in urls:
            return await reply("⚠️ Tayari ipo.")
        feed = await asyncio.to_thread(feedparser.parse, url)
        if not feed.entries:
            return await reply("❌ Link hii si RSS sahihi au haina entries.")

        urls.append(url)
        feeds[chat_id] = urls
        save_json(FEEDS_FILE, feeds)

        # hifadhi zilizopo ili zisitumwe upya
        seen = load_json(SEEN_FILE)
        seen[f"{chat_id}|{url}"] = [entry_id(e) for e in feed.entries if entry_id(e)]
        save_json(SEEN_FILE, seen)
        return await reply(f"✅ Imeongezwa: {feed.feed.get('title', url)}")

    # /rs stop url
    if action == "stop":
        if url not in urls:
            return await reply("❌ Haipo kwenye orodha.")
        urls.remove(url)
        feeds[chat_id] = urls
        save_json(FEEDS_FILE, feeds)

        seen = load_json(SEEN_FILE)
        seen.pop(f"{chat_id}|{url}", None)
        save_json(SEEN_FILE, seen)
        return await reply("🛑 Imesimamishwa.")

    await reply(USAGE)
