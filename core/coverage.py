"""Fast archive completeness reporting and targeted, idempotent repair."""
import threading

from core import analysis, audio_repair, identify, indexer, portable_metadata, source_health, source_metadata, store


def _category(key, label, eligible, ready, failed=0, description=""):
    return {
        "key": key, "label": label, "eligible": int(eligible or 0),
        "ready": int(ready or 0), "missing": max(0, int(eligible or 0) - int(ready or 0)),
        "failed": int(failed or 0), "description": description,
    }


def report(conn):
    """Return coverage using indexed database facts only (no filesystem walk)."""
    row = conn.execute("""
        SELECT COUNT(*) AS total,
          SUM(link NOT LIKE 'local://%') AS source_eligible,
          SUM(link NOT LIKE 'local://%' AND source_info_status = 'ok') AS source_ready,
          SUM(link NOT LIKE 'local://%' AND source_info_status = 'unavailable') AS source_failed,
          SUM(link NOT LIKE 'local://%' AND (comments_status = 'ok' OR EXISTS (
            SELECT 1 FROM comment_snapshot cs WHERE cs.item_id = item.id
          ))) AS comments_ready,
          SUM(status = 'done' AND offloaded = 0 AND archive_missing = 0) AS local_media,
          SUM(status = 'done' AND offloaded = 0 AND archive_missing = 0
              AND thumbnail_path IS NOT NULL) AS thumbnails_ready,
          SUM(status = 'done' AND offloaded = 0 AND archive_missing = 0
              AND index_error IS NOT NULL) AS index_failed,
          SUM(song_id IS NOT NULL) AS songs_ready,
          SUM(song_status = 'error') AS songs_failed,
          SUM(portable_metadata_status = 'ok') AS portable_ready,
          SUM(portable_metadata_status = 'error') AS portable_failed,
          SUM(has_audio = 1 AND COALESCE(audio_silent, 0) = 0) AS audio_ready,
          SUM(status = 'done' AND offloaded = 0 AND archive_missing = 0
              AND indexed_at IS NOT NULL) AS indexed
        FROM item
    """).fetchone()
    analysis_rows = conn.execute("""
        SELECT source, COUNT(DISTINCT item_id) AS ready
        FROM analysis_source_state WHERE status = 'completed' GROUP BY source
    """).fetchall()
    analyzed = {r["source"]: r["ready"] for r in analysis_rows}
    total = row["total"] or 0
    source_eligible = row["source_eligible"] or 0
    local_media = row["local_media"] or 0
    indexed = row["indexed"] or 0
    categories = [
        _category("source_metadata", "Source details", source_eligible, row["source_ready"], row["source_failed"], "Descriptions, creator facts, dates and engagement."),
        _category("comments", "Comment snapshots", source_eligible, row["comments_ready"], 0, "Local searchable conversations."),
        _category("thumbnails", "Gallery thumbnails", local_media, row["thumbnails_ready"], row["index_failed"], "Local poster images and media facts."),
        _category("transcripts", "Speech transcripts", indexed, analyzed.get("transcript", 0), 0, "Locally generated searchable speech."),
        _category("ocr", "On-screen text", indexed, analyzed.get("ocr", 0), 0, "Locally generated searchable screen text."),
        _category("songs", "Identified songs", indexed, row["songs_ready"], row["songs_failed"], "Recognized music attached to posts."),
        _category("portable_metadata", "Portable metadata", indexed, row["portable_ready"], row["portable_failed"], "Metadata embedded into local media files."),
        _category("audio", "Usable audio", indexed, row["audio_ready"], 0, "Indexed videos with a non-silent audio stream."),
    ]
    return {"total_items": total, "categories": categories, "source_health": source_health.report(conn)}


def run_repair(conn, download_dir, targets=None, item_ids=None, progress=None,
               wait=None, control=None):
    """Repair selected coverage categories; every underlying worker is resumable."""
    targets = list(dict.fromkeys(targets or []))
    allowed = {"source_metadata", "comments", "thumbnails", "transcripts", "ocr", "songs", "portable_metadata", "audio"}
    unknown = set(targets) - allowed
    if unknown:
        raise ValueError("unknown coverage target: " + ", ".join(sorted(unknown)))
    ids = None if item_ids is None else {int(value) for value in item_ids}
    should_continue = control.should_continue if control else None
    notify = control.progress if control else progress
    result = {}
    source_selected = "source_metadata" in targets or "comments" in targets
    overlap_selected = any(
        target in targets for target in ("thumbnails", "transcripts", "ocr", "songs")
    )
    source_thread = None
    source_outcome = {}
    source_errors = []

    def source_work(source_conn):
        try:
            source_outcome["value"] = source_metadata.backfill(
                source_conn, download_dir, include_comments="comments" in targets,
                recheck=False, item_ids=ids, progress=notify,
                should_continue=should_continue,
            )
        except Exception as error:
            source_errors.append(error)
        finally:
            if source_conn is not conn:
                source_conn.close()

    if source_selected and overlap_selected:
        database = next(
            (row["file"] for row in conn.execute("PRAGMA database_list") if row["name"] == "main"),
            "",
        )
        if database:
            source_thread = threading.Thread(
                target=source_work,
                args=(store.connect(database),),
                name="coverage-source-metadata",
            )
            source_thread.start()
    if source_selected and source_thread is None:
        source_work(conn)

    def finish_source():
        nonlocal source_thread
        if source_thread is not None:
            source_thread.join()
            source_thread = None
        if source_errors:
            raise source_errors[0]
        if source_selected:
            result["source_metadata"] = source_outcome["value"]

    try:
        if "thumbnails" in targets:
            result["thumbnails"] = indexer.index_pending_items(
                conn, download_dir, item_ids=ids, progress=notify,
                should_continue=should_continue,
            )
        if "transcripts" in targets or "ocr" in targets:
            result["analysis"] = analysis.run_analysis(
                conn, download_dir, control=control, item_ids=ids,
                sources=[
                    source for source, target in (
                        ("transcript", "transcripts"), ("ocr", "ocr"),
                    ) if target in targets
                ],
            )
        if "songs" in targets:
            if not store.get_library_settings(conn)["song_id_enabled"]:
                result["songs"] = {"skipped": "Song identification is not enabled in library settings."}
            else:
                result["songs"] = identify.run_identification(
                    conn, download_dir, control=control, item_ids=ids,
                )
        # Portable embedding consumes source facts, and audio repair talks to
        # TikTok itself, so both start only after the source lane has drained.
        finish_source()
        if "portable_metadata" in targets:
            if not store.get_library_settings(conn)["portable_metadata_enabled"]:
                result["portable_metadata"] = {"skipped": "Portable metadata is not enabled in library settings."}
            else:
                result["portable_metadata"] = portable_metadata.embed_library(
                    conn, download_dir, item_ids=ids, progress=notify,
                    should_continue=should_continue,
                )
        if "audio" in targets:
            result["audio"] = audio_repair.run_audio_repair(
                conn, download_dir, item_ids=ids, progress=notify,
                should_continue=should_continue,
            )
    finally:
        if source_thread is not None:
            source_thread.join()
    return result
