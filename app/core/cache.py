import json
import logging
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_client: aioredis.Redis | None = None

ACCOUNT_TTL = 1800              # 30 minutes
CHARGES_TTL = 1800              # 30 minutes
BOOK_DETAIL_TTL = 7 * 24 * 3600  # 7 days
BOOK_AVAILABILITY_TTL = 120     # 2 minutes


def account_key(roll_no: str) -> str:
    return f"account:{roll_no}"


def charges_key(roll_no: str) -> str:
    return f"charges:{roll_no}"


def borrowed_set_key(roll_no: str) -> str:
    return f"borrowed_books:{roll_no}"


def book_detail_key(biblio_id: int) -> str:
    return f"book:detail:{biblio_id}"


def book_availability_key(biblio_id: int) -> str:
    return f"books:availability:{biblio_id}"


async def init(url: str, enabled: bool = True) -> None:
    global _client
    if not enabled:
        logger.info("Redis caching disabled via CACHE_ENABLED=False")
        _client = None
        return
    try:
        _client = aioredis.from_url(url, decode_responses=True)
        await _client.ping()
        logger.info("Redis connected: %s", url)
    except Exception as e:
        logger.warning("Redis unavailable, caching disabled: %s", e)
        _client = None


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def get_json(key: str) -> dict | None:
    if _client is None:
        return None
    try:
        raw = await _client.get(key)
        return json.loads(raw) if raw else None
    except Exception as e:
        logger.warning("Redis get failed key=%s: %s", key, e)
        return None


async def set_json(key: str, value: Any, ttl: int) -> None:
    if _client is None:
        return
    try:
        await _client.setex(key, ttl, json.dumps(value))
    except Exception as e:
        logger.warning("Redis set failed key=%s: %s", key, e)


async def delete(*keys: str) -> None:
    if _client is None or not keys:
        return
    try:
        await _client.delete(*keys)
    except Exception as e:
        logger.warning("Redis delete failed keys=%s: %s", keys, e)


async def sadd_with_ttl(key: str, members: list[str], ttl: int) -> None:
    if _client is None or not members:
        return
    try:
        pipe = _client.pipeline()
        pipe.sadd(key, *members)
        pipe.expire(key, ttl)
        await pipe.execute()
    except Exception as e:
        logger.warning("Redis sadd failed key=%s: %s", key, e)


async def sismember(key: str, member: str) -> bool | None:
    """Returns True/False if the set key exists in Redis, None on cache miss (key absent)."""
    if _client is None:
        return None
    try:
        if not await _client.exists(key):
            return None
        return bool(await _client.sismember(key, member))
    except Exception as e:
        logger.warning("Redis sismember failed key=%s member=%s: %s", key, member, e)
        return None
