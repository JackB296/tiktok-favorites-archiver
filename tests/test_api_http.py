"""HTTP-tier tests: TestClient over ``create_app`` with an injected JobManager.

Exercises the routes end-to-end — status codes, the saved named-list trios,
busy-guard 409s, sync control dispatch, and the /media path-traversal guard —
with fake runners, so no requests/moviepy/ffmpeg are needed. Requires FastAPI
and httpx2 (present in the Docker image); on a bare host this file SKIPS loudly
but exits 0 so the stdlib-only suite stays green.
"""
import os
import sys
import tempfile
import threading
import json

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


def _client(app):
    return TestClient(app, headers={"X-Archive-Request": "1"})


def _build(tmp, runners=None):
    from core import store
    from server.jobs import JobManager
    from server.main import create_app

    db_path = os.path.join(tmp, "archive.db")
    downloads = os.path.join(tmp, "downloads")
    os.makedirs(downloads, exist_ok=True)
    store.init_db(store.connect(db_path)).close()
    jobs = JobManager(db_path, downloads, runners=runners or {"sync": lambda *a, **k: None})
    app = create_app(
        db_path=db_path,
        download_dir=downloads,
        jobs=jobs,
        allowed_hosts={"testserver"},
    )
    return app, jobs, db_path, downloads


def test_mutating_routes_require_browser_intent():
    if TestClient is None:
        return
    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, _db, _dl = _build(tmp)
        with TestClient(app) as client:
            assert client.get(
                "/api/status",
                headers={"Host": "evil.example"},
            ).status_code == 403
            assert client.post("/api/sync/unknown").status_code == 403
            assert client.post(
                "/api/sync/unknown",
                headers={"Origin": "https://evil.example"},
            ).status_code == 403
            same_origin = client.post(
                "/api/sync/unknown",
                headers={"Origin": "http://testserver"},
            )
            assert same_origin.status_code == 400
            marked = client.post(
                "/api/sync/unknown",
                headers={"X-Archive-Request": "1"},
            )
            assert marked.status_code == 400


def test_health_and_status_routes():
    if TestClient is None:
        return
    with tempfile.TemporaryDirectory() as tmp:
        app, jobs, _db, _dl = _build(tmp)
        with _client(app) as client:
            body = client.get("/api/status").json()
            assert body["state"] == "idle" and body["running"] is False
            assert client.get("/api/run-history").json() == []
            assert client.get("/api/incremental/stop-marker").status_code == 404
            # When the SPA is built, the absent POST falls through to the
            # static mount, which rejects unsupported methods with 405; on a
            # checkout without web/dist there is no mount and it is a plain 404.
            spa_built = os.path.isdir(
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "dist")
            )
            assert client.post("/api/incremental/import").status_code == (405 if spa_built else 404)


def test_comment_search_route_defaults_to_latest_and_can_include_history():
    if TestClient is None:
        return
    from core import store
    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, db_path, _dl = _build(tmp)
        conn = store.connect(db_path)
        try:
            item_id = store.insert_item(conn, 1, "https://www.tiktok.com/@maker/video/123")
            store.record_comment_snapshot(conn, item_id, [{"id": "a", "text": "old comet", "author_username": "alice"}], captured_at="2025-01-01T00:00:00Z")
            store.record_comment_snapshot(conn, item_id, [{"id": "b", "text": "new nebula", "author_username": "bob"}], captured_at="2025-02-01T00:00:00Z")
        finally:
            conn.close()
        with _client(app) as client:
            assert client.get("/api/comments/search", params={"q": "comet"}).json()["results"] == []
            response = client.get("/api/comments/search", params={"q": "comet", "history": "true"})
            assert response.status_code == 200
            assert response.json()["results"][0]["author_username"] == "alice"


