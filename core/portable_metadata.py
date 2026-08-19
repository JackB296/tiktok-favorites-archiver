"""Atomically embed useful Archive sidecars into portable MP4 files."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import json
import os
import subprocess
import tempfile

from core import config, layout, media_index, store


def _digest_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 128), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _subtitle_files(download_dir, item_id):
    path = os.path.join(download_dir, f"{item_id}.info.json")
    try:
        with open(path, encoding="utf-8") as source:
            saved = json.load(source).get("subtitle_files") or {}
    except (OSError, ValueError, AttributeError):
        return []
    result = []
    for language, relative in sorted(saved.items()):
        candidate = os.path.abspath(os.path.join(download_dir, str(relative)))
        if os.path.commonpath((os.path.abspath(download_dir), candidate)) != os.path.abspath(download_dir):
            continue
        if os.path.isfile(candidate):
            result.append((str(language), candidate))
    return result


def _embed_spec(download_dir, item):
    poster = layout.poster(download_dir, item["id"])
    poster = poster if os.path.isfile(poster) else None
    subtitles = _subtitle_files(download_dir, item["id"])
    description = item["description"] or item["caption"] or ""
    source = item["link"] or ""
    tags = {
        "title": item["caption"] or f"Favorite {item['id']}",
        "artist": item["author"] or "",
        "description": description,
        # MOV/MP4 does not preserve an arbitrary `purl` tag together with
        # attached artwork on all supported FFmpeg releases. `comment` is a
        # standard portable atom, so keep the human-readable source there.
        "comment": "\n\n".join(filter(None, [description, f"Source: {source}" if source else ""])),
        "date": str(item["source_posted_at"] or item["favorited_at"] or "")[:10],
        "encoded_by": "TikTok Favorites Archiver",
    }
    identity = {
        "tags": tags,
        "poster": _digest_file(poster) if poster else None,
        "subtitles": [(language, _digest_file(path)) for language, path in subtitles],
    }
    content_hash = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return tags, poster, subtitles, content_hash


def _command(movie, output, tags, poster, subtitles):
    command = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", movie]
    poster_input = None
    if poster:
        poster_input = 1
        command.extend(["-i", poster])
    subtitle_inputs = []
    for language, path in subtitles:
        input_index = 1 + (1 if poster else 0) + len(subtitle_inputs)
        command.extend(["-i", path])
        subtitle_inputs.append((language, input_index))

    command.extend(["-map", "0:v:0", "-map", "0:a?", "-c:v:0", "copy", "-c:a", "copy"])
    if poster_input is not None:
        command.extend([
            "-map", f"{poster_input}:v:0", "-c:v:1", "mjpeg",
            "-disposition:v:1", "attached_pic",
        ])
    for subtitle_index, (language, input_index) in enumerate(subtitle_inputs):
        command.extend([
            "-map", f"{input_index}:0", f"-metadata:s:s:{subtitle_index}", f"language={language}",
        ])
    if subtitle_inputs:
        command.extend(["-c:s", "mov_text"])
    for name, value in tags.items():
        if value:
            command.extend(["-metadata", f"{name}={value}"])
    command.extend(["-movflags", "+faststart", output])
    return command


def _validate(path):
    facts = media_index.inspect_media(path)
    return bool(facts.width and facts.height and os.path.getsize(path) > 0)


def _embed_one(download_dir, item, runner, validate):
    temporary = None
    try:
        tags, poster, subtitles, content_hash = _embed_spec(download_dir, item)
        movie = layout.movie(download_dir, item["id"])
        current_fingerprint = media_index.file_fingerprint(movie)
        if (
            item["portable_metadata_status"] == "ok"
            and item["portable_metadata_hash"] == content_hash
            and item["media_fingerprint"] == current_fingerprint
        ):
            return "skipped", None
        fd, temporary = tempfile.mkstemp(
            prefix=f".{item['id']}-portable-", suffix=".mp4", dir=download_dir,
        )
        os.close(fd)
        os.unlink(temporary)
        runner(_command(movie, temporary, tags, poster, subtitles), check=True, capture_output=True)
        if not os.path.isfile(temporary) or not validate(temporary):
            raise ValueError("embedded MP4 did not pass media validation")
        os.replace(temporary, movie)
        temporary = None
        return "embedded", {
            "content_hash": content_hash,
            "file_size": os.path.getsize(movie),
            "fingerprint": media_index.file_fingerprint(movie),
        }
    finally:
        if temporary and os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass


def embed_library(conn, download_dir, progress=None, should_continue=None,
                  runner=subprocess.run, validate=_validate, item_ids=None,
                  workers=None):
    """Embed changed metadata into finished local MP4s; never rewrite unchanged files."""
    candidates = [
        item for item in store.items_by_status(conn, ["done"])
        if os.path.isfile(layout.movie(download_dir, item["id"]))
    ]
    if item_ids is not None:
        wanted = {int(value) for value in item_ids}
        candidates = [item for item in candidates if item["id"] in wanted]
    workers = max(1, int(workers or config.PORTABLE_METADATA_WORKERS))
    result = {"embedded": 0, "skipped": 0, "failed": 0}
    completed = 0

    def record(item, outcome):
        nonlocal completed
        try:
            status, details = outcome()
            if status == "skipped":
                result["skipped"] += 1
            else:
                store.record_portable_metadata(
                    conn, item["id"], details["content_hash"],
                    file_size=details["file_size"],
                    fingerprint=details["fingerprint"],
                )
                result["embedded"] += 1
        except Exception as error:
            store.record_portable_metadata_error(conn, item["id"], error)
            result["failed"] += 1
        completed += 1
        if progress:
            progress({
                "event": "portable-metadata", "completed": completed,
                "total": len(candidates), **result,
            })

    if workers == 1:
        for item in candidates:
            if should_continue and not should_continue():
                break
            record(item, lambda item=item: _embed_one(
                download_dir, item, runner, validate,
            ))
        return result

    iterator = iter(candidates)
    accepting = True
    pending = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
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
                _embed_one, download_dir, item, runner, validate,
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
                    _embed_one, download_dir, next_item, runner, validate,
                )] = next_item
    return result
