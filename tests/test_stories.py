"""Story Builder persistence, validation, and local atomic FFmpeg rendering."""
import os
import subprocess
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import layout, stories, story_render, store


def _db():
    return store.init_db(store.connect(":memory:"))


def _item(conn, item_id, duration=12.0, has_audio=True):
    store.insert_item(
        conn, item_id, f"https://example.test/{item_id}",
        favorited_at="2025-01-01", kind="video", status="done",
    )
    conn.execute(
        "UPDATE item SET duration_s = ?, has_audio = ? WHERE id = ?",
        (duration, None if has_audio is None else int(has_audio), item_id),
    )
    conn.commit()


def _story_body(name="Weekend recipes"):
    return {
        "name": name,
        "description": "Three recipes to make again.",
        "chapters": [
            {"item_id": 1, "title": "The sauce", "start_s": 1, "end_s": 5},
            {"item_id": 2, "title": "The finish", "start_s": 0, "end_s": 6},
        ],
    }


def test_story_crud_preserves_chapter_order_and_last_complete_render():
    conn = _db()
    _item(conn, 1)
    _item(conn, 2)
    story = stories.create_story(conn, _story_body())

    assert story["id"] == 1
    assert [chapter["item_id"] for chapter in story["chapters"]] == [1, 2]
    conn.execute(
        "UPDATE story SET rendered_path = '.archive/stories/1.mp4' WHERE id = 1"
    )
    conn.commit()

    updated = stories.update_story(conn, 1, {
        "name": "Weekend recipe reel",
        "chapters": list(reversed(story["chapters"])),
    })
    assert updated["name"] == "Weekend recipe reel"
    assert [chapter["item_id"] for chapter in updated["chapters"]] == [2, 1]
    assert updated["rendered_path"] == ".archive/stories/1.mp4"
    assert stories.list_stories(conn)[0]["id"] == story["id"]
    renamed = stories.update_story(conn, 1, {"description": "New description"})
    assert renamed["rendered_path"] == ".archive/stories/1.mp4"
    assert stories.delete_story(conn, story["id"]) is True
    assert stories.get_story(conn, story["id"]) is None
    assert stories.delete_story(conn, story["id"]) is False


def test_story_validation_rejects_duplicates_unknown_items_and_bad_bounds():
    conn = _db()
    _item(conn, 1, duration=10)
    _item(conn, 2, duration=8)
    invalid = [
        {**_story_body(), "chapters": []},
        {**_story_body(), "chapters": [
            {"item_id": 1, "title": "A"}, {"item_id": 1, "title": "B"},
        ]},
        {**_story_body(), "chapters": [{"item_id": 999, "title": "Missing"}]},
        {**_story_body(), "chapters": [{"item_id": 1, "start_s": 8, "end_s": 4}]},
        {**_story_body(), "chapters": [{"item_id": 1, "start_s": 0, "end_s": 11}]},
    ]
    for body in invalid:
        try:
            stories.create_story(conn, body)
        except stories.StoryError:
            pass
        else:
            raise AssertionError(f"invalid story accepted: {body}")

    stories.create_story(conn, _story_body("Unique"))
    try:
        stories.create_story(conn, _story_body("unique"))
    except stories.StoryError as error:
        assert "name" in str(error)
    else:
        raise AssertionError("case-insensitive duplicate name should fail")


def test_render_normalizes_audio_and_silent_chapters_then_atomically_publishes():
    conn = _db()
    _item(conn, 1, duration=12, has_audio=True)
    _item(conn, 2, duration=9, has_audio=False)
    story = stories.create_story(conn, _story_body())
    calls = []

    def fake_runner(command, **_kwargs):
        calls.append(command)
        with open(command[-1], "wb") as target:
            target.write(b"rendered")
        return subprocess.CompletedProcess(command, 0, "", "")

    with tempfile.TemporaryDirectory() as downloads:
        for item_id in (1, 2):
            with open(layout.movie(downloads, item_id), "wb") as target:
                target.write(b"source")
        rendered = story_render.render_story(
            conn, downloads, story["id"], runner=fake_runner,
        )
        final = layout.story_movie(downloads, story["id"])
        assert os.path.isfile(final)
        assert open(final, "rb").read() == b"rendered"

    assert len(calls) == 3
    assert "anullsrc=r=48000:cl=stereo" not in " ".join(calls[0])
    assert "anullsrc=r=48000:cl=stereo" in " ".join(calls[1])
    assert "-f concat" in " ".join(calls[2])
    assert rendered["rendered_path"] == layout.story_relpath(story["id"])
    assert rendered["render_error"] is None