def test_coverage_route_is_fast_to_read_and_repairs_current_gallery_filter():
    if TestClient is None:
        return
    from core import store
    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, db_path, _dl = _build(tmp)
        conn = store.connect(db_path)
        try:
            store.insert_item(conn, 1, "https://tiktok.com/1", status="done")
            store.insert_item(conn, 2, "https://tiktok.com/2", status="failed")
        finally:
            conn.close()
        with _client(app) as client:
            report = client.get("/api/coverage")
            assert report.status_code == 200 and report.json()["total_items"] == 2
            repair = client.post("/api/coverage/repair", json={
                "targets": ["comments"], "filter": {"status": "failed"},
            })
            assert repair.status_code == 200 and repair.json()["matched"] == 1


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
        with _client(app) as client:
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

        with _client(app) as client:
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


def test_items_page_search_scopes_and_rich_metadata_filters_are_http_queryable():
    if TestClient is None:
        return
    from core import store

    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, db_path, _dl = _build(tmp)
        conn = store.connect(db_path)
        store.insert_item(conn, 1, "https://tiktok.com/a", status="done")
        store.insert_item(conn, 2, "https://tiktok.com/b", status="done")
        store.record_comment_snapshot(conn, 1, [{"id": "c", "text": "celadon glaze"}])
        conn.execute(
            "UPDATE item SET source_posted_at = '2025-02-03', view_count = 100000, "
            "like_count = 5000, comment_count = 200, source_info_status = 'ok', "
            "comments_status = 'ok', download_source = 'yt-dlp', "
            "portable_metadata_status = 'ok' WHERE id = 1"
        )
        conn.commit()
        conn.close()

        with _client(app) as client:
            scoped = client.get("/api/items/page", params={
                "search": "celadon", "search_scope": "comments",
            })
            assert scoped.status_code == 200, scoped.text
            assert [item["id"] for item in scoped.json()["items"]] == [1]
            marked = client.post("/api/items/mark", json={
                "action": "offload", "dry_run": True,
                "filter": {"search": "celadon", "search_scope": "comments"},
            })
            assert marked.status_code == 200, marked.text
            assert marked.json()["matched"] == 1
            filtered = client.get("/api/items/page", params={
                "posted_from": "2025-01-01", "posted_to": "2025-12-31T23:59:59",
                "min_views": 10000, "min_likes": 1000, "min_comments": 100,
                "source_info": "saved", "comments_state": "with_comments",
                "download_source": "yt-dlp", "portable_metadata": "embedded",
            })
            assert filtered.status_code == 200, filtered.text
            assert [item["id"] for item in filtered.json()["items"]] == [1]
            preset = client.post("/api/gallery-presets", json={
                "name": "Rich local search",
                "filters": {
                    "search": "celadon", "searchScope": "comments",
                    "commentsState": "with_comments", "downloadSource": "yt-dlp",
                    "minViews": "10000", "postedFrom": "2025-01-01",
                },
            })
            assert preset.status_code == 200, preset.text
            preset_id = preset.json()["id"]
            assert client.get(f"/api/gallery-presets/{preset_id}/summary").json()["count"] == 1
            for key, value in (
                ("search_scope", "outside"), ("source_info", "maybe"),
                ("min_views", "-1"), ("comments_state", "unknown"),
            ):
                assert client.get("/api/items/page", params={key: value}).status_code == 400


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

        with _client(app) as client:
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
        with _client(app) as client:
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
        os.symlink(secret, os.path.join(downloads, "linked.txt"))

        with _client(app) as client:
            ok = client.get("/media/1.mp4")
            assert ok.status_code == 200 and ok.content == b"movie-bytes"
            ranged = client.get("/media/1.mp4", headers={"Range": "bytes=1-4"})
            assert ranged.status_code == 206
            assert ranged.content == b"ovie"
            assert ranged.headers["content-range"] == "bytes 1-4/11"

            assert client.get("/media/missing.mp4").status_code == 404
            linked = client.get("/media/linked.txt")
            assert linked.status_code == 403
            assert linked.content != b"keep out"
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

        with _client(app) as client:
            assert client.get("/media/.archive/uploads/staged.upload").status_code == 403
            assert client.get("/media/.archive/replaced/1.mp4").status_code == 403
            ok = client.get("/media/.archive/thumbnails/1.webp")
            assert ok.status_code == 200 and ok.content == b"thumb"


