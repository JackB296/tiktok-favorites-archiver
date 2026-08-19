"""Normalized post metadata and durable, privacy-safe source sidecars."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
import re
import threading

from core import config, store


_HTTP_LOCAL = threading.local()


def _resource_session():
    session = getattr(_HTTP_LOCAL, "session", None)
    if session is None:
        import requests
        session = requests.Session()
        _HTTP_LOCAL.session = session
    return session


def fetch_resource(url, target):
    """Stream one remote sidecar asset to an atomic local file."""
    temporary = target + ".part"
    try:
        with _resource_session().get(url, stream=True, timeout=30) as response:
            response.raise_for_status()
            with open(temporary, "wb") as output:
                for chunk in response.iter_content(1024 * 128):
                    if chunk:
                        output.write(chunk)
        if os.path.getsize(temporary) == 0:
            raise ValueError("empty sidecar resource")
        os.replace(temporary, target)
        return True
    except Exception:
        try:
            os.remove(temporary)
        except OSError:
            pass
        return False


def _count(value):
    return int(value) if isinstance(value, (int, float)) else None


def _posted_at(info):
    value = info.get("timestamp")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    upload_date = info.get("upload_date")
    if isinstance(upload_date, str) and re.fullmatch(r"\d{8}", upload_date):
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}T00:00:00+00:00"
    return None


@dataclass(frozen=True)
class SourceMetadata:
    post_id: str
    webpage_url: str
    title: str | None
    description: str | None
    posted_at: str | None
    duration_s: float | None
    width: int | None
    height: int | None
    creator_username: str | None
    creator_display_name: str | None
    creator_id: str | None
    creator_url: str | None
    channel_id: str | None
    view_count: int | None
    like_count: int | None
    comment_count: int | None
    repost_count: int | None
    save_count: int | None
    thumbnail_url: str | None
    formats: tuple
    subtitles: dict
    comments: tuple
    comments_attempted: bool

    def sidecar(self):
        value = asdict(self)
        value["formats"] = list(self.formats)
        value["comments"] = list(self.comments)
        return value


def _safe_formats(formats):
    keys = (
        "format_id", "ext", "width", "height", "vcodec", "acodec",
        "tbr", "vbr", "abr", "filesize", "filesize_approx", "format_note",
    )
    return tuple(
        {key: entry.get(key) for key in keys if entry.get(key) is not None}
        for entry in (formats or []) if isinstance(entry, dict)
    )


def _safe_subtitles(subtitles):
    result = {}
    for language, entries in (subtitles or {}).items():
        if not isinstance(entries, list):
            continue
        result[str(language)] = [
            {key: entry.get(key) for key in ("name", "ext", "url") if entry.get(key) is not None}
            for entry in entries if isinstance(entry, dict)
        ]
    return result


def _safe_comments(comments):
    keys = ("id", "parent", "author", "author_id", "author_username", "text", "timestamp", "like_count")
    return tuple(
        {key: comment.get(key) for key in keys if comment.get(key) is not None}
        for comment in (comments or []) if isinstance(comment, dict)
    )


def from_info(info, fallback_url="", fallback_username=None):
    if not isinstance(info, dict):
        raise ValueError("extractor metadata must be an object")
    creator_username = info.get("uploader") or fallback_username
    subtitles = dict(info.get("automatic_captions") or {})
    subtitles.update(info.get("subtitles") or {})
    return SourceMetadata(
        post_id=str(info.get("id") or ""),
        webpage_url=info.get("webpage_url") or fallback_url,
        title=info.get("title") or info.get("description"),
        description=info.get("description") or info.get("title"),
        posted_at=_posted_at(info),
        duration_s=float(info["duration"]) if isinstance(info.get("duration"), (int, float)) else None,
        width=_count(info.get("width")),
        height=_count(info.get("height")),
        creator_username=str(creator_username) if creator_username else None,
        creator_display_name=info.get("channel") or (str(creator_username) if creator_username else None),
        creator_id=str(info.get("uploader_id")) if info.get("uploader_id") is not None else None,
        creator_url=info.get("uploader_url"),
        channel_id=str(info.get("channel_id")) if info.get("channel_id") is not None else None,
        view_count=_count(info.get("view_count")),
        like_count=_count(info.get("like_count")),
        comment_count=_count(info.get("comment_count")),
        repost_count=_count(info.get("repost_count")),
        save_count=_count(info.get("save_count")),
        thumbnail_url=info.get("thumbnail"),
        formats=_safe_formats(info.get("formats")),
        subtitles=_safe_subtitles(subtitles),
        comments=_safe_comments(info.get("comments")),
        comments_attempted=(
            bool(info["_comments_attempted"])
            if "_comments_attempted" in info
            else info.get("comments") is not None
        ),
    )


def _atomic_text(path, text):
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as output:
        output.write(text)
    os.replace(temporary, path)


def _extension(url, default):
    match = re.search(r"\.([A-Za-z0-9]{2,5})(?:[?#]|$)", url or "")
    extension = (match.group(1).lower() if match else default).replace("jpeg", "jpg")
    return default if extension in {"image", "img"} else extension


def write_sidecars(download_dir, item_id, metadata, fetch=None):
    os.makedirs(download_dir, exist_ok=True)
    thumbnail_path = None
    subtitle_files = {}
    if fetch is not None and metadata.thumbnail_url:
        extension = _extension(metadata.thumbnail_url, "jpg")
        thumbnail_path = f"{item_id}.source.{extension}"
        if not fetch(metadata.thumbnail_url, os.path.join(download_dir, thumbnail_path)):
            thumbnail_path = None
    if fetch is not None:
        for language, entries in metadata.subtitles.items():
            if not entries:
                continue
            selected = entries[-1]
            url = selected.get("url")
            if not url:
                continue
            safe_language = re.sub(r"[^A-Za-z0-9_-]", "_", language)[:30] or "und"
            extension = str(selected.get("ext") or _extension(url, "vtt"))
            filename = f"{item_id}.{safe_language}.{extension}"
            if fetch(url, os.path.join(download_dir, filename)):
                subtitle_files[language] = filename

    sidecar = metadata.sidecar()
    sidecar["thumbnail_file"] = thumbnail_path
    sidecar["subtitle_files"] = subtitle_files
    # Signed CDN URLs can carry session cookies/tokens and expire quickly; the
    # downloaded assets are durable, while those URLs do not belong in backups.
    sidecar["thumbnail_url"] = None
    sidecar["subtitles"] = {
        language: [{key: value for key, value in entry.items() if key != "url"} for entry in entries]
        for language, entries in metadata.subtitles.items()
    }
    _atomic_text(
        os.path.join(download_dir, f"{item_id}.info.json"),
        json.dumps(sidecar, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    if metadata.description:
        _atomic_text(os.path.join(download_dir, f"{item_id}.description"), metadata.description)
    if metadata.comments_attempted:
        _atomic_text(
            os.path.join(download_dir, f"{item_id}.comments.json"),
            json.dumps(list(metadata.comments), ensure_ascii=False, indent=2) + "\n",
        )
    return thumbnail_path


def archive(conn, download_dir, item_id, metadata, fetch=None):
    thumbnail_path = write_sidecars(download_dir, item_id, metadata, fetch=fetch)
    _persist(conn, item_id, metadata, thumbnail_path)
    return metadata


def _persist(conn, item_id, metadata, thumbnail_path):
    """Commit one prepared source result on the connection-owning thread."""
    store.set_source_metadata(conn, item_id, metadata, source_thumbnail_path=thumbnail_path)
    if metadata.comments_attempted:
        store.record_comment_snapshot(
            conn, item_id, metadata.comments, reported_count=metadata.comment_count,
        )


def _prepare(item, download_dir, extractor, fetch, include_comments):
    """Perform the slow, independent network and sidecar work for one post."""
    info = extractor(item["link"], include_comments=include_comments)
    metadata = from_info(info, fallback_url=item["link"])
    thumbnail_path = write_sidecars(
        download_dir, item["id"], metadata, fetch=fetch,
    )
    return metadata, thumbnail_path


def refresh_item(conn, download_dir, item_id, extractor=None,
                 fetch=fetch_resource, include_comments=True):
    """Re-fetch one post's public facts, adding a fresh comment snapshot.

    The bulk backfill deliberately skips posts whose metadata is already saved,
    so nothing in the ordinary Sync chain ever picks up comments written since
    the last fetch. This is the one-post version of the Sync tab's "re-fetch
    everything", for when a single conversation is worth catching up on.

    Earlier snapshots are kept: store.record_comment_snapshot diffs against the
    previous one, so a refresh adds history rather than overwriting it.
    """
    item = store.get_item(conn, item_id)
    if item is None:
        raise KeyError("favorite not found")
    if str(item["link"]).startswith("local://"):
        raise ValueError("this favorite has no public post to refresh")
    if extractor is None:
        from core.ytdlp_adapter import extract_post
        extractor = extract_post
    try:
        metadata, thumbnail_path = _prepare(
            item, download_dir, extractor, fetch, include_comments,
        )
    except Exception as error:
        # Never downgrade a post we already hold facts for: marking it
        # unavailable on a transient network failure would also hide it from
        # the incremental backfill, which only revisits pending or unknown
        # posts. A post that never succeeded still records the failure.
        if item["source_info_status"] != "ok":
            store.set_source_metadata_unavailable(conn, item_id, error)
        raise
    _persist(conn, item_id, metadata, thumbnail_path)
    return metadata


def backfill(conn, download_dir, extractor=None, fetch=fetch_resource,
             include_comments=True, progress=None, should_continue=None,
             recheck=False, item_ids=None, workers=None):
    """Archive rich source facts for the entire existing library backlog."""
    if extractor is None:
        from core.ytdlp_adapter import extract_post
        extractor = extract_post
    items = store.items_needing_source_metadata(conn, recheck=recheck)
    if item_ids is not None:
        wanted = {int(value) for value in item_ids}
        items = [item for item in items if item["id"] in wanted]
    workers = max(1, int(workers or config.SOURCE_METADATA_WORKERS))
    result = {"completed": 0, "saved": 0, "unavailable": 0}
    empty_results = 0
    if progress:
        progress({"event": "source-metadata", "total": len(items), **result})
    def record(item, outcome):
        nonlocal empty_results
        try:
            metadata, thumbnail_path = outcome()
            _persist(conn, item["id"], metadata, thumbnail_path)
            result["saved"] += 1
            if not any((metadata.title, metadata.description, metadata.creator_username, metadata.width, metadata.height)):
                empty_results += 1
        except Exception as error:
            store.set_source_metadata_unavailable(conn, item["id"], error)
            result["unavailable"] += 1
        result["completed"] += 1
        if progress:
            progress({
                "event": "source-metadata", "id": item["id"],
                "total": len(items), **result,
            })

    if workers == 1:
        for item in items:
            if should_continue and not should_continue():
                break
            record(item, lambda item=item: _prepare(
                item, download_dir, extractor, fetch, include_comments,
            ))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            iterator = iter(items)
            pending = {}
            accepting = True
            while accepting and len(pending) < workers:
                if should_continue and not should_continue():
                    accepting = False
                    break
                try:
                    item = next(iterator)
                except StopIteration:
                    accepting = False
                    break
                pending[pool.submit(
                    _prepare, item, download_dir, extractor, fetch,
                    include_comments,
                )] = item

            while pending:
                completed_futures, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in completed_futures:
                    item = pending.pop(future)
                    record(item, future.result)
                    if not accepting:
                        continue
                    if should_continue and not should_continue():
                        accepting = False
                        continue
                    try:
                        next_item = next(iterator)
                    except StopIteration:
                        accepting = False
                        continue
                    pending[pool.submit(
                        _prepare, next_item, download_dir, extractor, fetch,
                        include_comments,
                    )] = next_item
    if items:
        from core import source_health
        source_health.record(
            conn, "source-metadata", attempted=result["completed"],
            succeeded=result["saved"] - empty_results, empty=empty_results,
            failed=result["unavailable"],
        )
    return result
