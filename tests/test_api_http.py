"""HTTP-tier tests: TestClient over ``create_app`` with an injected JobManager.

Exercises the routes end-to-end — status codes, the saved named-list trios,
busy-guard 409s, sync control dispatch, and the /media path-traversal guard —
with fake runners, so no requests/moviepy/ffmpeg are needed. Requires FastAPI
and httpx (present in the Docker image); on a bare host this file SKIPS loudly
but exits 0 so the stdlib-only suite stays green.
"""
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:
    TestClient = None
    if "pytest" in sys.modules:  # visible skip instead of vacuous green
        import pytest
        pytest.skip("fastapi/httpx not installed — full run happens in the container",
                    allow_module_level=True)


def _skip():
    print("SKIP test_api_http (fastapi/httpx not installed — full run happens in the container)")
    return True


def _build(tmp, runners=None):
    from core import store
    from server.jobs import JobManager
    from server.main import create_app

    db_path = os.path.join(tmp, "archive.db")
    downloads = os.path.join(tmp, "downloads")
    os.makedirs(downloads, exist_ok=True)
    store.init_db(store.connect(db_path)).close()
    jobs = JobManager(db_path, downloads, runners=runners or {"sync": lambda *a, **k: None})
    app = create_app(db_path=db_path, download_dir=downloads, jobs=jobs)
    return app, jobs, db_path, downloads


def test_health_and_status_routes():
    if TestClient is None:
        return
    with tempfile.TemporaryDirectory() as tmp:
        app, jobs, _db, _dl = _build(tmp)
        with TestClient(app) as client:
            body = client.get("/api/status").json()
            assert body["state"] == "idle" and body["running"] is False
            assert client.get("/api/run-history").json() == []


