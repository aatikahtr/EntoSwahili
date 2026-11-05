"""Rss/rss_cmd.py
/rs list [titles]          - orodha ya feeds
/rs add url [url2 ...]     - ongeza feed moja au nyingi
/rs stop url|namba [...]   - ondoa feed (au /rs stop all)
/rs latest url|namba [n]   - posts za hivi karibuni
/rs test url               - jaribu link bila kuhifadhi
/rs help                   - msaada
/rmv url|namba [...]       - futa feed kutoka MongoDB (chat hii tu)
/rmv all                   - futa feeds ZOTE za chat hii tu
/vw hidden|show            - muundo wa post: link imefichwa kwenye kichwa | kichwa + link wazi
"""
import asyncio
import time

from telegram import Update
from telegram.ext import ContextTypes

from . import rss_db as db
from .rss_updt import ERRORS, feed_keys, fetch_feed, is_safe_url

USAGE = (
    "📖 Amri za /rs:\n"
    "/rs list [short]\n"
    "/rs add url [url2 ...]  (hadi 5)\n"
    "/rs stop url|namba [...]  au  /rs stop all\n"
    "/rs latest url|namba [idadi]\n"
    "/rs test url\n"
    "/rmv url|namba [...]  — futa feed kutoka database\n"
    "/rmv all  — futa feeds zote za chat hii tu\n"
    "/vw hidden  — kichwa cha post kiwe link (url imefichwa)\n"
    "/vw show  — kichwa kisha link wazi chini yake"
)
MAX_FEEDS = 20       # kwa kila chat
MAX_ADD_AT_ONCE = 5
MAX_LATEST = 5
TITLE_TTL = 6 * 3600     # jina la feed linakaa cache masaa 6
TITLE_MAX = 500          # kikomo cha cache
TITLE_CONCURRENCY = 5    # feeds zinazopakuliwa kwa wakati mmoja kwenye /rs list
_title_sem = asyncio.Semaphore(TITLE_CONCURRENCY)
TG_LIMIT = 4000      # Telegram ina kikomo cha 4096

ALIASES = {
    "ls": "list", "l": "list",
    "a": "add",
    "rm": "stop", "del": "stop", "remove": "stop",
    "last": "latest", "new": "latest",
    "check": "test",
    "h": "help",
}


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


def _normalize(url: str) -> str:
    """Ongeza https:// kama imesahaulika."""
    url = url.strip()
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _resolve(token: str, urls: list[str]) -> str | None:
    """Namba -> link kutoka kwenye orodha; vinginevyo normalize link."""
    if token.isdigit():
        i = int(token)
        return urls[i - 1] if 1 <= i <= len(urls) else None
    return _normalize(token)


_TITLES: dict[str, tuple[float, str]] = {}  # url -> (muda, jina)


def _cache_title(url: str, title: str) -> None:
    if len(_TITLES) >= TITLE_MAX:  # ondoa ya zamani zaidi
        _TITLES.pop(min(_TITLES, key=lambda k: _TITLES[k][0]), None)
    _TITLES[url] = (time.time(), title)


async def _title_of(url: str) -> str:
    hit = _TITLES.get(url)
    if hit and time.time() - hit[0] < TITLE_TTL:
        return hit[1]
    try:
        async with _title_sem:
            feed = await asyncio.wait_for(fetch_feed(url), timeout=15)
        title = (feed.feed.get("title") or "").strip() if feed else ""
        if title:
            _cache_title(url, title)
            return title
    except Exception:
        pass
    return "(jina halipatikani)"


async def _remove(chat_id: int, rest: list, reply) -> None:
    """Mantiki ya pamoja: /rmv na /rs stop. Inafuta MongoDB kwa chat_id hii tu."""
    if not rest:
        return await reply("Tumia: /rmv url|namba [...]  au  /rmv all")
    urls = await db.list_urls(chat_id)

    if rest[0].lower() == "all":
        if not urls:
            return await reply("Hakuna cha kuondoa.")
        removed = await db.remove_all(chat_id)  # chat_id hii tu
        return await reply(f"🗑️ Feeds {removed} zimefutwa kutoka database.")

    # tatua namba zote kwanza (kabla ya kuondoa, ili namba zisibadilike)
    targets = [(tok, _resolve(tok, urls)) for tok in rest]
    results = []
    for tok, t in targets:
        if t is None:
            results.append(f"❌ Namba {tok} haipo")
        elif await db.remove_feed(chat_id, t):
            _TITLES.pop(t, None)
            results.append(f"🗑️ {t}")
        else:
            results.append(f"❌ Haipo kwenye orodha: {t}")
    await reply("\n".join(results))


