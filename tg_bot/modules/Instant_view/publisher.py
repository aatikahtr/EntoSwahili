"""
publisher.py — kuchapisha blocks kwenye Telegraph (na pages nyingi kama ni ndefu).

    link = await publish(title, blocks, author_name, author_url)

Picha zikileta tatizo → inajaribu tena kwa maandishi tu (haishindwi kwa sababu ya picha).
"""

import os
import re
import asyncio
import logging
from html import escape, unescape

from telegraph.aio import Telegraph

try:
    from telegraph.exceptions import RetryAfterError
except ImportError:  # toleo la maktaba lisilo na class hii
    class RetryAfterError(Exception):  # type: ignore
        retry_after = 5

logger = logging.getLogger(__name__)

# Telegraph: title 1-256, author_name 0-128, content ~64KB kwa page
MAX_TITLE = 256
MAX_AUTHOR = 128
MAX_PAGE_BYTES = 35_000      # tunapima kwa bytes (Kiarabu/emoji zinakula zaidi)
MAX_TOTAL_BYTES = 500_000    # makala ndefu kupita hapa inakatwa
MAX_RETRY_WAIT = 30

_telegraph: Telegraph | None = None


def _get_telegraph() -> Telegraph:
    global _telegraph
    if _telegraph is None:
        token = os.getenv("INSTANT_TOKEN")
        if not token:
            raise RuntimeError("INSTANT_TOKEN haijawekwa kwenye environment variables")
        _telegraph = Telegraph(access_token=token)
    return _telegraph


async def _call(fn, **kwargs):
    """Ita Telegraph; ikipigwa flood-wait ngoja kisha jaribu tena."""
    for attempt in range(3):
        try:
            return await fn(**kwargs)
        except RetryAfterError as e:
            wait = int(getattr(e, "retry_after", 5))
            if attempt == 2 or wait > MAX_RETRY_WAIT:
                raise
            logger.warning("Telegraph flood-wait: nasubiri %ss", wait)
            await asyncio.sleep(wait + 1)


# ── Pagination ───────────────────────────────────────────────
def _size(s: str) -> int:
    return len(s.encode("utf-8"))


def _split_huge(block: str) -> list[str]:
    """Block moja kubwa kuliko ukurasa mzima → igawe kwa maandishi tu."""
    m = re.match(r"<(\w+)", block)
    tag = m.group(1) if m else "p"
    if tag == "img":
        return [block]
    text = unescape(re.sub(r"<[^>]+>", "", block))
    step = MAX_PAGE_BYTES // 6  # herufi (Kiarabu = bytes 2-3 kwa herufi)
    return [f"<{tag}>{escape(text[i:i + step], quote=False)}</{tag}>" for i in range(0, len(text), step)]


def paginate(blocks: list[str]) -> list[str]:
    pages: list[str] = []
    cur: list[str] = []
    cur_size = 0
    total = 0

    expanded: list[str] = []
    for b in blocks:
        expanded.extend(_split_huge(b) if _size(b) > MAX_PAGE_BYTES else [b])

    for b in expanded:
        n = _size(b)
        total += n
        if total > MAX_TOTAL_BYTES:
            cur.append("<p>… (makala imekatwa kwa sababu ni ndefu sana)</p>")
            break
        if cur and cur_size + n > MAX_PAGE_BYTES:
            pages.append("".join(cur))
            cur, cur_size = [], 0
        cur.append(b)
        cur_size += n

    if cur:
        pages.append("".join(cur))
    return pages


def _nav(paths: list[str], i: int, with_next: bool = True) -> str:
    nav = ""
    if i > 0:
        nav += f'<p><a href="https://telegra.ph/{paths[i - 1]}">⬅️ Previous page</a></p>'
    if with_next and i < len(paths) - 1:
        nav += f'<p><a href="https://telegra.ph/{paths[i + 1]}">➡️ Next page</a></p>'
    return nav


def _page_title(title: str, i: int) -> str:
    if i == 0:
        return title[:MAX_TITLE]
    suffix = f" (Page {i + 1})"
    return title[: MAX_TITLE - len(suffix)] + suffix


async def _publish(title: str, blocks: list[str], author_name: str, author_url: str) -> str:
    tg = _get_telegraph()
    pages = paginate(blocks)
    if not pages:
        raise ValueError("Hakuna content ya kuchapisha.")

    def common(i: int) -> dict:
        return {
            "title": _page_title(title, i),
            "author_name": author_name[:MAX_AUTHOR],
            "author_url": author_url,
        }

    if len(pages) == 1:
        r = await _call(tg.create_page, html_content=pages[0], **common(0))
        return f"https://telegra.ph/{r['path']}"

    paths: list[str] = []
    for i, content in enumerate(pages):
        r = await _call(
            tg.create_page, html_content=_nav(paths, i, with_next=False) + content, **common(i)
        )
        paths.append(r["path"])

    for i in range(len(paths) - 1):  # page ya mwisho haihitaji edit
        await _call(
            tg.edit_page, path=paths[i], html_content=_nav(paths, i) + pages[i], **common(i)
        )
    return f"https://telegra.ph/{paths[0]}"


async def publish(title: str, blocks: list[str], author_name: str, author_url: str) -> str:
    try:
        return await _publish(title, blocks, author_name, author_url)
    except RuntimeError:
        raise  # token haipo — hakuna maana kujaribu tena
    except Exception:
        text_only = [b for b in blocks if not b.startswith("<img")]
        if not text_only or len(text_only) == len(blocks):
            raise
        logger.exception("Publish imeshindwa — najaribu tena bila picha")
        return await _publish(title, text_only, author_name, author_url)
