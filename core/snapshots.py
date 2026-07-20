"""Portable, checksummed ``.tiktok-archive`` snapshots and guarded restore."""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
from datetime import datetime

from core import archive_filesystem, layout, migrations, storage, store


FORMAT = "tiktok-favorites-archive"
VERSION = 1


class SnapshotError(ValueError):
    pass


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_relative(relative):
    if not isinstance(relative, str):
        raise SnapshotError("snapshot manifest contains an unsafe path")
    relative = relative.replace(os.sep, "/")
    parts = relative.split("/")
    if not relative or os.path.isabs(relative) \
            or any(part in ("", ".", "..") for part in parts):
        raise SnapshotError("snapshot manifest contains an unsafe path")
    return relative


def _entry(root, relative):
    relative = _manifest_relative(relative)
    try:
        return archive_filesystem.contained_path(root, os.path.join(*relative.split("/")))
    except archive_filesystem.ArchivePathError as exc:
        raise SnapshotError("snapshot manifest path escapes its directory") from exc


def _read_metadata(path, allow_partial_suffix=False):
    if not path.endswith(".tiktok-archive") and not allow_partial_suffix:
        raise SnapshotError("snapshot directory must end in .tiktok-archive")
    metadata_path = os.path.join(path, "snapshot.json")
    try:
        with open(metadata_path, encoding="utf-8") as source:
            metadata = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"snapshot metadata is unreadable: {exc}") from exc
    if not isinstance(metadata, dict) \
            or metadata.get("format") != FORMAT or metadata.get("version") != VERSION:
        raise SnapshotError("snapshot format or version is incompatible")
    if metadata.get("mode") not in ("metadata", "complete") \
            or not isinstance(metadata.get("files"), list):
        raise SnapshotError("snapshot metadata is malformed")
    snapshot_schema = metadata.get("schema_version")
    if type(snapshot_schema) is not int or not 0 <= snapshot_schema <= migrations.CURRENT_SCHEMA_VERSION:
        raise SnapshotError("snapshot database schema is incompatible")
    seen = set()
    for entry in metadata["files"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256"}:
            raise SnapshotError("snapshot manifest entry is malformed")
        relative = _manifest_relative(entry["path"])
        if type(entry["size"]) is not int or entry["size"] < 0 \
                or not isinstance(entry["sha256"], str) \
                or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None:
            raise SnapshotError("snapshot manifest entry is malformed")
        if relative in seen:
            raise SnapshotError("snapshot manifest contains duplicate paths")
        seen.add(relative)
    if "database/archive.db" not in seen:
        raise SnapshotError("snapshot manifest does not contain the Archive database")
    return metadata, seen


def _copy_verified(source, target):
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.isfile(target) and os.path.getsize(target) == os.path.getsize(source) \
            and _sha256(target) == _sha256(source):
        return
    partial = target + ".part"
    try:
        shutil.copyfile(source, partial)
        if os.path.getsize(partial) != os.path.getsize(source) or _sha256(partial) != _sha256(source):
            raise SnapshotError("snapshot copy verification failed")
        os.replace(partial, target)
    finally:
        try:
            os.unlink(partial)
        except OSError:
            pass


def _sanitize_database(path):
    """Remove renewable credentials from a portable database copy."""
    snapshot = sqlite3.connect(path)
    try:
        snapshot.execute("PRAGMA journal_mode = DELETE")
        snapshot.execute("PRAGMA secure_delete = ON")
        if snapshot.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'spotify_auth'"
        ).fetchone():
            snapshot.execute(
                "UPDATE spotify_auth SET access_token = NULL, refresh_token = NULL, "
                "expires_at = NULL"
            )
            snapshot.commit()
        # Rewrite the sanitized database so removed values cannot remain in free pages.
        snapshot.execute("VACUUM")
    finally:
        snapshot.close()


