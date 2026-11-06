"""Rss/rss_db.py - Uhifadhi wa RSS kwenye MongoDB (usajili haupotei kwenye redeploy).

Collection 1: rss_feeds  (usajili wa kila chat)
  { _id: "chat_id|url", chat_id: int, url: str, created: float,
    ids: [token, ...] | None,   # token = "~" + sha1(key)[:16]  (rekodi za zamani za URL kamili zinabadilishwa zenyewe)
    pending: bool,              # kuna posts bado hazijatumwa (retry / zimezidi MAX_PER_CYCLE)
    lock_until: float }         # lease: instance moja tu inachakata feed hii kwa wakati mmoja
  ids = None -> feed mpya bado haijawekewa baseline.

Collection 2: rss_urls  (hali ya kila URL, inashirikiwa na chats zote zinazoitumia)
  { _id: url, etag, modified, fails, first_fail, next_check, last_error, notified_chats, last_ok }

Collection 3: rss_settings  (muundo wa post kwa kila chat)
"""
import json
import logging
import os
import time

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError

log = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise RuntimeError("MONGO_URI haijawekwa kwenye environment variables")

_client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=10000)
_db = _client[os.getenv("MONGO_DB", "entoswahili")]
_col = _db["rss_feeds"]
_urls = _db["rss_urls"]
_settings = _db["rss_settings"]
_ready = False
VIEW_MODES = ("show", "hidden")


def make_key(chat_id, url: str) -> str:
    return f"{int(chat_id)}|{url}"  # int() ili aina ya chat_id isiathiri key


async def init() -> None:
    """Tengeneza index na hamisha data ya JSON ya zamani (mara moja tu)."""
    global _ready
    if _ready:
        return
    await _col.create_index([("chat_id", 1), ("created", 1)])
    await _migrate_json()
    _ready = True


