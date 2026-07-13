"""Import a TikTok export + existing downloads into the SQLite store, and
regenerate ``downloads/manifest.csv`` from the DB (stdlib only).

Numbering rule (matches the legacy behaviour): favorites are inserted in export
order, so item ``N`` ↔ the Nth favorite ↔ ``downloads/N.mp4``. Existing files are
then marked ``done``; a file with no matching favorite (export shrank) is
represented with a synthetic ``local://`` link so it still shows in the library.
"""
import os
import csv
import logging

from core import config, export, inventory, store


def import_export(conn, export_file):
    """Upsert one item per favorite, in order. Idempotent (dedups by link)."""
    favorites = export.load_all_favorites(export_file)
    for link, favorited_at in favorites:
        store.upsert_link(conn, link, favorited_at=favorited_at)
    return len(favorites)


def import_existing_files(conn, download_dir):
    """Mark items whose ``<n>.mp4`` already exists as done; flag present raw assets."""
    if not os.path.isdir(download_dir):
        return 0
    marked = 0
    for name in os.listdir(download_dir):
        stem = name.split(".")[0]
        # Exactly "<n>.mp4": a crashed encode's "<n>.mp4.part.mp4" temp must not
        # be imported as a finished item.
        if not (stem.isdigit() and name == f"{stem}.mp4"):
            continue
        n = int(stem)
        item = store.get_item(conn, n)
        if item is None:
            store.insert_item(
                conn,
                n,
                f"local://file/{n}",
                kind="unknown",
                status="done",
                favorite_order=store.next_favorite_order(conn),
            )
        elif item["status"] != "done":
            store.set_status(conn, n, "done")
        if os.path.isdir(os.path.join(download_dir, str(n))):
            store.set_has_assets(conn, n, True)
        marked += 1
    return marked


def regenerate_manifest(conn, download_dir):
    """Rewrite ``manifest.csv`` from the DB (provenance for files present on disk)."""
    if not os.path.isdir(download_dir):
        return 0
    manifest_path = os.path.join(download_dir, config.MANIFEST_FILE)
    written = 0
    try:
        with open(manifest_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["file", "link", "type", "status", "timestamp"])
            for row in store.all_items(conn):
                if os.path.exists(os.path.join(download_dir, f"{row['id']}.mp4")):
                    writer.writerow([f"{row['id']}.mp4", inventory._safe_cell(row["link"]),
                                     row["kind"], row["status"], row["updated_at"]])
                    written += 1
    except OSError as e:
        logging.error(f"Could not write manifest {manifest_path}: {e}")
    return written


def import_all(conn, export_file, download_dir):
    n_fav = import_export(conn, export_file)
    n_files = import_existing_files(conn, download_dir)
    n_manifest = regenerate_manifest(conn, download_dir)
    logging.info(
        f"Import: {n_fav} favorites, {n_files} existing files marked, {n_manifest} manifest rows"
    )
    return {"favorites": n_fav, "existing_files": n_files, "manifest_rows": n_manifest}