def test_local_lens_import_status_and_search_routes():
    if TestClient is None:
        return
    from core import store

    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, db_path, _downloads = _build(tmp)
        conn = store.connect(db_path)
        store.insert_item(
            conn, 1, "https://www.tiktok.com/@cook/video/1", status="done",
        )
        store.insert_item(
            conn, 2, "https://www.tiktok.com/@cook/video/2", status="done",
        )
        conn.close()
        document = {
            "items": [{"item_id": 1, "segments": [{
                "source": "transcript",
                "text": "Press the parmesan side down for crispy potatoes.",
                "start_s": 18,
                "end_s": 24,
            }]}],
        }

        with _client(app) as client:
            imported = client.post(
                "/api/lens/import",
                files={"file": ("analysis.json", json.dumps(document), "application/json")},
            )
            assert imported.status_code == 200, imported.text
            assert imported.json() == {"items": 1, "segments": 1}
            status = client.get("/api/lens/status").json()
            assert status["items"] == 1
            assert status["segments"] == 1
            assert status["coverage"]["eligible"] == 0
            assert set(status["tools"]) == {"speech", "ocr"}

            searched = client.get("/api/lens/search", params={"q": "crispy parmesan"})
            assert searched.status_code == 200, searched.text
            result = searched.json()["results"][0]
            assert result["item"]["id"] == 1
            assert result["source"] == "transcript"
            assert result["start_s"] == 18
            assert result["feed_url"] == "/?item=1&start_s=18"

            captions = client.get("/api/items/1/captions")
            assert captions.status_code == 200, captions.text
            assert captions.json() == {
                "item_id": 1,
                "captions": [{
                    "id": 1,
                    "item_id": 1,
                    "source": "transcript",
                    "text": "Press the parmesan side down for crispy potatoes.",
                    "start_s": 18.0,
                    "end_s": 24.0,
                }],
            }
            assert client.get("/api/items/2/captions").json() == {
                "item_id": 2,
                "captions": [],
            }
            assert client.get("/api/items/999/captions").status_code == 404

            bad = client.post(
                "/api/lens/import",
                files={"file": ("analysis.json", '{"items":"bad"}', "application/json")},
            )
            assert bad.status_code == 400
            refreshed = client.get("/api/lens/status").json()
            assert refreshed["items"] == 1 and refreshed["segments"] == 1


def test_local_analysis_is_default_pipeline_work_and_startable_in_app():
    if TestClient is None:
        return
    started = threading.Event()
    release = threading.Event()

    def analyze_runner(conn, download_dir, control=None):
        started.set()
        release.wait(3)

    with tempfile.TemporaryDirectory() as tmp:
        app, jobs, _db, _downloads = _build(
            tmp, runners={"analyze": analyze_runner},
        )
        with _client(app) as client:
            catalog = client.get("/api/run-catalog").json()
            analyze = next(entry for entry in catalog if entry["kind"] == "analyze")
            assert analyze["label"] == "Local analysis"
            assert analyze["resumable"] is True
            assert client.get("/api/pipeline-settings").json()["phases"][-1] == "analyze"

            assert client.post("/api/sync/analyze").json() == {"started": True}
            assert started.wait(3)
            try:
                assert client.get("/api/status").json()["phase"] == "analyze"
            finally:
                release.set()
                jobs._thread.join(3)


def test_manual_sidecar_recheck_refreshes_comment_snapshots():
    if TestClient is None:
        return
    received = []

    def sidecars_runner(conn, download_dir, control=None, recheck=False):
        received.append(recheck)

    with tempfile.TemporaryDirectory() as tmp:
        app, jobs, _db, _downloads = _build(
            tmp, runners={"sidecars": sidecars_runner},
        )
        with _client(app) as client:
            assert client.post("/api/sync/sidecars?recheck=1").json() == {"started": True}
            jobs._thread.join(3)

    assert received == [True]


def test_existing_silent_video_repair_is_startable_from_sync_controls():
    if TestClient is None:
        return
    ran = []

    def repair_runner(conn, download_dir, control=None):
        ran.append(download_dir)

    with tempfile.TemporaryDirectory() as tmp:
        app, jobs, _db, downloads = _build(
            tmp, runners={"audio-repair": repair_runner},
        )
        with _client(app) as client:
            assert client.post("/api/sync/repair-audio").json() == {"started": True}
            jobs._thread.join(3)

    assert ran == [downloads]


