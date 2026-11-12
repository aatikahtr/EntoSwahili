"""
instant_command.py — command ya /iv (Instant View)

    /iv                    → msaada (command zote + jinsi ya kutumia)
    /iv LINK               → Instant View (maandishi + picha)
    /iv txt LINK           → maandishi tu, bila picha
    /iv LINK1 LINK2 ...    → link kadhaa kwa mara moja (hadi 5)
    /iv new LINK           → tengeneza upya (bila kutumia ya kumbukumbu)
    reply kwenye message yenye link + /iv  (au /iv txt)

  Author (mwandishi anayeonekana kwenye page) — inahifadhiwa MongoDB kwa kila mtumiaji
  (au kwa kila channel ukiandika command ndani ya channel):
    /iv author JINA [LINK] → weka jina (na link)
    /iv name JINA          → weka jina tu
    /iv url LINK           → weka link tu
    /iv me                 → angalia author wako
    /iv reset [name|url]   → rudisha ya kawaida (kutoka Telegram)

Kazi ya pamoja `make_instant_view()` inatumika pia na handle/msghandle.py
"""

import re
import time
import asyncio
import logging
from collections import OrderedDict
from typing import NamedTuple
from urllib.parse import urlparse

from telegram import Update, Message
from telegram.ext import ContextTypes

from .extractor import extract
from .publisher import publish
from . import iv_db

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s<>\"']+")
BARE_DOMAIN_RE = re.compile(r"^[\w-]+(?:\.[\w-]+)+(?:[/?#]\S*)?$")

HELP_WORDS = {"help", "msaada", "?", "h"}
TXT_WORDS = {"txt", "text", "t", "-t", "maandishi"}
NEW_WORDS = {"new", "upya", "fresh"}
FLAG_WORDS = HELP_WORDS | TXT_WORDS | NEW_WORDS

# Maneno ya kuweka author (yakiwa neno la kwanza, si link ya kutengeneza)
AUTHOR_WORDS = {"author", "name", "jina", "url", "me", "reset", "futa"}
MAX_NAME = 128   # kikomo cha Telegraph kwa author_name
MAX_URL = 400    # kikomo cha Telegraph kwa author_url ni 512
DB_TIMEOUT = 4   # sekunde — DB ikichelewa, tumia author wa kawaida

MAX_URLS = 5
WORDS_PER_MINUTE = 200

# Tovuti za video/social — hazina makala ya kusoma
UNSUPPORTED = ("youtube.com", "youtu.be", "tiktok.com", "instagram.com")

HELP_TEXT = (
    "📖 <b>Instant View — Msaada</b>\n"
    "Geuza link ya makala kuwa Instant View ya Telegram.\n\n"
    "<b>Command:</b>\n"
    "• <code>/iv</code> — msaada huu\n"
    "• <code>/iv LINK</code> — Instant View yenye maandishi na picha\n"
    "• <code>/iv txt LINK</code> — maandishi tu (bila picha)\n"
    "• <code>/iv LINK1 LINK2</code> — link kadhaa kwa mara moja (hadi 5)\n"
    "• <code>/iv new LINK</code> — tengeneza upya (si ya kumbukumbu)\n\n"
    "<b>Author (mwandishi kwenye page):</b>\n"
    "• <code>/iv author JINA LINK</code> — weka jina na link\n"
    "• <code>/iv name JINA</code> — weka jina tu\n"
    "• <code>/iv url LINK</code> — weka link tu\n"
    "• <code>/iv me</code> — angalia author wako\n"
    "• <code>/iv reset</code> — rudisha ya kawaida (jina lako la Telegram)\n"
    "Mfano: <code>/iv author Hamis https://t.me/Dczote</code>\n"
    "Inahifadhiwa — haubadiliki hadi ubadilishe mwenyewe.\n\n"
    "<b>Njia za mkato:</b>\n"
    "• Reply kwenye message yenye link kisha andika <code>/iv</code> au <code>/iv txt</code>\n"
    "• Unaweza kuandika <code>txt</code> mwisho: <code>/iv LINK txt</code>\n"
    "• Link bila <code>https://</code> inakubalika: <code>/iv dw.com/sw/...</code>\n\n"
    "<b>Maneno mbadala:</b>\n"
    "• txt = text, t, -t, maandishi\n"
    "• new = upya\n\n"
    "<b>Kumbuka:</b>\n"
    "• YouTube, TikTok na Instagram hazitumiki\n"
    "• Picha zikileta tatizo, inajaribu kiotomatiki bila picha\n"
    "• Link ile ile ndani ya saa 1 inatumia ya kumbukumbu (tumia <code>new</code> kuipuuza)"
)


