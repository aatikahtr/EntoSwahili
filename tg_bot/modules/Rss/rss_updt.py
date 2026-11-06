"""Rss/rss_updt.py - Hukagua RSS feeds kila baada ya muda na kutuma updates mpya.

Maboresho:
  #2 Hakuna post inayopotea kimya (zinahifadhiwa zilizotumwa tu; zilizobaki zinaendelea mzunguko ujao)
  #4 Mpangilio wa entries unategemea tarehe (si nafasi kwenye feed)
  #5 ids zinahifadhiwa baada ya KILA send + lease kuzuia instance mbili
  #6 ETag/Last-Modified (304), backoff ya feeds zinazoshindwa, taarifa kwa watumiaji
  #7 ids ni hash fupi, na hakuna kuandika upya kila mzunguko
  #8 SSRF: IP iliyokaguliwa ndiyo inayounganishwa (DNS rebinding haiwezekani)
"""
import asyncio
import calendar
import hashlib
import html
import ipaddress
import logging
import socket
import time
from collections import Counter
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import ContextTypes

from . import rss_db as db

log = logging.getLogger(__name__)

INTERVAL = 300            # sekunde (dakika 5)
MAX_PER_CYCLE = 10        # posts za kutuma kwa kila feed kwa mzunguko mmoja (zilizobaki zinaenda mzunguko ujao)
MAX_ENTRIES = 50          # feeds kubwa (mamia ya posts): tunatazama entries 50 za juu tu
MAX_BACKLOG = 50          # zaidi ya hapa: za zamani zinarukwa kwa makusudi na mtumiaji anaarifiwa
MAX_SEEN = 3000           # tokens za mwisho zinazohifadhiwa kwa kila feed
MAX_BYTES = 10_000_000    # kikomo cha ukubwa wa feed (feeds za WordPress zenye maudhui kamili ni kubwa)
RETRY_DELAY = 3           # sekunde kabla ya kujaribu tena kosa la muda (timeout, 5xx, feed iliyokatika)
MAX_REDIRECTS = 3
CONCURRENCY = 10          # feeds zinazopakuliwa kwa wakati mmoja
MAX_TEXT = 4000           # Telegram: 4096
MAX_HTML_LINK = 1500
LEASE = 240               # sekunde: muda wa lock ya feed moja
BACKOFF_CAP = 72          # x INTERVAL = masaa 6 ndiyo kikomo cha kusubiri
SLACK = 30                # sekunde: uvumilivu wa muda wa mzunguko
WARN_AFTER_DAYS = 3       # feed ikishindwa siku hizi mfululizo -> mtumiaji anaarifiwa (mara moja)
AUTO_REMOVE_DAYS = None   # weka namba (mf. 14) kuondoa feed otomatiki; None = usiondoe
CLEANUP_EVERY = 12        # kila mizunguko hii, futa hali za URL zisizotumika

HEADERS = {  # tovuti nyingi (Cloudflare/Wordfence) huzuia UA ya bot; tumia ya kivinjari
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
    "Accept-Language": "en-US,en;q=0.8,sw;q=0.6",
}
# Muunganisho haurudiwi: tunaunganisha kwa IP + SNI maalum, kwa hiyo pool isishiriki connections
TIMEOUT = httpx.Timeout(30.0, connect=10.0)  # feeds nzito huchelewa kutoka
LIMITS = httpx.Limits(max_keepalive_connections=0, max_connections=50)

ERRORS: dict = {}  # url -> sababu ya kushindwa mara ya mwisho (kwa /rs test na /rs add)
ERRORS_MAX = 500
NOT_MODIFIED = object()
_cycle = 0


# ---------- Keys na tokens ----------
def entry_id(entry) -> str:
    """Imebaki kwa ajili ya rss_cmd.py (utangamano na msimbo wa zamani)."""
    return entry.get("id") or entry.get("link") or ""


def entry_keys(entry, dup_links: set) -> list:
    """Vitambulisho vyote vya entry: id, link (kama ni ya kipekee kwenye feed),
    au hash ya title+published kama fallback."""
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


