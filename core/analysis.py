"""Fully local speech and scene-text analysis for Archive media."""
import json
import math
import os
import re
import shutil
import subprocess
import tempfile

from core import config, layout, lens, media_index, runs, store


class AnalysisError(RuntimeError):
    pass


def _clean_text(value):
    if not isinstance(value, str):
        raise AnalysisError("analysis text must be a string")
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) > lens.MAX_TEXT_LENGTH:
        raise AnalysisError("analysis text is too long")
    return text


def _milliseconds(value, field):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise AnalysisError(f"{field} must be a finite non-negative number")
    return float(value) / 1000.0


def parse_whisper_document(document):
    if not isinstance(document, dict):
        raise AnalysisError("Whisper output must be an object")
    entries = document.get("transcription")
    if not isinstance(entries, list) or len(entries) > lens.MAX_SEGMENTS_PER_ITEM:
        raise AnalysisError("Whisper transcription must be a bounded list")
    segments = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("offsets"), dict):
            raise AnalysisError("Whisper segment is malformed")
        start_s = _milliseconds(entry["offsets"].get("from"), "Whisper start")
        end_s = _milliseconds(entry["offsets"].get("to"), "Whisper end")
        if end_s < start_s:
            raise AnalysisError("Whisper end precedes its start")
        text = _clean_text(entry.get("text"))
        if text:
            segments.append({
                "source": "transcript",
                "text": text,
                "start_s": start_s,
                "end_s": end_s,
            })
    return segments


def ocr_segments(samples, interval_s=2.0):
    if (
        type(interval_s) not in (int, float)
        or not math.isfinite(interval_s)
        or interval_s <= 0
    ):
        raise AnalysisError("OCR interval must be a finite positive number")
    result = []
    current = None
    previous_time = -1.0
    for timestamp, raw_text in samples:
        if (
            type(timestamp) not in (int, float)
            or not math.isfinite(timestamp)
            or timestamp < 0
            or timestamp < previous_time
        ):
            raise AnalysisError("OCR sample timestamps must be ordered")
        timestamp = float(timestamp)
        previous_time = timestamp
        text = _clean_text(raw_text)
        key = text.casefold()
        if not text or not any(character.isalnum() for character in text):
            if current is not None:
                current["end_s"] = timestamp
                result.append(current)
                current = None
            continue
        if current is not None and current["_key"] == key:
            current["end_s"] = timestamp + float(interval_s)
            continue
        if current is not None:
            current.pop("_key")
            current["end_s"] = timestamp
            result.append(current)
        current = {
            "source": "ocr",
            "text": text,
            "start_s": timestamp,
            "end_s": timestamp + float(interval_s),
            "_key": key,
        }
    if current is not None:
        current.pop("_key")
        result.append(current)
    for segment in result:
        segment.pop("_key", None)
    return result


def _is_eligible(item, download_dir):
    return (
        item["status"] == "done"
        and not item["offloaded"]
        and not item["archive_missing"]
        and os.path.isfile(layout.movie(download_dir, item["id"]))
        and os.access(layout.movie(download_dir, item["id"]), os.R_OK)
    )


def eligible_items(conn, download_dir):
    return [
        item for item in store.all_items(conn)
        if _is_eligible(item, download_dir)
    ]


def items_needing_analysis(conn, download_dir):
    states = {
        (row["item_id"], row["source"]): row
        for row in conn.execute("SELECT * FROM analysis_source_state")
    }
    pending = []
    for item in eligible_items(conn, download_dir):
        try:
            fingerprint = media_index.file_fingerprint(
                layout.movie(download_dir, item["id"])
            )
        except OSError:
            continue
        if any(
            lens.state_needs_analysis(
                states.get((item["id"], source)), fingerprint,
            )
            for source in lens.SOURCES
        ):
            pending.append(item)
    return pending