# ── Cache ndogo (LRU + TTL) ──
class _Cache:
    def __init__(self, max_size: int = 200, ttl: int = 3600):
        self.data: OrderedDict = OrderedDict()
        self.max_size, self.ttl = max_size, ttl

    def get(self, key):
        item = self.data.get(key)
        if not item:
            return None
        value, ts = item
        if time.time() - ts > self.ttl:
            del self.data[key]
            return None
        self.data.move_to_end(key)
        return value

    def set(self, key, value):
        self.data[key] = (value, time.time())
        self.data.move_to_end(key)
        if len(self.data) > self.max_size:
            self.data.popitem(last=False)


_cache = _Cache()


# ── Matokeo ──
class Result(NamedTuple):
    title: str
    link: str
    images: int
    minutes: int


def _stats(blocks: list[str]) -> tuple[int, int]:
    images = sum(1 for b in blocks if b.startswith("<img"))
    words = sum(
        len(re.sub(r"<[^>]+>", " ", b).split())
        for b in blocks
        if not b.startswith("<img")
    )
    return images, max(1, round(words / WORDS_PER_MINUTE))


# ── Kazi ya pamoja ──
async def make_instant_view_full(
    url: str,
    author_name: str,
    author_url: str,
    text_only: bool = False,
    use_cache: bool = True,
) -> Result:
    """Tengeneza Instant View → Result(title, link, images, minutes). Inatupa ValueError kwa makosa yanayoeleweka."""
    key = (url, text_only, author_name, author_url)
    if use_cache:
        hit = _cache.get(key)
        if hit:
            return hit

    title, blocks = await extract(url, images=not text_only)
    link = await publish(title, blocks, author_name, author_url)

    images, minutes = _stats(blocks)
    result = Result(title, link, images, minutes)
    _cache.set(key, result)
    return result


async def make_instant_view(
    url: str,
    author_name: str,
    author_url: str,
    text_only: bool = False,
) -> tuple[str, str]:
    """Toleo fupi: (title, link). Inatumika na handle/msghandle.py."""
    r = await make_instant_view_full(url, author_name, author_url, text_only)
    return r.title, r.link


# ── Helpers ──
def _clean_url(url: str) -> str:
    return url.rstrip(".,;:!?)]}>'\"")


def _unsupported(url: str) -> bool:
    host = urlparse(url).netloc.lower().split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    return any(host == d or host.endswith("." + d) for d in UNSUPPORTED)


def _urls_in_message(message: Message | None) -> list[str]:
    if message is None:
        return []
    urls = [
        e.url
        for e in list(message.entities or []) + list(message.caption_entities or [])
        if e.type == "text_link" and e.url
    ]
    text = message.text or message.caption or ""
    urls += [_clean_url(u) for u in URL_RE.findall(text)]
    return list(dict.fromkeys(urls))


def _urls_in_args(args: list[str]) -> list[str]:
    urls: list[str] = []
    for token in args:
        if token.lower() in FLAG_WORDS:
            continue
        found = URL_RE.findall(token)
        if found:
            urls.extend(_clean_url(u) for u in found)
        elif BARE_DOMAIN_RE.match(token):  # mf. dw.com/sw/habari
            urls.append("https://" + _clean_url(token))
    return list(dict.fromkeys(urls))


def _default_author(update: Update) -> tuple[str, str]:
    """Author wa kawaida: kutoka kwa mtumiaji wa Telegram, au channel kama hakuna mtumiaji."""
    user, chat = update.effective_user, update.effective_chat
    if user:
        name = user.full_name or "Telegram User"
        url = f"https://t.me/{user.username}" if user.username else "https://t.me/telegram"
        return name, url
    if chat:
        url = f"https://t.me/{chat.username}" if chat.username else "https://t.me/telegram"
        return chat.title or "Telegram", url
    return "Telegram User", "https://t.me/telegram"


