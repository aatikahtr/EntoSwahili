"""Rss/rss_updt.py - Hukagua RSS feeds kila baada ya muda na kutuma updates mpya."""
import asyncio
import json
import os

import feedparser
from telegram.ext import ContextTypes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FEEDS_FILE = os.path.join(BASE_DIR, "rss_feeds.json")  # {chat_id: [urls]}
SEEN_FILE = os.path.join(BASE_DIR, "rss_seen.json")    # {"chat_id|url": [ids]}
INTERVAL = 300  # sekunde (dakika 5)


def load_json(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def entry_id(entry) -> str:
    return entry.get("id") or entry.get("link") or ""


async def rss_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job inayokagua feeds zote za kila chat na kutuma mpya."""
    feeds = load_json(FEEDS_FILE)
    seen = load_json(SEEN_FILE)

    for chat_id, urls in feeds.items():
        for url in urls:
            key = f"{chat_id}|{url}"
            try:
                feed = await asyncio.to_thread(feedparser.parse, url)
            except Exception:
                continue
            if not feed.entries:
                continue

            old = set(seen.get(key, []))
            new = [e for e in feed.entries if entry_id(e) and entry_id(e) not in old]

            for e in reversed(new):  # ya zamani kwanza
                text = (
                    f"📰 {feed.feed.get('title', 'RSS')}\n"
                    f"{e.get('title', '')}\n{e.get('link', '')}"
                )
                try:
                    await context.bot.send_message(chat_id=int(chat_id), text=text)
                    await asyncio.sleep(1)  # epuka flood limit
                except Exception:
                    pass

            ids = {entry_id(e) for e in feed.entries if entry_id(e)}
            seen[key] = list(old | ids)[-500:]

    save_json(SEEN_FILE, seen)


def start_rss_job(app) -> None:
    """Iite mara moja kwenye main baada ya kutengeneza app."""
    app.job_queue.run_repeating(rss_job, interval=INTERVAL, first=10)
