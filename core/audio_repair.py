"""Repair already-archived videos whose indexed audio is missing or silent."""
import os
import tempfile

from core import layout, media_index, store, ytdlp_adapter


def run_audio_repair(conn, download_dir, progress=None, should_continue=None,
                     download=ytdlp_adapter.download_best_video,
                     inspect=media_index.inspect_media, item_ids=None):
    candidates = [
        item for item in store.items_needing_audio_repair(conn)
        if os.path.isfile(layout.movie(download_dir, item["id"]))
    ]
    if item_ids is not None:
        wanted = {int(value) for value in item_ids}
        candidates = [item for item in candidates if item["id"] in wanted]
    result = {"completed": 0, "total": len(candidates), "repaired": 0, "failed": 0}
    if progress:
        progress({"event": "audio-repair", **result})
    for item in candidates:
        if should_continue and not should_continue():
            break
        fd, staged = tempfile.mkstemp(
            prefix=f".{item['id']}-audio-repair-", suffix=".mp4", dir=download_dir,
        )
        os.close(fd)
        os.unlink(staged)
        try:
            if not download(item["link"], staged) or not os.path.isfile(staged):
                raise ValueError("yt-dlp did not return replacement media")
            facts = inspect(staged)
            if not facts.has_audio or facts.audio_silent is True:
                raise ValueError("yt-dlp replacement still has no usable sound")

            target = layout.movie(download_dir, item["id"])
            backup = layout.replaced_movie(download_dir, item["id"])
            os.makedirs(os.path.dirname(backup), exist_ok=True)
            os.replace(target, backup)
            try:
                os.replace(staged, target)
            except OSError:
                os.replace(backup, target)
                raise
            staged = None
            store.record_audio_repair(
                conn, item["id"],
                facts.to_index(item["thumbnail_path"])._asdict(),
                media_index.file_fingerprint(target),
            )
            result["repaired"] += 1
        except Exception:
            result["failed"] += 1
        finally:
            if staged and os.path.exists(staged):
                try:
                    os.unlink(staged)
                except OSError:
                    pass
            result["completed"] += 1
            if progress:
                progress({"event": "audio-repair", "id": item["id"], **result})
    return result
