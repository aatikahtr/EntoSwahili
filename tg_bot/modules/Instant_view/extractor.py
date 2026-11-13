"""
extractor.py — kuchukua ukurasa, kutafuta makala, kuisafisha.

    title, blocks = await extract(url, images=True)

Hatua: fetch → title → tafuta content (selectors za site) → futa uchafu → Cleaner.
"""

import asyncio
import logging
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import httpx
from bs4 import BeautifulSoup

from .cleaner import Cleaner
from .sites import get_rules, MIN_ROOT_CHARS

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "sw,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.google.com/",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-User": "?1",
}

# Tovuti nyingi (mf. DW) huzuia request inayoonekana kama bot kwa 403.
# Tunajaribu tena kwa "utambulisho" mwingine — wa kwanza ni browser ya kawaida.
FALLBACK_AGENTS = (
    "TelegramBot (like TwitterBot)",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
)
RETRY_STATUS = {403, 429, 503}

# Vigezo vya kufuatilia (tracking) kwenye URL — havina uhusiano na makala
TRACKING_PARAMS = {
    "maca", "fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "ref", "ref_src",
    "source", "cmpid", "ocid", "ncid", "spm", "yclid", "_ga",
}

MAX_PAGE_BYTES = 5_000_000
SEMAPHORE = asyncio.Semaphore(5)  # zuia requests nyingi kwa wakati mmoja

_client: httpx.AsyncClient | None = None

HTTP_ERRORS = {
    403: "Tovuti imekataa ufikiaji (403) — inazuia bots.",
    404: "Ukurasa haupatikani (404).",
    429: "Maombi mengi sana, jaribu tena baadaye (429).",
}


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            headers=HEADERS,
            follow_redirects=True,
            timeout=httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=5.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _client


def clean_url(url: str) -> str:
    """Ondoa tracking params (maca=, utm_*, fbclid=...) — mara nyingi vinachochea kizuizi cha bot."""
    parts = urlsplit(url)
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")
    ]
    return urlunsplit(parts._replace(query=urlencode(query), fragment=""))


async def _get(client, url: str):
    """GET; ikipata 403/429/503 jaribu tena kwa user-agent nyingine."""
    resp = await client.get(url)
    for ua in FALLBACK_AGENTS:
        if resp.status_code not in RETRY_STATUS:
            break
        logger.info("HTTP %s kwa %s — najaribu tena kama %s", resp.status_code, url, ua.split()[0])
        await asyncio.sleep(1)
        resp = await client.get(url, headers={"User-Agent": ua})
    return resp


async def fetch(url: str) -> bytes:
    async with SEMAPHORE:
        client = await _get_client()
        try:
            resp = await _get(client, url)
        except httpx.TimeoutException:
            raise ValueError("Tovuti haikujibu kwa wakati.")
        except httpx.RequestError as e:
            raise ValueError(f"Siwezi kufikia link ({type(e).__name__}).")

    if resp.status_code >= 400:
        raise ValueError(HTTP_ERRORS.get(resp.status_code, f"Tovuti imejibu kwa kosa {resp.status_code}."))

    ctype = resp.headers.get("content-type", "").lower()
    if ctype and "html" not in ctype and "xml" not in ctype:
        raise ValueError("Link hii si ukurasa wa tovuti (si HTML).")
    if len(resp.content) > MAX_PAGE_BYTES:
        raise ValueError("Ukurasa ni mkubwa kupita kiasi.")
    return resp.content


def get_title(soup: BeautifulSoup, rules: dict) -> str:
    for sel in rules["title"]:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            return _tidy_title(el.get_text(" ", strip=True))

    og = soup.find("meta", property="og:title")
    if og and og.get("content", "").strip():
        return _tidy_title(og["content"])

    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return _tidy_title(h1.get_text(" ", strip=True))

    if soup.title and soup.title.get_text(strip=True):
        return _tidy_title(soup.title.get_text(" ", strip=True))

    return "Habari"


def _tidy_title(title: str) -> str:
    return " ".join(title.split("|")[0].split()) or "Habari"


def find_content(soup: BeautifulSoup, selectors: list[str]):
    """Selector ya kwanza yenye maandishi ya kutosha; la sivyo kubwa kuliko zote."""
    best, best_len = None, 0
    for sel in selectors:
        try:
            found = soup.select(sel)[:3]
        except Exception:
            logger.warning("Selector batili: %s", sel)
            continue
        for el in found:
            n = len(el.get_text(" ", strip=True))
            if n >= MIN_ROOT_CHARS:
                return el
            if n > best_len:
                best, best_len = el, n
    return best or soup.body or soup


def prune(root, selectors: list[str]) -> None:
    for sel in selectors:
        try:
            for el in root.select(sel):
                if el is not root and not el.decomposed:
                    el.decompose()
        except Exception:
            logger.warning("Selector ya kufuta batili: %s", sel)


async def extract(url: str, images: bool = True) -> tuple[str, list[str]]:
    url = clean_url(url)
    content = await fetch(url)
    soup = BeautifulSoup(content, "html.parser")

    rules = get_rules(url, soup)
    title = get_title(soup, rules)

    root = find_content(soup, rules["content"])
    prune(root, rules["remove"])

    blocks = Cleaner(
        base_url=url,
        title=title,
        images=images and rules["images"],
        stop_at=rules["stop_at"],
        drop_text=rules["drop_text"],
    ).run(root)

    if not blocks:
        raise ValueError("Sikupata maudhui ya kusoma kwenye link hiyo.")
    return title, blocks
