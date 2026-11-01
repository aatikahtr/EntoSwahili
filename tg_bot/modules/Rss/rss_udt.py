import asyncio
import json
import os

import feedparser
from telegram import Update
from telegram.ext import ContextTypes

FEEDS_FILE = "rss_feeds.json"  # {chat_id: [urls]}
SEEN_FILE = "rss_seen.json"    # {chat_id|url: [ids]}


def _load(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


async def rs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/rs list | /rs add url | /rs stop url"""
    msg = update.channel_post or update.message
    if not msg:
        return

    chat_id = str(msg.chat.id)
    args = context.args
    feeds = _load(FEEDS_FILE)
    urls = feeds.get(chat_id, [])

    async def reply(text):
        await msg.reply_text(
            text,
            message_thread_id=msg.message_thread_id,
            disable_web_page_preview=True,
        )

    if not args or args[0] == "list":
        if not urls:
            return await reply("Hakuna RSS iliyoongezwa.\nTumia: /rs add url")
        return await reply("📡 RSS zako:\n" + "\n".join(f"{i}. {u}" for i, u in enumerate(urls, 1)))

    if len(args) < 2:
        return await reply("Tumia:\n/rs list\n/rs add url\n/rs stop url")

    action, url = args[0].lower(), args[1]

    if action == "add":
        if url in urls:
            return await reply("⚠️ Tayari ipo.")
        feed = await asyncio.to_thread(feedparser.parse, url)
        if not feed.entries:
            return await reply("❌ Link hii si RSS sahihi au haina entries.")

        urls.append(url)
        feeds[chat_id] = urls
        _save(FEEDS_FILE, feeds)

        # hifadhi zilizopo ili zisitumwe upya
        seen = _load(SEEN_FILE)
        seen[f"{chat_id}|{url}"] = [e.get("id") or e.get("link") for e in feed.entries]
        _save(SEEN_FILE, seen)
        return await reply(f"✅ Imeongezwa: {feed.feed.get('title', url)}")

    if action == "stop":
        if url not in urls:
            return await reply("❌ Haipo kwenye orodha.")
        urls.remove(url)
        feeds[chat_id] = urls
        _save(FEEDS_FILE, feeds)

        seen = _load(SEEN_FILE)
        seen.pop(f"{chat_id}|{url}", None)
        _save(SEEN_FILE, seen)
        return await reply("🛑 Imesimamishwa.")

    await reply("Tumia:\n/rs list\n/rs add url\n/rs stop url")


async def rss_job(context: ContextTypes.DEFAULT_TYPE):
    """Hukagua feeds zote za kila chat na kutuma mpya."""
    feeds = _load(FEEDS_FILE)
    seen = _load(SEEN_FILE)

    for chat_id, urls in feeds.items():
        for url in urls:
            key = f"{chat_id}|{url}"
            feed = await asyncio.to_thread(feedparser.parse, url)
            if not feed.entries:
                continue

            old = set(seen.get(key, []))
            new = [e for e in feed.entries if (e.get("id") or e.get("link")) not in old]

            for e in reversed(new):
                text = f"📰 {feed.feed.get('title', 'RSS')}\n{e.get('title', '')}\n{e.get('link', '')}"
                try:
                    await context.bot.send_message(chat_id=int(chat_id), text=text)
                    await asyncio.sleep(1)
                except Exception:
                    pass

            ids = {e.get("id") or e.get("link") for e in feed.entries}
            seen[key] = list(old | ids)[-500:]

    _save(SEEN_FILE, seen)