def test_saved_list_trios_roundtrip_for_all_four_collections():
    if TestClient is None:
        return
    cases = [
        ("gallery-presets", {"name": "Games", "filters": {"search": "games"}}, "filters"),
        ("gallery-term-lists", {"name": "No FYP", "mode": "exclude", "terms": ["#fyp"]}, "terms"),
        ("playback-queues", {"name": "Weekend", "item_ids": [3, 1]}, "item_ids"),
        ("song-playlists", {"name": "Drive", "song_ids": [1]}, "song_ids"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, _db, _dl = _build(tmp)
        with TestClient(app) as client:
            for resource, payload, field in cases:
                created = client.post(f"/api/{resource}", json=payload)
                assert created.status_code == 200, (resource, created.text)
                entry = created.json()
                assert entry["name"] == payload["name"]
                assert entry[field] == payload[field]

                listed = client.get(f"/api/{resource}").json()
                assert [e["id"] for e in listed] == [entry["id"]]

                # Duplicate name -> 409; bad body -> 400; unknown id -> 404.
                assert client.post(f"/api/{resource}", json=payload).status_code == 409
                assert client.post(f"/api/{resource}", json={"name": ""}).status_code == 400
                assert client.delete(f"/api/{resource}/9999").status_code == 404
                assert client.delete(f"/api/{resource}/{entry['id']}").json() == {"ok": True}
                assert client.get(f"/api/{resource}").json() == []


def test_items_page_and_mark_and_requeue():
    if TestClient is None:
        return
    from core import store

    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, db_path, _dl = _build(tmp)
        conn = store.connect(db_path)
        store.insert_item(conn, 1, "https://tiktok.com/a", status="failed")
        store.insert_item(conn, 2, "https://tiktok.com/b", status="done")
        conn.close()

        with TestClient(app) as client:
            page = client.get("/api/items/page", params={"status": "failed"}).json()
            assert [item["id"] for item in page["items"]] == [1]

            assert client.get("/api/items/page", params={"nope": "x"}).status_code == 400

            marked = client.post("/api/items/mark", json={"action": "ignore", "ids": [1]}).json()
            assert marked == {"matched": 1, "changed": 1}

            bad = client.post("/api/items/mark", json={"action": "vanish", "ids": [1]})
            assert bad.status_code == 400

            requeued = client.post("/api/items/requeue", json={"ids": [2]}).json()
            assert requeued["requeued"] == [2]  # done + no file -> back to pending

            assert client.post("/api/items/requeue", json={"ids": []}).status_code == 400


def test_mutating_routes_refuse_while_a_run_is_active():
    if TestClient is None:
        return
    release = threading.Event()
    started = threading.Event()

    def blocking_runner(conn, download_dir, control=None):
        started.set()
        release.wait(3)

    with tempfile.TemporaryDirectory() as tmp:
        app, jobs, db_path, _dl = _build(tmp, runners={"sync": blocking_runner})
        from core import store
        conn = store.connect(db_path)
        store.insert_item(conn, 1, "https://tiktok.com/a", status="failed")
        conn.close()

        with TestClient(app) as client:
            assert client.post("/api/sync/start").json()["started"] is True
            assert started.wait(3)
            try:
                busy_mark = client.post("/api/items/mark", json={"action": "ignore", "ids": [1]})
                busy_requeue = client.post("/api/items/requeue", json={"ids": [1]})
                busy_verify = client.post("/api/verify/requeue")
                assert busy_mark.status_code == 409, busy_mark.text
                assert busy_requeue.status_code == 409
                assert busy_verify.status_code == 409
                assert client.post("/api/sync/start").json()["started"] is False  # single-run guard
            finally:
                release.set()
                jobs._thread.join(3)


def test_sync_control_dispatch_and_stop_precedence():
    if TestClient is None:
        return
    release = threading.Event()
    started = threading.Event()

    def blocking_runner(conn, download_dir, control=None):
        started.set()
        release.wait(3)

    with tempfile.TemporaryDirectory() as tmp:
        app, jobs, _db, _dl = _build(tmp, runners={"sync": blocking_runner})
        with TestClient(app) as client:
            assert client.post("/api/sync/unknown").status_code == 400

            assert client.post("/api/sync/start").json()["started"] is True
            assert started.wait(3)
            try:
                assert client.post("/api/sync/pause").status_code == 200
                assert client.get("/api/status").json()["state"] == "paused"
                assert client.post("/api/sync/continue").status_code == 200
                assert client.post("/api/sync/stop").status_code == 200
                # Stop is not cancellable by pause/continue (409 from the store guard).
                assert client.post("/api/sync/pause").status_code == 409
            finally:
                release.set()
                jobs._thread.join(3)


def test_media_route_blocks_path_traversal_and_serves_files():
    if TestClient is None:
        return
    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, _db, downloads = _build(tmp)
        with open(os.path.join(downloads, "1.mp4"), "wb") as f:
            f.write(b"movie-bytes")
        secret = os.path.join(tmp, "secret.txt")
        with open(secret, "w") as f:
            f.write("keep out")

        with TestClient(app) as client:
            ok = client.get("/media/1.mp4")
            assert ok.status_code == 200 and ok.content == b"movie-bytes"

            assert client.get("/media/missing.mp4").status_code == 404
            # Traversal out of the download dir must 403/404, never 200.
            # (A raw "/media/../secret.txt" is normalized by the CLIENT before
            # it is sent, so only percent-encoded probes exercise the guard.)
            for probe in ("/media/%2e%2e/secret.txt", "/media/..%2fsecret.txt",
                          "/media/%2e%2e%2fsecret.txt"):
                response = client.get(probe)
                assert response.status_code in (403, 404), (probe, response.status_code)
                assert response.content != b"keep out", probe


def test_media_route_never_serves_internal_archive_areas():
    if TestClient is None:
        return
    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, _db, downloads = _build(tmp)
        # Internal areas: staged uploads and replaced-video backups.
        for sub in (("uploads", "staged.upload"), ("replaced", "1.mp4")):
            os.makedirs(os.path.join(downloads, ".archive", sub[0]), exist_ok=True)
            with open(os.path.join(downloads, ".archive", *sub), "wb") as f:
                f.write(b"internal")
        # Thumbnails must stay servable.
        os.makedirs(os.path.join(downloads, ".archive", "thumbnails"), exist_ok=True)
        with open(os.path.join(downloads, ".archive", "thumbnails", "1.webp"), "wb") as f:
            f.write(b"thumb")

        with TestClient(app) as client:
            assert client.get("/media/.archive/uploads/staged.upload").status_code == 403
            assert client.get("/media/.archive/replaced/1.mp4").status_code == 403
            ok = client.get("/media/.archive/thumbnails/1.webp")
            assert ok.status_code == 200 and ok.content == b"thumb"


def test_feed_ids_rejects_paging_keys_like_mark_does():
    if TestClient is None:
        return
    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, _db, _dl = _build(tmp)
        with TestClient(app) as client:
            assert client.get("/api/feed/ids").json() == []
            for key, value in (("limit", "5"), ("cursor", "3"), ("feed", "true")):
                response = client.get("/api/feed/ids", params={key: value})
                assert response.status_code == 400, (key, response.status_code)


def test_malformed_json_bodies_are_400_not_500():
    if TestClient is None:
        return
    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, _db, _dl = _build(tmp)
        with TestClient(app) as client:
            for path in ("/api/items/mark", "/api/items/requeue", "/api/items/selection",
                         "/api/gallery-presets"):
                response = client.post(path, content=b"{not json", headers={"Content-Type": "application/json"})
                assert response.status_code == 400, (path, response.status_code)


def test_library_settings_rejects_a_non_object_body():
    if TestClient is None:
        return
    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, _db, _dl = _build(tmp)
        with TestClient(app) as client:
            response = client.put("/api/library-settings", json=[1, 2])  # was a 500
            assert response.status_code == 400
            assert client.get("/api/library-stats").status_code == 200


def test_invalid_utf8_body_is_400_not_500():
    if TestClient is None:
        return
    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, _db, _dl = _build(tmp)
        with TestClient(app) as client:
            response = client.post("/api/items/mark", content=b'\xff\xfe{"a": 1}',
                                   headers={"Content-Type": "application/json"})
            assert response.status_code == 400  # UnicodeDecodeError path


def test_items_selection_projects_in_request_order():
    if TestClient is None:
        return
    from core import store

    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, db_path, downloads = _build(tmp)
        conn = store.connect(db_path)
        for n in (1, 2, 3):
            store.insert_item(conn, n, f"https://tiktok.com/{n}", status="done")
        conn.close()
        with open(os.path.join(downloads, "2.mp4"), "wb") as f:
            f.write(b"m")

        with TestClient(app) as client:
            got = client.post("/api/items/selection", json={"ids": [3, 1, 2, 999]}).json()
            assert [item["id"] for item in got] == [3, 1, 2]  # order kept, missing dropped
            by_id = {item["id"]: item for item in got}
            assert by_id[2]["video_url"] is not None
            assert by_id[1]["video_url"] is None
            assert client.post("/api/items/selection", json={"ids": []}).json() == []


def test_manual_song_attach_validates_field_types():
    if TestClient is None:
        return
    from core import store

    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, db_path, _dl = _build(tmp)
        conn = store.connect(db_path)
        store.insert_item(conn, 1, "https://tiktok.com/a", status="done")
        conn.close()

        with TestClient(app) as client:
            ok = client.post("/api/items/1/song", json={"title": "Track", "artist": "Artist"})
            assert ok.status_code == 200
            assert ok.json()["song"]["title"] == "Track"

            for bad in ({"title": 123}, {"title": "ok", "artist": {"x": 1}},
                        {"title": "ok", "key": 42}, {"title": ""}):
                response = client.post("/api/items/1/song", json=bad)
                assert response.status_code == 400, bad  # was a 500

            assert client.post("/api/items/999/song", json={"title": "T"}).status_code == 404


def _import_response(client, payload_bytes):
    return client.post(
        "/api/import",
        files={"file": ("user_data_tiktok.json", payload_bytes, "application/json")},
    )


def test_import_upload_end_to_end():
    """First multipart coverage: a valid export imports; unusable ones 400
    (malformed JSON used to silently succeed with zero favorites, and a
    wrong-shape export used to 500)."""
    if TestClient is None:
        return
    import json as jsonlib

    valid = jsonlib.dumps({"Activity": {"Favorite Videos": {"FavoriteVideoList": [
        {"Link": "https://www.tiktokv.com/a", "Date": "2025-01-01"},
        {"Link": "https://www.tiktok.com/b", "Date": "2025-01-02"},
    ]}}}).encode()

    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, _db, _dl = _build(tmp)
        with TestClient(app) as client:
            ok = _import_response(client, valid)
            assert ok.status_code == 200, ok.text
            assert ok.json()["favorites"] == 2

            malformed = _import_response(client, b"{not json")
            assert malformed.status_code == 400
            assert "Invalid export" in malformed.json()["detail"]

            wrong_shape = _import_response(client, jsonlib.dumps({"Activity": "text"}).encode())
            assert wrong_shape.status_code == 400  # was an AttributeError 500


def test_verify_and_library_stats_routes():
    if TestClient is None:
        return
    from core import store

    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, db_path, _dl = _build(tmp)
        conn = store.connect(db_path)
        store.insert_item(conn, 1, "https://tiktok.com/a", status="done")  # file missing
        conn.close()

        with TestClient(app) as client:
            report = client.get("/api/verify").json()
            assert report["ok"] is False
            assert report["missing"]["count"] == 1

            requeued = client.post("/api/verify/requeue").json()
            assert requeued == {"requeued": 1}


if __name__ == "__main__":
    import traceback
    if TestClient is None:
        _skip()
        raise SystemExit(0)
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failures += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failures else 0)
