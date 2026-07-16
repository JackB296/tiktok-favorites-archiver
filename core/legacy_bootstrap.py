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

from core import export, layout, store


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
    ids = layout.finished_movie_ids(names)
    if not ids:
        raise LegacyBootstrapError("No numeric MP4 files were found in the downloads directory.")
    if ids[0] < 1:
        raise LegacyBootstrapError("Legacy archive numbers must be positive integers.")
    return tuple(ids)


def _bounds_or_none(first, last):
    """The inclusive bounds of an id span, or (None, None) when the span is empty."""
    return (first, last) if first <= last else (None, None)


@dataclass(frozen=True)
class MappingSegment:
    start_id: int
    end_id: int
    offset: int
    first_position: int
    last_position: int

    def public(self):
        return {
            "start_id": self.start_id,
            "end_id": self.end_id,
            "offset": self.offset,
            "first_position": self.first_position,
            "last_position": self.last_position,
        }


def _build_segments(mapping_segments, local_ids, old_count, checkpoint_position):
    local_first, local_last = local_ids[0], local_ids[-1]
    if mapping_segments is None:
        mapping_segments = [{
            "start_id": local_first,
            "offset": local_last - checkpoint_position,
        }]
    if not isinstance(mapping_segments, list) or not mapping_segments:
        raise LegacyBootstrapError("Mapping segments must be a non-empty list.")

    specs = []
    for value in mapping_segments:
        if not isinstance(value, dict) or type(value.get("start_id")) is not int or type(value.get("offset")) is not int:
            raise LegacyBootstrapError("Each mapping segment needs integer start_id and offset values.")
        specs.append((value["start_id"], value["offset"]))
    if specs != sorted(set(specs)) or len({start for start, _offset in specs}) != len(specs):
        raise LegacyBootstrapError("Mapping segment start IDs must be unique and ascending.")
    if specs[0][0] != local_first:
        raise LegacyBootstrapError("The first mapping segment must start at the lowest local archive number.")

    local_set = set(local_ids)
    segments = []
    reused_positions = []
    previous_last_position = None
    for index, (start_id, offset) in enumerate(specs):
        if start_id not in local_set:
            raise LegacyBootstrapError(f"Mapping segment #{start_id} must begin at an existing MP4.")
        end_id = specs[index + 1][0] - 1 if index + 1 < len(specs) else local_last
        if not local_first <= start_id <= end_id <= local_last:
            raise LegacyBootstrapError("Mapping segment bounds must stay inside the local archive range.")
        first_position = start_id - offset
        last_position = end_id - offset
        if first_position < 1 or last_position > old_count:
            raise LegacyBootstrapError("A mapping segment lands outside the old export.")
        if previous_last_position is not None:
            if first_position <= previous_last_position:
                raise LegacyBootstrapError("Mapping segments overlap or reverse favorite positions.")
            reused_positions.extend(range(previous_last_position + 1, first_position))
        segments.append(MappingSegment(
            start_id=start_id,
            end_id=end_id,
            offset=offset,
            first_position=first_position,
            last_position=last_position,
        ))
        previous_last_position = last_position

    if segments[-1].last_position != checkpoint_position:
        raise LegacyBootstrapError("The final mapping segment does not land on the checkpoint.")
    return tuple(segments), tuple(reused_positions)