def test_archive_intelligence_history_and_memory_routes():
    if TestClient is None:
        return
    from core import layout, store

    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, db_path, downloads = _build(tmp)
        export_body = {
            "Activity": {"Favorite Videos": {"FavoriteVideoList": [
                {"Link": "https://tiktok.com/1", "Date": "2024-07-19 10:00:00"},
                {"Link": "https://tiktok.com/2", "Date": "2023-07-01 10:00:00"},
            ]}},
        }
        with _client(app) as client:
            imported = client.post(
                "/api/import",
                files={"file": ("user_data_tiktok.json", json.dumps(export_body), "application/json")},
            )
            assert imported.status_code == 200, imported.text
            record = imported.json()["import_record"]
            assert record["comparison"]["counts"]["new"] == 2
            assert client.get("/api/imports").json()[0]["id"] == record["id"]
            assert client.get(f"/api/imports/{record['id']}").json()["favorite_count"] == 2
            assert client.get("/api/imports/9999").status_code == 404

            conn = store.connect(db_path)
            for item_id in (1, 2):
                store.set_status(conn, item_id, "done")
                conn.execute(
                    "UPDATE item SET duration_s = 8, has_audio = 1 WHERE id = ?",
                    (item_id,),
                )
                with open(layout.movie(downloads, item_id), "wb") as target:
                    target.write(b"movie")
            conn.commit()
            conn.close()

            memories = client.get("/api/memories", params={"date": "2026-07-19"})
            assert memories.status_code == 200
            assert memories.json()["sections"][0]["item_ids"] == [2]
            assert client.post("/api/items/1/played").json()["play_count"] == 1
            assert client.post("/api/items/999/played").status_code == 404

def test_feed_ids_rejects_paging_keys_like_mark_does():
    if TestClient is None:
        return
    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, _db, _dl = _build(tmp)
        with _client(app) as client:
            assert client.get("/api/feed/ids").json() == []
            for key, value in (("limit", "5"), ("cursor", "3"), ("feed", "true")):
                response = client.get("/api/feed/ids", params={key: value})
                assert response.status_code == 400, (key, response.status_code)


def test_malformed_json_bodies_are_400_not_500():
    if TestClient is None:
        return
    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, _db, _dl = _build(tmp)
        with _client(app) as client:
            for path in ("/api/items/mark", "/api/items/requeue", "/api/items/selection",
                         "/api/gallery-presets"):
                response = client.post(path, content=b"{not json", headers={"Content-Type": "application/json"})
                assert response.status_code == 400, (path, response.status_code)


def test_library_settings_rejects_a_non_object_body():
    if TestClient is None:
        return
    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, _db, _dl = _build(tmp)
        with _client(app) as client:
            response = client.put("/api/library-settings", json=[1, 2])  # was a 500
            assert response.status_code == 400
            assert client.get("/api/library-stats").status_code == 200