def test_failed_render_keeps_previous_file_and_records_retryable_error():
    conn = _db()
    _item(conn, 1)
    _item(conn, 2)
    story = stories.create_story(conn, _story_body())

    def failing_runner(command, **_kwargs):
        if "concat" in command:
            raise subprocess.CalledProcessError(1, command, stderr="concat failed")
        with open(command[-1], "wb") as target:
            target.write(b"segment")
        return subprocess.CompletedProcess(command, 0, "", "")

    with tempfile.TemporaryDirectory() as downloads:
        os.makedirs(layout.stories_dir(downloads))
        for item_id in (1, 2):
            with open(layout.movie(downloads, item_id), "wb") as target:
                target.write(b"source")
        final = layout.story_movie(downloads, story["id"])
        with open(final, "wb") as target:
            target.write(b"previous")
        stories.record_render_success(
            conn, story["id"], layout.story_relpath(story["id"]),
        )
        try:
            story_render.render_story(
                conn, downloads, story["id"], runner=failing_runner,
            )
        except story_render.StoryRenderError as error:
            assert "concat failed" in str(error)
        else:
            raise AssertionError("failed render should raise")
        assert open(final, "rb").read() == b"previous"
        failed = stories.get_story(conn, story["id"])
        assert "concat failed" in failed["render_error"]
        assert failed["rendered_path"] == layout.story_relpath(story["id"])


def test_render_setup_failure_is_mapped_and_recorded():
    conn = _db()
    _item(conn, 1)
    _item(conn, 2)
    story = stories.create_story(conn, _story_body())

    with tempfile.TemporaryDirectory() as downloads:
        with patch(
            "core.story_render.os.makedirs",
            side_effect=PermissionError("story directory is read-only"),
        ):
            try:
                story_render.render_story(conn, downloads, story["id"])
            except story_render.StoryRenderError as error:
                assert "read-only" in str(error)
            else:
                raise AssertionError("render setup failure should be mapped")

    failed = stories.get_story(conn, story["id"])
    assert "read-only" in failed["render_error"]


def test_render_aborts_if_chapters_change_before_publication():
    conn = _db()
    _item(conn, 1)
    _item(conn, 2)
    story = stories.create_story(conn, _story_body())

    def editing_runner(command, **_kwargs):
        with open(command[-1], "wb") as target:
            target.write(b"new render")
        if "concat" in command:
            stories.update_story(conn, story["id"], {
                "chapters": list(reversed(story["chapters"])),
            })
        return subprocess.CompletedProcess(command, 0, "", "")

    with tempfile.TemporaryDirectory() as downloads:
        os.makedirs(layout.stories_dir(downloads))
        for item_id in (1, 2):
            with open(layout.movie(downloads, item_id), "wb") as target:
                target.write(b"source")
        final = layout.story_movie(downloads, story["id"])
        with open(final, "wb") as target:
            target.write(b"previous")
        stories.record_render_success(
            conn, story["id"], layout.story_relpath(story["id"]),
        )

        try:
            story_render.render_story(
                conn, downloads, story["id"], runner=editing_runner,
            )
        except story_render.StoryRenderError as error:
            assert "changed during render" in str(error)
        else:
            raise AssertionError("stale render should not publish")

        assert open(final, "rb").read() == b"previous"
        current = stories.get_story(conn, story["id"])
        assert [chapter["item_id"] for chapter in current["chapters"]] == [2, 1]
        assert current["rendered_path"] == layout.story_relpath(story["id"])


def test_render_aborts_without_orphan_if_story_is_deleted():
    conn = _db()
    _item(conn, 1)
    _item(conn, 2)
    story = stories.create_story(conn, _story_body())

    def deleting_runner(command, **_kwargs):
        with open(command[-1], "wb") as target:
            target.write(b"new render")
        if "concat" in command:
            stories.delete_story(conn, story["id"])
        return subprocess.CompletedProcess(command, 0, "", "")

    with tempfile.TemporaryDirectory() as downloads:
        for item_id in (1, 2):
            with open(layout.movie(downloads, item_id), "wb") as target:
                target.write(b"source")

        try:
            story_render.render_story(
                conn, downloads, story["id"], runner=deleting_runner,
            )
        except story_render.StoryRenderError as error:
            assert "deleted during render" in str(error)
        else:
            raise AssertionError("deleted story render should abort")

        assert not os.path.exists(layout.story_movie(downloads, story["id"]))


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
