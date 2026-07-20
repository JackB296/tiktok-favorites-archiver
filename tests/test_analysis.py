"""Fully local speech/OCR analysis behavior."""
import json
import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import analysis, lens, store


def _item(conn, item_id, *, status="done"):
    store.insert_item(
        conn, item_id, f"https://www.tiktok.com/@local/video/{item_id}",
        status=status,
    )


def test_whisper_json_becomes_bounded_transcript_segments():
    document = {
        "result": {"language": "en"},
        "transcription": [
            {
                "timestamps": {"from": "00:00:01.000", "to": "00:00:03.500"},
                "offsets": {"from": 1000, "to": 3500},
                "text": "  A crispy potato. ",
            },
            {
                "timestamps": {"from": "00:00:03.500", "to": "00:00:05.000"},
                "offsets": {"from": 3500, "to": 5000},
                "text": " ",
            },
        ],
    }

    assert analysis.parse_whisper_document(document) == [
        {
            "source": "transcript",
            "text": "A crispy potato.",
            "start_s": 1.0,
            "end_s": 3.5,
        },
    ]


def test_whisper_json_rejects_invalid_offsets_and_oversized_text():
    invalid = [
        {"transcription": [{"offsets": {"from": -1, "to": 2}, "text": "bad"}]},
        {"transcription": [{"offsets": {"from": 5, "to": 4}, "text": "bad"}]},
        {"transcription": [{"offsets": {"from": 0, "to": 1}, "text": "x" * 4001}]},
        {"transcription": "not a list"},
    ]

    for document in invalid:
        try:
            analysis.parse_whisper_document(document)
        except analysis.AnalysisError:
            pass
        else:
            raise AssertionError("invalid Whisper output was accepted")


def test_sampled_ocr_collapses_equivalent_text_and_discards_low_value_noise():
    samples = [
        (0.0, " GARLIC\nPOTATOES "),
        (2.0, "garlic potatoes"),
        (4.0, " — • — "),
        (6.0, "Garlic   potatoes"),
        (8.0, "400°F"),
    ]

    assert analysis.ocr_segments(samples, interval_s=2.0) == [
        {
            "source": "ocr",
            "text": "GARLIC POTATOES",
            "start_s": 0.0,
            "end_s": 4.0,
        },
        {
            "source": "ocr",
            "text": "Garlic potatoes",
            "start_s": 6.0,
            "end_s": 8.0,
        },
        {
            "source": "ocr",
            "text": "400°F",
            "start_s": 8.0,
            "end_s": 10.0,
        },
    ]


def test_eligible_items_include_only_readable_canonical_local_media():
    conn = store.init_db(store.connect(":memory:"))
    for item_id in range(1, 6):
        _item(conn, item_id, status="expired" if item_id == 4 else "done")
    store.set_offloaded(conn, [2])
    conn.execute("UPDATE item SET archive_missing = 1 WHERE id = 3")
    conn.commit()

    with tempfile.TemporaryDirectory() as downloads:
        for item_id in (1, 2, 3, 4):
            open(os.path.join(downloads, f"{item_id}.mp4"), "wb").close()

        assert [row["id"] for row in analysis.eligible_items(conn, downloads)] == [1]


def test_analyze_item_fills_only_missing_sources_and_skips_unchanged_work():
    conn = store.init_db(store.connect(":memory:"))
    _item(conn, 1)
    lens.import_document(conn, {"items": [{
        "item_id": 1,
        "segments": [
            {"source": "transcript", "text": "manual speech", "start_s": 0},
        ],
    }]})
    calls = []

    def unexpected_transcript(_path):
        raise AssertionError("manual transcript was passed to the generator")

    def recognize(_path):
        calls.append("ocr")
        return [{"source": "ocr", "text": "LOCAL SIGN", "start_s": 2}]

    with tempfile.TemporaryDirectory() as downloads:
        open(os.path.join(downloads, "1.mp4"), "wb").close()
        item = store.get_item(conn, 1)
        result = analysis.analyze_item(
            conn, downloads, item,
            transcribe=unexpected_transcript, recognize=recognize,
        )
        assert result == {
            "completed_sources": 1, "failed_sources": 0, "segments": 1,
        }
        assert calls == ["ocr"]
        assert lens.search_segments(conn, "manual")[0]["source"] == "transcript"
        assert lens.search_segments(conn, "local")[0]["source"] == "ocr"

        again = analysis.analyze_item(
            conn, downloads, item,
            transcribe=unexpected_transcript,
            recognize=lambda _path: (_ for _ in ()).throw(
                AssertionError("unchanged OCR was repeated")
            ),
        )
        assert again == {
            "completed_sources": 0, "failed_sources": 0, "segments": 0,
        }


