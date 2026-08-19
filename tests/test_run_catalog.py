"""Archive run catalog is the single source for names, workers, and pipelines."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import run_catalog, store


def test_catalog_contains_every_existing_user_run_and_action_name():
    assert set(run_catalog.kinds()) == {
        "sync", "creator-monitor", "backfill", "index", "sidecars", "audio-repair", "enrich", "identify", "analyze",
        "storage-copy", "storage-move", "storage-restore",
        "snapshot",
        "snapshot-restore",
        "discovery-backfill",
        "verify", "coverage-repair", "creator-followups",
    }
    assert {
        action: run_catalog.kind_for_action(action)
        for action in (
            "start", "backfill", "reindex", "sidecars", "enrich", "identify",
            "analyze", "repair-audio", "discovery",
        )
    } == {
        "start": "sync",
        "backfill": "backfill",
        "reindex": "index",
        "sidecars": "sidecars",
        "enrich": "enrich",
        "identify": "identify",
        "analyze": "analyze",
        "repair-audio": "audio-repair",
        "discovery": "discovery-backfill",
    }


def test_sync_pipeline_and_default_workers_live_in_the_catalog():
    assert run_catalog.pipeline_for("sync") == (
        "sync", "enrich", "sidecars", "identify", "analyze",
    )
    assert run_catalog.pipeline_for("creator-monitor") == ("creator-monitor", "sync", "creator-followups")
    assert run_catalog.pipeline_for("backfill") == ("backfill",)
    assert set(run_catalog.default_runners()) == set(run_catalog.kinds())


def test_followup_eligibility_preserves_enrich_and_identify_rules():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://x/1", status="done")

    assert run_catalog.has_work(conn, "enrich") is True
    assert run_catalog.has_work(conn, "identify") is False
    store.set_library_settings(conn, song_id_enabled=True)
    assert run_catalog.has_work(conn, "identify") is True


def test_analysis_followup_requires_unprocessed_readable_local_media():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://x/1", status="done")
    with tempfile.TemporaryDirectory() as downloads:
        assert run_catalog.has_work(conn, "analyze", downloads) is False
        open(os.path.join(downloads, "1.mp4"), "wb").close()
        assert run_catalog.has_work(conn, "analyze", downloads) is True


def test_audio_repair_work_requires_an_indexed_silent_local_video():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://x/1", status="done")
    conn.execute("UPDATE item SET has_audio = 1, audio_silent = 1 WHERE id = 1")
    conn.commit()
    with tempfile.TemporaryDirectory() as downloads:
        assert run_catalog.has_work(conn, "audio-repair", downloads) is False
        open(os.path.join(downloads, "1.mp4"), "wb").close()
        assert run_catalog.has_work(conn, "audio-repair", downloads) is True


def test_unknown_names_are_rejected_consistently():
    for operation in (
        lambda: run_catalog.get("nope"),
        lambda: run_catalog.pipeline_for("nope"),
        lambda: run_catalog.kind_for_action("nope"),
    ):
        try:
            operation()
        except ValueError as exc:
            assert "unknown" in str(exc)
        else:
            raise AssertionError("unknown run was accepted")


if __name__ == "__main__":
    import traceback

    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception:
            failures += 1
            print(f"FAIL {test.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failures else 0)