def token(key: str) -> str:
    """Kitambulisho kifupi (16 hex) badala ya URL kamili. Kiambishi '~' kinatofautisha na rekodi za zamani."""
    return "~" + hashlib.sha1(key.encode("utf-8", "ignore")).hexdigest()[:16]


def _as_token(k: str) -> str:
    return k if k.startswith("~") else token(k)


# ---------- Mpangilio wa entries ----------
def _stamp(e):
    t = e.get("published_parsed") or e.get("updated_parsed")
    try:
        return calendar.timegm(t) if t else None
    except (TypeError, ValueError, OverflowError):
        return None


def _newest_first(entries) -> bool:
    """Feed nyingi huorodhesha mpya kwanza. Tunagundua kinyume (oldest-first) kwa tarehe zilizopo."""
    dated = [s for s in map(_stamp, entries) if s is not None]
    return not (len(dated) >= 2 and dated[0] < dated[-1])


def sort_entries(entries, newest_first: bool | None = None) -> list:
    """Rudisha entries za zamani kwanza -> mpya mwisho.
    Tarehe zikiwepo kwa zote: zinapangwa kwa tarehe. Vinginevyo tunategemea mwelekeo wa feed."""
    es = list(entries)
    if newest_first is None:
        newest_first = _newest_first(es)
    if newest_first:
        es.reverse()  # feed ilikuwa mpya-kwanza -> sasa za zamani kwanza
    stamps = [_stamp(e) for e in es]
    if es and all(s is not None for s in stamps):
        es = [e for _, e in sorted(zip(stamps, es), key=lambda p: p[0])]  # stable
    return es


def prepare(feed) -> list:
    """Orodha ya (entry, [tokens]) kwa mpangilio wa muda (za zamani kwanza).
    Feed kubwa (mfano posts 500): tunachukua MAX_ENTRIES za 'mpya' tu (kwa nafasi kwenye feed,
    kwa sababu tarehe zinaweza kuwa zimechanganyika kwa posts zilizopangwa), ili baseline na
    ulinganisho viwe vidogo na thabiti."""
    es = list(feed.entries)
    nf = _newest_first(es)
    if len(es) > MAX_ENTRIES:
        es = es[:MAX_ENTRIES] if nf else es[-MAX_ENTRIES:]
    entries = sort_entries(es, nf)
    counts = Counter(e.get("link") for e in entries if e.get("link"))
    dup_links = {l for l, n in counts.items() if n > 1}
    out = []
    for e in entries:
        keys = entry_keys(e, dup_links)
        if keys:
            out.append((e, [token(k) for k in keys]))
    return out


def _all_tokens(items: list) -> list:
    toks = list(dict.fromkeys(t for _, ts in items for t in ts))
    return toks[-MAX_SEEN:]


def feed_keys(feed) -> list:
    """Tokens zote za feed (zinatumika na /rs add ili baseline ilingane na job)."""
    return _all_tokens(prepare(feed))


# ---------- Usalama: IP iliyokaguliwa ndiyo inayotumika ----------
def _ip_ok(ip) -> bool:
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global


async def _resolve(url: str):
    """Rudisha (hali, ips): ("ok", [ip..]) | ("unsafe", None) | ("dns", None).
    unsafe = link mbovu/ya ndani (kataa daima); dns = DNS imeshindwa (huenda ni ya muda)."""
    try:
        p = urlparse(url)
        host, port = p.hostname, p.port
    except ValueError:
        return "unsafe", None
    if p.scheme not in ("http", "https") or not host or p.username or p.password:
        return "unsafe", None
    port = port or (443 if p.scheme == "https" else 80)
    try:
        infos = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM), 5
        )
    except (socket.gaierror, asyncio.TimeoutError, UnicodeError, OSError):
        return "dns", None
    ips = []
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            return "unsafe", None
        if not _ip_ok(ip):
            return "unsafe", None  # hata IP moja ya ndani = kataa yote
        if ip not in ips:
            ips.append(ip)
    ips.sort(key=lambda i: i.version)  # IPv4 kwanza
    return ("ok", [str(i) for i in ips]) if ips else ("dns", None)


async def _resolve_public(url: str):
    """Rudisha orodha ya IP salama (IPv4 kwanza), au None."""
    status, ips = await _resolve(url)
    return ips if status == "ok" else None


