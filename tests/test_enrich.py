"""Tests for core.enrich — oEmbed parse + enrich loop (no network needed)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import store, enrich, cobalt


def test_parse_oembed():
    assert enrich.parse_oembed({"title": "hi #cats", "author_name": "Someone"}) == ("hi #cats", "Someone")
    assert enrich.parse_oembed({}) == (None, None)
    assert enrich.parse_oembed(None) == (None, None)


def test_fetch_metadata_graceful_on_failure():
    def raiser(link):
        raise ConnectionError("down")
    assert enrich.fetch_metadata("x", getter=raiser) == (None, None)
    assert enrich.fetch_metadata("x", getter=lambda l: None) == (None, None)


def test_enrich_items_updates_and_skips():
    conn = store.init_db(store.connect(":memory:"))
    store.upsert_link(conn, "https://tiktok.com/a")   # id 1
    store.upsert_link(conn, "https://tiktok.com/b")   # id 2
    store.insert_item(conn, 3, "local://file/3", status="done")  # synthetic -> skipped

    data = {
        "https://tiktok.com/a": {"title": "caption A #x", "author_name": "alice"},
        "https://tiktok.com/b": {},  # oEmbed returned nothing useful
    }
    # A no-op limiter (max_calls large) so acquire() never blocks.
    limiter = cobalt.RateLimiter(1000, period=1000, now=lambda: 0.0, sleep=lambda s: None)
    n = enrich.enrich_items(conn, getter=lambda link: data.get(link), limiter=limiter)

    assert n == 1
    assert store.get_item(conn, 1)["caption"] == "caption A #x"
    assert store.get_item(conn, 1)["author"] == "alice"
    assert store.get_item(conn, 2)["caption"] is None      # nothing to store
    assert store.get_item(conn, 3)["caption"] is None      # local:// never fetched


def test_enrich_is_idempotent_for_captioned():
    conn = store.init_db(store.connect(":memory:"))
    store.upsert_link(conn, "https://tiktok.com/a")
    store.set_metadata(conn, 1, "already", "bob")
    calls = []
    enrich.enrich_items(conn, getter=lambda link: calls.append(link) or {"title": "new"},
                        limiter=cobalt.RateLimiter(1000, 1000, now=lambda: 0.0, sleep=lambda s: None))
    assert calls == []  # item already has a caption -> not re-fetched


def test_enrichment_job_reports_progress_and_stops_between_items():
    conn = store.init_db(store.connect(":memory:"))
    store.upsert_link(conn, "https://tiktok.com/a")
    store.upsert_link(conn, "https://tiktok.com/b")
    store.set_run_state(conn, state="running", phase="enrich")
    events = []

    def getter(link):
        store.set_run_state(conn, state="stopping")
        return {"title": "first caption"}

    limiter = cobalt.RateLimiter(1000, 1000, now=lambda: 0.0, sleep=lambda s: None)
    result = enrich.run_enrichment(conn, ".", getter=getter, limiter=limiter, progress=events.append)

    assert result == 1
    assert store.get_item(conn, 1)["caption"] == "first caption"
    assert store.get_item(conn, 2)["caption"] is None
    assert {
        key: events[0][key]
        for key in ("event", "completed", "total", "enriched", "unavailable")
    } == {"event": "enrichment", "completed": 0, "total": 2, "enriched": 0, "unavailable": 0}
    assert events[-1]["event"] == "enrichment"
    assert events[-1]["completed"] == 1
    assert events[-1]["enriched"] == 1
    assert events[-1]["unavailable"] == 0


def test_unavailable_items_are_skipped_by_default_but_retried_on_recheck():
    # The fix for "get metadata re-tries all 6803 every run": an item that came
    # back with no oEmbed metadata is marked 'unavailable' and skipped by the
    # automatic (Sync-chained) run, but an explicit backfill (recheck) retries it.
    conn = store.init_db(store.connect(":memory:"))
    store.upsert_link(conn, "https://tiktok.com/a")   # id 1
    limiter = cobalt.RateLimiter(1000, 1000, now=lambda: 0.0, sleep=lambda s: None)

    # First pass: oEmbed returns nothing -> marked 'unavailable'.
    first = []
    enrich.enrich_items(conn, getter=lambda link: first.append(link) or None, limiter=limiter)
    assert first == ["https://tiktok.com/a"]
    assert store.get_item(conn, 1)["enrich_status"] == "unavailable"

    # Automatic re-run: the unavailable item is not re-fetched.
    again = []
    enrich.enrich_items(conn, getter=lambda link: again.append(link) or None, limiter=limiter)
    assert again == []
    assert enrich.items_needing_enrichment(conn) == []

    # Backfill (recheck=True): it is retried, and this time metadata exists.
    backfilled = []
    n = enrich.enrich_items(
        conn,
        getter=lambda link: backfilled.append(link) or {"title": "found now", "author_name": "amy"},
        limiter=limiter, recheck=True,
    )
    assert backfilled == ["https://tiktok.com/a"]
    assert n == 1
    assert store.get_item(conn, 1)["caption"] == "found now"
    assert store.get_item(conn, 1)["enrich_status"] == "ok"


def test_new_items_are_still_enriched_after_others_marked_unavailable():
    # A brand-new favorite (never attempted) is picked up by the automatic run
    # even while previously-failed items are correctly skipped.
    conn = store.init_db(store.connect(":memory:"))
    store.upsert_link(conn, "https://tiktok.com/old")   # id 1 -> will be unavailable
    limiter = cobalt.RateLimiter(1000, 1000, now=lambda: 0.0, sleep=lambda s: None)
    enrich.enrich_items(conn, getter=lambda link: None, limiter=limiter)
    assert store.get_item(conn, 1)["enrich_status"] == "unavailable"

    store.upsert_link(conn, "https://tiktok.com/new")   # id 2 -> never attempted
    fetched = []
    enrich.enrich_items(
        conn,
        getter=lambda link: fetched.append(link) or {"title": "fresh", "author_name": "ned"},
        limiter=limiter,
    )
    assert fetched == ["https://tiktok.com/new"]        # only the new one, not the unavailable one
    assert store.get_item(conn, 2)["caption"] == "fresh"


def test_enrichment_progress_counts_links_that_return_no_metadata():
    conn = store.init_db(store.connect(":memory:"))
    store.upsert_link(conn, "https://tiktok.com/a")
    events = []
    limiter = cobalt.RateLimiter(1000, 1000, now=lambda: 0.0, sleep=lambda s: None)

    enrich.enrich_items(conn, getter=lambda _link: None, limiter=limiter, progress=events.append)

    assert events[-1]["completed"] == 1
    assert events[-1]["enriched"] == 0
    assert events[-1]["unavailable"] == 1


if __name__ == "__main__":
    import traceback
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