def test_analyze_item_records_one_source_failure_and_keeps_the_other_source():
    conn = store.init_db(store.connect(":memory:"))
    _item(conn, 1)

    def fail_transcript(_path):
        raise analysis.AnalysisError("speech model unavailable")

    with tempfile.TemporaryDirectory() as downloads:
        open(os.path.join(downloads, "1.mp4"), "wb").close()
        result = analysis.analyze_item(
            conn,
            downloads,
            store.get_item(conn, 1),
            transcribe=fail_transcript,
            recognize=lambda _path: [
                {"source": "ocr", "text": "surviving text", "start_s": 1},
            ],
        )

    assert result == {
        "completed_sources": 1, "failed_sources": 1, "segments": 1,
    }
    failed = lens.source_state(conn, 1, "transcript")
    assert failed["origin"] == "generated"
    assert failed["status"] == "failed"
    assert failed["last_error"] == "speech model unavailable"
    assert lens.source_needs_analysis(
        conn, 1, "transcript", failed["media_fingerprint"],
    ) is True
    assert lens.search_segments(conn, "surviving")[0]["source"] == "ocr"


def test_transcribe_media_uses_fixed_local_commands_and_cleans_temporary_files():
    commands = []
    temporary_paths = []

    def runner(command, **_kwargs):
        commands.append(command)
        if command[0] == "ffprobe":
            return SimpleNamespace(stdout="0\n", stderr="")
        if command[0] == "ffmpeg":
            temporary_paths.append(command[-1])
            with open(command[-1], "wb") as target:
                target.write(b"wav")
        else:
            output_base = command[command.index("-of") + 1]
            output_path = f"{output_base}.json"
            temporary_paths.append(output_path)
            with open(output_path, "w", encoding="utf-8") as target:
                json.dump({
                    "transcription": [{
                        "offsets": {"from": 250, "to": 1250},
                        "text": " local words ",
                    }],
                }, target)
        return SimpleNamespace(stdout="", stderr="")

    result = analysis.transcribe_media(
        "/archive/17.mp4",
        runner=runner,
        whisper_bin="whisper-cli",
        model_path="/models/base.bin",
    )

    assert result[0]["text"] == "local words"
    assert commands[0][0] == "ffprobe"
    assert commands[1][0] == "ffmpeg"
    assert commands[2][0] == "whisper-cli"
    assert commands[2][commands[2].index("-m") + 1] == "/models/base.bin"
    assert commands[2][commands[2].index("-l") + 1] == "auto"
    assert all(not os.path.exists(path) for path in temporary_paths)