async def url_status(url: str) -> str:
    """'ok' | 'unsafe' | 'dns' - kwa /rs add kutofautisha link mbovu na tatizo la muda."""
    return (await _resolve(url))[0]


async def is_safe_url(url: str) -> bool:
    """Kubali http/https tu, na zuia localhost/IP za ndani (SSRF)."""
    return bool(await _resolve_public(url))


def _pin(url: str, ip: str) -> str:
    p = urlparse(url)
    host = f"[{ip}]" if ":" in ip else ip
    return p._replace(netloc=f"{host}:{p.port}" if p.port else host).geturl()


async def _request(client: httpx.AsyncClient, url: str, ip: str, etag, modified):
    """Ombi moja kwa IP maalum (Host + SNI zinabaki za tovuti halisi, cheti kinakaguliwa kawaida).
    Rudisha (aina, data, headers)."""
    p = urlparse(url)
    h = p.hostname
    hostport = f"[{h}]" if ":" in h else h
    if p.port:
        hostport += f":{p.port}"
    hdrs = {"Host": hostport}
    if etag:
        hdrs["If-None-Match"] = etag
    if modified:
        hdrs["If-Modified-Since"] = modified
    ext = {"sni_hostname": h} if h != ip else {}

    async with client.stream("GET", _pin(url, ip), headers=hdrs, extensions=ext) as r:
        if r.status_code == 304:
            return "notmodified", None, None
        if r.is_redirect:
            return "redirect", r.headers.get("location"), None
        if r.status_code >= 400:
            return "http", r.status_code, None
        buf = bytearray()
        async for chunk in r.aiter_bytes():
            buf += chunk
            if len(buf) > MAX_BYTES:
                return "toobig", None, None
        return "ok", bytes(buf), r.headers


def _looks_complete(data: bytes) -> bool:
    """XML iliyokatika nusu (PHP/seva imekata jibu) inaweza kuparse vizuri kwa entries chache tu.
    Baseline ya namna hiyo ndiyo inayosababisha mamia ya posts 'mpya' baadaye. Kataa feed isiyo na tag ya mwisho."""
    tail = data[-1500:].lower()
    return any(t in tail for t in (b"</rss>", b"</feed>", b"</rdf:rdf>"))


_TRANSIENT = (
    "imeshindwa kuunganisha", "feed imekatika", "HTTP 5", "HTTP 429",
    "ReadTimeout", "ConnectTimeout", "WriteTimeout", "PoolTimeout",
    "ReadError", "RemoteProtocolError", "ConnectError", "TimeoutException",
)


async def _fetch(client: httpx.AsyncClient, url: str, etag=None, modified=None):
    """Kama _fetch_once, lakini inajaribu tena mara moja kwa makosa ya muda (timeout, 5xx, feed iliyokatika)."""
    res = await _fetch_once(client, url, etag, modified)
    if res is None and str(ERRORS.get(url, "")).startswith(_TRANSIENT):
        await asyncio.sleep(RETRY_DELAY)
        res = await _fetch_once(client, url, etag, modified)
    return res


