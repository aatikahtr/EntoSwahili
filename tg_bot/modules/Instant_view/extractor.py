"""
extractor.py — kuchukua ukurasa, kutafuta makala, kuisafisha.

    title, blocks = await extract(url, images=True)

Hatua: fetch → title → tafuta content (selectors za site) → futa uchafu → Cleaner.
"""

import re
import json
import asyncio
import logging
from html import escape
from urllib.parse import urljoin
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import httpx
from bs4 import BeautifulSoup

from .cleaner import Cleaner
from .sites import get_rules

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


# Kiwango cha maneno
GOOD_WORDS = 120   # makala yenye maneno haya au zaidi ni nzuri — acha kutafuta
MIN_WORDS = 80     # chini ya haya → jaribu njia za akiba (JSON-LD, AMP, ukurasa mzima)
MIN_CANDIDATE_CHARS = 100
MAX_CANDIDATES = 6
GUARD_RATIO = 0.4  # selector ya kufuta isifute kipande chenye > 40% ya maandishi ya makala


def _words(blocks: list[str]) -> int:
    return sum(
        len(re.sub(r"<[^>]+>", " ", b).split())
        for b in blocks
        if not b.startswith("<img")
    )


def find_candidates(soup: BeautifulSoup, selectors: list[str]) -> list:
    """Vyombo vya makala kwa mpangilio wa kipaumbele (bila kurudia)."""
    found, seen = [], set()
    for sel in selectors:
        try:
            matches = soup.select(sel)[:3]
        except Exception:
            logger.warning("Selector batili: %s", sel)
            continue
        for el in matches:
            if id(el) in seen:
                continue
            if len(el.get_text(" ", strip=True)) >= MIN_CANDIDATE_CHARS:
                seen.add(id(el))
                found.append(el)
        if len(found) >= MAX_CANDIDATES:
            break
    return found


def prune(root, selectors: list[str]) -> None:
    """Futa uchafu ndani ya root. Kipande chenye sehemu kubwa ya makala hakifutwi
    (selector pana kama [class*='share-'] isifute makala nzima kimakosa)."""
    root_len = len(root.get_text(" ", strip=True))
    for sel in selectors:
        try:
            for el in root.select(sel):
                if el is root or el.decomposed:
                    continue
                if root_len > 500 and len(el.get_text(" ", strip=True)) > GUARD_RATIO * root_len:
                    continue
                el.decompose()
        except Exception:
            logger.warning("Selector ya kufuta batili: %s", sel)


def _clean(root, url: str, title: str, images: bool, rules: dict, lead: str | None = None) -> list[str]:
    return Cleaner(
        base_url=url,
        title=title,
        images=images and rules["images"],
        stop_at=rules["stop_at"],
        drop_text=rules["drop_text"],
        lead_image=lead,
    ).run(root)


def best_blocks(soup, url: str, title: str, images: bool, rules: dict, lead: str | None = None) -> list[str]:
    """Jaribu vyombo kwa mpangilio; kipaumbele kwa cha kwanza, lakini kikiwa na maneno
    machache chukua kinachofuata kikiwa na angalau mara 2 ya maneno."""
    best: list[str] = []
    best_w = 0
    for i, root in enumerate(find_candidates(soup, rules["content"])):
        prune(root, rules["remove"])
        blocks = _clean(root, url, title, images, rules, lead)
        w = _words(blocks)
        if i == 0 or w >= 2 * best_w:
            best, best_w = blocks, w
        if best_w >= GOOD_WORDS:
            break
    return best


# ── Njia za akiba ──────────────────────────────────────────────
def _find_key(data, key: str):
    """Tafuta thamani ya key (mf. articleBody) ndani ya JSON-LD yoyote (nested/list/@graph)."""
    if isinstance(data, dict):
        if isinstance(data.get(key), str) and data[key].strip():
            return data[key]
        for v in data.values():
            r = _find_key(v, key)
            if r:
                return r
    elif isinstance(data, list):
        for v in data:
            r = _find_key(v, key)
            if r:
                return r
    return None


