"""Public Favorite projection for the Archive web interface.

The module hides SQLite rows and archive-file layout behind ``list`` and
``get``. Routes receive only the public Favorite shape consumed by the web app.
"""
import os

from core import store


_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


class ArchiveItems:
    """Project Archive items into the web-facing Favorite representation."""

    def __init__(self, conn, download_dir):
        self._conn = conn
        self._download_dir = download_dir

    def list(self, query=None, kinds=None, statuses=None):
        rows = store.search_items(self._conn, query=query, kinds=kinds, statuses=statuses)
        return [self._public(row) for row in rows]

    def get(self, item_id):
        row = store.get_item(self._conn, item_id)
        return None if row is None else self._public(row)

    def page(self, query=None, kinds=None, statuses=None, limit=50, cursor=None, order="latest", min_duration=None, max_duration=None, min_size=None, max_size=None, min_width=None, max_width=None, min_height=None, max_height=None, codecs=None, date_from=None, date_to=None, orientations=None, has_assets=None, index_state=None, include=None, exclude=None):
        rows = store.page_items(
            self._conn,
            query=query,
            kinds=kinds,
            statuses=statuses,
            limit=limit,
            cursor=cursor,
            order=order,
            min_duration=min_duration,
            max_duration=max_duration,
            min_size=min_size,
            max_size=max_size,
            min_width=min_width,
            max_width=max_width,
            min_height=min_height,
            max_height=max_height,
            codecs=codecs,
            date_from=date_from,
            date_to=date_to,
            orientations=orientations,
            has_assets=has_assets,
            index_state=index_state,
            include=include,
            exclude=exclude,
        )
        items = [self._public(row) for row in rows]
        return {"items": items, "next_cursor": items[-1]["id"] if len(items) == limit else None}

    def window(self, item_id, limit=50):
        return {"items": [self._public(row) for row in store.window_items(self._conn, item_id, limit)]}

    def selected(self, item_ids):
        rows = [store.get_item(self._conn, item_id) for item_id in item_ids]
        return [self._public(row) for row in rows if row is not None]

    def _public(self, row):
        item_id = row["id"]
        data = {
            "id": item_id,
            "link": row["link"],
            "caption": row["caption"],
            "author": row["author"],
            "kind": row["kind"],
            "status": row["status"],
            "favorited_at": row["favorited_at"],
            "has_assets": bool(row["has_assets"]),
            "duration_s": row["duration_s"],
            "media_width": row["media_width"],
            "media_height": row["media_height"],
            "media_codec": row["media_codec"],
            "media_size": row["media_size"],
            "video_url": None,
            "images": [],
            "audio": None,
            "thumbnail_url": None,
        }
        if os.path.exists(os.path.join(self._download_dir, f"{item_id}.mp4")):
            data["video_url"] = f"/media/{item_id}.mp4"
        if row["has_assets"]:
            data.update(self._slideshow_assets(item_id))
        if row["thumbnail_path"]:
            data["thumbnail_url"] = f"/media/{row['thumbnail_path']}"
        return data

    def _slideshow_assets(self, item_id):
        folder = os.path.join(self._download_dir, str(item_id))
        if not os.path.isdir(folder):
            return {"images": [], "audio": None}
        names = sorted(os.listdir(folder))
        return {
            "images": [
                f"/media/{item_id}/{name}"
                for name in names
                if name.lower().endswith(_IMAGE_EXTS)
            ],
            "audio": f"/media/{item_id}/audio.mp3" if "audio.mp3" in names else None,
        }
