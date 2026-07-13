"""Validate and atomically install user-supplied Archive media."""
import os
import tempfile

from core import media_index, store


class MediaReplacementError(ValueError):
    pass


def _validate_mp4(path):
    try:
        with open(path, "rb") as file:
            header = file.read(12)
    except OSError as error:
        raise MediaReplacementError("replacement MP4 could not be read") from error
    if len(header) < 12 or header[4:8] != b"ftyp":
        raise MediaReplacementError("replacement video must be a valid MP4 file")


def _image_extension(path):
    try:
        with open(path, "rb") as file:
            header = file.read(16)
    except OSError as error:
        raise MediaReplacementError("replacement thumbnail could not be read") from error
    if header.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp"
    raise MediaReplacementError("replacement thumbnail must be JPEG, PNG, or WebP")


def _fingerprint(path):
    stat = os.stat(path)
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def replace_item_media(
    conn,
    download_dir,
    item_id,
    staged_video=None,
    staged_thumbnail=None,
    inspect=media_index.inspect_media,
    make_thumbnail=media_index.make_thumbnail,
):
    """Install validated staged files at paths derived only from ``item_id``."""
    if not staged_video and not staged_thumbnail:
        raise MediaReplacementError("at least one replacement file is required")
    if store.get_item(conn, item_id) is None:
        raise MediaReplacementError("archive item not found")

    download_dir = os.path.abspath(download_dir)
    generated_temp = None
    index = None
    custom_relative = None
    custom_target = None
    try:
        if staged_video:
            _validate_mp4(staged_video)
            try:
                facts = inspect(staged_video)
            except Exception as error:
                raise MediaReplacementError("replacement MP4 could not be inspected by FFprobe") from error
            thumbnail_dir = os.path.join(download_dir, ".archive", "thumbnails")
            os.makedirs(thumbnail_dir, exist_ok=True)
            fd, generated_temp = tempfile.mkstemp(prefix=f".{item_id}-", suffix=".webp", dir=thumbnail_dir)
            os.close(fd)
            os.unlink(generated_temp)
            try:
                width = int(store.get_library_settings(conn)["thumbnail_width"])
                make_thumbnail(staged_video, generated_temp, width)
            except Exception as error:
                raise MediaReplacementError("replacement MP4 thumbnail could not be created") from error
            index = media_index.MediaIndex(
                *facts[:5],
                f".archive/thumbnails/{item_id}.webp",
                facts.has_audio,
            )._asdict()

        if staged_thumbnail:
            extension = _image_extension(staged_thumbnail)
            custom_relative = f".archive/custom-thumbnails/{item_id}.{extension}"
            custom_target = os.path.join(download_dir, custom_relative)
            os.makedirs(os.path.dirname(custom_target), exist_ok=True)

        if staged_video:
            os.replace(staged_video, os.path.join(download_dir, f"{item_id}.mp4"))
            os.replace(generated_temp, os.path.join(download_dir, index["thumbnail_path"]))
            generated_temp = None
        if staged_thumbnail:
            os.replace(staged_thumbnail, custom_target)

        target_video = os.path.join(download_dir, f"{item_id}.mp4")
        store.record_manual_media(
            conn,
            item_id,
            index=index,
            fingerprint=_fingerprint(target_video) if index else None,
            custom_thumbnail_path=custom_relative,
        )
        return {
            "video_replaced": bool(staged_video),
            "thumbnail_replaced": bool(staged_thumbnail),
        }
    finally:
        if generated_temp:
            try:
                os.unlink(generated_temp)
            except OSError:
                pass