async def _fetch_once(client: httpx.AsyncClient, url: str, etag=None, modified=None):
    """Rudisha: feed | NOT_MODIFIED | None (imeshindwa; sababu iko kwenye ERRORS)."""
    orig = url

    def fail(reason: str):
        if len(ERRORS) >= ERRORS_MAX and orig not in ERRORS:
            ERRORS.pop(next(iter(ERRORS)), None)
        ERRORS[orig] = reason
        log.warning("Fetch imeshindwa %s: %s", orig, reason)
        return None

    try:
        for _ in range(MAX_REDIRECTS + 1):
            ips = await _resolve_public(url)
            if not ips:
                return fail("link si salama / DNS imeshindwa")
            res = None
            for ip in ips[:3]:
                try:
                    res = await _request(client, url, ip, etag, modified)
                    break
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    continue
            if res is None:
                return fail("imeshindwa kuunganisha na seva")

            kind, data, headers = res
            if kind == "notmodified":
                ERRORS.pop(orig, None)
                return NOT_MODIFIED
            if kind == "redirect":
                if not data:
                    return fail("redirect bila location")
                url = urljoin(url, data)  # inakaguliwa tena mwanzoni mwa mzunguko
                continue
            if kind == "http":
                return fail(f"HTTP {data} (seva imekataa bot)")
            if kind == "toobig":
                return fail(f"feed kubwa mno (>{MAX_BYTES // 1_000_000}MB)")

            if not _looks_complete(data):
                return fail("feed imekatika nusu (seva imekata jibu kabla ya mwisho)")
            feed = await asyncio.to_thread(feedparser.parse, data)
            if not feed.entries:
                why = type(feed.get("bozo_exception", "")).__name__ if feed.get("bozo") else "hakuna entries"
                return fail(f"si RSS/Atom sahihi ({why})")
            feed["http_etag"] = headers.get("etag")
            feed["http_modified"] = headers.get("last-modified")
            ERRORS.pop(orig, None)
            return feed
        return fail("redirects nyingi mno")
    except Exception as e:
        return fail(f"{type(e).__name__}: {e}")


async def fetch_feed(url: str, client: httpx.AsyncClient | None = None):
    """Inafanya kazi kama ya zamani: fetch_feed(url). Client ni hiari. Haitumii ETag."""
    if client is not None:
        return await _fetch(client, url)
    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=False, headers=HEADERS, limits=LIMITS
    ) as c:
        return await _fetch(c, url)


# ---------- Kutuma ----------
# Makosa ya Telegram (BadRequest) yanagawanywa kwa maana yake:
_GONE = ("chat not found", "peer_id_invalid", "channel_private", "group chat was deleted")
_CHAT_PROBLEM = (  # tatizo la chat, si la post -> usiweke "seen", jaribu tena baadaye
    "not enough rights", "have no rights", "write_forbidden", "need administrator rights",
    "topic_closed", "topic_deleted", "chat_restricted",
)


async def _send(bot, chat_id: int, text: str, as_html: bool = False, preview: bool = True) -> str:
    """Rudisha: 'ok' | 'skip' (tatizo la post hii tu) | 'stop' (chat haipatikani) | 'retry'."""
    if not as_html:
        text = text[:MAX_TEXT]  # HTML haikatwi (ingeharibu tags); format_entry inahakikisha ukubwa
    for attempt in range(2):
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML if as_html else None,
                disable_web_page_preview=None if preview else True,
            )
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
            m = str(e).lower()
            log.warning("Chat %s: %s", chat_id, e)
            if any(s in m for s in _GONE):
                return "stop"
            if any(s in m for s in _CHAT_PROBLEM):
                return "retry"
            return "skip"
        except Exception as e:
            log.warning("Kutuma kumeshindwa %s: %s", chat_id, e)
            return "retry"
    return "retry"


def _render(e, latest: bool = False, hidden: bool = False, plain: bool = False):
    """Rudisha (text, as_html).
    show   : kichwa + link wazi (mstari unaofuata)
    hidden : kichwa kinakuwa link (url imefichwa nyuma ya kichwa), HTML"""
    title = (e.get("title") or "").strip()
    link = (e.get("link") or "").strip()
    prefix = "🆕 Latest post\n" if latest else ""
    if hidden and link and not plain and len(link) <= MAX_HTML_LINK:
        head = html.escape(title[:300] or link)
        text = prefix + f'<a href="{html.escape(link, quote=True)}">{head}</a>'
        if len(text) <= MAX_TEXT:
            return text, True
    return prefix + f"{title}\n{link}", False


def format_entry(e, latest: bool = False, hidden: bool = False) -> str:
    """Utangamano na msimbo wa zamani."""
    return _render(e, latest, hidden)[0]


async def _deliver(bot, chat_id: int, e, hidden: bool, latest: bool = False) -> str:
    text, as_html = _render(e, latest, hidden)
    res = await _send(bot, chat_id, text, as_html)
    if res == "skip" and as_html:  # HTML imekataliwa -> jaribu maandishi ya kawaida
        text, _ = _render(e, latest, hidden, plain=True)
        res = await _send(bot, chat_id, text, False)
    if res == "skip":
        log.warning("Entry imerukwa (Telegram imekataa): chat=%s link=%s", chat_id, e.get("link"))
    return res


