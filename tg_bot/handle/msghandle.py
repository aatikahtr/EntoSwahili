"""
msghandle.py — inapokea updates za messages (channel posts) na kuchukua URL tu.

Mtiririko wa sasa:
    post mpya kwenye channel iliyo ndani ya ROUTES
      → chukua URL (isiyo ya YouTube / TikTok / Instagram)
      → tengeneza Instant View (kazi ile ile ya /view)
      → itume kwenye channel ya kupokelea (thamani ya ROUTES)

Kuongeza channel nyingine ya chanzo: ongeza mstari kwenye ROUTES.
"""

import re
import asyncio
import logging
from urllib.parse import urlparse

from telegram import Message, Update
from telegram.ext import ContextTypes

from ID import error_chat_id
from modules.Instant_view.instant_command import make_instant_view

logger = logging.getLogger(__name__)

# ── SETTINGS ─────────────────────────────────────────────────
# chanzo (chat_id) → mahali Instant View inapotumwa
ROUTES: dict[int, int] = {
    -1003733738728: -1001248885302,
}

# URL za tovuti hizi HAZIPITI hapa
SKIP_DOMAINS = ("youtube.com", "youtu.be", "tiktok.com", "instagram.com")

URL_RE = re.compile(r"https?://[^\s<>\"']+")

_tasks: set[asyncio.Task] = set()  # zuia task zisifutwe na garbage collector


# ── URL helpers ──────────────────────────────────────────────
def _clean(url: str) -> str:
    return url.rstrip(".,;:!?)]}>'\"")


def get_urls(msg: Message) -> list[str]:
    """URL zote kwenye message (text, caption, na links zilizofichwa), bila kurudia."""
    urls: list[str] = []

    for ent in list(msg.entities or []) + list(msg.caption_entities or []):
        if ent.type == "text_link" and ent.url:
            urls.append(ent.url)

    text = msg.text or msg.caption or ""
    urls.extend(_clean(u) for u in URL_RE.findall(text))

    return list(dict.fromkeys(urls))


def is_skipped(url: str) -> bool:
    host = urlparse(url).netloc.lower().split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    return any(host == d or host.endswith("." + d) for d in SKIP_DOMAINS)


def pick_url(msg: Message) -> str | None:
    """URL ya kwanza inayofaa (http/https na si ya YouTube/TikTok/Instagram)."""
    for url in get_urls(msg):
        if url.lower().startswith(("http://", "https://")) and not is_skipped(url):
            return url
    return None


# ── Handler ──────────────────────────────────────────────────
async def msg_handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.channel_post  # updates za channel tu
    if msg is None:
        return

    target = ROUTES.get(msg.chat.id)
    if target is None:
        return

    url = pick_url(msg)
    if url is None:
        return

    # Kazi ndefu (fetch + Telegraph) — isizuie updates nyingine
    task = asyncio.create_task(_send_instant_view(context, msg, url, target))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _send_instant_view(
    context: ContextTypes.DEFAULT_TYPE, msg: Message, url: str, target: int
) -> None:
    try:
        chat = msg.chat
        author_url = f"https://t.me/{chat.username}" if chat.username else "https://t.me/telegram"

        title, link = await make_instant_view(url, chat.title or "Telegram", author_url)
        await context.bot.send_message(chat_id=target, text=f"{title}\n{link}")

    except Exception as e:
        logger.exception("msghandle: imeshindwa kwa %s", url)
        await _notify_error(context, msg.chat.id, url, e)


async def _notify_error(context, chat_id: int, url: str, error: Exception) -> None:
    try:
        await context.bot.send_message(
            chat_id=error_chat_id,
            text=f"⚠️ msghandle (chat {chat_id})\n{url}\n{type(error).__name__}: {str(error)[:300]}",
        )
    except Exception:
        logger.exception("msghandle: siwezi kutuma kosa kwenye error_chat_id")
