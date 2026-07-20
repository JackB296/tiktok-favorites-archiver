"""Contained Archive paths and symlink-safe public media access.

This module is the filesystem seam for Archive-owned files. Callers ask it to
resolve a contained path or securely open a public media file instead of
reimplementing traversal and symlink policy.
"""
import errno
import os
import stat

from core import layout


class ArchivePathError(ValueError):
    """A requested path is outside the Archive or is unsafe to follow."""


def contained_path(root, candidate):
    """Return ``candidate`` as a canonical path contained beneath ``root``."""
    root = os.path.realpath(os.fspath(root))
    candidate = os.fspath(candidate)
    path = candidate if os.path.isabs(candidate) else os.path.join(root, candidate)
    resolved = os.path.realpath(path)
    try:
        common = os.path.commonpath((root, resolved))
    except ValueError as exc:
        raise ArchivePathError("path is on a different filesystem root") from exc
    if common != root:
        raise ArchivePathError("path escapes its filesystem root")
    if resolved == root:
        raise ArchivePathError("path must name a file beneath its filesystem root")
    return resolved


def _relative_parts(relative):
    if not isinstance(relative, str) or not relative or os.path.isabs(relative):
        raise ArchivePathError("media path must be relative to the Archive")
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ArchivePathError("media path contains an unsafe segment")
    normalized = os.sep.join(parts)
    if layout.is_private_relpath(normalized):
        raise ArchivePathError("media path is private Archive state")
    return parts


def _translate_open_error(exc):
    if exc.errno == errno.ENOENT:
        raise FileNotFoundError(exc.errno, exc.strerror, exc.filename) from exc
    if exc.errno in (errno.ELOOP, errno.ENOTDIR, errno.EACCES, errno.EPERM):
        raise ArchivePathError("media path crosses an unsafe filesystem entry") from exc
    raise exc


def open_public_media(root, relative):
    """Open a regular public media file without following any path symlink.

    Each directory component and the final file are opened relative to an
    already-open directory descriptor with ``O_NOFOLLOW``. The returned binary
    file owns its descriptor and must be closed by the caller.
    """
    parts = _relative_parts(relative)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW
    current_fd = None
    file_fd = None
    try:
        current_fd = os.open(os.path.realpath(os.fspath(root)), directory_flags)
        for part in parts[:-1]:
            try:
                next_fd = os.open(part, directory_flags, dir_fd=current_fd)
            except OSError as exc:
                _translate_open_error(exc)
            os.close(current_fd)
            current_fd = next_fd
        try:
            file_fd = os.open(parts[-1], file_flags, dir_fd=current_fd)
        except OSError as exc:
            _translate_open_error(exc)
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise FileNotFoundError(relative)
        opened = os.fdopen(file_fd, "rb")
        file_fd = None
        return opened
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if current_fd is not None:
            os.close(current_fd)