# ---------- Kuchakata feed moja kwa chat moja ----------
async def _process(bot, chat_id: int, url: str, items: list) -> None:
    if not await db.acquire(chat_id, url, LEASE):  # imefutwa au instance nyingine inaichakata
        return
    try:
        await _process_locked(bot, chat_id, url, items)
    finally:
        await db.release(chat_id, url)


async def _drop(chat_id: int, url: str) -> None:
    await db.remove_feed(chat_id, url)
    log.info("Feed imeondolewa (chat imefungwa): %s|%s", chat_id, url)


async def _process_locked(bot, chat_id: int, url: str, items: list) -> None:
    doc = await db.get_feed(chat_id, url)
    if doc is None or not items:
        return
    old = doc.get("ids")
    hidden = (await db.get_view(chat_id)) == "hidden"

    # --- Hakuna baseline: tuma post ya hivi karibuni, kisha hifadhi ---
    if old is None:
        res = await _deliver(bot, chat_id, items[-1][0], hidden, latest=True)
        if res == "stop":
            return await _drop(chat_id, url)
        if res == "retry":  # usihifadhi baseline, jaribu tena mzunguko ujao
            return
        await db.set_ids(chat_id, url, _all_tokens(items))
        log.info("Baseline imehifadhiwa: %s|%s", chat_id, url)
        return

    # --- Rekodi za zamani (URL kamili) -> tokens, mara moja tu ---
    if any(not x.startswith("~") for x in old):
        old = list(dict.fromkeys(_as_token(x) for x in reversed(old)))[-MAX_SEEN:]
        await db.set_ids(chat_id, url, old)
        log.info("ids zimebadilishwa kuwa tokens: %s|%s", chat_id, url)
    old_set = set(old)

    fresh = [it for it in items if not any(t in old_set for t in it[1])]  # za zamani kwanza
    if not fresh:
        if doc.get("pending"):
            await db.set_pending(chat_id, url, False)
        return

    # --- Zimezidi sana: ruka za zamani KWA MAKUSUDI na umjulishe mtumiaji ---
    note = None
    if len(fresh) > MAX_BACKLOG:
        dropped, fresh = fresh[:-MAX_BACKLOG], fresh[-MAX_BACKLOG:]
        await db.push_ids(chat_id, url, [t for _, ts in dropped for t in ts], MAX_SEEN)
        note = f"ℹ️ Posts {len(dropped)} za zamani zimerukwa (zilikuwa nyingi mno kwa mara moja):\n{url}"

    batch = fresh[:MAX_PER_CYCLE]
    rest = len(fresh) - len(batch)  # zitatumwa mzunguko ujao (hazijawekwa "seen")
    incomplete = False

    for e, toks in batch:
        res = await _deliver(bot, chat_id, e, hidden)
        if res == "stop":  # bot amezuiwa/ametolewa -> futa usajili wa feed hii
            return await _drop(chat_id, url)
        if res == "retry":  # hii na zinazofuata zinabaki bila "seen"
            incomplete = True
            break
        await db.push_ids(chat_id, url, toks, MAX_SEEN)  # hifadhi mara moja baada ya kutuma
        await asyncio.sleep(1)  # epuka flood limit

    if note:
        await _send(bot, chat_id, note, preview=False)

    pending = incomplete or rest > 0
    if pending != bool(doc.get("pending")):
        await db.set_pending(chat_id, url, pending)


# ---------- Hali ya URL: mafanikio / kushindwa ----------
async def _ok(url: str, st: dict, etag, modified) -> None:
    """Hifadhi validators na futa hali ya kushindwa. Haiandiki kama hakuna kilichobadilika."""
    if not (st.get("fails") or st.get("etag") != etag or st.get("modified") != modified):
        return
    await db.put_url_state(
        url,
        set_={"etag": etag, "modified": modified, "fails": 0, "last_ok": time.time()},
        unset=["first_fail", "next_check", "last_error", "notified", "notified_chats"],
    )


