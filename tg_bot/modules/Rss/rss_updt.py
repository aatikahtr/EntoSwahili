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
MAX_SEEN = 3000         # kila entry inaweza kuhifadhi keys 2 (id + link)
MAX_BYTES = 5_000_000   # kikomo cha ukubwa wa feed (feeds za WordPress zenye maudhui kamili ni kubwa)
MAX_REDIRECTS = 3
CONCURRENCY = 10        # feeds zinazopakuliwa kwa wakati mmoja
MAX_TEXT = 4000         # Telegram: 4096
HEADERS = {  # tovuti nyingi (Cloudflare/Wordfence) huzuia UA ya bot; tumia ya kivinjari
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
    "Accept-Language": "en-US,en;q=0.8,sw;q=0.6",
}
ERRORS: dict = {}  # url -> sababu ya kushindwa mara ya mwisho (kwa /rs test na /rs add)


def entry_id(entry) -> str:
    """Imebaki kwa ajili ya rss_cmd.py (utangamano na msimbo wa zamani)."""
    return entry.get("id") or entry.get("link") or ""


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


def feed_keys(feed) -> list:
    """Keys zote za feed (zinatumika na /rs add na job ili baseline ilingane)."""
    link_counts = Counter(e.get("link") for e in feed.entries if e.get("link"))
    dup_links = {l for l, n in link_counts.items() if n > 1}
    return list(dict.fromkeys(k for e in feed.entries for k in entry_keys(e, dup_links)))


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


async def _fetch(client: httpx.AsyncClient, url: str):
    """Pakua kwa usalama (redirects zinakaguliwa, ukubwa umewekewa kikomo) kisha parse."""
    orig = url

    def fail(reason: str):
        ERRORS[orig] = reason
        log.warning("Fetch imeshindwa %s: %s", orig, reason)
        return None

    try:
        for _ in range(MAX_REDIRECTS + 1):
            if not await is_safe_url(url):
                return fail("link si salama / DNS imeshindwa")
            async with client.stream("GET", url) as r:
                if r.is_redirect:
                    loc = r.headers.get("location")
                    if not loc:
                        return fail("redirect bila location")
                    url = urljoin(url, loc)
                    continue
                if r.status_code >= 400:
                    return fail(f"HTTP {r.status_code} (seva imekataa bot)")
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    if len(buf) > MAX_BYTES:
                        return fail(f"feed kubwa mno (>{MAX_BYTES // 1_000_000}MB)")
            feed = await asyncio.to_thread(feedparser.parse, bytes(buf))
            if not feed.entries:
                why = type(feed.get("bozo_exception", "")).__name__ if feed.get("bozo") else "hakuna entries"
                return fail(f"si RSS/Atom sahihi ({why})")
            ERRORS.pop(orig, None)
            return feed
        return fail("redirects nyingi mno")
    except Exception as e:
        return fail(f"{type(e).__name__}: {e}")


async def fetch_feed(url: str, client: httpx.AsyncClient | None = None):
    """Inafanya kazi kama ya zamani: fetch_feed(url). Client ni hiari (job inashiriki moja)."""
    if client is not None:
        return await _fetch(client, url)
    async with httpx.AsyncClient(
        timeout=15, follow_redirects=False, headers=HEADERS
    ) as c:
        return await _fetch(c, url)


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

    if old is None:  # hakuna baseline: tuma post ya hivi karibuni, kisha hifadhi
        res = await _send(bot, chat_id, format_entry(feed.entries[0], latest=True))
        if res == "stop":  # chat haipatikani -> ondoa feed
            await db.remove_feed(chat_id, url)
            log.info("Feed imeondolewa (chat imefungwa): %s|%s", chat_id, url)
            return
        if res == "retry":  # usihifadhi baseline, jaribu tena mzunguko ujao
            return
        await db.set_ids(chat_id, url, current[:MAX_SEEN])
        log.info("Baseline imehifadhiwa: %s|%s", chat_id, url)
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
        if res == "stop":  # bot amezuiwa/ametolewa -> futa usajili wote wa feed hii
            await db.remove_feed(chat_id, url)
            log.info("Feed imeondolewa (chat imefungwa): %s|%s", chat_id, url)
            return
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
                feed = await _fetch(client, url)
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
    app.job_queue.run_repeating(
        rss_job, interval=INTERVAL, first=10,
        job_kwargs={"max_instances": 1, "coalesce": True},  # zuia mizunguko kuingiliana
    )