async def _migrate_json() -> None:
    base = os.getenv("RSS_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
    ff, sf = os.path.join(base, "rss_feeds.json"), os.path.join(base, "rss_seen.json")
    if not os.path.exists(ff):
        return
    try:
        with open(ff, encoding="utf-8") as f:
            feeds = json.load(f)
        seen = {}
        if os.path.exists(sf):
            with open(sf, encoding="utf-8") as f:
                seen = json.load(f)
        n = 0
        for chat_id, urls in feeds.items():
            for url in urls:
                key = make_key(chat_id, url)
                await _col.update_one(
                    {"_id": key},
                    {"$setOnInsert": {
                        "chat_id": int(chat_id), "url": url,
                        "ids": seen.get(key), "created": time.time(),
                    }},
                    upsert=True,
                )
                n += 1
        os.replace(ff, ff + ".migrated")
        if os.path.exists(sf):
            os.replace(sf, sf + ".migrated")
        log.info("Imehamisha feeds %d kutoka JSON kwenda MongoDB", n)
    except Exception:
        log.exception("Migration ya JSON imeshindwa")


# ---------- Usajili (rss_feeds) ----------
async def list_urls(chat_id: int) -> list:
    await init()
    cur = _col.find({"chat_id": chat_id}, {"url": 1}).sort("created", 1)
    return [d["url"] async for d in cur]


async def add_feed(chat_id: int, url: str, ids: list) -> bool:
    """False kama tayari ipo."""
    await init()
    try:
        await _col.insert_one({
            "_id": make_key(chat_id, url), "chat_id": chat_id,
            "url": url, "ids": ids, "created": time.time(),
        })
        return True
    except DuplicateKeyError:
        return False


async def remove_feed(chat_id: int, url: str) -> bool:
    await init()
    res = await _col.delete_one({"_id": make_key(chat_id, url)})
    return res.deleted_count > 0


async def remove_all(chat_id: int) -> int:
    """Futa feeds ZOTE za chat_id hii tu (chats nyingine haziguswi). Rudisha idadi."""
    await init()
    res = await _col.delete_many({"chat_id": int(chat_id)})
    return res.deleted_count


async def all_feeds() -> list:
    await init()
    return await _col.find({}, {"chat_id": 1, "url": 1, "pending": 1, "created": 1}).to_list(None)


async def get_feed(chat_id: int, url: str):
    """Rudisha doc (ids, pending) au None kama imefutwa."""
    await init()
    return await _col.find_one({"_id": make_key(chat_id, url)}, {"ids": 1, "pending": 1})


async def get_ids(chat_id: int, url: str):
    """Rudisha (exists, ids). ids=None maana baseline haijawekwa."""
    doc = await get_feed(chat_id, url)
    if doc is None:
        return False, None
    return True, doc.get("ids")


async def set_ids(chat_id: int, url: str, ids: list) -> None:
    """Badilisha ids zote (baseline / ubadilishaji wa rekodi za zamani).
    Haifanyi chochote kama feed imeshafutwa (haifufui usajili)."""
    await _col.update_one({"_id": make_key(chat_id, url)}, {"$set": {"ids": ids}})


async def push_ids(chat_id: int, url: str, tokens: list, limit: int) -> None:
    """Ongeza tokens mwishoni (atomic) na weka mipaka ya `limit` za mwisho tu.
    Inaitwa baada ya KILA post iliyotumwa, ili crash isisababishe duplicates."""
    if not tokens:
        return
    await _col.update_one(
        {"_id": make_key(chat_id, url)},
        {"$push": {"ids": {"$each": list(tokens), "$slice": -int(limit)}}},
    )


async def set_pending(chat_id: int, url: str, flag: bool) -> None:
    await _col.update_one({"_id": make_key(chat_id, url)}, {"$set": {"pending": bool(flag)}})


# ---------- Lease (kuzuia instance mbili kuchakata feed moja) ----------
async def acquire(chat_id: int, url: str, lease: float) -> bool:
    """True kama tumepata lock. False kama instance nyingine inaichakata au feed imefutwa."""
    now = time.time()
    res = await _col.update_one(
        {
            "_id": make_key(chat_id, url),
            "$or": [{"lock_until": {"$exists": False}}, {"lock_until": {"$lt": now}}],
        },
        {"$set": {"lock_until": now + lease}},
    )
    return res.modified_count == 1


async def release(chat_id: int, url: str) -> None:
    await _col.update_one({"_id": make_key(chat_id, url)}, {"$set": {"lock_until": 0}})


# ---------- Hali ya URL (rss_urls): ETag, backoff, makosa ----------
async def get_url_states(urls: list) -> dict:
    if not urls:
        return {}
    docs = await _urls.find({"_id": {"$in": list(urls)}}).to_list(None)
    return {d["_id"]: d for d in docs}


async def put_url_state(url: str, set_: dict | None = None, unset: list | None = None) -> None:
    upd = {}
    if set_:
        upd["$set"] = set_
    if unset:
        upd["$unset"] = {k: "" for k in unset}
    if upd:
        await _urls.update_one({"_id": url}, upd, upsert=True)


async def drop_url_state(url: str) -> None:
    await _urls.delete_one({"_id": url})


async def clean_url_states(active_urls: list) -> None:
    """Futa hali za URL ambazo hakuna chat inayozitumia tena."""
    await _urls.delete_many({"_id": {"$nin": list(active_urls)}})


# ---------- Muundo wa post ----------
async def get_view(chat_id: int) -> str:
    """Muundo wa post za chat hii: 'show' (kawaida) au 'hidden'."""
    doc = await _settings.find_one({"_id": int(chat_id)}, {"view": 1})
    view = (doc or {}).get("view", "show")
    return view if view in VIEW_MODES else "show"


async def set_view(chat_id: int, view: str) -> None:
    await _settings.update_one(
        {"_id": int(chat_id)}, {"$set": {"view": view}}, upsert=True
    )