async def _on_failure(bot, url: str, docs: list, st: dict, now: float) -> None:
    fails = int(st.get("fails", 0)) + 1
    first = st.get("first_fail") or now
    delay = INTERVAL * min(2 ** min(fails - 1, 20), BACKOFF_CAP)  # 5m,10m,20m,... hadi masaa 6
    reason = ERRORS.get(url, "haijulikani")
    days = (now - first) / 86400
    fields = {"fails": fails, "first_fail": first, "next_check": now + delay, "last_error": reason}

    if AUTO_REMOVE_DAYS and days >= AUTO_REMOVE_DAYS:
        for d in docs:
            await db.remove_feed(d["chat_id"], url)
            await _send(
                bot, d["chat_id"],
                f"🗑️ Feed imeondolewa (haipatikani kwa siku {int(days)}):\n{url}\nSababu: {reason}",
                preview=False,
            )
        await db.drop_url_state(url)
        return

    # Taarifa kwa kila chat, siku 3 baada ya feed kuanza kushindwa AU kuongezwa (kipi cha baadaye)
    notified = set(st.get("notified_chats", []))
    changed = False
    for d in docs:
        if d["chat_id"] in notified:
            continue
        since = max(first, d.get("created") or first)
        d_days = (now - since) / 86400
        if d_days < WARN_AFTER_DAYS:
            continue
        res = await _send(
            bot, d["chat_id"],
            f"⚠️ Link hii haifanyi kazi kwa siku {int(d_days)} sasa:\n{url}\n"
            f"Sababu: {reason}\n"
            f"Unaweza kuifuta kwa /rmv. Bot itaendelea kujaribu kwa vipindi virefu.",
            preview=False,
        )
        if res == "stop":
            await db.remove_feed(d["chat_id"], url)
        notified.add(d["chat_id"])
        changed = True
    if changed:
        fields["notified_chats"] = list(notified)

    await db.put_url_state(url, set_=fields)


# ---------- Job ----------
async def rss_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    global _cycle
    _cycle += 1
    try:
        feeds = await db.all_feeds()
        by_url: dict[str, list] = {}
        for d in feeds:
            by_url.setdefault(d["url"], []).append(d)
        states = await db.get_url_states(list(by_url))
    except Exception:
        log.exception("MongoDB: kusoma feeds kumeshindwa")
        return

    now = time.time()
    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=False, headers=HEADERS, limits=LIMITS
    ) as client:

        async def run(url: str, docs: list) -> None:
            try:
                st = states.get(url) or {}
                if st.get("next_check", 0) > now + SLACK:  # backoff: bado haijafika wakati
                    return
                # Kama kuna chat yenye posts zilizobaki, tunahitaji maudhui kamili (si 304)
                backlog = any(d.get("pending") for d in docs)
                etag = None if backlog else st.get("etag")
                modified = None if backlog else st.get("modified")

                async with sem:
                    feed = await _fetch(client, url, etag, modified)

                if feed is NOT_MODIFIED:  # hakuna mabadiliko -> hakuna kazi
                    if st.get("fails"):
                        await _ok(url, st, st.get("etag"), st.get("modified"))
                    return
                if feed is None:
                    await _on_failure(context.bot, url, docs, st, now)
                    return

                await _ok(url, st, feed.get("http_etag"), feed.get("http_modified"))
                items = prepare(feed)
                if not items:
                    return
                for d in docs:
                    try:
                        await _process(context.bot, d["chat_id"], url, items)
                    except Exception:
                        log.exception("rss_job kosa: %s|%s", d["chat_id"], url)
            except Exception:
                log.exception("rss_job kosa (url): %s", url)

        await asyncio.gather(*(run(u, d) for u, d in by_url.items()))

    if _cycle % CLEANUP_EVERY == 0:
        try:
            await db.clean_url_states(list(by_url))
        except Exception:
            log.exception("clean_url_states imeshindwa")


def start_rss_job(app) -> None:
    """Iite mara moja kwenye main baada ya kutengeneza app."""
    app.job_queue.run_repeating(
        rss_job, interval=INTERVAL, first=10,
        job_kwargs={"max_instances": 1, "coalesce": True},  # zuia mizunguko kuingiliana
    )
