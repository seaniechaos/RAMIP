"""fetch: download RSS feeds listed in sources.yaml.

Pulls feeds in parallel, deduplicates items against seen_items.db, respects
ETag/Last-Modified caching, and writes results to fetched_items.json.
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import feedparser
import yaml

# Some sites (e.g. Treasury) refuse feedparser's default User-Agent and
# return an HTML "blocked" page that then fails XML parsing.
feedparser.USER_AGENT = (
    "Mozilla/5.0 (compatible; RAMIP/1.0; "
    "+https://github.com/seaniechaos/ramip)"
)

ROOT = Path(__file__).resolve().parent
SOURCES_PATH = ROOT / "sources.yaml"
DB_PATH = ROOT / "seen_items.db"
OUTPUT_PATH = ROOT / "fetched_items.json"
MAX_WORKERS = 16

logger = logging.getLogger("ramip.fetch")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS seen_items "
        "(url_hash TEXT PRIMARY KEY, seen_at DATETIME)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS feed_cache "
        "(url TEXT PRIMARY KEY, etag TEXT, last_modified TEXT)"
    )
    conn.commit()


def _load_sources() -> list[tuple[str, str, str]]:
    with open(SOURCES_PATH) as f:
        data = yaml.safe_load(f) or {}
    feeds: list[tuple[str, str, str]] = []
    for category, entries in data.items():
        for entry in entries or []:
            feeds.append((category, entry["name"], entry["url"]))
    return feeds


def _hash_url(link: str) -> str:
    return hashlib.sha256(link.encode("utf-8")).hexdigest()


def _fetch_one(
    category: str,
    name: str,
    url: str,
    etag: str | None,
    modified: str | None,
) -> dict[str, Any]:
    """Fetch a single feed. Always returns a result dict; never raises."""
    try:
        parsed = feedparser.parse(url, etag=etag, modified=modified)
    except Exception as exc:
        return {
            "url": url,
            "name": name,
            "category": category,
            "error": f"parse error: {exc!r}",
        }

    status = getattr(parsed, "status", None)
    if status == 304:
        return {
            "url": url,
            "name": name,
            "category": category,
            "items": [],
            "etag": etag,
            "modified": modified,
        }

    if parsed.bozo and not parsed.entries:
        return {
            "url": url,
            "name": name,
            "category": category,
            "error": f"feed error: {parsed.bozo_exception!r}",
        }

    items: list[dict[str, Any]] = []
    for entry in parsed.entries:
        link = entry.get("link") or entry.get("id")
        if not link:
            continue
        items.append(
            {
                "title": (entry.get("title") or "").strip(),
                "summary": (entry.get("summary") or "").strip(),
                "link": link,
                "source": name,
                "category": category,
                "published": entry.get("published") or entry.get("updated"),
            }
        )

    return {
        "url": url,
        "name": name,
        "category": category,
        "items": items,
        "etag": getattr(parsed, "etag", None) or etag,
        "modified": getattr(parsed, "modified", None) or modified,
    }


def fetch_all() -> tuple[list[dict[str, Any]], dict[str, int]]:
    feeds = _load_sources()
    stats = {"configured": len(feeds), "pulled": 0, "failed": 0}
    new_items: list[dict[str, Any]] = []

    if not feeds:
        logger.warning("no feeds configured in %s", SOURCES_PATH)
        OUTPUT_PATH.write_text("[]")
        return new_items, stats

    conn = sqlite3.connect(DB_PATH)
    try:
        _ensure_schema(conn)

        cache: dict[str, tuple[str | None, str | None]] = {
            url: (etag, modified)
            for url, etag, modified in conn.execute(
                "SELECT url, etag, last_modified FROM feed_cache"
            )
        }
        seen: set[str] = {
            row[0] for row in conn.execute("SELECT url_hash FROM seen_items")
        }

        now = datetime.now(timezone.utc).isoformat()

        with cf.ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(feeds))) as pool:
            futures = [
                pool.submit(
                    _fetch_one,
                    cat,
                    name,
                    url,
                    *cache.get(url, (None, None)),
                )
                for cat, name, url in feeds
            ]
            for fut in cf.as_completed(futures):
                result = fut.result()
                if "error" in result:
                    stats["failed"] += 1
                    logger.error(
                        "[%s] %s (%s): %s",
                        result["category"],
                        result["name"],
                        result["url"],
                        result["error"],
                    )
                    continue

                stats["pulled"] += 1
                conn.execute(
                    "INSERT OR REPLACE INTO feed_cache "
                    "(url, etag, last_modified) VALUES (?, ?, ?)",
                    (result["url"], result.get("etag"), result.get("modified")),
                )

                for item in result["items"]:
                    h = _hash_url(item["link"])
                    if h in seen:
                        continue
                    seen.add(h)
                    conn.execute(
                        "INSERT OR IGNORE INTO seen_items "
                        "(url_hash, seen_at) VALUES (?, ?)",
                        (h, now),
                    )
                    new_items.append(item)

        conn.commit()
    finally:
        conn.close()

    OUTPUT_PATH.write_text(json.dumps(new_items, indent=2, ensure_ascii=False))
    logger.info("wrote %d items to %s", len(new_items), OUTPUT_PATH)
    return new_items, stats


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    items, stats = fetch_all()
    print(f"{stats['pulled']} feeds pulled, {len(items)} new items found")


if __name__ == "__main__":
    main()
