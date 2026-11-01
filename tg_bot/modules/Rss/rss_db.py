"""Rss/rss_db.py - Uhifadhi wa RSS kwenye MongoDB (usajili haupotei kwenye redeploy).

Collection moja: rss_feeds
  { _id: "chat_id|url", chat_id: int, url: str, ids: [..] | None, created: float }
  ids = None  -> feed mpya bado haijawekewa baseline.
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
_col = _client[os.getenv("MONGO_DB", "entoswahili")]["rss_feeds"]
_ready = False


def make_key(chat_id, url: str) -> str:
    return f"{chat_id}|{url}"


async def init() -> None:
    """Tengeneza index na hamisha data ya JSON ya zamani (mara moja tu)."""
    global _ready
    if _ready:
        return
    await _col.create_index("chat_id")
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


async def all_feeds() -> list:
    await init()
    return await _col.find({}, {"chat_id": 1, "url": 1}).to_list(None)


async def get_ids(chat_id: int, url: str):
    """Rudisha (exists, ids). ids=None maana baseline haijawekwa."""
    await init()
    doc = await _col.find_one({"_id": make_key(chat_id, url)}, {"ids": 1})
    if doc is None:
        return False, None
    return True, doc.get("ids")


async def set_ids(chat_id: int, url: str, ids: list) -> None:
    """Haifanyi chochote kama feed imeshafutwa (haifufui usajili)."""
    await _col.update_one({"_id": make_key(chat_id, url)}, {"$set": {"ids": ids}})