def _owner_id(update: Update) -> int | None:
    if update.effective_user:
        return update.effective_user.id
    if update.effective_chat:
        return update.effective_chat.id
    return None


async def author_for(owner_id: int | None, default_name: str, default_url: str) -> tuple[str, str]:
    """
    Author kutoka MongoDB (kama ameweka), vinginevyo wa kawaida.
    DB ikishindwa/ikichelewa → wa kawaida (Instant View haikwami).
    Inatumika na /iv na na handle/msghandle.py (owner_id = chat_id ya channel).
    """
    if owner_id is None:
        return default_name, default_url
    try:
        custom = await asyncio.wait_for(iv_db.get_author(owner_id), DB_TIMEOUT)
    except Exception:
        logger.exception("iv_db.get_author imeshindwa — natumia author wa kawaida")
        return default_name, default_url
    return custom.get("name", default_name), custom.get("url", default_url)


async def _get_author(update: Update) -> tuple[str, str]:
    name, url = _default_author(update)
    return await author_for(_owner_id(update), name, url)


def _host(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _format(url: str, r: Result) -> str:
    stats = []
    if r.images:
        stats.append(f"🖼 picha {r.images}")
    stats.append(f"⏱ ~dakika {r.minutes}")
    return f"📄 {r.title}\n{' · '.join(stats)}\n{r.link}"


# ── Author: kusafisha na kuhakiki ──
def _clean_name(raw: str) -> str | None:
    name = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", raw).split())
    return name[:MAX_NAME] if name else None


def _clean_author_url(raw: str) -> str | None:
    """Kubali https://..., t.me/..., au @username. Vinginevyo None."""
    raw = raw.strip().strip("<>")
    if raw.startswith("@") and re.fullmatch(r"@[A-Za-z0-9_]{3,32}", raw):
        return f"https://t.me/{raw[1:]}"
    if re.match(r"^(?:t|telegram)\.me/", raw, re.I):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or "." not in parsed.netloc or " " in raw:
        return None
    return raw if len(raw) <= MAX_URL else None


def _looks_like_url(token: str) -> bool:
    return _clean_author_url(token) is not None


AUTHOR_USAGE = (
    "⚠️ Tumia:\n"
    "/iv author JINA LINK\n"
    "/iv name JINA\n"
    "/iv url LINK\n\n"
    "Mfano: /iv author Hamis https://t.me/Dczote"
)


async def _author_command(update: Update, args: list[str]) -> None:
    msg = update.effective_message
    sub, rest = args[0].lower(), args[1:]
    owner = _owner_id(update)
    if owner is None:
        await msg.reply_text("⚠️ Siwezi kukutambua. Jaribu kwenye chat ya kawaida na bot.")
        return

    async def reply(text: str):
        await msg.reply_text(text, disable_web_page_preview=True)

    try:
        # ── /iv me ──
        if sub == "me":
            d_name, d_url = _default_author(update)
            custom = await asyncio.wait_for(iv_db.get_author(owner), DB_TIMEOUT)
            tag = lambda key: "umeweka" if key in custom else "kawaida"
            await reply(
                "👤 Author wako\n"
                f"Jina: {custom.get('name', d_name)}  ({tag('name')})\n"
                f"Link: {custom.get('url', d_url)}  ({tag('url')})\n\n"
                "Badilisha: /iv author JINA LINK\nRudisha: /iv reset"
            )
            return

        # ── /iv reset [name|url] ──
        if sub in ("reset", "futa"):
            which = rest[0].lower() if rest else "all"
            if which not in ("all", "name", "jina", "url"):
                await reply("⚠️ Tumia: /iv reset  au  /iv reset name  au  /iv reset url")
                return
            done = await asyncio.wait_for(
                iv_db.reset_author(
                    owner, name=which in ("all", "name", "jina"), url=which in ("all", "url")
                ),
                DB_TIMEOUT,
            )
            await reply("✅ Nimerudisha author wa kawaida." if done else "ℹ️ Hukuwa umeweka chochote.")
            return

        # ── /iv name JINA ──
        if sub in ("name", "jina"):
            name = _clean_name(" ".join(rest))
            if not name:
                await reply(AUTHOR_USAGE)
                return
            await asyncio.wait_for(iv_db.set_author(owner, name=name), DB_TIMEOUT)
            await reply(f"✅ Author name imewekwa: {name}")
            return

        # ── /iv url LINK ──
        if sub == "url":
            url = _clean_author_url(rest[0]) if rest else None
            if not url:
                await reply("⚠️ Link si sahihi. Mfano:\n/iv url https://t.me/Dczote\n/iv url @Dczote")
                return
            await asyncio.wait_for(iv_db.set_author(owner, url=url), DB_TIMEOUT)
            await reply(f"✅ Author url imewekwa: {url}")
            return

        # ── /iv author JINA [LINK] ──
        if sub == "author":
            if not rest:
                await reply(AUTHOR_USAGE)
                return
            url = None
            if len(rest) >= 1 and _looks_like_url(rest[-1]):
                url, rest = _clean_author_url(rest[-1]), rest[:-1]
            name = _clean_name(" ".join(rest)) if rest else None
            if name is None and url is None:
                await reply(AUTHOR_USAGE)
                return
            await asyncio.wait_for(iv_db.set_author(owner, name=name, url=url), DB_TIMEOUT)
            lines = ["✅ Author imewekwa:"]
            if name:
                lines.append(f"👤 {name}")
            if url:
                lines.append(f"🔗 {url}")
            await reply("\n".join(lines))
            return

    except Exception:
        logger.exception("author command imeshindwa")
        await reply("❌ Siwezi kuhifadhi/kusoma sasa hivi (database). Jaribu tena baadaye.")


# ── Handler ──
async def instant_view_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if msg is None:
        return

    args = context.args or []
    words = {a.lower() for a in args}

    # /iv author|name|url|me|reset ...  → mipangilio ya author (si kutengeneza Instant View)
    if args and args[0].lower() in AUTHOR_WORDS:
        await _author_command(update, args)
        return

    urls = _urls_in_args(args)
    if not urls:
        urls = _urls_in_message(msg.reply_to_message)

    # /iv  au  /iv help  → msaada
    if (not args and not urls) or (args and args[0].lower() in HELP_WORDS):
        await msg.reply_text(HELP_TEXT, parse_mode="HTML")
        return

    if not urls:
        await msg.reply_text(
            "⚠️ Sikupata link.\nMfano: /iv txt https://example.com/habari\n"
            "au reply kwenye message yenye link.\n\nAndika /iv kuona msaada."
        )
        return

    text_only = bool(words & TXT_WORDS)
    use_cache = not (words & NEW_WORDS)

    supported = [u for u in urls if not _unsupported(u)]
    skipped = len(urls) - len(supported)
    if not supported:
        await msg.reply_text("⚠️ YouTube, TikTok na Instagram hazitumiki kwenye Instant View.")
        return

    notes = []
    if skipped:
        notes.append("ℹ️ Nimeruka link za YouTube/TikTok/Instagram.")
    if len(supported) > MAX_URLS:
        notes.append(f"ℹ️ Nimechukua link {MAX_URLS} za kwanza tu.")
        supported = supported[:MAX_URLS]

    author_name, author_url = await _get_author(update)
    status = await msg.reply_text("⏳ Inatengeneza Instant View...")

    lines: list[str] = []
    for i, url in enumerate(supported, 1):
        if len(supported) > 1:
            try:
                await status.edit_text(f"⏳ Inatengeneza {i}/{len(supported)}...")
            except Exception:
                pass
        try:
            r = await make_instant_view_full(url, author_name, author_url, text_only, use_cache)
            lines.append(_format(url, r))
        except ValueError as e:
            lines.append(f"❌ {_host(url)} — {e}")
        except Exception as e:
            logger.exception("instant_view_command error: %s", url)
            lines.append(f"❌ {_host(url)} — Hitilafu: {str(e)[:150]}")

    final = "\n\n".join(lines + notes)
    try:
        await status.edit_text(final)
    except Exception:
        logger.exception("instant_view_command: edit imeshindwa, natuma upya")
        await msg.reply_text(final)
