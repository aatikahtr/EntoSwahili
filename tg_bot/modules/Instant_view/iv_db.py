"""
iv_db.py — uhifadhi wa author (jina + link) za Instant View kwenye MongoDB.

Inatumia MONGO_URI na MONGO_DB zile zile za Rss/rss_db.py (database moja),
lakini collection yake mwenyewe:

    iv_authors:  { _id: user_id, name: str, url: str, updated: float }

`name` na `url` ni hiari — kimoja kikikosekana, kinachotumika ni cha kawaida
(kutoka kwa Telegram). Muunganisho unaundwa tu pale unapohitajika.
"""

import os
import time
import logging

from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)

_col = None


def _get_col():
    global _col
    if _col is None:
        uri = os.getenv("MONGO_URI")
        if not uri:
            raise RuntimeError("MONGO_URI haijawekwa kwenye environment variables")
        client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
        _col = client[os.getenv("MONGO_DB", "entoswahili")]["iv_authors"]
    return _col


async def get_author(owner_id: int) -> dict:
    """Rudisha {'name': ..., 'url': ...} — funguo zilizowekwa tu (au dict tupu)."""
    doc = await _get_col().find_one({"_id": int(owner_id)})
    if not doc:
        return {}
    return {k: doc[k] for k in ("name", "url") if doc.get(k)}


async def set_author(owner_id: int, name: str | None = None, url: str | None = None) -> None:
    fields = {"updated": time.time()}
    if name is not None:
        fields["name"] = name
    if url is not None:
        fields["url"] = url
    await _get_col().update_one({"_id": int(owner_id)}, {"$set": fields}, upsert=True)


async def reset_author(owner_id: int, name: bool = True, url: bool = True) -> bool:
    """Futa name na/au url. True kama kulikuwa na kitu cha kufuta."""
    col = _get_col()
    if name and url:
        return (await col.delete_one({"_id": int(owner_id)})).deleted_count > 0

    unset = {}
    if name:
        unset["name"] = ""
    if url:
        unset["url"] = ""
    res = await col.update_one({"_id": int(owner_id)}, {"$unset": unset})
    return res.modified_count > 0