def coverage(conn, download_dir):
    items = eligible_items(conn, download_dir)
    states = {
        (row["item_id"], row["source"]): row
        for row in conn.execute("SELECT * FROM analysis_source_state")
    }
    fingerprints = {}
    for item in items:
        try:
            fingerprints[item["id"]] = media_index.file_fingerprint(
                layout.movie(download_dir, item["id"])
            )
        except OSError:
            fingerprints[item["id"]] = None
    result = {"eligible": len(items)}
    for source in lens.SOURCES:
        counts = {
            "complete": 0, "manual": 0, "generated": 0,
            "pending": 0, "failed": 0,
        }
        for item in items:
            state = states.get((item["id"], source))
            fingerprint = fingerprints[item["id"]]
            complete = (
                state is not None
                and state["status"] == "completed"
                and (
                    state["origin"] == "manual"
                    or state["media_fingerprint"] == fingerprint
                )
            )
            if complete:
                counts["complete"] += 1
                counts[state["origin"]] += 1
            else:
                counts["pending"] += 1
                if state is not None and state["status"] == "failed":
                    counts["failed"] += 1
        result[source] = counts
    return result


def tool_readiness(
    *,
    which=shutil.which,
    is_file=os.path.isfile,
    whisper_bin=config.WHISPER_CPP_BIN,
    model_path=config.WHISPER_MODEL,
    tesseract_bin=config.TESSERACT_BIN,
):
    speech_missing = []
    if which(whisper_bin) is None:
        speech_missing.append("Whisper CLI")
    if not is_file(model_path):
        speech_missing.append("Whisper model")
    if which("ffmpeg") is None or which("ffprobe") is None:
        speech_missing.append("FFmpeg/FFprobe")
    ocr_missing = []
    if which(tesseract_bin) is None:
        ocr_missing.append("Tesseract")
    if which("ffmpeg") is None:
        ocr_missing.append("FFmpeg")
    return {
        "speech": {
            "available": not speech_missing,
            "error": (
                None if not speech_missing
                else f"{', '.join(speech_missing)} unavailable"
            ),
        },
        "ocr": {
            "available": not ocr_missing,
            "error": (
                None if not ocr_missing
                else f"{', '.join(ocr_missing)} unavailable"
            ),
        },
    }


def _run(command, runner, timeout):
    return runner(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _bounded_text(value):
    value = value or ""
    if len(value.encode("utf-8")) > config.ANALYSIS_MAX_OUTPUT_BYTES:
        raise AnalysisError("local analysis output is too large")
    return value


def _has_audio(media_path, runner, timeout):
    result = _run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=index", "-of", "csv=p=0", media_path,
        ],
        runner,
        timeout,
    )
    return bool(_bounded_text(result.stdout).strip())


def transcribe_media(
    media_path,
    *,
    runner=subprocess.run,
    whisper_bin=config.WHISPER_CPP_BIN,
    model_path=config.WHISPER_MODEL,
    timeout=config.ANALYSIS_TIMEOUT,
):
    if not _has_audio(media_path, runner, timeout):
        return []
    with tempfile.TemporaryDirectory(prefix="archive-analysis-speech-") as work:
        audio_path = os.path.join(work, "audio.wav")
        output_base = os.path.join(work, "transcript")
        _run(
            [
                "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", media_path,
                "-map", "0:a:0", "-ar", "16000", "-ac", "1",
                "-c:a", "pcm_s16le", audio_path,
            ],
            runner,
            timeout,
        )
        if not os.path.isfile(audio_path) or os.path.getsize(audio_path) == 0:
            return []
        _run(
            [
                whisper_bin, "-m", model_path, "-f", audio_path,
                "-l", "auto", "-oj", "-of", output_base, "-np",
            ],
            runner,
            timeout,
        )
        output_path = f"{output_base}.json"
        if not os.path.isfile(output_path):
            raise AnalysisError("speech analyzer produced no JSON output")
        if os.path.getsize(output_path) > config.ANALYSIS_MAX_OUTPUT_BYTES:
            raise AnalysisError("speech analyzer output is too large")
        try:
            with open(output_path, encoding="utf-8") as source:
                document = json.load(source)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AnalysisError(f"speech analyzer output is unreadable: {error}") from error
        return parse_whisper_document(document)