def create_snapshot(conn, db_path, download_dir, destination_dir, name, mode="metadata", control=None):
    if mode not in ("metadata", "complete"):
        raise SnapshotError("snapshot mode must be metadata or complete")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-") if isinstance(name, str) else ""
    if not slug:
        raise SnapshotError("snapshot name is required")
    final = os.path.join(destination_dir, f"{slug}.tiktok-archive")
    staging = final + ".partial"
    if os.path.exists(final):
        raise SnapshotError("a snapshot with that name already exists")
    os.makedirs(os.path.join(staging, "database"), exist_ok=True)
    marker = os.path.join(staging, ".partial")
    open(marker, "a").close()

    database_target = os.path.join(staging, "database", "archive.db")
    backup = sqlite3.connect(database_target)
    try:
        conn.backup(backup)
    finally:
        backup.close()
    _sanitize_database(database_target)

    if mode == "complete":
        items = store.all_items(conn)
        for index, item in enumerate(items):
            if control is not None and not control.should_continue():
                return {"partial": True, "path": staging}
            manifest = storage.item_media_manifest(download_dir, item)
            for file_entry in manifest["files"]:
                source = os.path.join(download_dir, *file_entry["path"].split("/"))
                target = _entry(staging, f"media/{file_entry['path']}")
                _copy_verified(source, target)
            if control is not None:
                control.progress({"event": "snapshot", "completed": index + 1, "total": len(items)})
        rendered_stories = conn.execute(
            "SELECT id, rendered_path FROM story "
            "WHERE rendered_path IS NOT NULL ORDER BY id"
        ).fetchall()
        for story in rendered_stories:
            relative = layout.story_relpath(story["id"])
            source = layout.story_movie(download_dir, story["id"])
            if story["rendered_path"] != relative or not os.path.isfile(source):
                continue
            target = _entry(staging, f"media/{relative}")
            _copy_verified(source, target)

    entries = []
    for root, directories, files in os.walk(staging):
        directories.sort()
        for filename in sorted(files):
            path = os.path.join(root, filename)
            relative = os.path.relpath(path, staging).replace(os.sep, "/")
            if relative in (".partial", "snapshot.json") or relative.endswith(".part"):
                continue
            entries.append({"path": relative, "size": os.path.getsize(path), "sha256": _sha256(path)})
    metadata = {
        "format": FORMAT,
        "version": VERSION,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "schema_version": migrations.schema_version(conn),
        "items": len(store.all_items(conn)),
        "files": sorted(entries, key=lambda entry: entry["path"]),
    }
    with open(os.path.join(staging, "snapshot.json"), "w", encoding="utf-8") as target:
        json.dump(metadata, target, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    os.unlink(marker)
    validate_snapshot(staging, allow_partial_suffix=True)
    os.replace(staging, final)
    return {"partial": False, "path": final, **metadata}


def validate_snapshot(path, allow_partial_suffix=False):
    metadata, seen = _read_metadata(path, allow_partial_suffix)
    snapshot_schema = metadata.get("schema_version")
    for entry in metadata["files"]:
        file_path = _entry(path, entry["path"])
        if not os.path.isfile(file_path) or os.path.getsize(file_path) != entry["size"] \
                or _sha256(file_path) != entry["sha256"]:
            raise SnapshotError(f"snapshot file is missing or corrupt: {entry['path']}")
    actual = set()
    for root, _directories, files in os.walk(path):
        for filename in files:
            relative = os.path.relpath(os.path.join(root, filename), path).replace(os.sep, "/")
            if relative != "snapshot.json":
                actual.add(relative)
    if actual != seen:
        raise SnapshotError("snapshot contains files that are missing from its manifest")
    check = sqlite3.connect(os.path.join(path, "database", "archive.db"))
    check.row_factory = sqlite3.Row
    try:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SnapshotError("snapshot database failed integrity check")
        if check.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'item'"
        ).fetchone() is None:
            raise SnapshotError("snapshot database does not contain an Archive")
        if migrations.schema_version(check) != snapshot_schema:
            raise SnapshotError("snapshot database schema does not match its metadata")
    finally:
        check.close()
    return metadata


