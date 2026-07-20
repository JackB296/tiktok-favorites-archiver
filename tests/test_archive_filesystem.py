"""Archive filesystem containment and public-media access."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import archive_filesystem


def test_contained_path_rejects_lexical_and_symlink_escapes():
    with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
        secret = os.path.join(outside, "secret.txt")
        with open(secret, "w", encoding="utf-8") as target:
            target.write("outside")
        os.symlink(outside, os.path.join(root, "linked"))

        for candidate in ("../secret.txt", os.path.join(root, "linked", "secret.txt")):
            try:
                archive_filesystem.contained_path(root, candidate)
            except archive_filesystem.ArchivePathError:
                pass
            else:
                raise AssertionError(f"accepted escaping path: {candidate}")


def test_public_media_open_rejects_symlinks_and_private_archive_areas():
    with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
        public = os.path.join(root, "1.mp4")
        with open(public, "wb") as target:
            target.write(b"movie")
        secret = os.path.join(outside, "secret.txt")
        with open(secret, "wb") as target:
            target.write(b"outside")
        os.symlink(secret, os.path.join(root, "linked.mp4"))
        os.symlink(outside, os.path.join(root, "linked-dir"))
        private = os.path.join(root, ".archive", "uploads")
        os.makedirs(private)
        with open(os.path.join(private, "staged.upload"), "wb") as target:
            target.write(b"private")

        with archive_filesystem.open_public_media(root, "1.mp4") as source:
            assert source.read() == b"movie"

        for relative in (
            "linked.mp4",
            "linked-dir/secret.txt",
            ".archive/uploads/staged.upload",
            "../secret.txt",
        ):
            try:
                archive_filesystem.open_public_media(root, relative)
            except archive_filesystem.ArchivePathError:
                pass
            else:
                raise AssertionError(f"served unsafe media path: {relative}")


def test_public_media_open_distinguishes_missing_files():
    with tempfile.TemporaryDirectory() as root:
        try:
            archive_filesystem.open_public_media(root, "missing.mp4")
        except FileNotFoundError:
            pass
        else:
            raise AssertionError("missing media file was opened")


if __name__ == "__main__":
    import traceback

    tests = [
        value for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
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