def test_portable_metadata_setting_is_off_by_default_and_can_be_enabled():
    if TestClient is None:
        return
    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, _db, _dl = _build(tmp)
        with _client(app) as client:
            assert client.get("/api/library-settings").json()["portable_metadata_enabled"] == 0
            updated = client.put(
                "/api/library-settings", json={"portable_metadata_enabled": True},
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["portable_metadata_enabled"] == 1


def test_invalid_utf8_body_is_400_not_500():
    if TestClient is None:
        return
    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, _db, _dl = _build(tmp)
        with _client(app) as client:
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

        with _client(app) as client:
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

        with _client(app) as client:
            ok = client.post("/api/items/1/song", json={"title": "Track", "artist": "Artist"})
            assert ok.status_code == 200
            assert ok.json()["song"]["title"] == "Track"

            for bad in ({"title": 123}, {"title": "ok", "artist": {"x": 1}},
                        {"title": "ok", "key": 42}, {"title": ""}):
                response = client.post("/api/items/1/song", json=bad)
                assert response.status_code == 400, bad  # was a 500

            assert client.post("/api/items/999/song", json={"title": "T"}).status_code == 404


def _import_response(client, payload_bytes, selection=None):
    data = {"selection": selection} if selection else None
    return client.post(
        "/api/import",
        data=data,
        files={"file": ("user_data_tiktok.json", payload_bytes, "application/json")},
    )


def test_storage_location_crud_health_and_conflicts():
    if TestClient is None:
        return
    from core import store

    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as mounted:
        app, _jobs, db_path, _dl = _build(tmp)
        with _client(app) as client:
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

        with _client(app) as client:
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

        with _client(app) as client:
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
        with _client(app) as client:
            ok = _import_response(client, valid)
            assert ok.status_code == 200, ok.text
            assert ok.json()["favorites"] == 2

            malformed = _import_response(client, b"{not json")
            assert malformed.status_code == 400
            assert "Invalid export" in malformed.json()["detail"]

            wrong_shape = _import_response(client, jsonlib.dumps({"Activity": "text"}).encode())
            assert wrong_shape.status_code == 400  # was an AttributeError 500


def test_likes_profile_and_myfavett_import_routes_end_to_end():
    if TestClient is None:
        return
    from server import api as api_module
    from core import store

    export_bytes = json.dumps({"Activity": {
        "Favorite Videos": {"FavoriteVideoList": [{"Link": "favorite"}]},
        "Like List": {"ItemFavoriteList": [{"Link": "liked"}]},
    }}).encode()
    original_profile = api_module.profile_import.import_profile
    original_adopt = api_module.myfavett.adopt_video
    try:
        api_module.profile_import.import_profile = lambda conn, username, **_kwargs: {
            "username": str(username).lstrip("@"), "discovered": 2,
            "added": 2, "existing": 0, "item_ids": [3, 4],
        }

        def fake_adopt(_conn, _downloads, video_id, staged, source_path=None):
            assert os.path.isfile(staged)
            assert source_path.endswith(f"/{video_id}.mp4")
            return {"status": "imported", "item_id": 1, "created": False, "matched_slot": True}

        api_module.myfavett.adopt_video = fake_adopt
        with tempfile.TemporaryDirectory() as tmp:
            app, _jobs, db_path, _downloads = _build(tmp)
            with _client(app) as client:
                likes = _import_response(client, export_bytes, selection="likes")
                assert likes.status_code == 200, likes.text
                assert likes.json()["selection"] == "likes" and likes.json()["favorites"] == 1

                profile = client.post("/api/import/profile", json={
                    "username": "@cook", "start_sync": False,
                })
                assert profile.status_code == 200, profile.text
                assert profile.json()["username"] == "cook"
                assert profile.json()["sync_started"] is False

                conn = store.connect(db_path)
                try:
                    row = conn.execute("SELECT id FROM item WHERE link = 'liked'").fetchone()
                    item_id = row["id"]
                    conn.execute(
                        "UPDATE item SET link = ? WHERE id = ?",
                        ("https://www.tiktok.com/@gone/video/12345", item_id),
                    )
                    conn.commit()
                finally:
                    conn.close()

                plan = client.post("/api/import/myfavett/plan", json={"paths": [
                    "archive/data/Favorites/videos/12345.mp4",
                    "archive/data/Likes/covers/12345.jpg",
                ]})
                assert plan.status_code == 200, plan.text
                assert plan.json()["counts"]["matched_slots"] == 1

                adopted = client.post(
                    "/api/import/myfavett/video",
                    data={"video_id": "12345", "source_path": "archive/data/Favorites/videos/12345.mp4"},
                    files={"video": ("12345.mp4", b"\x00\x00\x00\x18ftypisomdata", "video/mp4")},
                )
                assert adopted.status_code == 200, adopted.text
                assert adopted.json()["matched_slot"] is True
    finally:
        api_module.profile_import.import_profile = original_profile
        api_module.myfavett.adopt_video = original_adopt


def test_creator_monitor_routes_add_pause_refresh_and_remove():
    if TestClient is None:
        return
    from server import api as api_module
    from core import store

    original = api_module.profile_import.monitor_profile
    try:
        def fake_monitor(conn, username, downloads, interval_hours=6, **_kwargs):
            normalized = str(username).lstrip("@")
            store.save_creator_monitor(conn, normalized, interval_hours=interval_hours)
            return {
                "username": normalized, "discovered": 3, "added": 3,
                "existing": 0, "item_ids": [1, 2, 3],
            }

        api_module.profile_import.monitor_profile = fake_monitor
        with tempfile.TemporaryDirectory() as tmp:
            app, _jobs, _db, _downloads = _build(tmp)
            with _client(app) as client:
                created = client.post("/api/import/profile", json={
                    "username": "@cook", "start_sync": False,
                    "monitor": True, "interval_hours": 12,
                })
                assert created.status_code == 200, created.text
                monitors = client.get("/api/creator-monitors").json()
                assert len(monitors) == 1 and monitors[0]["username"] == "cook"
                assert monitors[0]["interval_hours"] == 12

                monitor_id = monitors[0]["id"]
                paused = client.patch(
                    f"/api/creator-monitors/{monitor_id}",
                    json={"enabled": False, "interval_hours": 24},
                )
                assert paused.status_code == 200, paused.text
                assert paused.json()["enabled"] is False
                assert paused.json()["interval_hours"] == 24

                resumed = client.patch(
                    f"/api/creator-monitors/{monitor_id}", json={"enabled": True},
                )
                assert resumed.status_code == 200 and resumed.json()["enabled"] is True

                due = client.post(f"/api/creator-monitors/{monitor_id}/check")
                assert due.status_code == 200 and due.json()["queued"] is True
                assert client.delete(f"/api/creator-monitors/{monitor_id}").json() == {"ok": True}
                assert client.get("/api/creator-monitors").json() == []
    finally:
        api_module.profile_import.monitor_profile = original


def test_rich_source_metadata_route_returns_description_engagement_and_saved_comments():
    if TestClient is None:
        return
    from core import source_metadata, store

    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, db_path, downloads = _build(tmp)
        conn = store.connect(db_path)
        store.upsert_link(conn, "https://www.tiktok.com/@cook/video/123")
        source_metadata.archive(conn, downloads, 1, source_metadata.from_info({
            "id": "123", "title": "caption", "description": "the full description",
            "uploader": "cook", "channel": "Cook Display",
            "view_count": 100, "like_count": 10, "comment_count": 2,
            "comments": [{"id": "one", "author": "fan", "text": "Looks good"}],
        }))
        source_metadata.archive(conn, downloads, 1, source_metadata.from_info({
            "id": "123", "title": "caption", "description": "the full description",
            "uploader": "cook", "channel": "Cook Display",
            "view_count": 101, "like_count": 11, "comment_count": 3,
            "comments": [
                {"id": "one", "author": "fan", "text": "Looks good", "like_count": 2},
                {"id": "two", "author": "cook", "text": "Thanks"},
            ],
        }))
        conn.close()

        with _client(app) as client:
            item = client.get("/api/items/page", params={"limit": 1}).json()["items"][0]
            assert item["creator"]["key"] == "cook"
            assert item["description"] == "the full description"
            assert item["view_count"] == 101 and item["like_count"] == 11
            assert item["comments_status"] == "ok"
            details = client.get("/api/items/1/source-metadata")
            assert details.status_code == 200, details.text
            assert details.json()["comments"][0]["text"] == "Looks good"
            snapshots = details.json()["comment_snapshots"]
            assert len(snapshots) == 2
            assert snapshots[0]["changes"] == {"added": 1, "removed": 0, "changed": 1}
            assert snapshots[1]["comments"][0]["text"] == "Looks good"


def test_gallery_and_feed_filter_exactly_by_identified_song():
    if TestClient is None:
        return
    from core import store

    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, db_path, _dl = _build(tmp)
        conn = store.connect(db_path)
        for item_id in (1, 2, 3):
            store.insert_item(conn, item_id, f"https://tiktok.com/{item_id}", status="done")
        wanted = store.upsert_song(conn, "shazam:wanted", "Wanted", artist="Singer")
        other = store.upsert_song(conn, "shazam:other", "Other", artist="Singer")
        store.set_item_song(conn, 1, wanted)
        store.set_item_song(conn, 2, wanted)
        store.set_item_song(conn, 3, other)
        conn.close()

        with _client(app) as client:
            page = client.get("/api/items/page", params={"song": wanted}).json()
            assert [item["id"] for item in page["items"]] == [2, 1]
            assert all(item["song"]["id"] == wanted for item in page["items"])
            assert client.get("/api/feed/ids", params={"song": wanted}).json() == [2, 1]
            assert client.get("/api/items/page", params={"song": 0}).status_code == 400


def test_spotify_routes_cover_status_connect_and_guards():
    if TestClient is None:
        return

    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, _db, _dl = _build(tmp)
        with _client(app) as client:
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

        with _client(app) as client:
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

        with _client(app) as client:
            payload = client.get("/api/stats").json()
            assert payload["hero"]["total"] == 1
            assert payload["growth"]["monthly"] == [{"month": "2023-05", "count": 1}]
            assert set(payload) == {
                "hero", "growth", "watcher", "reach", "discovery_lag",
                "quality", "conversation", "monitoring", "top", "health",
            }
            assert payload["reach"]["peak_posts"] == []


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
        with _client(app) as client:
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
            assert client.get("/api/pipeline-settings").json()["phases"] == [
                "sync", "enrich", "sidecars", "identify", "analyze",
            ]
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


def test_archive_intelligence_feature_routes_work_together():
    if TestClient is None:
        return
    from core import store

    with tempfile.TemporaryDirectory() as tmp:
        app, _jobs, db_path, downloads = _build(tmp)
        conn = store.connect(db_path)
        for item_id, caption in (
            (1, "late night ramen cooking"),
            (2, "tiny kitchen pasta recipe"),
            (3, "mountain trail run"),
        ):
            store.insert_item(
                conn, item_id, f"https://tiktok.com/{item_id}",
                kind="video", status="done",
            )
            store.set_metadata(conn, item_id, caption, "owner")
        conn.close()
        for item_id, content in (
            (1, b"same-media"), (2, b"same-media"), (3, b"different"),
        ):
            with open(os.path.join(downloads, f"{item_id}.mp4"), "wb") as target:
                target.write(content)

        with _client(app) as client:
            saved = client.put("/api/items/1/annotation", json={
                "starred": True, "note": "make this",
                "tags": ["Recipe"], "reviewed": True,
            })
            assert saved.status_code == 200, saved.text
            assert saved.json()["tags"] == ["Recipe"]
            assert client.get("/api/items/1/annotation").json()["starred"] is True
            starred = client.get(
                "/api/items/page", params={"starred": "true"},
            ).json()
            assert [item["id"] for item in starred["items"]] == [1]
            tagged = client.get(
                "/api/items/page", params={"private_tag": "recipe"},
            ).json()
            assert [item["id"] for item in tagged["items"]] == [1]
            session = client.get(
                "/api/curate/session", params={"source": "unreviewed", "limit": 2},
            ).json()
            assert [item["id"] for item in session["items"]] == [3, 2]

            vibe = client.get(
                "/api/vibes/search", params={"q": "night ramen cooking"},
            )
            assert vibe.status_code == 200, vibe.text
            assert vibe.json()["results"][0]["item_id"] == 1
            related = client.get("/api/vibes/related/1").json()
            assert related["results"][0]["item_id"] == 2

            duplicate_report = client.post("/api/duplicates/scan")
            assert duplicate_report.status_code == 200, duplicate_report.text
            assert duplicate_report.json()["groups"][0]["item_ids"] == [1, 2]
            assert os.path.exists(os.path.join(downloads, "1.mp4"))

            preset = client.post("/api/gallery-presets", json={
                "name": "Recipes", "filters": {"search": "recipe"},
            }).json()
            channel = client.post("/api/channels", json={
                "name": "Recipe TV", "preset_id": preset["id"],
                "shuffle": False, "prefer_unwatched": True,
            })
            assert channel.status_code == 200, channel.text
            channel_id = channel.json()["id"]
            assert client.get(
                f"/api/channels/{channel_id}/items",
            ).json()["item_ids"] == [2]
            assert client.delete(
                f"/api/channels/{channel_id}",
            ).json() == {"ok": True}


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
