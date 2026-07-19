"""Local Lens: validated local-analysis ingestion and SQLite FTS search."""
from datetime import datetime
import json
import math
import re

from core import store


SOURCES = ("transcript", "ocr")
MAX_ITEMS = 5_000
MAX_SEGMENTS_PER_ITEM = 5_000
MAX_SEGMENTS = 100_000
MAX_TEXT_LENGTH = 4_000


class LensError(ValueError):
    pass


def _now():
    return datetime.now().isoformat(timespec="seconds")


def load_document(path):
    try:
        with open(path, encoding="utf-8") as source:
            return json.load(source)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise LensError(f"analysis document is unreadable: {error}") from error


def _finite_time(value, field, *, allow_none=False):
    if value is None and allow_none:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise LensError(f"{field} must be a finite non-negative number")
    return float(value)


def validate_document(document):
    if not isinstance(document, dict):
        raise LensError("analysis document must be an object")
    items = document.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        raise LensError(f"items must contain 1 to {MAX_ITEMS} entries")
    normalized = []
    seen_items = set()
    total_segments = 0
    for item in items:
        if not isinstance(item, dict) or type(item.get("item_id")) is not int or item["item_id"] < 1:
            raise LensError("each item_id must be a positive integer")
        item_id = item["item_id"]
        if item_id in seen_items:
            raise LensError("item_id entries must be unique")
        seen_items.add(item_id)
        segments = item.get("segments")
        if not isinstance(segments, list) or len(segments) > MAX_SEGMENTS_PER_ITEM:
            raise LensError(
                f"segments must be an array of at most {MAX_SEGMENTS_PER_ITEM} entries"
            )
        clean_segments = []
        for segment in segments:
            if not isinstance(segment, dict) or segment.get("source") not in SOURCES:
                raise LensError("segment source must be transcript or ocr")
            text = segment.get("text")
            if not isinstance(text, str) or not (text := text.strip()) or len(text) > MAX_TEXT_LENGTH:
                raise LensError(
                    f"segment text must be between 1 and {MAX_TEXT_LENGTH} characters"
                )
            start_s = _finite_time(segment.get("start_s", 0), "start_s")
            end_s = _finite_time(segment.get("end_s"), "end_s", allow_none=True)
            if end_s is not None and end_s < start_s:
                raise LensError("end_s must be greater than or equal to start_s")
            clean_segments.append({
                "source": segment["source"],
                "text": text,
                "start_s": start_s,
                "end_s": end_s,
            })
        total_segments += len(clean_segments)
        if total_segments > MAX_SEGMENTS:
            raise LensError(f"analysis document exceeds {MAX_SEGMENTS} segments")
        normalized.append({"item_id": item_id, "segments": clean_segments})
    return normalized


def import_document(conn, document):
    items = validate_document(document)
    ids = [item["item_id"] for item in items]
    known = store.get_items(conn, ids)
    missing = [item_id for item_id in ids if item_id not in known]
    if missing:
        raise LensError(f"unknown Archive item: {missing[0]}")

    timestamp = _now()
    conn.execute("SAVEPOINT lens_import")
    try:
        for item in items:
            conn.execute(
                "DELETE FROM analysis_segment WHERE item_id = ?",
                (item["item_id"],),
            )
            conn.executemany(
                "INSERT INTO analysis_segment "
                "(item_id, source, text, start_s, end_s, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        item["item_id"], segment["source"], segment["text"],
                        segment["start_s"], segment["end_s"], timestamp,
                    )
                    for segment in item["segments"]
                ],
            )
        conn.execute("RELEASE lens_import")
    except Exception:
        conn.execute("ROLLBACK TO lens_import")
        conn.execute("RELEASE lens_import")
        raise
    return {
        "items": len(items),
        "segments": sum(len(item["segments"]) for item in items),
    }


def status(conn):
    row = conn.execute(
        "SELECT COUNT(DISTINCT item_id) AS items, COUNT(*) AS segments "
        "FROM analysis_segment"
    ).fetchone()
    return {"items": row["items"], "segments": row["segments"]}


def caption_segments(conn, item_id):
    if store.get_item(conn, item_id) is None:
        raise LensError("favorite not found")
    rows = conn.execute(
        "SELECT id, item_id, source, text, start_s, end_s "
        "FROM analysis_segment "
        "WHERE item_id = ? AND source = 'transcript' "
        "ORDER BY start_s, id "
        "LIMIT ?",
        (item_id, MAX_SEGMENTS_PER_ITEM),
    ).fetchall()
    return [dict(row) for row in rows]


def _fts_expression(query):
    if not isinstance(query, str):
        return ""
    terms = re.findall(r"[^\W_]+", query[:500], re.UNICODE)
    return " AND ".join(f'"{term}"*' for term in terms[:20])


def search_segments(conn, query, source=None, limit=50):
    if source is not None and source not in SOURCES:
        raise LensError("source must be transcript or ocr")
    expression = _fts_expression(query)
    if not expression:
        return []
    limit = max(1, min(int(limit), 100))
    source_clause = " AND segment.source = ?" if source else ""
    params = [expression]
    if source:
        params.append(source)
    params.append(limit)
    rows = conn.execute(
        "SELECT segment.id, segment.item_id, segment.source, segment.text, "
        "segment.start_s, segment.end_s, "
        "snippet(analysis_search, 0, '[[', ']]', ' … ', 18) AS snippet, "
        "bm25(analysis_search) AS rank "
        "FROM analysis_search "
        "JOIN analysis_segment segment ON segment.id = analysis_search.rowid "
        "WHERE analysis_search MATCH ?"
        f"{source_clause} "
        "ORDER BY rank, segment.item_id, segment.start_s, segment.id LIMIT ?",
        tuple(params),
    ).fetchall()
    return [dict(row) for row in rows]
