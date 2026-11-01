"""Rss/rss_updt.py - Hukagua RSS feeds kila baada ya muda na kutuma updates mpya."""
import asyncio
import ipaddress
import json
import logging
import os
import socket
from urllib.parse import urlparse

import feedparser
import httpx
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import ContextTypes

log = logging.getLogger(__name__)

# Weka RSS_DATA_DIR kwenye persistent volume ili data isipotee kwenye redeploy
BASE_DIR = os.getenv("RSS_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
os.makedirs(BASE_DIR, exist_ok=True)
FEEDS_FILE = os.path.join(BASE_DIR, "rss_feeds.json")  # {chat_id: [urls]}
SEEN_FILE = os.path.join(BASE_DIR, "rss_seen.json")    # {"chat_id|url": [ids]}

INTERVAL = 300          # sekunde (dakika 5)
MAX_PER_CYCLE = 10      # entries za juu kwa kila feed kwa mzunguko mmoja
MAX_SEEN = 1000
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RSSBot/1.0)"}

# Lock moja inalinda kusoma/kuandika files (cmd na job hazigongani)
LOCK = asyncio.Lock()


# ---------- Storage ----------
def load_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)  # atomic: file haliharibiki ikizimwa katikati


def entry_id(entry) -> str:
    return entry.get("id") or entry.get("link") or ""


# ---------- Usalama + Fetch ----------
async def is_safe_url(url: str) -> bool:
    """Kubali http/https tu, na zuia localhost/IP za ndani (SSRF)."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, p.hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    return True


async def fetch_feed(url: str):
    """Pakua kwa timeout kisha parse. Inarudisha None ikishindwa."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=HEADERS) as c:
            r = await c.get(url)
            r.raise_for_status()
        return await asyncio.to_thread(feedparser.parse, r.content)
    except Exception as e:
        log.warning("Fetch imeshindwa %s: %s", url, e)
        return None


# ---------- Job ----------
async def _send(bot, chat_id: int, text: str) -> str:
    """Rudisha: 'ok' | 'skip' (hitilafu ya kudumu) | 'retry' (jaribu mzunguko ujao)."""
    for attempt in range(2):
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            return "ok"
        except RetryAfter as e:
            if attempt == 0:
                await asyncio.sleep(e.retry_after + 1)
                continue
            return "retry"
        except (Forbidden, BadRequest) as e:
            log.warning("Chat %s: %s", chat_id, e)
            return "skip"
        except Exception as e:
            log.warning("Kutuma kumeshindwa %s: %s", chat_id, e)
            return "retry"
    return "retry"


async def _process(bot, chat_id: str, url: str) -> None:
    key = f"{chat_id}|{url}"
    feed = await fetch_feed(url)
    if not feed or not feed.entries:
        return

    async with LOCK:
        old = list(load_json(SEEN_FILE).get(key, []))
    old_set = set(old)

    current = [entry_id(e) for e in feed.entries if entry_id(e)]
    new = [e for e in feed.entries if entry_id(e) and entry_id(e) not in old_set]
    new = list(reversed(new))[-MAX_PER_CYCLE:]  # ya zamani kwanza, mpya 10 tu

    title = feed.feed.get("title", "RSS")
    unsent = set()
    for i, e in enumerate(new):
        text = f"📰 {title}\n{e.get('title', '')}\n{e.get('link', '')}"
        if await _send(bot, int(chat_id), text) == "retry":
            unsent = {entry_id(x) for x in new[i:]}  # zitajaribiwa tena
            break
        await asyncio.sleep(1)  # epuka flood limit

    kept = [i for i in current if i not in unsent]
    merged = kept + [i for i in old if i not in set(kept)]

    async with LOCK:
        feeds = load_json(FEEDS_FILE)
        if url not in feeds.get(chat_id, []):  # imefutwa wakati job inaendesha
            return
        seen = load_json(SEEN_FILE)
        seen[key] = merged[:MAX_SEEN]
        save_json(SEEN_FILE, seen)


async def rss_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    async with LOCK:
        feeds = load_json(FEEDS_FILE)
    for chat_id, urls in feeds.items():
        for url in list(urls):
            try:
                await _process(context.bot, chat_id, url)
            except Exception:
                log.exception("rss_job kosa: %s", url)


def start_rss_job(app) -> None:
    """Iite mara moja kwenye main baada ya kutengeneza app."""
    app.job_queue.run_repeating(rss_job, interval=INTERVAL, first=10)
