"""Local Lens analysis import and search behavior."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import lens, store


def _archive():
    conn = store.init_db(store.connect(":memory:"))
    store.insert_item(conn, 1, "https://www.tiktok.com/@cook/video/1", status="done")
    store.insert_item(conn, 2, "https://www.tiktok.com/@home/video/2", status="done")
    return conn


def test_valid_analysis_import_is_searchable_with_timestamps_and_sources():
    conn = _archive()
    result = lens.import_document(conn, {
        "items": [
            {"item_id": 1, "segments": [
                {"source": "transcript", "text": "Press the parmesan side down for crispy potatoes.", "start_s": 18, "end_s": 24},
                {"source": "ocr", "text": "GARLIC BABY POTATOES", "start_s": 7},
            ]},
            {"item_id": 2, "segments": [
                {"source": "transcript", "text": "A calm apartment reset.", "start_s": 2},
            ]},
        ],
    })

    assert result == {"items": 2, "segments": 3}
    assert lens.status(conn) == {"items": 2, "segments": 3}
    matches = lens.search_segments(conn, "crispy parmesan")
    assert len(matches) == 1
    assert matches[0]["item_id"] == 1
    assert matches[0]["source"] == "transcript"
    assert matches[0]["start_s"] == 18
    assert matches[0]["end_s"] == 24
    assert "[[" in matches[0]["snippet"] and "]]" in matches[0]["snippet"]
    assert lens.search_segments(conn, "potatoes", source="ocr")[0]["start_s"] == 7
    assert lens.search_segments(conn, "potatoes", source="transcript")[0]["start_s"] == 18


def test_caption_segments_are_transcript_only_and_ordered():
    conn = _archive()
    lens.import_document(conn, {
        "items": [
            {"item_id": 1, "segments": [
                {"source": "transcript", "text": "Second caption", "start_s": 4, "end_s": 6},
                {"source": "ocr", "text": "Visible sign text", "start_s": 1, "end_s": 2},
                {"source": "transcript", "text": "First caption", "start_s": 0},
            ]},
        ],
    })

    captions = lens.caption_segments(conn, 1)
    assert [caption["text"] for caption in captions] == ["First caption", "Second caption"]
    assert [caption["start_s"] for caption in captions] == [0, 4]
    assert captions[0]["end_s"] is None
    assert all(caption["source"] == "transcript" for caption in captions)
    assert lens.caption_segments(conn, 2) == []

    try:
        lens.caption_segments(conn, 999)
    except lens.LensError as exc:
        assert "favorite not found" in str(exc)
    else:
        raise AssertionError("unknown favorite was accepted")


def test_reimport_replaces_only_the_included_items():
    conn = _archive()
    lens.import_document(conn, {"items": [
        {"item_id": 1, "segments": [{"source": "transcript", "text": "old one", "start_s": 0}]},
        {"item_id": 2, "segments": [{"source": "ocr", "text": "keep me", "start_s": 1}]},
    ]})

    lens.import_document(conn, {"items": [
        {"item_id": 1, "segments": [{"source": "transcript", "text": "new one", "start_s": 3}]},
    ]})

    assert lens.search_segments(conn, "old") == []
    assert lens.search_segments(conn, "new")[0]["item_id"] == 1
    assert lens.search_segments(conn, "keep")[0]["item_id"] == 2


def test_manual_import_marks_present_sources_authoritative_and_omitted_sources_missing():
    conn = _archive()
    lens.replace_generated_source(
        conn,
        1,
        "ocr",
        [{"source": "ocr", "text": "generated sign", "start_s": 1, "end_s": 3}],
        "100:1",
    )

    lens.import_document(conn, {"items": [
        {"item_id": 1, "segments": [
            {"source": "transcript", "text": "manual words", "start_s": 2},
        ]},
    ]})

    transcript = lens.source_state(conn, 1, "transcript")
    assert transcript["origin"] == "manual"
    assert transcript["status"] == "completed"
    assert lens.source_state(conn, 1, "ocr") is None
    assert lens.source_needs_analysis(conn, 1, "transcript", "100:1") is False
    assert lens.source_needs_analysis(conn, 1, "ocr", "100:1") is True
    assert lens.search_segments(conn, "generated") == []
    assert lens.search_segments(conn, "manual")[0]["source"] == "transcript"


def test_generated_sources_are_fingerprint_aware_and_never_replace_manual_evidence():
    conn = _archive()
    assert lens.source_needs_analysis(conn, 1, "ocr", "100:1") is True

    assert lens.replace_generated_source(
        conn,
        1,
        "ocr",
        [{"source": "ocr", "text": "first generated sign", "start_s": 1}],
        "100:1",
    ) is True
    state = lens.source_state(conn, 1, "ocr")
    assert state["origin"] == "generated"
    assert state["status"] == "completed"
    assert state["media_fingerprint"] == "100:1"
    assert lens.source_needs_analysis(conn, 1, "ocr", "100:1") is False
    assert lens.source_needs_analysis(conn, 1, "ocr", "101:2") is True

    lens.import_document(conn, {"items": [
        {"item_id": 1, "segments": [
            {"source": "ocr", "text": "hand corrected sign", "start_s": 3},
        ]},
    ]})
    assert lens.replace_generated_source(
        conn,
        1,
        "ocr",
        [{"source": "ocr", "text": "must not win", "start_s": 5}],
        "101:2",
    ) is False
    assert lens.search_segments(conn, "corrected")[0]["start_s"] == 3
    assert lens.search_segments(conn, "must") == []


def test_successful_empty_generated_source_is_remembered():
    conn = _archive()

    assert lens.replace_generated_source(
        conn, 1, "transcript", [], "100:1",
    ) is True

    assert lens.source_state(conn, 1, "transcript")["status"] == "completed"
    assert lens.source_needs_analysis(conn, 1, "transcript", "100:1") is False
    assert lens.caption_segments(conn, 1) == []


def test_invalid_or_unknown_item_documents_are_atomic():
    conn = _archive()
    lens.import_document(conn, {"items": [
        {"item_id": 1, "segments": [{"source": "transcript", "text": "existing text", "start_s": 0}]},
    ]})

    invalid_documents = [
        {"items": [
            {"item_id": 1, "segments": [{"source": "transcript", "text": "replacement", "start_s": 0}]},
            {"item_id": 99, "segments": [{"source": "ocr", "text": "unknown", "start_s": 0}]},
        ]},
        {"items": [
            {"item_id": 1, "segments": [{"source": "cloud", "text": "bad source", "start_s": 0}]},
        ]},
        {"items": [
            {"item_id": 1, "segments": [{"source": "ocr", "text": "bad time", "start_s": -1}]},
        ]},
    ]
    for document in invalid_documents:
        try:
            lens.import_document(conn, document)
        except lens.LensError:
            pass
        else:
            raise AssertionError("invalid Lens document was accepted")

    assert lens.status(conn) == {"items": 1, "segments": 1}
    assert lens.search_segments(conn, "existing")[0]["item_id"] == 1
    assert lens.search_segments(conn, "replacement") == []


def test_search_ignores_punctuation_only_queries_and_rejects_unknown_sources():
    conn = _archive()
    assert lens.search_segments(conn, "?! #") == []
    try:
        lens.search_segments(conn, "hello", source="captions")
    except lens.LensError as exc:
        assert "source" in str(exc)
    else:
        raise AssertionError("unknown source was accepted")


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
