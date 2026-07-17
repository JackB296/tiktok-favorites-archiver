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
            assert client.get("/api/incremental/stop-marker").status_code == 404
            # The absent POST falls through to the SPA static mount, which
            # correctly rejects unsupported methods with 405.
            assert client.post("/api/incremental/import").status_code == 405


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


def test_storage_location_crud_health_and_conflicts():
    if TestClient is None:
        return
    from core import store

    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as mounted:
        app, _jobs, db_path, _dl = _build(tmp)
        with TestClient(app) as client:
            created = client.post(
                "/api/storage-locations", json={"name": "NAS", "path": mounted},
            )
            assert created.status_code == 200, created.text
            location = created.json()
            assert location["available"] is True
            assert client.get("/api/storage-locations").json()[0]["id"] == location["id"]

            renamed = client.patch(
                f"/api/storage-locations/{location['id']}", json={"name": "Archive NAS"},
            )
            assert renamed.status_code == 200
            assert renamed.json()["name"] == "Archive NAS"
            assert client.post(
                f"/api/storage-locations/{location['id']}/check"
            ).json()["available"] is True

            conn = store.connect(db_path)
            store.insert_item(conn, 1, "https://tiktok.com/1")
            store.record_media_placement(
                conn, 1, location["id"], "items/1", 1, "a" * 64, verified=True,
            )
            conn.close()
            assert client.delete(
                f"/api/storage-locations/{location['id']}"
            ).status_code == 409

            assert client.post(
                "/api/storage-locations", json={"name": "Bad", "path": _dl},
            ).status_code == 400
            assert client.patch("/api/storage-locations/999", json={"name": "x"}).status_code == 404
            assert client.delete("/api/storage-locations/999").status_code == 404


def test_storage_transfer_preview_rejects_stale_plan_and_runs_copy():
    if TestClient is None:
        return
    from core import storage, store

    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as mounted:
        app, jobs, db_path, downloads = _build(
            tmp, runners={"storage-copy": storage.run_copy},
        )
        conn = store.connect(db_path)
        location = storage.create_location(conn, "NAS", mounted, downloads, db_path)
        store.insert_item(conn, 1, "https://tiktok.com/1", status="done")
        conn.close()
        movie = os.path.join(downloads, "1.mp4")
        with open(movie, "wb") as target:
            target.write(b"first")

        with TestClient(app) as client:
            first = client.post("/api/storage-transfers/preview", json={
                "action": "copy", "location_id": location["id"], "ids": [1],
            })
            assert first.status_code == 200, first.text
            with open(movie, "wb") as target:
                target.write(b"changed after preview")
            stale = client.post(
                "/api/storage-transfers", json={"plan_id": first.json()["plan_id"]},
            )
            assert stale.status_code == 409

            preview = client.post("/api/storage-transfers/preview", json={
                "action": "copy", "location_id": location["id"], "ids": [1],
            }).json()
            started = client.post(
                "/api/storage-transfers", json={"plan_id": preview["plan_id"]},
            )
            assert started.status_code == 200, started.text
            jobs._thread.join(3)
            status = client.get(
                f"/api/storage-transfers/{started.json()['id']}"
            ).json()
            assert status["action"] == "copy"

        copied = os.path.join(mounted, "items", "1", "1.mp4")
        assert open(copied, "rb").read() == b"changed after preview"


def test_snapshot_create_list_validate_and_metadata_download():
    if TestClient is None:
        return
    import io
    import zipfile
    from core import snapshots, storage, store

    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as mounted:
        app, jobs, db_path, downloads = _build(
            tmp, runners={"snapshot": snapshots.run_create},
        )
        conn = store.connect(db_path)
        location = storage.create_location(conn, "NAS", mounted, downloads, db_path)
        store.insert_item(conn, 1, "https://tiktok.com/1")
        conn.close()

        with TestClient(app) as client:
            started = client.post("/api/snapshots", json={
                "location_id": location["id"], "name": "portable", "mode": "metadata",
            })
            assert started.status_code == 200, started.text
            jobs._thread.join(3)
            resources = client.get("/api/snapshots").json()
            assert len(resources) == 1 and resources[0]["state"] == "complete"
            snapshot_id = resources[0]["id"]
            assert client.post(f"/api/snapshots/{snapshot_id}/validate").json()["valid"] is True
            downloaded = client.get(f"/api/snapshots/{snapshot_id}/download")
            assert downloaded.status_code == 200
            with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
                names = archive.namelist()
                assert "snapshot.json" in names
                assert "database/archive.db" in names
                assert all(not name.startswith("/") and ".." not in name.split("/") for name in names)


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