def list_snapshots(destination_dir):
    if not os.path.isdir(destination_dir):
        return []
    result = []
    for name in sorted(os.listdir(destination_dir)):
        path = os.path.join(destination_dir, name)
        if name.endswith(".tiktok-archive") and os.path.isdir(path):
            try:
                metadata, _ = _read_metadata(path)
                result.append({"name": name, "path": path, "state": "complete", **metadata})
            except SnapshotError as exc:
                result.append({"name": name, "path": path, "state": "invalid", "error": str(exc)})
        elif name.endswith(".tiktok-archive.partial") and os.path.isdir(path):
            result.append({"name": name, "path": path, "state": "partial"})
    return result


def run_create(conn, download_dir, control=None, **kwargs):
    return create_snapshot(conn, download_dir=download_dir, control=control, **kwargs)


def restore_plan(snapshot_path, conn, download_dir):
    metadata = validate_snapshot(snapshot_path)
    target_items = conn.execute("SELECT COUNT(*) FROM item").fetchone()[0]
    source = sqlite3.connect(os.path.join(snapshot_path, "database", "archive.db"))
    try:
        snapshot_items = source.execute("SELECT COUNT(*) FROM item").fetchone()[0]
    finally:
        source.close()
    media_entries = [entry for entry in metadata["files"] if entry["path"].startswith("media/")]
    conflicts = 0
    for entry in media_entries:
        relative = entry["path"][len("media/"):]
        target = _entry(download_dir, relative)
        if os.path.exists(target) and (
            not os.path.isfile(target)
            or os.path.getsize(target) != entry["size"]
            or _sha256(target) != entry["sha256"]
        ):
            conflicts += 1
    target_fingerprint = conn.execute(
        "SELECT COUNT(*), COALESCE(MAX(updated_at), '') FROM item"
    ).fetchone()
    token_source = json.dumps({
        "snapshot": _sha256(os.path.join(snapshot_path, "snapshot.json")),
        "target": list(target_fingerprint),
        "conflicts": conflicts,
    }, separators=(",", ":"), sort_keys=True).encode()
    return {
        "token": hashlib.sha256(token_source).hexdigest(),
        "mode": metadata["mode"],
        "snapshot_items": snapshot_items,
        "target_items": target_items,
        "required_bytes": sum(entry["size"] for entry in media_entries),
        "conflicts": conflicts,
        "requires_replace": bool(target_items),
        "confirmation": "REPLACE ARCHIVE" if target_items else None,
    }


def apply_restore(
    snapshot_path,
    conn,
    db_path,
    download_dir,
    rollback_dir,
    plan_token,
    confirmation=None,
    copier=shutil.copyfile,
):
    plan = restore_plan(snapshot_path, conn, download_dir)
    if plan["token"] != plan_token:
        raise SnapshotError("restore plan is stale; preview again")
    if plan["requires_replace"] and confirmation != "REPLACE ARCHIVE":
        raise SnapshotError("replacement requires confirmation: REPLACE ARCHIVE")
    rollback = None
    if plan["requires_replace"]:
        rollback = create_snapshot(
            conn, db_path, download_dir, rollback_dir,
            f"rollback-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
            "complete",
        )["path"]

    metadata = validate_snapshot(snapshot_path)
    staging = tempfile.mkdtemp(prefix="snapshot-restore-", dir=os.path.dirname(download_dir))
    try:
        for entry in metadata["files"]:
            if not entry["path"].startswith("media/"):
                continue
            relative = entry["path"][len("media/"):]
            source = _entry(snapshot_path, entry["path"])
            target = _entry(staging, relative)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            copier(source, target)
            if os.path.getsize(target) != entry["size"] or _sha256(target) != entry["sha256"]:
                raise SnapshotError(f"staged restore file failed verification: {relative}")
        for root, _directories, files in os.walk(staging):
            for filename in files:
                staged = os.path.join(root, filename)
                relative = os.path.relpath(staged, staging)
                target = _entry(download_dir, relative)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(staged, target)

        source_db = sqlite3.connect(os.path.join(snapshot_path, "database", "archive.db"))
        try:
            source_db.backup(conn)
        finally:
            source_db.close()
        store.init_db(conn)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"restored": True, "rollback_snapshot": rollback, **plan}


def run_restore_snapshot(conn, download_dir, control=None, **kwargs):
    return apply_restore(conn=conn, download_dir=download_dir, **kwargs)
