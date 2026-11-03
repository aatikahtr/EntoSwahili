"""Rss/rss_updt.py - Hukagua RSS feeds kila baada ya muda na kutuma updates mpya."""
import asyncio
import hashlib
import ipaddress
import logging
import socket
from collections import Counter
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import ContextTypes

from . import rss_db as db

log = logging.getLogger(__name__)

INTERVAL = 300          # sekunde (dakika 5)
MAX_PER_CYCLE = 10      # entries za juu kwa kila feed kwa mzunguko mmoja
MAX_SEEN = 2000         # kila entry inaweza kuhifadhi keys 2 (id + link)
MAX_BYTES = 2_000_000   # kikomo cha ukubwa wa feed
MAX_REDIRECTS = 3
CONCURRENCY = 10        # feeds zinazopakuliwa kwa wakati mmoja
MAX_TEXT = 4000         # Telegram: 4096
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RSSBot/1.0)"}


def entry_keys(entry, dup_links: set) -> list:
    """Vitambulisho vyote vya entry: id, link (kama ni ya kipekee kwenye feed),
    au hash ya title+published kama fallback. Rekodi za zamani (id tu) zinaendelea kufanya kazi."""
    keys = []
    eid = entry.get("id")
    link = entry.get("link")
    if eid:
        keys.append(eid)
    if link and link != eid and link not in dup_links:
        keys.append(link)
    if not keys:
        raw = f"{entry.get('title', '')}|{entry.get('published', '')}"
        if raw != "|":
            keys.append("h:" + hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest())
    return keys


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
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            return False
    return True


async def fetch_feed(client: httpx.AsyncClient, url: str):
    """Pakua kwa usalama (redirects zinakaguliwa, ukubwa umewekewa kikomo) kisha parse."""
    try:
        for _ in range(MAX_REDIRECTS + 1):
            if not await is_safe_url(url):
                log.warning("URL si salama: %s", url)
                return None
            async with client.stream("GET", url) as r:
                if r.is_redirect:
                    loc = r.headers.get("location")
                    if not loc:
                        return None
                    url = urljoin(url, loc)
                    continue
                r.raise_for_status()
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    if len(buf) > MAX_BYTES:
                        log.warning("Feed kubwa mno: %s", url)
                        return None
            return await asyncio.to_thread(feedparser.parse, bytes(buf))
        log.warning("Redirects nyingi mno: %s", url)
        return None
    except Exception as e:
        log.warning("Fetch imeshindwa %s: %s", url, e)
        return None


# ---------- Job ----------
async def _send(bot, chat_id: int, text: str) -> str:
    """Rudisha: 'ok' | 'skip' (entry hii tu) | 'stop' (chat haipatikani) | 'retry'."""
    for attempt in range(2):
        try:
            await bot.send_message(chat_id=chat_id, text=text[:MAX_TEXT])
            return "ok"
        except RetryAfter as e:
            if attempt == 0:
                await asyncio.sleep(e.retry_after + 1)
                continue
            return "retry"
        except Forbidden as e:  # bot amezuiwa / ametolewa
            log.warning("Chat %s imefungwa: %s", chat_id, e)
            return "stop"
        except BadRequest as e:
            log.warning("Chat %s: %s", chat_id, e)
            return "skip"
        except Exception as e:
            log.warning("Kutuma kumeshindwa %s: %s", chat_id, e)
            return "retry"
    return "retry"


def format_entry(e, latest: bool = False) -> str:
    text = f"{e.get('title', '')}\n{e.get('link', '')}"
    return f"🆕 Latest post\n{text}" if latest else text


async def _process(bot, chat_id: int, url: str, feed) -> None:
    link_counts = Counter(e.get("link") for e in feed.entries if e.get("link"))
    dup_links = {l for l, n in link_counts.items() if n > 1}
    keys = {id(e): entry_keys(e, dup_links) for e in feed.entries}
    current = list(dict.fromkeys(k for ks in keys.values() for k in ks))

    exists, old = await db.get_ids(chat_id, url)
    if not exists:  # imefutwa wakati job inaendesha
        return
    if old is None:  # hakuna rekodi: hifadhi baseline, tuma post ya hivi karibuni tu
        await db.set_ids(chat_id, url, current[:MAX_SEEN])
        log.info("Baseline imehifadhiwa: %s|%s", chat_id, url)
        await _send(bot, chat_id, format_entry(feed.entries[0], latest=True))
        return
    old_set = set(old)

    new = [
        e for e in feed.entries
        if keys[id(e)] and not any(k in old_set for k in keys[id(e)])
    ]
    new = list(reversed(new))[-MAX_PER_CYCLE:]  # ya zamani kwanza, mpya 10 tu

    unsent = set()
    for i, e in enumerate(new):
        res = await _send(bot, chat_id, format_entry(e))
        if res == "retry":
            unsent = {k for x in new[i:] for k in keys[id(x)]}  # zitajaribiwa tena
            break
        if res == "stop":
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

    by_url: dict[str, list[int]] = {}
    for d in feeds:
        by_url.setdefault(d["url"], []).append(d["chat_id"])

    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(
        timeout=15, follow_redirects=False, headers=HEADERS
    ) as client:

        async def run(url: str, chats: list[int]) -> None:
            async with sem:
                feed = await fetch_feed(client, url)
            if not feed or not feed.entries:
                return
            for chat_id in chats:
                try:
                    await _process(context.bot, chat_id, url, feed)
                except Exception:
                    log.exception("rss_job kosa: %s|%s", chat_id, url)

        await asyncio.gather(*(run(u, c) for u, c in by_url.items()))


def start_rss_job(app) -> None:
    """Iite mara moja kwenye main baada ya kutengeneza app."""
    app.job_queue.run_repeating(rss_job, interval=INTERVAL, first=10)
