"""Turn DB item rows into the JSON shape the frontend consumes (stdlib only).

Media is exposed as ``/media/...`` URLs served by the backend; slideshow items
also list their raw carousel images + audio from ``downloads/<n>/``.
"""
import os

_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def slideshow_assets(download_dir, n):
    """Return ``{"images": [url, ...], "audio": url|None}`` for ``downloads/<n>/``."""
    folder = os.path.join(download_dir, str(n))
    if not os.path.isdir(folder):
        return {"images": [], "audio": None}
    names = sorted(os.listdir(folder))
    images = [f"/media/{n}/{name}" for name in names if name.lower().endswith(_IMAGE_EXTS)]
    audio = f"/media/{n}/audio.mp3" if os.path.exists(os.path.join(folder, "audio.mp3")) else None
    return {"images": images, "audio": audio}


def item_to_public(row, download_dir):
    """Map an ``item`` row to a JSON-serializable dict with media URLs."""
    n = row["id"]
    data = {
        "id": n,
        "link": row["link"],
        "caption": row["caption"],
        "author": row["author"],
        "kind": row["kind"],
        "status": row["status"],
        "favorited_at": row["favorited_at"],
        "has_assets": bool(row["has_assets"]),
        "video_url": None,
        "images": [],
        "audio": None,
    }
    if os.path.exists(os.path.join(download_dir, f"{n}.mp4")):
        data["video_url"] = f"/media/{n}.mp4"
    if row["has_assets"]:
        assets = slideshow_assets(download_dir, n)
        data["images"] = assets["images"]
        data["audio"] = assets["audio"]
    return data
