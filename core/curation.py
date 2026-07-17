"""Bulk curation of Archive items: Offloaded/Ignored marks and requeueing.

The single home for the user-directed lifecycle changes the web routes expose:
resolve a selector (explicit ids, an archive-number range, or a Gallery
filter) to Archive item ids, then apply one action. Distinct from
``core/verify`` — that module reports archive integrity; this one changes
lifecycle state on the user's behalf.
"""
import os

from core import layout, selection, store

MARK_ACTIONS = ("offload", "unoffload", "ignore", "unignore")


def resolve_selector(conn, kind, value):
    """Selector -> concrete Archive item ids (``ids`` / ``range`` / ``filter``)."""
    return selection.ArchiveSelection.bulk(kind, value).ids(conn)


def mark(conn, download_dir, action, kind, value, dry_run=False):
    """Apply one bulk lifecycle action to the selected Archive items.

    ``dry_run`` reports the match count without changing anything, powering
    the confirm step for filter- and range-scoped marks.
    """
    ids = resolve_selector(conn, kind, value)
    if dry_run:
        return {"matched": len(ids), "changed": 0, "dry_run": True}
    if action == "offload":
        changed = store.set_offloaded(conn, ids, offloaded=True)
    elif action == "unoffload":
        return {"matched": len(ids), **unoffload_items(conn, download_dir, ids)}
    elif action in ("ignore", "unignore"):
        changed = store.set_ignored(conn, ids, ignored=(action == "ignore"))
    else:
        raise ValueError(f"unknown mark action: {action}")
    return {"matched": len(ids), "changed": changed}


def requeue_selected(conn, download_dir, item_ids):
    """Queue explicitly selected recoverable items for the next Sync.

    A failed remote favorite is retryable. A finished remote favorite is only
    retryable when its numbered video is actually gone. This intentionally
    leaves healthy, in-progress, and synthetic local placeholders unchanged.
    """
    files = os.listdir(download_dir) if os.path.isdir(download_dir) else []
    movies = set(layout.finished_movie_ids(files))
    requested = list(dict.fromkeys(item_ids))
    rows = store.get_items(conn, requested)
    requeued = []
    for item_id in requested:
        row = rows.get(item_id)
        if row is None or not store.is_redownloadable(row):
            continue
        missing_done_file = row["status"] == "done" and item_id not in movies
        if row["status"] != "failed" and not missing_done_file:
            continue
        store.set_status(conn, item_id, "pending")
        requeued.append(item_id)
    return {"requeued": requeued, "skipped": len(requested) - len(requeued)}


def unoffload_items(conn, download_dir, item_ids):
    """Clear offload marks, returning file-less favorites to pending.

    Marking forced these items to ``done``; once the external-storage claim is
    withdrawn, a favorite with no local video has nothing standing behind that
    status, so it goes back in the download queue.
    """
    cleared = store.offloaded_ids(conn, item_ids)
    changed = store.set_offloaded(conn, item_ids, offloaded=False)
    requeued = requeue_selected(conn, download_dir, cleared)["requeued"] if cleared else []
    return {"changed": changed, "requeued": len(requeued)}