def test_transcribe_media_without_an_audio_stream_completes_empty():
    commands = []

    def runner(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(stdout="", stderr="")

    assert analysis.transcribe_media(
        "/archive/silent.mp4", runner=runner,
        whisper_bin="whisper-cli", model_path="/models/base.bin",
    ) == []
    assert len(commands) == 1
    assert commands[0][0] == "ffprobe"


def test_recognize_media_samples_bounded_frames_and_collapses_tesseract_text():
    commands = []

    def runner(command, **_kwargs):
        commands.append(command)
        if command[0] == "ffmpeg":
            pattern = command[-1]
            for number in range(1, 4):
                with open(pattern.replace("%06d", f"{number:06d}"), "wb") as frame:
                    frame.write(b"png")
            return SimpleNamespace(stdout="", stderr="")
        frame_name = os.path.basename(command[1])
        text = {
            "frame-000001.png": "DINNER\nTIME",
            "frame-000002.png": "dinner time",
            "frame-000003.png": "",
        }[frame_name]
        return SimpleNamespace(stdout=text, stderr="")

    segments = analysis.recognize_media(
        "/archive/17.mp4",
        runner=runner,
        tesseract_bin="tesseract",
        interval_s=2.0,
        max_frames=12,
    )

    assert segments == [{
        "source": "ocr", "text": "DINNER TIME",
        "start_s": 0.0, "end_s": 4.0,
    }]
    ffmpeg = commands[0]
    assert ffmpeg[ffmpeg.index("-frames:v") + 1] == "12"
    assert ffmpeg[ffmpeg.index("-vf") + 1] == "fps=1/2"
    assert all(command[0] == "tesseract" for command in commands[1:])


def test_analysis_run_skips_a_candidate_that_disappears_without_aborting():
    conn = store.init_db(store.connect(":memory:"))
    _item(conn, 1)
    _item(conn, 2)
    events = []

    with tempfile.TemporaryDirectory() as downloads:
        for item_id in (1, 2):
            open(os.path.join(downloads, f"{item_id}.mp4"), "wb").close()

        class Control:
            calls = 0
            def should_continue(self):
                self.calls += 1
                if self.calls == 2:
                    os.unlink(os.path.join(downloads, "2.mp4"))
                return True
            def progress(self, event):
                events.append(event)

        result = analysis.run_analysis(
            conn,
            downloads,
            control=Control(),
            transcribe=lambda _path: [],
            recognize=lambda _path: [],
        )

    assert result == {
        "completed": 2,
        "total": 2,
        "items_analyzed": 1,
        "completed_sources": 2,
        "failed_sources": 0,
        "segments": 0,
        "skipped": 1,
    }
    assert events[-1]["completed"] == events[-1]["total"] == 2
    assert events[-1]["skipped"] == 1


def test_coverage_distinguishes_manual_generated_pending_and_failed_sources():
    conn = store.init_db(store.connect(":memory:"))
    for item_id in (1, 2, 3):
        _item(conn, item_id)
    lens.import_document(conn, {"items": [{
        "item_id": 1,
        "segments": [
            {"source": "transcript", "text": "manual", "start_s": 0},
        ],
    }]})

    with tempfile.TemporaryDirectory() as downloads:
        for item_id in (1, 2, 3):
            open(os.path.join(downloads, f"{item_id}.mp4"), "wb").close()
        fingerprint = analysis.media_index.file_fingerprint(
            os.path.join(downloads, "2.mp4")
        )
        for source in ("transcript", "ocr"):
            lens.replace_generated_source(conn, 2, source, [], fingerprint)
        item3_fingerprint = analysis.media_index.file_fingerprint(
            os.path.join(downloads, "3.mp4")
        )
        lens.record_generated_failure(
            conn, 3, "transcript", item3_fingerprint, "model failed",
        )
        lens.replace_generated_source(conn, 3, "ocr", [], item3_fingerprint)

        assert analysis.coverage(conn, downloads) == {
            "eligible": 3,
            "transcript": {
                "complete": 2, "manual": 1, "generated": 1,
                "pending": 1, "failed": 1,
            },
            "ocr": {
                "complete": 2, "manual": 0, "generated": 2,
                "pending": 1, "failed": 0,
            },
        }


def test_tool_readiness_requires_local_binaries_and_the_speech_model():
    found = {
        "ffmpeg": "/bin/ffmpeg",
        "ffprobe": "/bin/ffprobe",
        "whisper-cli": "/bin/whisper-cli",
        "tesseract": "/bin/tesseract",
    }
    ready = analysis.tool_readiness(
        which=found.get,
        is_file=lambda path: path == "/models/base.bin",
        whisper_bin="whisper-cli",
        model_path="/models/base.bin",
        tesseract_bin="tesseract",
    )
    assert ready == {
        "speech": {"available": True, "error": None},
        "ocr": {"available": True, "error": None},
    }

    missing = analysis.tool_readiness(
        which=lambda _name: None,
        is_file=lambda _path: False,
        whisper_bin="whisper-cli",
        model_path="/models/missing.bin",
        tesseract_bin="tesseract",
    )
    assert missing["speech"]["available"] is False
    assert "Whisper" in missing["speech"]["error"]
    assert missing["ocr"]["available"] is False
    assert "Tesseract" in missing["ocr"]["error"]


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