def jsonld_blocks(soup: BeautifulSoup) -> list[str]:
    """Tovuti nyingi huweka makala kamili ndani ya <script type="application/ld+json"> (articleBody)."""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except Exception:
            continue
        body = _find_key(data, "articleBody")
        if body:
            body = re.sub(r"<br\s*/?>|</p>", "\n", body, flags=re.I)
            body = re.sub(r"<[^>]+>", "", body)
            paras = [" ".join(p.split()) for p in re.split(r"\n+", body)]
            return [f"<p>{escape(p, quote=False)}</p>" for p in paras if p]
    return []


def _as_url(value) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        return _as_url(value.get("url") or value.get("contentUrl"))
    if isinstance(value, list):
        for v in value:
            r = _as_url(v)
            if r:
                return r
    return None


def _ld_image(data) -> str | None:
    if isinstance(data, dict):
        r = _as_url(data.get("image")) or _as_url(data.get("thumbnailUrl"))
        if r:
            return r
        for v in data.values():
            r = _ld_image(v)
            if r:
                return r
    elif isinstance(data, list):
        for v in data:
            r = _ld_image(v)
            if r:
                return r
    return None


def lead_image(soup: BeautifulSoup, url: str, rules: dict) -> str | None:
    """Picha kuu ya makala (mara nyingi iko nje ya mwili wa makala): og:image → twitter:image → JSON-LD."""
    if not rules.get("lead_image", True):
        return None
    for attrs in (
        {"property": "og:image"}, {"property": "og:image:secure_url"},
        {"name": "twitter:image"}, {"property": "twitter:image"}, {"name": "twitter:image:src"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content", "").strip():
            return urljoin(url, tag["content"].strip())
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            found = _ld_image(json.loads(tag.string or tag.get_text() or ""))
        except Exception:
            continue
        if found:
            return urljoin(url, found)
    link = soup.find("link", rel="image_src")
    if link and link.get("href"):
        return urljoin(url, link["href"])
    return None


def amp_url(soup: BeautifulSoup, url: str) -> str | None:
    link = soup.find("link", rel="amphtml")
    if link and link.get("href"):
        amp = urljoin(url, link["href"])
        if amp != url:
            return amp
    return None


async def extract(url: str, images: bool = True) -> tuple[str, list[str]]:
    url = clean_url(url)
    soup = BeautifulSoup(await fetch(url), "html.parser")

    rules = get_rules(url, soup)
    title = get_title(soup, rules)

    # amp link na JSON-LD zinasomwa KABLA ya kufuta chochote kwenye soup
    amp = amp_url(soup, url)
    ld_blocks = jsonld_blocks(soup)
    use_images = images and rules["images"]
    lead = lead_image(soup, url, rules) if use_images else None
    if lead and any(w in lead.lower() for w in ("logo", "favicon", "placeholder")):
        lead = None  # picha ya tovuti nzima, si ya makala

    blocks = best_blocks(soup, url, title, images, rules, lead)
    words = _words(blocks)

    # 1) JSON-LD articleBody
    if words < MIN_WORDS and ld_blocks:
        w = _words(ld_blocks)
        if w >= max(MIN_WORDS, 1.5 * words):
            blocks, words = ([f'<img src="{escape(lead)}"/>'] if lead else []) + ld_blocks, w

    # 2) Toleo la AMP (mara nyingi lina maudhui kamili bila JavaScript)
    if words < MIN_WORDS and amp:
        try:
            amp_soup = BeautifulSoup(await fetch(amp), "html.parser")
            amp_blocks = best_blocks(amp_soup, amp, title, images, rules, lead)
            w = _words(amp_blocks)
            if w >= 1.5 * words:
                blocks, words = amp_blocks, w
        except Exception as e:
            logger.info("AMP fallback imeshindwa (%s): %s", amp, e)

    # 3) Ukurasa mzima (body) — kama ni mkubwa kwa angalau mara 2
    if words < MIN_WORDS and soup.body is not None:
        prune(soup.body, rules["remove"])
        body_blocks = _clean(soup.body, url, title, images, rules, lead)
        w = _words(body_blocks)
        if w >= 2 * words:
            blocks, words = body_blocks, w

    if not blocks:
        raise ValueError("Sikupata maudhui ya kusoma kwenye link hiyo.")
    return title, blocks
