"""Mounted-filesystem Storage locations and verified Media placements."""
import os
import hashlib
import json
import sqlite3
import tempfile
import shutil

from core import store
from core import layout


class StorageError(ValueError):
    """A mounted path or Storage-location request is invalid."""


class StorageConflictError(StorageError):
    """The location is still referenced by durable Archive state."""


def _public(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "path": row["path"],
        "available": bool(row["available"]),
        "last_error": row["last_error"],
        "last_checked_at": row["last_checked_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def canonical_path(path):
    if not isinstance(path, str) or not path.strip():
        raise StorageError("path must be a non-empty absolute mounted path")
    expanded = os.path.expanduser(path.strip())
    if not os.path.isabs(expanded):
        raise StorageError("path must be absolute")
    return os.path.realpath(expanded)


def validate_path(path, download_dir, db_path, *, write=True):
    candidate = canonical_path(path)
    if not os.path.exists(candidate):
        raise StorageError("mounted path does not exist")
    if not os.path.isdir(candidate):
        raise StorageError("mounted path is not a directory")
    protected = (
        os.path.realpath(download_dir),
        os.path.realpath(os.path.dirname(db_path)),
    )
    for source in protected:
        try:
            common = os.path.commonpath((candidate, source))
        except ValueError:
            continue
        if common in (candidate, source):
            raise StorageError("Storage location must not overlap downloads or database storage")
    if not os.access(candidate, os.R_OK | os.X_OK):
        raise StorageError("mounted path is not readable")
    if write:
        try:
            fd, probe = tempfile.mkstemp(prefix=".tiktok-storage-check-", dir=candidate)
            os.close(fd)
            os.unlink(probe)
        except OSError as exc:
            raise StorageError(f"mounted path is not writable: {exc}") from exc
    return candidate


def create_location(conn, name, path, download_dir, db_path):
    if not isinstance(name, str) or not (name := name.strip()) or len(name) > 80:
        raise StorageError("name must be between 1 and 80 characters")
    candidate = validate_path(path, download_dir, db_path)
    try:
        location_id = store.insert_storage_location(conn, name, candidate, True)
    except sqlite3.IntegrityError as exc:
        raise StorageError("a Storage location with that name or path already exists") from exc
    return _public(store.get_storage_location(conn, location_id))


def list_locations(conn):
    return [_public(row) for row in store.list_storage_locations(conn)]


def check_location(conn, location_id, download_dir, db_path):
    row = store.get_storage_location(conn, location_id)
    if row is None:
        raise KeyError(location_id)
    try:
        validate_path(row["path"], download_dir, db_path)
        error = None
        available = 1
    except StorageError as exc:
        error = str(exc)
        available = 0
    updated = store.update_storage_location(
        conn,
        location_id,
        available=available,
        last_error=error,
        last_checked_at=store._now(),
    )
    return _public(updated)


def update_location(conn, location_id, changes, download_dir, db_path):
    current = store.get_storage_location(conn, location_id)
    if current is None:
        raise KeyError(location_id)
    name = changes.get("name", current["name"])
    path = changes.get("path", current["path"])
    if not isinstance(name, str) or not (name := name.strip()) or len(name) > 80:
        raise StorageError("name must be between 1 and 80 characters")
    candidate = validate_path(path, download_dir, db_path)
    try:
        updated = store.update_storage_location(
            conn,
            location_id,
            name=name,
            path=candidate,
            available=1,
            last_error=None,
            last_checked_at=store._now(),
        )
    except sqlite3.IntegrityError as exc:
        raise StorageError("a Storage location with that name or path already exists") from exc
    return _public(updated)


def delete_location(conn, location_id):
    if store.get_storage_location(conn, location_id) is None:
        raise KeyError(location_id)
    if not store.delete_storage_location(conn, location_id):
        raise StorageConflictError("Storage location is referenced by Media placements")


def _safe_relative(download_dir, path):
    root = os.path.realpath(download_dir)
    absolute = os.path.realpath(path if os.path.isabs(path) else os.path.join(root, path))
    try:
        common = os.path.commonpath((root, absolute))
    except ValueError as exc:
        raise StorageError("media path is on a different filesystem root") from exc
    if common != root:
        raise StorageError("media path escapes the active download directory")
    relative = os.path.relpath(absolute, root).replace(os.sep, "/")
    if relative == "." or relative.startswith("../") or "/../" in relative:
        raise StorageError("media path is not a contained relative path")
    return relative, absolute


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def item_media_manifest(download_dir, item):
    """Stable facts for every durable local file owned by one Favorite."""
    item_id = int(item["id"])
    candidates = [
        layout.movie(download_dir, item_id),
        layout.nfo(download_dir, item_id),
        layout.poster(download_dir, item_id),
        layout.replaced_movie(download_dir, item_id),
    ]
    for field in ("thumbnail_path", "custom_thumbnail_path"):
        if item[field]:
            candidates.append(item[field])
    assets = layout.assets_dir(download_dir, item_id)
    if os.path.isdir(assets):
        for root, directories, files in os.walk(assets, followlinks=False):
            directories[:] = sorted(name for name in directories if not os.path.islink(os.path.join(root, name)))
            for name in sorted(files):
                if name.endswith(layout.TEMP_SUFFIXES):
                    continue
                candidates.append(os.path.join(root, name))

    by_relative = {}
    for candidate in candidates:
        relative, absolute = _safe_relative(download_dir, candidate)
        if not os.path.isfile(absolute) or os.path.islink(absolute):
            continue
        by_relative[relative] = absolute
    files = [
        {
            "path": relative,
            "size": os.path.getsize(by_relative[relative]),
            "sha256": _sha256(by_relative[relative]),
        }
        for relative in sorted(by_relative)
    ]
    encoded = json.dumps(files, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return {
        "item_id": item_id,
        "files": files,
        "file_count": len(files),
        "byte_count": sum(entry["size"] for entry in files),
        "digest": hashlib.sha256(encoded).hexdigest(),
    }


def _destination(location_path, item_id, relative):
    root = os.path.join(location_path, "items", str(item_id))
    _relative, source = _safe_relative(root, relative)
    return source


def _matches(path, entry):
    return os.path.isfile(path) \
        and os.path.getsize(path) == entry["size"] \
        and _sha256(path) == entry["sha256"]


def preview_transfer(conn, download_dir, location_id, item_ids):
    location = store.get_storage_location(conn, location_id)
    if location is None:
        raise KeyError(location_id)
    files = bytes_total = conflicts = already_verified = 0
    items = 0
    placements = {
        row["item_id"]: row
        for row in store.media_placements(conn)
        if row["location_id"] == location_id and row["verified"]
    }
    for item_id in item_ids:
        item = store.get_item(conn, item_id)
        if item is None:
            continue
        items += 1
        manifest = item_media_manifest(download_dir, item)
        files += manifest["file_count"]
        bytes_total += manifest["byte_count"]
        if item_id in placements and placements[item_id]["manifest_digest"] == manifest["digest"]:
            already_verified += 1
        for entry in manifest["files"]:
            target = _destination(location["path"], item_id, entry["path"])
            if os.path.exists(target) and not _matches(target, entry):
                conflicts += 1
    return {
        "items": items,
        "files": files,
        "bytes": bytes_total,
        "conflicts": conflicts,
        "already_verified": already_verified,
    }


def _copy_verified(source, target, entry, copier):
    if _matches(target, entry):
        return False
    os.makedirs(os.path.dirname(target), exist_ok=True)
    partial = target + ".part"
    try:
        copier(source, partial)
        if not _matches(partial, entry):
            raise StorageError(f"checksum verification failed for {entry['path']}")
        os.replace(partial, target)
    finally:
        try:
            os.unlink(partial)
        except OSError:
            pass
    return True


def copy_items(conn, download_dir, location_id, item_ids, *, control=None, copier=shutil.copyfile):
    location = store.get_storage_location(conn, location_id)
    if location is None:
        raise KeyError(location_id)
    validate_path(location["path"], download_dir, conn.execute("PRAGMA database_list").fetchone()["file"])
    report = {"items": 0, "files": 0, "bytes": 0, "skipped_files": 0}
    for item_id in item_ids:
        if control is not None and not control.should_continue():
            break
        item = store.get_item(conn, item_id)
        if item is None:
            continue
        manifest = item_media_manifest(download_dir, item)
        for entry in manifest["files"]:
            source = os.path.join(download_dir, *entry["path"].split("/"))
            target = _destination(location["path"], item_id, entry["path"])
            if _copy_verified(source, target, entry, copier):
                report["files"] += 1
                report["bytes"] += entry["size"]
            else:
                report["skipped_files"] += 1
        store.record_media_placement(
            conn, item_id, location_id, f"items/{item_id}",
            manifest["byte_count"], manifest["digest"], verified=True,
            files=manifest["files"],
        )
        report["items"] += 1
        if control is not None:
            control.progress({"event": "transfer", "completed": report["items"], "total": len(item_ids), **report})
    return report


def move_items(conn, download_dir, location_id, item_ids, *, control=None, copier=shutil.copyfile):
    copied = copy_items(
        conn, download_dir, location_id, item_ids, control=control, copier=copier,
    )
    moved = 0
    for item_id in item_ids[:copied["items"]]:
        placement = next(
            (row for row in store.media_placements(conn, item_id)
             if row["location_id"] == location_id and row["verified"]),
            None,
        )
        if placement is None:
            continue
        for entry in store.placement_files(conn, placement["id"]):
            path = os.path.join(download_dir, *entry["path"].split("/"))
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        assets = layout.assets_dir(download_dir, item_id)
        for root, directories, _files in os.walk(assets, topdown=False):
            for directory in directories:
                try:
                    os.rmdir(os.path.join(root, directory))
                except OSError:
                    pass
            try:
                os.rmdir(root)
            except OSError:
                pass
        store.set_offloaded(conn, [item_id], True)
        moved += 1
    return {**copied, "moved": moved}


def restore_items(conn, download_dir, location_id, item_ids, *, control=None, copier=shutil.copyfile):
    location = store.get_storage_location(conn, location_id)
    if location is None:
        raise KeyError(location_id)
    restored = 0
    for item_id in item_ids:
        if control is not None and not control.should_continue():
            break
        placement = next(
            (row for row in store.media_placements(conn, item_id)
             if row["location_id"] == location_id and row["verified"]),
            None,
        )
        if placement is None:
            raise StorageError(f"Favorite #{item_id} has no verified external placement")
        for entry in store.placement_files(conn, placement["id"]):
            source = _destination(location["path"], item_id, entry["path"])
            target = os.path.join(download_dir, *entry["path"].split("/"))
            if not _matches(source, entry):
                raise StorageError(f"external placement is corrupt: {entry['path']}")
            _copy_verified(source, target, entry, copier)
        store.set_offloaded(conn, [item_id], False)
        restored += 1
    return {"restored": restored}


def preview_restore(conn, location_id, item_ids):
    if store.get_storage_location(conn, location_id) is None:
        raise KeyError(location_id)
    placements = files = byte_count = 0
    missing_verified = []
    for item_id in item_ids:
        placement = next(
            (row for row in store.media_placements(conn, item_id)
             if row["location_id"] == location_id and row["verified"]),
            None,
        )
        if placement is None:
            missing_verified.append(item_id)
            continue
        entries = store.placement_files(conn, placement["id"])
        placements += 1
        files += len(entries)
        byte_count += sum(entry["size"] for entry in entries)
    return {
        "items": len(item_ids), "placements": placements, "files": files,
        "bytes": byte_count, "missing_verified": missing_verified,
    }


def run_copy(conn, download_dir, control=None, **kwargs):
    return copy_items(conn, download_dir, control=control, **kwargs)


def run_move(conn, download_dir, control=None, **kwargs):
    return move_items(conn, download_dir, control=control, **kwargs)


def run_restore(conn, download_dir, control=None, **kwargs):
    return restore_items(conn, download_dir, control=control, **kwargs)
