"""Container-tier smoke test for the multipart legacy bootstrap routes.

The normal host suite is dependency-free, so this file exits successfully
when FastAPI is unavailable. The Docker verification runs the full test.
"""
import asyncio
import json
import os
from types import SimpleNamespace
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from fastapi import UploadFile
except ModuleNotFoundError:
    UploadFile = None


def _make_export(path, favorites, section):
    rows = [{"Link": link, "Date": date} for link, date in reversed(favorites)]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({section: {"Favorite Videos": {"FavoriteVideoList": rows}}}, f)


def _upload(path):
    return UploadFile(open(path, "rb"), filename=os.path.basename(path))


def test_legacy_routes_preview_then_apply_with_container_dependencies():
    if UploadFile is None:
        return
    from core import store
    from server import api, jobs

    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "archive.db")
        downloads = os.path.join(d, "downloads")
        os.makedirs(downloads)
        store.init_db(store.connect(db_path)).close()
        old = [(f"https://tiktok.com/{n}", str(n)) for n in range(1, 6)]
        current = old + [("https://tiktok.com/6", "6")]
        old_path = os.path.join(d, "old.json")
        current_path = os.path.join(d, "current.json")
        checkpoint_path = os.path.join(d, "last_downloaded_link.txt")
        _make_export(old_path, old, "Activity")
        _make_export(current_path, current, "Likes and Favorites")
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            f.write("https://tiktok.com/5")
        for item_id in (8, 10):
            open(os.path.join(downloads, f"{item_id}.mp4"), "wb").close()

        state = SimpleNamespace(
            db_path=db_path,
            download_dir=downloads,
            jobs=jobs.JobManager(db_path, downloads, runners={}),
        )
        request = SimpleNamespace(app=SimpleNamespace(state=state))

        preview = asyncio.run(api.legacy_import_preview(
            request,
            _upload(old_path),
            _upload(current_path),
            _upload(checkpoint_path),
        ))
        assert preview["offset"] == 5
        assert preview["allocation"]["new_pending"] == 1

        result = asyncio.run(api.legacy_import_apply(
            request,
            _upload(old_path),
            _upload(current_path),
            _upload(checkpoint_path),
            preview["token"],
            "MIGRATE",
        ))
        assert result["local_done"] == 2
        assert result["legacy_gaps_ignored"] == 1
        assert result["new_pending"] == 1
        conn = store.connect(db_path)
        try:
            assert [row["id"] for row in store.page_items(conn, order="latest")] == [13, 10, 9, 8, 12, 11]
        finally:
            conn.close()


if __name__ == "__main__":
    if UploadFile is None:
        print("SKIP test_legacy_routes_preview_then_apply_with_container_dependencies (FastAPI unavailable)")
    else:
        test_legacy_routes_preview_then_apply_with_container_dependencies()
        print("PASS test_legacy_routes_preview_then_apply_with_container_dependencies")
