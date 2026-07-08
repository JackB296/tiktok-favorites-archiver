"""Metadata enrichment via TikTok's public oEmbed endpoint.

Cobalt returns no caption/author, so — to power search — we fetch each post's
``title`` (caption, hashtags included) and ``author_name`` from
``https://www.tiktok.com/oembed``. One unauthenticated request per item,
rate-limited, and skipped gracefully on any failure (search then degrades to
date/type/number for that item).

``requests`` is imported lazily; the pure ``parse_oembed`` stays testable.
"""
import time
import logging

from core import config, store
from core.cobalt import RateLimiter

OEMBED_URL = "https://www.tiktok.com/oembed"


def parse_oembed(data):
    """Extract (caption, author) from an oEmbed JSON body (pure)."""
    if not data:
        return (None, None)
    caption = data.get("title") or None
    author = data.get("author_name") or None
    return (caption, author)


def _default_getter(link):
    import requests  # lazy
    resp = requests.get(OEMBED_URL, params={"url": link}, timeout=config.REQUEST_TIMEOUT)
    if resp.status_code == 200:
        return resp.json()
    return None


def fetch_metadata(link, getter=None):
    getter = getter or _default_getter
    try:
        data = getter(link)
    except Exception as e:
        logging.warning(f"oEmbed fetch failed for {link}: {e}")
        return (None, None)
    return parse_oembed(data)


def items_needing_enrichment(conn):
    """Items with a real link and no caption yet (skips synthetic local:// files)."""
    return [
        row for row in store.all_items(conn)
        if row["caption"] is None and not str(row["link"]).startswith("local://")
    ]


def enrich_items(conn, getter=None, limiter=None, progress=None):
    """Fetch + store caption/author for items that lack it. Returns count enriched."""
    getter = getter or _default_getter
    if limiter is None:
        limiter = RateLimiter(config.RATE_MAX_CALLS, config.RATE_PERIOD)
    enriched = 0
    for item in items_needing_enrichment(conn):
        limiter.acquire()
        caption, author = fetch_metadata(item["link"], getter=getter)
        if caption is not None or author is not None:
            store.set_metadata(conn, item["id"], caption, author)
            enriched += 1
        if progress:
            progress({"id": item["id"], "caption": caption, "author": author})
    return enriched


def run_cli(argv=None):
    """`python -m core enrich` — fetch captions/authors for items missing them."""
    import argparse
    parser = argparse.ArgumentParser(prog="core enrich",
                                     description="Fetch captions/authors via TikTok oEmbed.")
    parser.add_argument("--db", default=config.DB_FILE)
    args = parser.parse_args(argv)
    config.setup_logging()
    conn = store.init_db(store.connect(args.db))

    def progress(event):
        got = "caption" if event.get("caption") else "no metadata"
        logging.info(f"[{event['id']}] {got}")

    n = enrich_items(conn, progress=progress)
    logging.info(f"Enriched {n} item(s)")

