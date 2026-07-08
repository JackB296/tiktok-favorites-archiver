"""Provenance manifest (CSV) and output-file numbering (stdlib only)."""
import os
import csv
import logging
from datetime import datetime

from core import config


def get_next_starting_count(directory):
    if not os.path.exists(directory):
        return 1
    existing_files = os.listdir(directory)
    video_numbers = [
        int(f.split(".")[0]) for f in existing_files
        if f.endswith(".mp4") and f.split(".")[0].isdigit()
    ]
    return max(video_numbers, default=0) + 1


def append_manifest(download_dir, filename, link, media_type, status):
    """Append one provenance row (creating the CSV with a header if needed)."""
    manifest_path = os.path.join(download_dir, config.MANIFEST_FILE)
    file_exists = os.path.exists(manifest_path)
    try:
        with open(manifest_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["file", "link", "type", "status", "timestamp"])
            writer.writerow([filename, link, media_type, status,
                             datetime.now().isoformat(timespec="seconds")])
    except OSError as e:
        logging.error(f"Could not write manifest {manifest_path}: {e}")


def backfill_manifest(download_dir, all_links):
    """Best-effort provenance for files downloaded before the manifest existed.

    File ``N.mp4`` maps to the Nth link in the export's processing order, exact
    for a single uninterrupted run over one export. Runs where links failed near
    a resume boundary can shift this, so backfilled rows are marked
    ``status="backfilled"`` and ``type="unknown"`` (a bare .mp4 doesn't reveal
    whether it was a video or a rebuilt slideshow).
    """
    if not os.path.isdir(download_dir):
        return
    manifest_path = os.path.join(download_dir, config.MANIFEST_FILE)
    recorded = set()
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    recorded.add(row.get("file"))
        except OSError as e:
            logging.error(f"Could not read manifest {manifest_path}: {e}")
            return

    mp4s = [f for f in os.listdir(download_dir)
            if f.endswith(".mp4") and f.split(".")[0].isdigit() and f not in recorded]
    added = 0
    for filename in sorted(mp4s, key=lambda x: int(x.split(".")[0])):
        n = int(filename.split(".")[0])
        link = all_links[n - 1] if 1 <= n <= len(all_links) else ""
        append_manifest(download_dir, filename, link, "unknown", "backfilled")
        added += 1
    if added:
        logging.info(f"Backfilled {added} pre-existing file(s) into {manifest_path} (best-effort provenance)")
