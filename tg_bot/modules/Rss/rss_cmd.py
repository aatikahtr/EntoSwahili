"""Rss/rss_cmd.py - /rs list | /rs add url | /rs stop url (au namba)"""
from telegram import Update
from telegram.ext import ContextTypes

from .rss_updt import (
    FEEDS_FILE, LOCK, SEEN_FILE, entry_id, fetch_feed,
    is_safe_url, load_json, save_json,
)

USAGE = "Tumia:\n/rs list\n/rs add url\n/rs stop url (au namba)"
MAX_FEEDS = 20  # kwa kila chat


async def _can_manage(msg, context) -> bool:
    """Private/channel: sawa. Group: admins tu."""
    if msg.chat.type in ("private", "channel"):
        return True
    if msg.sender_chat and msg.sender_chat.id == msg.chat.id:  # anonymous admin
        return True
    if not msg.from_user:
        return False
    member = await context.bot.get_chat_member(msg.chat.id, msg.from_user.id)
    return member.status in ("administrator", "creator")


async def rs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.channel_post or update.message
    if not msg:
        return

    async def reply(text: str):
        await msg.reply_text(
            text,
            message_thread_id=msg.message_thread_id,
            disable_web_page_preview=True,
        )

    if not await _can_manage(msg, context):
        return await reply("⛔ Admins tu ndio wanaweza kutumia /rs hapa.")

    chat_id = str(msg.chat.id)
    args = context.args or []

    # /rs au /rs list
    if not args or args[0].lower() == "list":
        async with LOCK:
            urls = load_json(FEEDS_FILE).get(chat_id, [])
        if not urls:
            return await reply("Hakuna RSS iliyoongezwa.\n/rs add url")
        lines = "\n".join(f"{i}. {u}" for i, u in enumerate(urls, 1))
        return await reply(f"📡 RSS zako ({len(urls)}):\n{lines}")

    if len(args) < 2:
        return await reply(USAGE)

    action, target = args[0].lower(), args[1]

    # /rs add url
    if action == "add":
        if not await is_safe_url(target):
            return await reply("❌ Link si sahihi (tumia http/https ya tovuti ya kawaida).")
        feed = await fetch_feed(target)
        if not feed or not feed.entries:
            return await reply("❌ Link hii si RSS sahihi au haina entries.")

        async with LOCK:
            feeds = load_json(FEEDS_FILE)
            urls = feeds.get(chat_id, [])
            if target in urls:
                return await reply("⚠️ Tayari ipo.")
            if len(urls) >= MAX_FEEDS:
                return await reply(f"⚠️ Kikomo ni feeds {MAX_FEEDS}. Ondoa nyingine kwanza.")
            urls.append(target)
            feeds[chat_id] = urls
            save_json(FEEDS_FILE, feeds)

            # hifadhi zilizopo ili zisitumwe upya
            seen = load_json(SEEN_FILE)
            seen[f"{chat_id}|{target}"] = [entry_id(e) for e in feed.entries if entry_id(e)]
            save_json(SEEN_FILE, seen)
        return await reply(f"✅ Imeongezwa: {feed.feed.get('title', target)}")

    # /rs stop url  |  /rs stop 2
    if action == "stop":
        async with LOCK:
            feeds = load_json(FEEDS_FILE)
            urls = feeds.get(chat_id, [])
            if target.isdigit() and 1 <= int(target) <= len(urls):
                target = urls[int(target) - 1]
            if target not in urls:
                return await reply("❌ Haipo kwenye orodha.")
            urls.remove(target)
            feeds[chat_id] = urls
            save_json(FEEDS_FILE, feeds)

            seen = load_json(SEEN_FILE)
            seen.pop(f"{chat_id}|{target}", None)
            save_json(SEEN_FILE, seen)
        return await reply("🛑 Imesimamishwa.")

    await reply(USAGE)