async def _guarded(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rudisha (msg, chat_id, reply) au None kama hairuhusiwi."""
    msg = update.channel_post or update.message
    if not msg:
        return None

    async def reply(text: str):
        if len(text) > TG_LIMIT:
            text = text[:TG_LIMIT] + "\n…"
        await msg.reply_text(
            text,
            message_thread_id=msg.message_thread_id,
            disable_web_page_preview=True,
        )

    if not await _can_manage(msg, context):
        await reply("⛔ Admins tu ndio wanaweza kutumia amri hii hapa.")
        return None
    return msg, msg.chat.id, reply


async def rmv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/rmv url|namba [...]  |  /rmv all"""
    g = await _guarded(update, context)
    if not g:
        return
    _, chat_id, reply = g
    try:
        await _remove(chat_id, context.args or [], reply)
    except Exception as e:
        await reply(f"❌ Hitilafu: {type(e).__name__}")
        raise


async def vw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/vw hidden | /vw show | /vw (hali ya sasa). Inahifadhiwa kwa chat hii tu."""
    g = await _guarded(update, context)
    if not g:
        return
    _, chat_id, reply = g
    arg = (context.args[0].lower() if context.args else "")
    try:
        if arg in ("hidden", "hide", "h"):
            await db.set_view(chat_id, "hidden")
            return await reply("✅ Muundo: hidden — kichwa cha post ni link (url imefichwa).")
        if arg in ("show", "s"):
            await db.set_view(chat_id, "show")
            return await reply(
                "✅ Muundo: show — post itatumwa hivi:\n\n"
                "Nijitolee figo na kupewa gari?\n"
                "https://firqatunnajia.com/nijitolee-figo-na-kupewa-gari/"
            )
        cur = await db.get_view(chat_id)
        await reply(f"Muundo wa sasa: {cur}\n/vw hidden\n/vw show")
    except Exception as e:
        await reply(f"❌ Hitilafu: {type(e).__name__}")
        raise


async def rs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    g = await _guarded(update, context)
    if not g:
        return
    msg, chat_id, reply = g

    args = context.args or []
    action = ALIASES.get(args[0].lower(), args[0].lower()) if args else "list"
    rest = args[1:]

    try:
        # ---------- /rs help ----------
        if action == "help":
            return await reply(USAGE)

        # ---------- /rs list [titles] ----------
        if action == "list":
            urls = await db.list_urls(chat_id)
            if not urls:
                return await reply("Hakuna RSS iliyoongezwa.\n/rs add url")
            if rest and rest[0].lower() in ("short", "urls", "url", "s"):
                # orodha ya haraka: link tu
                lines = "\n".join(f"{i}. {u}" for i, u in enumerate(urls, 1))
            else:
                # kawaida: jina + link (feeds zote zinasomwa kwa pamoja)
                titles = await asyncio.gather(*(_title_of(u) for u in urls))
                lines = "\n\n".join(
                    f"{i}. {t}\n{u}" for i, (t, u) in enumerate(zip(titles, urls), 1)
                )
            return await reply(f"📡 RSS zako ({len(urls)}/{MAX_FEEDS}):\n{lines}")

        # ---------- /rs add url [url2 ...] ----------
        if action == "add":
            if not rest:
                return await reply("Tumia: /rs add url [url2 ...]")
            targets = list(dict.fromkeys(_normalize(t) for t in rest))  # ondoa duplicates
            if len(targets) > MAX_ADD_AT_ONCE:
                return await reply(f"⚠️ Ongeza hadi feeds {MAX_ADD_AT_ONCE} kwa mara moja.")

            count = len(await db.list_urls(chat_id))
            results = []
            for target in targets:
                if count >= MAX_FEEDS:
                    results.append(f"⚠️ Kikomo {MAX_FEEDS} kimefika: {target}")
                    continue
                if not await is_safe_url(target):
                    results.append(f"❌ Link si sahihi: {target}")
                    continue
                feed = await fetch_feed(target)
                if not feed or not feed.entries:
                    results.append(f"❌ {target}\n   Sababu: {ERRORS.get(target, 'si RSS sahihi / haina entries')}")
                    continue
                # hifadhi zilizopo ili zisitumwe upya
                ids = feed_keys(feed)
                if not await db.add_feed(chat_id, target, ids):
                    results.append(f"⚠️ Tayari ipo: {target}")
                    continue
                count += 1
                if feed.feed.get("title"):
                    _cache_title(target, feed.feed["title"].strip())
                results.append(f"✅ {feed.feed.get('title', target)}")
            return await reply("\n".join(results))

        # ---------- /rs stop (sawa na /rmv) ----------
        if action == "stop":
            return await _remove(chat_id, rest, reply)

        # ---------- /rs latest url|namba [idadi] ----------
        if action == "latest":
            if not rest:
                return await reply("Tumia: /rs latest url|namba [idadi]")
            urls = await db.list_urls(chat_id)
            target = _resolve(rest[0], urls)
            if not target:
                return await reply("❌ Namba hiyo haipo kwenye orodha.")

            n = 3
            if len(rest) > 1 and rest[1].isdigit():
                n = max(1, min(int(rest[1]), MAX_LATEST))

            feed = await fetch_feed(target)
            if not feed or not feed.entries:
                return await reply("❌ Imeshindwa kusoma feed hii.")
            lines = []
            for e in feed.entries[:n]:
                title = e.get("title", "(bila kichwa)")
                link = e.get("link", "")
                lines.append(f"• {title}\n  {link}")
            head = feed.feed.get("title", target)
            return await reply(f"📰 {head}\n" + "\n".join(lines))

        # ---------- /rs test url ----------
        if action == "test":
            if not rest:
                return await reply("Tumia: /rs test url")
            target = _normalize(rest[0])
            if not await is_safe_url(target):
                return await reply("❌ Link si sahihi.")
            feed = await fetch_feed(target)
            if not feed or not feed.entries:
                return await reply(f"❌ Imeshindwa: {ERRORS.get(target, 'si RSS sahihi au haina entries')}")
            first = feed.entries[0]
            return await reply(
                f"✅ RSS sahihi\n"
                f"Jina: {feed.feed.get('title', '-')}\n"
                f"Entries: {len(feed.entries)}\n"
                f"Ya hivi karibuni: {first.get('title', '-')}\n"
                f"(Haijahifadhiwa. Tumia /rs add kuiongeza.)"
            )

        await reply(USAGE)

    except Exception as e:
        await reply(f"❌ Hitilafu: {type(e).__name__}")
        raise
