"""FFmpeg adapter for atomic, normalized Story Builder renders."""
import os
import shutil
import subprocess
import tempfile

from core import layout, media_index, store, stories


class StoryRenderError(RuntimeError):
    pass


_VIDEO_FILTER = (
    "scale=1080:1920:force_original_aspect_ratio=decrease,"
    "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p"
)


def _error_text(error):
    detail = getattr(error, "stderr", None)
    if isinstance(detail, bytes):
        detail = detail.decode("utf-8", errors="replace")
    return str(detail or error).strip() or "FFmpeg render failed"


def _run(command, runner):
    return runner(command, check=True, capture_output=True, text=True)


def _concat_manifest_line(path):
    escaped = path.replace("'", "'\\''")
    return f"file '{escaped}'\n"


def render_story(
    conn,
    download_dir,
    story_id,
    *,
    runner=subprocess.run,
    audio_probe=media_index.has_audio_stream,
):
    story = stories.get_story(conn, story_id)
    if story is None:
        raise StoryRenderError("story not found")
    staging = None
    try:
        output_dir = layout.stories_dir(download_dir)
        os.makedirs(output_dir, exist_ok=True)
        staging_root = layout.uploads_dir(download_dir)
        os.makedirs(staging_root, exist_ok=True)
        staging = tempfile.mkdtemp(
            prefix=f"story-{int(story_id)}-", dir=staging_root,
        )
        segments = []
        for index, chapter in enumerate(story["chapters"], start=1):
            item = store.get_item(conn, chapter["item_id"])
            source = layout.movie(download_dir, chapter["item_id"])
            if item is None or not os.path.isfile(source):
                raise StoryRenderError(
                    f"favorite #{chapter['item_id']} is not available locally"
                )
            start = float(chapter["start_s"])
            end = chapter["end_s"]
            if end is None:
                if item["duration_s"] is None:
                    raise StoryRenderError(
                        f"favorite #{chapter['item_id']} needs an end time or media index"
                    )
                end = float(item["duration_s"])
            duration = float(end) - start
            if duration <= 0:
                raise StoryRenderError(f"chapter {index} has no playable duration")
            target = os.path.join(staging, f"{index:03d}.mp4")
            has_audio = (
                bool(item["has_audio"])
                if item["has_audio"] is not None
                else bool(audio_probe(source))
            )
            command = [
                "ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
                "-i", source,
            ]
            if has_audio:
                command += [
                    "-filter_complex",
                    f"[0:v:0]{_VIDEO_FILTER}[v];"
                    "[0:a:0]aresample=48000,"
                    "aformat=sample_fmts=fltp:channel_layouts=stereo[a]",
                    "-map", "[v]", "-map", "[a]",
                ]
            else:
                command += [
                    "-f", "lavfi", "-t", f"{duration:.3f}",
                    "-i", "anullsrc=r=48000:cl=stereo",
                    "-filter_complex", f"[0:v:0]{_VIDEO_FILTER}[v]",
                    "-map", "[v]", "-map", "1:a:0",
                ]
            command += [
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                "-movflags", "+faststart", "-f", "mp4", target,
            ]
            _run(command, runner)
            if not os.path.isfile(target) or os.path.getsize(target) == 0:
                raise StoryRenderError(f"FFmpeg did not create chapter {index}")
            segments.append(target)

        manifest = os.path.join(staging, "chapters.txt")
        with open(manifest, "w", encoding="utf-8") as target:
            for segment in segments:
                target.write(_concat_manifest_line(segment))
        combined = os.path.join(staging, "story.mp4")
        _run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", manifest,
            "-c", "copy", "-movflags", "+faststart", "-f", "mp4", combined,
        ], runner)
        if not os.path.isfile(combined) or os.path.getsize(combined) == 0:
            raise StoryRenderError("FFmpeg did not create the final story")
        conn.execute("BEGIN IMMEDIATE")
        current = stories.get_story(conn, story_id)
        if current is None:
            conn.rollback()
            raise StoryRenderError("story was deleted during render")
        if current["chapters"] != story["chapters"]:
            conn.rollback()
            raise StoryRenderError("story changed during render; retry")
        final = layout.story_movie(download_dir, story_id)
        os.replace(combined, final)
        return stories.record_render_success(
            conn, story_id, layout.story_relpath(story_id),
        )
    except StoryRenderError as error:
        stories.record_render_error(conn, story_id, error)
        raise
    except (OSError, subprocess.SubprocessError) as error:
        mapped = StoryRenderError(_error_text(error))
        stories.record_render_error(conn, story_id, mapped)
        raise mapped from error
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
