"""Plan and atomically apply a pre-SQLite CLI archive migration.

Planning is deliberately pure and read-only. Applying writes only item rows to
an empty database; it never mutates the downloads directory or source files.
"""
from dataclasses import dataclass
import hashlib
import json
import os
import re
from typing import Optional

from core import export, store


class LegacyBootstrapError(ValueError):
    """The legacy inputs cannot be migrated without an unsafe assumption."""


def _normalize_link(link):
    return re.sub(r"tiktokv\.com", "tiktok.com", link.strip())


def _unique_links(favorites, label):
    links = [link for link, _date in favorites]
    if len(links) != len(set(links)):
        raise LegacyBootstrapError(f"The {label} export contains duplicate favorite links.")
    return links


def _read_checkpoint(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            lines = [line.strip() for line in f if line.strip()]
    except OSError as exc:
        raise LegacyBootstrapError(f"Could not read the checkpoint file: {exc}") from exc
    if len(lines) != 1:
        raise LegacyBootstrapError("The checkpoint file must contain exactly one non-empty link.")
    return _normalize_link(lines[0])


def _numeric_mp4_ids(download_dir):
    try:
        names = os.listdir(download_dir)
    except OSError as exc:
        raise LegacyBootstrapError(f"Could not scan the downloads directory: {exc}") from exc
    ids = sorted({
        int(name[:-4])
        for name in names
        if name.endswith(".mp4") and name[:-4].isdigit()
    })
    if not ids:
        raise LegacyBootstrapError("No numeric MP4 files were found in the downloads directory.")
    if ids[0] < 1:
        raise LegacyBootstrapError("Legacy archive numbers must be positive integers.")
    return tuple(ids)


def _range(first, last):
    return (first, last) if first <= last else (None, None)


@dataclass(frozen=True)
class LegacyBootstrapPlan:
    old_favorites: tuple
    current_favorites: tuple
    checkpoint: str
    checkpoint_old_position: int
    checkpoint_current_position: int
    local_ids: tuple
    gap_ids: tuple
    offset: int
    mapped_first_position: int
    mapped_last_position: int
    offloaded_first_id: Optional[int]
    offloaded_last_id: Optional[int]
    pending_first_id: Optional[int]
    pending_last_id: Optional[int]
    next_archive_number: int
    token: str

    @property
    def local_first_id(self):
        return self.local_ids[0]

    @property
    def local_last_id(self):
        return self.local_ids[-1]

    @property
    def offloaded_count(self):
        return self.mapped_first_position - 1

    @property
    def pending_count(self):
        return len(self.current_favorites) - self.checkpoint_current_position

    @property
    def total_rows(self):
        return (self.local_last_id - self.local_first_id + 1) + self.offloaded_count + self.pending_count

    def preview(self):
        samples = []
        if len(self.local_ids) <= 5:
            sample_ids = self.local_ids
        else:
            indexes = (0, len(self.local_ids) // 4, len(self.local_ids) // 2,
                       (len(self.local_ids) * 3) // 4, len(self.local_ids) - 1)
            sample_ids = tuple(dict.fromkeys(self.local_ids[index] for index in indexes))
        for item_id in sample_ids:
            old_position = item_id - self.offset
            link, favorited_at = self.old_favorites[old_position - 1]
            samples.append({
                "archive_number": item_id,
                "old_export_position": old_position,
                "link": link,
                "favorited_at": favorited_at,
            })

        return {
            "valid": True,
            "token": self.token,
            "offset": self.offset,
            "checkpoint": {
                "link": self.checkpoint,
                "old_position": self.checkpoint_old_position,
                "current_position": self.checkpoint_current_position,
                "favorites_after_checkpoint": self.pending_count,
            },
            "exports": {
                "old_favorites": len(self.old_favorites),
                "current_favorites": len(self.current_favorites),
            },
            "inventory": {
                "local_files": len(self.local_ids),
                "lowest_number": self.local_first_id,
                "highest_number": self.local_last_id,
                "mapped_old_position_first": self.mapped_first_position,
                "mapped_old_position_last": self.mapped_last_position,
                "gaps": len(self.gap_ids),
            },
            "allocation": {
                "reserved_physical_first": 1,
                "reserved_physical_last": self.local_first_id - 1,
                "local_segment_first": self.local_first_id,
                "local_segment_last": self.local_last_id,
                "local_done": len(self.local_ids),
                "legacy_gaps_ignored": len(self.gap_ids),
                "offloaded_first": self.offloaded_first_id,
                "offloaded_last": self.offloaded_last_id,
                "offloaded": self.offloaded_count,
                "new_pending_first": self.pending_first_id,
                "new_pending_last": self.pending_last_id,
                "new_pending": self.pending_count,
                "next_archive_number": self.next_archive_number,
                "total_rows": self.total_rows,
            },
            "samples": samples,
            "warnings": [
                "Applying creates database rows only; it does not rename, delete, move, index, or download media.",
                "Archive numbers below the local segment remain reserved for inaccessible NAS history.",
            ],
        }


def plan_bootstrap(old_export_path, current_export_path, checkpoint_path, download_dir):
    """Validate legacy evidence and return a deterministic, read-only plan."""
    old_favorites = tuple(export.load_all_favorites(old_export_path))
    current_favorites = tuple(export.load_all_favorites(current_export_path))
    if not old_favorites:
        raise LegacyBootstrapError("The old export contains no readable favorite links.")
    if not current_favorites:
        raise LegacyBootstrapError("The current export contains no readable favorite links.")

    old_links = _unique_links(old_favorites, "old")
    current_links = _unique_links(current_favorites, "current")
    checkpoint = _read_checkpoint(checkpoint_path)
    if checkpoint not in old_links:
        raise LegacyBootstrapError("The checkpoint link was not found in the old export.")
    if checkpoint not in current_links:
        raise LegacyBootstrapError("The checkpoint link was not found in the current export.")

    old_position = old_links.index(checkpoint) + 1
    current_position = current_links.index(checkpoint) + 1
    if old_position != len(old_links):
        raise LegacyBootstrapError("The checkpoint must be the final favorite in the old export.")
    if current_links[:len(old_links)] != old_links:
        raise LegacyBootstrapError(
            "The old export must be an exact prefix of the current export; favorites appear removed or reordered."
        )
    if current_position != old_position:
        raise LegacyBootstrapError("The checkpoint position changed between exports.")

    local_ids = _numeric_mp4_ids(download_dir)
    local_first = local_ids[0]
    local_last = local_ids[-1]
    offset = local_last - old_position
    mapped_first = local_first - offset
    mapped_last = local_last - offset
    if mapped_first < 1 or mapped_last > len(old_favorites):
        raise LegacyBootstrapError(
            "The inferred archive-number offset maps local files outside the old export."
        )
    if mapped_last != old_position:
        raise LegacyBootstrapError("The highest local archive number does not map to the checkpoint.")

    local_set = set(local_ids)
    gap_ids = tuple(item_id for item_id in range(local_first, local_last + 1) if item_id not in local_set)
    offloaded_count = mapped_first - 1
    pending_count = len(current_favorites) - current_position
    offloaded_first, offloaded_last = _range(local_last + 1, local_last + offloaded_count)
    pending_first, pending_last = _range(local_last + offloaded_count + 1,
                                          local_last + offloaded_count + pending_count)
    next_archive_number = local_last + offloaded_count + pending_count + 1

    token_payload = {
        "version": 1,
        "old_favorites": old_favorites,
        "current_favorites": current_favorites,
        "checkpoint": checkpoint,
        "local_ids": local_ids,
        "gap_ids": gap_ids,
        "offset": offset,
    }
    token = hashlib.sha256(
        json.dumps(token_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return LegacyBootstrapPlan(
        old_favorites=old_favorites,
        current_favorites=current_favorites,
        checkpoint=checkpoint,
        checkpoint_old_position=old_position,
        checkpoint_current_position=current_position,
        local_ids=local_ids,
        gap_ids=gap_ids,
        offset=offset,
        mapped_first_position=mapped_first,
        mapped_last_position=mapped_last,
        offloaded_first_id=offloaded_first,
        offloaded_last_id=offloaded_last,
        pending_first_id=pending_first,
        pending_last_id=pending_last,
        next_archive_number=next_archive_number,
        token=token,
    )


def apply_bootstrap(conn, plan, preview_token):
    """Insert a validated plan into an empty library in one transaction."""
    if preview_token != plan.token:
        raise LegacyBootstrapError("The preview token is stale; run preview again before applying.")
    if conn.execute("SELECT 1 FROM item LIMIT 1").fetchone() is not None:
        raise LegacyBootstrapError("Legacy bootstrap requires an empty library database.")

    local_set = set(plan.local_ids)
    now = store._now()

    def insert(item_id, favorite_order, favorite, status, *, offloaded=0, error=None):
        link, favorited_at = favorite
        conn.execute(
            "INSERT INTO item "
            "(id, favorite_order, link, favorited_at, kind, status, error, offloaded, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'unknown', ?, ?, ?, ?, ?)",
            (item_id, favorite_order, link, favorited_at, status, error, offloaded, now, now),
        )

    try:
        conn.execute("BEGIN IMMEDIATE")
        for item_id in range(plan.local_first_id, plan.local_last_id + 1):
            old_position = item_id - plan.offset
            favorite = plan.old_favorites[old_position - 1]
            if item_id in local_set:
                insert(item_id, old_position, favorite, "done")
            else:
                insert(
                    item_id,
                    old_position,
                    favorite,
                    "ignored",
                    error="legacy CLI gap: no local MP4 was present during bootstrap",
                )

        next_id = plan.local_last_id + 1
        for favorite_order, favorite in enumerate(
            plan.current_favorites[:plan.mapped_first_position - 1], start=1
        ):
            insert(next_id, favorite_order, favorite, "done", offloaded=1)
            next_id += 1
        for favorite_order, favorite in enumerate(
            plan.current_favorites[plan.checkpoint_current_position:],
            start=plan.checkpoint_current_position + 1,
        ):
            insert(next_id, favorite_order, favorite, "pending")
            next_id += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        "items_created": plan.total_rows,
        "local_done": len(plan.local_ids),
        "legacy_gaps_ignored": len(plan.gap_ids),
        "offloaded": plan.offloaded_count,
        "new_pending": plan.pending_count,
        "next_archive_number": plan.next_archive_number,
    }