def test_spotify_routes_cover_status_connect_and_guards():
    if TestClient is None:
        return

    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, _db, _dl = _build(tmp)
        with TestClient(app) as client:
            status = client.get("/api/spotify/status").json()
            assert status["connected"] is False
            assert status["redirect_uri"].endswith("/api/spotify/callback")

            # No client id anywhere yet: a clear 400, not a broken authorize URL.
            missing = client.post("/api/spotify/connect", json={})
            assert missing.status_code == 400

            ok = client.post("/api/spotify/connect", json={"client_id": "cid123"}).json()
            assert "accounts.spotify.com/authorize" in ok["authorize_url"]
            assert "code_challenge=" in ok["authorize_url"]
            assert client.get("/api/spotify/status").json()["client_id"] == "cid123"

            # A stale/forged callback never exchanges; it bounces to Music with an error.
            stale = client.get("/api/spotify/callback?code=x&state=wrong", follow_redirects=False)
            assert stale.status_code == 303
            assert "spotify_error" in stale.headers["location"]

            # Pushing without a connected account is a clear 400.
            created = client.post("/api/song-playlists", json={"name": "P", "song_ids": [1]})
            assert created.status_code == 200, created.text
            push = client.post(f"/api/song-playlists/{created.json()['id']}/push")
            assert push.status_code == 400
            assert "not connected" in push.json()["detail"]

            # A missing playlist is its own clear 400.
            gone = client.post("/api/song-playlists/9999/push")
            assert gone.status_code == 400
            assert "no longer exists" in gone.json()["detail"]

            disconnected = client.post("/api/spotify/disconnect").json()
            assert disconnected == {"connected": False}


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


def test_stats_route_returns_the_aggregate_payload():
    if TestClient is None:
        return
    from core import store

    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, db_path, _dl = _build(tmp)
        conn = store.connect(db_path)
        store.insert_item(conn, 1, "https://tiktok.com/a",
                          favorited_at="2023-05-01 10:00:00", kind="video", status="done")
        conn.close()

        with TestClient(app) as client:
            payload = client.get("/api/stats").json()
            assert payload["hero"]["total"] == 1
            assert payload["growth"]["monthly"] == [{"month": "2023-05", "count": 1}]
            assert set(payload) == {"hero", "growth", "watcher", "top", "health"}


def test_smart_collections_pipeline_schedules_and_discovery_routes():
    if TestClient is None:
        return
    from core import store

    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, db_path, _dl = _build(tmp)
        conn = store.connect(db_path)
        for item_id, caption, author in (
            (1, "#Cats first", "@Alice"),
            (2, "#Dogs", "@Bob"),
            (3, "#cats newest", "@Alice"),
        ):
            store.insert_item(conn, item_id, f"https://tiktok.com/{item_id}", status="done")
            store.set_metadata(conn, item_id, caption, author)
        conn.close()
        with TestClient(app) as client:
            created = client.post(
                "/api/gallery-presets",
                json={"name": "Cats", "filters": {"search": "cats", "order": "archive"}},
            ).json()
            preset = created["id"]
            assert client.get(f"/api/gallery-presets/{preset}/summary").json()["count"] == 2
            page = client.get(f"/api/gallery-presets/{preset}/items").json()
            assert [item["id"] for item in page["items"]] == [1, 3]
            assert client.get(f"/api/gallery-presets/{preset}/inventory").text.startswith("id,")
            preview = client.post(
                f"/api/gallery-presets/{preset}/mark",
                json={"action": "ignore", "dry_run": True},
            ).json()
            assert preview == {"matched": 2, "changed": 0, "dry_run": True}

            catalog = client.get("/api/run-catalog").json()
            assert any(entry["kind"] == "discovery-backfill" for entry in catalog)
            assert client.get("/api/pipeline-settings").json()["phases"] == ["sync", "enrich", "identify"]
            changed = client.put(
                "/api/pipeline-settings",
                json={"phases": ["sync", "identify", "enrich"]},
            )
            assert changed.status_code == 200
            assert changed.json()["phases"] == ["sync", "identify", "enrich"]
            assert client.put(
                "/api/pipeline-settings", json={"phases": ["enrich", "sync"]},
            ).status_code == 400

            schedule = client.post("/api/run-schedules", json={
                "name": "Nightly", "run_kind": "sync", "cadence": "daily",
                "local_time": "02:00", "weekday": None,
                "timezone": "America/New_York", "enabled": True,
            })
            assert schedule.status_code == 200, schedule.text
            schedule_id = schedule.json()["id"]
            assert client.patch(
                f"/api/run-schedules/{schedule_id}", json={"enabled": False},
            ).json()["enabled"] is False
            assert len(client.get("/api/run-schedules").json()) == 1
            assert client.delete(f"/api/run-schedules/{schedule_id}").json() == {"ok": True}

            creators = client.get("/api/creators", params={"q": "ali"}).json()
            assert creators["items"][0]["key"] == "alice"
            hashtags = client.get("/api/hashtags", params={"q": "#cat"}).json()
            assert hashtags["items"][0]["count"] == 2
            exact = client.get("/api/feed/ids", params={"creator": "alice"}).json()
            assert exact == [3, 1]


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
