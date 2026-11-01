"""Rss/rss_updt.py - Hukagua RSS feeds kila baada ya muda na kutuma updates mpya."""
import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urlparse

import feedparser
import httpx
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import ContextTypes

from . import rss_db as db

log = logging.getLogger(__name__)

INTERVAL = 300          # sekunde (dakika 5)
MAX_PER_CYCLE = 10      # entries za juu kwa kila feed kwa mzunguko mmoja
MAX_SEEN = 1000
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RSSBot/1.0)"}


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


async def _process(bot, chat_id: int, url: str) -> None:
    feed = await fetch_feed(url)
    if not feed or not feed.entries:
        return

    current = [entry_id(e) for e in feed.entries if entry_id(e)]

    exists, old = await db.get_ids(chat_id, url)
    if not exists:  # imefutwa wakati job inaendesha
        return
    if old is None:  # hakuna rekodi: hifadhi kimya, usitume za zamani
        await db.set_ids(chat_id, url, current[:MAX_SEEN])
        log.info("Baseline imehifadhiwa: %s|%s", chat_id, url)
        return
    old_set = set(old)

    new = [e for e in feed.entries if entry_id(e) and entry_id(e) not in old_set]
    new = list(reversed(new))[-MAX_PER_CYCLE:]  # ya zamani kwanza, mpya 10 tu

    title = feed.feed.get("title", "RSS")
    unsent = set()
    for i, e in enumerate(new):
        text = f"📰 {title}\n{e.get('title', '')}\n{e.get('link', '')}"
        if await _send(bot, chat_id, text) == "retry":
            unsent = {entry_id(x) for x in new[i:]}  # zitajaribiwa tena
            break
        await asyncio.sleep(1)  # epuka flood limit

    kept = [i for i in current if i not in unsent]
    kept_set = set(kept)
    merged = kept + [i for i in old if i not in kept_set]
    await db.set_ids(chat_id, url, merged[:MAX_SEEN])


async def rss_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        feeds = await db.all_feeds()
    except Exception:
        log.exception("MongoDB: kusoma feeds kumeshindwa")
        return
    for d in feeds:
        try:
            await _process(context.bot, d["chat_id"], d["url"])
        except Exception:
            log.exception("rss_job kosa: %s", d.get("url"))


def start_rss_job(app) -> None:
    """Iite mara moja kwenye main baada ya kutengeneza app."""
    app.job_queue.run_repeating(rss_job, interval=INTERVAL, first=10)