@dataclass(frozen=True)
class LegacyBootstrapPlan:
    old_favorites: tuple
    current_favorites: tuple
    checkpoint: str
    checkpoint_old_position: int
    checkpoint_current_position: int
    local_ids: tuple
    gap_ids: tuple
    segments: tuple
    reused_number_positions: tuple
    offset: int
    mapped_first_position: int
    mapped_last_position: int
    offloaded_first_id: Optional[int]
    offloaded_last_id: Optional[int]
    pending_first_id: Optional[int]
    pending_last_id: Optional[int]
    reused_marker_first_id: Optional[int]
    reused_marker_last_id: Optional[int]
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
        return (
            (self.local_last_id - self.local_first_id + 1)
            + self.offloaded_count
            + len(self.reused_number_positions)
            + self.pending_count
        )

    def position_for_id(self, item_id):
        for segment in self.segments:
            if segment.start_id <= item_id <= segment.end_id:
                return item_id - segment.offset
        raise LegacyBootstrapError(f"Archive number #{item_id} is not covered by a mapping segment.")

    def preview(self):
        samples = []
        sample_ids = []
        for segment in self.segments:
            segment_ids = [
                item_id for item_id in self.local_ids
                if segment.start_id <= item_id <= segment.end_id
            ]
            indexes = (0, len(segment_ids) // 2, len(segment_ids) - 1)
            sample_ids.extend(segment_ids[index] for index in indexes)
        sample_ids = tuple(dict.fromkeys(sample_ids))
        for item_id in sample_ids:
            old_position = self.position_for_id(item_id)
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
            "segments": [segment.public() for segment in self.segments],
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
                "physical_gaps": len(self.gap_ids),
                "reused_number_markers": len(self.reused_number_positions),
                "gaps": len(self.gap_ids) + len(self.reused_number_positions),
            },
            "allocation": {
                "reserved_physical_first": 1,
                "reserved_physical_last": self.local_first_id - 1,
                "local_segment_first": self.local_first_id,
                "local_segment_last": self.local_last_id,
                "local_done": len(self.local_ids),
                "legacy_gaps_ignored": len(self.gap_ids) + len(self.reused_number_positions),
                "physical_gaps_ignored": len(self.gap_ids),
                "reused_number_markers": len(self.reused_number_positions),
                "offloaded_first": self.offloaded_first_id,
                "offloaded_last": self.offloaded_last_id,
                "offloaded": self.offloaded_count,
                "reused_marker_first": self.reused_marker_first_id,
                "reused_marker_last": self.reused_marker_last_id,
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


def plan_bootstrap(
    old_export_path,
    current_export_path,
    checkpoint_path,
    download_dir,
    mapping_segments=None,
):
    """Validate legacy evidence and return a deterministic, read-only plan."""
    try:
        old_favorites = tuple(export.load_all_favorites(old_export_path))
        current_favorites = tuple(export.load_all_favorites(current_export_path))
    except export.ExportError as error:
        raise LegacyBootstrapError(f"Unreadable export: {error}") from error
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
    segments, reused_positions = _build_segments(
        mapping_segments, local_ids, len(old_favorites), old_position
    )
    offset = segments[-1].offset
    mapped_first = segments[0].first_position
    mapped_last = segments[-1].last_position

    local_set = set(local_ids)
    gap_ids = tuple(item_id for item_id in range(local_first, local_last + 1) if item_id not in local_set)
    offloaded_count = mapped_first - 1
    pending_count = len(current_favorites) - current_position
    offloaded_first, offloaded_last = _bounds_or_none(local_last + 1, local_last + offloaded_count)
    reused_first, reused_last = _bounds_or_none(
        local_last + offloaded_count + 1,
        local_last + offloaded_count + len(reused_positions),
    )
    pending_first, pending_last = _bounds_or_none(
        local_last + offloaded_count + len(reused_positions) + 1,
        local_last + offloaded_count + len(reused_positions) + pending_count,
    )
    next_archive_number = local_last + offloaded_count + len(reused_positions) + pending_count + 1

    token_payload = {
        "version": 2,
        "old_favorites": old_favorites,
        "current_favorites": current_favorites,
        "checkpoint": checkpoint,
        "local_ids": local_ids,
        "gap_ids": gap_ids,
        "segments": [segment.public() for segment in segments],
        "reused_number_positions": reused_positions,
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
        segments=segments,
        reused_number_positions=reused_positions,
        offset=offset,
        mapped_first_position=mapped_first,
        mapped_last_position=mapped_last,
        offloaded_first_id=offloaded_first,
        offloaded_last_id=offloaded_last,
        pending_first_id=pending_first,
        pending_last_id=pending_last,
        reused_marker_first_id=reused_first,
        reused_marker_last_id=reused_last,
        next_archive_number=next_archive_number,
        token=token,
    )


def apply_bootstrap(conn, plan, preview_token):
    """Insert a validated plan into an empty library in one transaction."""
    if preview_token != plan.token:
        raise LegacyBootstrapError("The preview token is stale; run preview again before applying.")
    if store.has_items(conn):
        raise LegacyBootstrapError("Legacy bootstrap requires an empty library database.")

    local_set = set(plan.local_ids)
    rows = []

    def insert(item_id, favorite_order, favorite, status, *, offloaded=0, error=None):
        link, favorited_at = favorite
        rows.append({
            "id": item_id, "favorite_order": favorite_order, "link": link,
            "favorited_at": favorited_at, "status": status, "error": error,
            "offloaded": offloaded,
        })

    for segment in plan.segments:
        for item_id in range(segment.start_id, segment.end_id + 1):
            old_position = item_id - segment.offset
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
    for favorite_order in plan.reused_number_positions:
        insert(
            next_id,
            favorite_order,
            plan.old_favorites[favorite_order - 1],
            "ignored",
            error="legacy CLI restart reused archive number; no local MP4 exists",
        )
        next_id += 1
    for favorite_order, favorite in enumerate(
        plan.current_favorites[plan.checkpoint_current_position:],
        start=plan.checkpoint_current_position + 1,
    ):
        insert(next_id, favorite_order, favorite, "pending")
        next_id += 1

    store.bulk_insert_items(conn, rows)

    return {
        "items_created": plan.total_rows,
        "local_done": len(plan.local_ids),
        "legacy_gaps_ignored": len(plan.gap_ids) + len(plan.reused_number_positions),
        "physical_gaps_ignored": len(plan.gap_ids),
        "reused_number_markers": len(plan.reused_number_positions),
        "offloaded": plan.offloaded_count,
        "new_pending": plan.pending_count,
        "next_archive_number": plan.next_archive_number,
    }