def recognize_media(
    media_path,
    *,
    runner=subprocess.run,
    tesseract_bin=config.TESSERACT_BIN,
    interval_s=config.OCR_INTERVAL_SECONDS,
    max_frames=config.OCR_MAX_FRAMES,
    timeout=config.ANALYSIS_TIMEOUT,
):
    if type(max_frames) is not int or not 1 <= max_frames <= 10_000:
        raise AnalysisError("OCR frame limit must be between 1 and 10000")
    if (
        type(interval_s) not in (int, float)
        or not math.isfinite(interval_s)
        or interval_s <= 0
    ):
        raise AnalysisError("OCR interval must be positive")
    with tempfile.TemporaryDirectory(prefix="archive-analysis-ocr-") as work:
        pattern = os.path.join(work, "frame-%06d.png")
        _run(
            [
                "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", media_path,
                "-vf", f"fps=1/{float(interval_s):g}",
                "-frames:v", str(max_frames), pattern,
            ],
            runner,
            timeout,
        )
        names = sorted(
            name for name in os.listdir(work)
            if name.startswith("frame-") and name.endswith(".png")
        )
        samples = []
        output_bytes = 0
        for index, name in enumerate(names):
            result = _run(
                [
                    tesseract_bin, os.path.join(work, name), "stdout",
                    "-l", "eng", "--psm", "6",
                ],
                runner,
                timeout,
            )
            text = result.stdout or ""
            output_bytes += len(text.encode("utf-8"))
            if output_bytes > config.ANALYSIS_MAX_OUTPUT_BYTES:
                raise AnalysisError("OCR output is too large")
            samples.append((index * float(interval_s), text))
        return ocr_segments(samples, interval_s=interval_s)


def analyze_item(
    conn,
    download_dir,
    item,
    *,
    transcribe=None,
    recognize=None,
):
    if not _is_eligible(item, download_dir):
        raise AnalysisError("favorite does not have readable local media")
    transcribe = transcribe or transcribe_media
    recognize = recognize or recognize_media
    media_path = layout.movie(download_dir, item["id"])
    fingerprint = media_index.file_fingerprint(media_path)
    result = {"completed_sources": 0, "failed_sources": 0, "segments": 0}
    for source, generate in (
        ("transcript", transcribe),
        ("ocr", recognize),
    ):
        if not lens.source_needs_analysis(
            conn, item["id"], source, fingerprint,
        ):
            continue
        try:
            segments = generate(media_path)
            if lens.replace_generated_source(
                conn, item["id"], source, segments, fingerprint,
            ):
                result["completed_sources"] += 1
                result["segments"] += len(segments)
        except Exception as error:
            lens.record_generated_failure(
                conn, item["id"], source, fingerprint, error,
            )
            result["failed_sources"] += 1
    return result


def run_analysis(
    conn,
    download_dir,
    progress=None,
    wait=None,
    control=None,
    transcribe=None,
    recognize=None,
):
    if control is None:
        control = runs.RunControl(conn, progress=progress, wait=wait)
    items = items_needing_analysis(conn, download_dir)
    totals = {
        "completed": 0,
        "total": len(items),
        "items_analyzed": 0,
        "completed_sources": 0,
        "failed_sources": 0,
        "segments": 0,
        "skipped": 0,
    }
    control.progress({"event": "analysis", **totals})
    for item in items:
        if not control.should_continue():
            break
        try:
            outcome = analyze_item(
                conn,
                download_dir,
                item,
                transcribe=transcribe,
                recognize=recognize,
            )
        except (AnalysisError, OSError):
            totals["completed"] += 1
            totals["skipped"] += 1
            control.progress({
                "event": "analysis", "id": item["id"], **totals,
            })
            continue
        totals["completed"] += 1
        if outcome["completed_sources"] or outcome["failed_sources"]:
            totals["items_analyzed"] += 1
        for field in ("completed_sources", "failed_sources", "segments"):
            totals[field] += outcome[field]
        control.progress({
            "event": "analysis", "id": item["id"], **totals,
        })
    return totals
