"""Plan and adopt video files from an existing myfaveTT archive."""
import os
import re

from core import importer, layout, manual_media, store


class MyfaveTTImportError(ValueError):
    pass


_VIDEO_ID = re.compile(r"^[0-9]{5,30}$")
_VIDEO_PATH = re.compile(
    r"(?:^|/)(?:data/(?:Likes|Favorites)/videos|"
    r"data/Following/[^/]+/videos|videos)/([0-9]{5,30})\.mp4$",
    re.I,
)


def video_id_from_path(value):
    if not isinstance(value, str):
        return None
    normalized = value.replace("\\", "/").strip("/")
    match = _VIDEO_PATH.search(normalized)
    return match.group(1) if match else None


def validate_video_id(value):
    video_id = str(value or "").strip()
    if not _VIDEO_ID.fullmatch(video_id):
        raise MyfaveTTImportError("myfaveTT video id must be 5 to 30 digits")
    return video_id


def _find_item(conn, video_id):
    return (
        store.get_item_by_video_id(conn, video_id)
        or store.get_item_by_link(conn, f"local://myfavett/{video_id}")
    )


def plan_import(conn, download_dir, relative_paths):
    if not isinstance(relative_paths, list):
        raise MyfaveTTImportError("paths must be a list")
    if len(relative_paths) > 100_000:
        raise MyfaveTTImportError("a myfaveTT import may contain at most 100000 paths")
    discovered = {}
    duplicate_files = 0
    for relative_path in relative_paths:
        video_id = video_id_from_path(relative_path)
        if video_id is None:
            continue
        if video_id in discovered:
            duplicate_files += 1
            continue
        discovered[video_id] = relative_path.replace("\\", "/")
    if not discovered:
        raise MyfaveTTImportError(
            "no myfaveTT videos were found; choose the archive folder containing data/Likes or data/Favorites"
        )

    items = []
    counts = {"ready": 0, "already_archived": 0, "matched_slots": 0, "new_local_items": 0}
    for video_id, relative_path in discovered.items():
        row = _find_item(conn, video_id)
        item_id = row["id"] if row is not None else None
        already_archived = row is not None and os.path.isfile(layout.movie(download_dir, item_id))
        status = "already_archived" if already_archived else "ready"
        match = "archive_slot" if row is not None else "new_local_item"
        counts[status] += 1
        counts["matched_slots" if row is not None else "new_local_items"] += 1
        items.append({
            "video_id": video_id,
            "relative_path": relative_path,
            "item_id": item_id,
            "status": status,
            "match": match,
        })
    return {
        "items": items,
        "counts": counts,
        "video_files": len(items),
        "duplicate_files": duplicate_files,
        "ignored_paths": len(relative_paths) - len(items) - duplicate_files,
    }


def adopt_video(
    conn,
    download_dir,
    video_id,
    staged_video,
    source_path=None,
    overwrite=False,
    inspect=None,
    make_thumbnail=None,
):
    """Install one staged myfaveTT MP4 in its stable TikTok-id slot."""
    video_id = validate_video_id(video_id)
    if source_path is not None and video_id_from_path(source_path) != video_id:
        raise MyfaveTTImportError("selected file path does not match its myfaveTT video id")
    row = _find_item(conn, video_id)
    created = row is None
    if created:
        item_id = store.insert_item(
            conn,
            store.next_item_id(conn),
            f"local://myfavett/{video_id}",
            kind="video",
            status="pending",
            favorite_order=store.next_favorite_order(conn),
        )
    else:
        item_id = row["id"]
        if os.path.isfile(layout.movie(download_dir, item_id)) and not overwrite:
            return {"status": "already_archived", "item_id": item_id, "created": False}

    kwargs = {"staged_video": staged_video}
    if inspect is not None:
        kwargs["inspect"] = inspect
    if make_thumbnail is not None:
        kwargs["make_thumbnail"] = make_thumbnail
    try:
        manual_media.replace_item_media(conn, download_dir, item_id, **kwargs)
    except Exception:
        if created:
            conn.execute("DELETE FROM item WHERE id = ?", (item_id,))
            conn.commit()
        raise
    importer.regenerate_manifest(conn, download_dir)
    return {
        "status": "imported",
        "item_id": item_id,
        "created": created,
        "matched_slot": not created,
    }
