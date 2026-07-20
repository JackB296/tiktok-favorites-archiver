"""Non-destructive exact-media duplicate scanning."""
import hashlib
import os
from datetime import datetime

from core import archive_filesystem, layout


CHUNK_SIZE = 1024 * 1024


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _fingerprint(stat):
    return (
        f"{stat.st_dev}:{stat.st_ino}:{stat.st_size}:"
        f"{stat.st_mtime_ns}:{stat.st_ctime_ns}"
    )


def _open_media(download_dir, item_id):
    opened = archive_filesystem.open_public_media(
        download_dir, layout.movie_name(item_id),
    )
    return opened, _fingerprint(os.fstat(opened.fileno()))


def _digest_opened(opened):
    digest = hashlib.sha256()
    byte_count = 0
    try:
        while True:
            chunk = opened.read(CHUNK_SIZE)
            if not chunk:
                break
            byte_count += len(chunk)
            digest.update(chunk)
    finally:
        opened.close()
    return digest.hexdigest(), byte_count


def scan(conn, download_dir):
    rows = conn.execute(
        "SELECT id FROM item WHERE status = 'done' AND offloaded = 0 "
        "AND archive_missing = 0 ORDER BY id"
    ).fetchall()
    eligible = {row["id"] for row in rows}
    hashed = reused = 0
    missing = []
    updated = []
    for item_id in sorted(eligible):
        try:
            opened, fingerprint = _open_media(download_dir, item_id)
        except (FileNotFoundError, archive_filesystem.ArchivePathError):
            missing.append(item_id)
            continue
        cached = conn.execute(
            "SELECT media_fingerprint FROM media_digest WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        if cached is not None and cached["media_fingerprint"] == fingerprint:
            opened.close()
            reused += 1
            continue
        sha256, byte_count = _digest_opened(opened)
        updated.append((item_id, fingerprint, sha256, byte_count, _now()))
        hashed += 1
    try:
        conn.execute("BEGIN")
        conn.executemany(
            "DELETE FROM media_digest WHERE item_id = ?",
            [(item_id,) for item_id in missing],
        )
        conn.executemany(
            "INSERT INTO media_digest "
            "(item_id, media_fingerprint, sha256, byte_count, hashed_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(item_id) DO UPDATE SET "
            "media_fingerprint = excluded.media_fingerprint, "
            "sha256 = excluded.sha256, byte_count = excluded.byte_count, "
            "hashed_at = excluded.hashed_at",
            updated,
        )
        conn.execute(
            "DELETE FROM media_digest WHERE item_id NOT IN ("
            "SELECT id FROM item WHERE status = 'done' AND offloaded = 0 "
            "AND archive_missing = 0)"
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {**report(conn), "scan": {"hashed": hashed, "reused": reused}}


def report(conn):
    groups = []
    total = 0
    rows = conn.execute(
        "SELECT sha256, MIN(byte_count) AS byte_count, COUNT(*) AS copies "
        "FROM media_digest GROUP BY sha256 HAVING COUNT(*) > 1 "
        "ORDER BY ((COUNT(*) - 1) * MIN(byte_count)) DESC, sha256"
    ).fetchall()
    for row in rows:
        item_ids = [
            item["item_id"] for item in conn.execute(
                "SELECT item_id FROM media_digest WHERE sha256 = ? ORDER BY item_id",
                (row["sha256"],),
            )
        ]
        reclaimable = (row["copies"] - 1) * row["byte_count"]
        total += reclaimable
        groups.append({
            "sha256": row["sha256"],
            "byte_count": row["byte_count"],
            "copies": row["copies"],
            "reclaimable_bytes": reclaimable,
            "item_ids": item_ids,
        })
    return {
        "groups": groups,
        "group_count": len(groups),
        "duplicate_items": sum(group["copies"] for group in groups),
        "reclaimable_bytes": total,
    }
