"""
instant_command.py — command ya /view

    /view <link>            → Instant View yenye maandishi + picha
    /view text <link>       → maandishi tu
    (reply kwenye message yenye link, pamoja na/bila "text")
"""

import re
import time
import logging
from collections import OrderedDict

from telegram import Update, Message
from telegram.ext import ContextTypes

from .extractor import extract
from .publisher import publish

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s<>\"']+")
TEXT_FLAGS = {"text", "-t", "t", "maandishi"}


# ── Cache ndogo (LRU + TTL): link ile ile haitengenezi page mpya kila mara ──
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


# ── Helpers ──
def _clean_url(url: str) -> str:
    return url.rstrip(".,;:!?)]}>'\"")


def _url_in_text(text: str) -> str | None:
    m = URL_RE.search(text or "")
    return _clean_url(m.group(0)) if m else None


def _url_in_message(message: Message | None) -> str | None:
    if message is None:
        return None
    for ent in list(message.entities or []) + list(message.caption_entities or []):
        if ent.type == "text_link" and ent.url:  # link iliyofichwa nyuma ya neno
            return ent.url
    return _url_in_text(message.text or message.caption or "")


def _author(update: Update) -> tuple[str, str]:
    """(author_name, author_url) kutoka kwa mtumiaji, au channel kama hakuna mtumiaji."""
    user, chat = update.effective_user, update.effective_chat
    if user:
        name = user.full_name or "Telegram User"
        url = f"https://t.me/{user.username}" if user.username else "https://t.me/telegram"
        return name, url
    if chat:
        url = f"https://t.me/{chat.username}" if chat.username else "https://t.me/telegram"
        return chat.title or "Telegram", url
    return "Telegram User", "https://t.me/telegram"


# ── Kazi ya pamoja: inatumika na /view na na modules/handle/msghandle.py ──
async def make_instant_view(
    url: str,
    author_name: str,
    author_url: str,
    text_only: bool = False,
) -> tuple[str, str]:
    """
    Tengeneza Instant View ya url → (title, link ya telegra.ph).
    Inatupa ValueError kwa makosa yanayoeleweka (403, hakuna maudhui, n.k.).
    """
    key = (url, text_only, author_name)
    hit = _cache.get(key)
    if hit:
        return hit

    title, blocks = await extract(url, images=not text_only)
    link = await publish(title, blocks, author_name, author_url)

    _cache.set(key, (title, link))
    return title, link


# ── Handler ──
async def instant_view_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if msg is None:
        return

    args = context.args or []
    text_only = any(a.lower() in TEXT_FLAGS for a in args)

    url = _url_in_text(" ".join(args)) or _url_in_message(msg.reply_to_message)
    if not url:
        await msg.reply_text(
            "⚠️ Tumia:\n/view <link>\n/view text <link>  (maandishi tu)\n\n"
            "au ku-reply message yenye link."
        )
        return

    author_name, author_url = _author(update)

    try:
        title, link = await make_instant_view(url, author_name, author_url, text_only)
        await msg.reply_text(f"{title}\n{link}")

    except ValueError as e:
        await msg.reply_text(f"❌ {e}")
    except Exception as e:
        logger.exception("instant_view_command error: %s", url)
        await msg.reply_text(f"❌ Hitilafu: {str(e)[:200]}")
