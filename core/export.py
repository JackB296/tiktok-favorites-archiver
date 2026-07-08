"""Parse the TikTok data export and apply the resume bookmark (stdlib only)."""
import json
import re
import logging

from core import config


def load_all_favorites(file_path):
    """Return ``[(link, favorited_at), ...]`` for every favorite, in processing order.

    The full, un-filtered list (oldest-first, after reversing the export). ``link``
    has ``tiktokv.com`` normalized to ``tiktok.com``; ``favorited_at`` is the
    export's ``Date`` for that item (``None`` if absent).
    """
    try:
        with open(file_path, "r", encoding="utf-8") as json_file:
            data = json.load(json_file)
    except FileNotFoundError:
        logging.error(f"Video links file not found: {file_path}")
        return []
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from file: {file_path}")
        return []

    item_favorite_list = data.get("Activity", {}).get("Favorite Videos", {}).get("FavoriteVideoList", [])

    return [
        (re.sub(r"tiktokv.com", "tiktok.com", item["Link"]), item.get("Date"))
        for item in item_favorite_list if "Link" in item
    ][::-1]


def load_all_links(file_path):
    """Every favorited link in processing order (drops the dates).

    ``read_video_links`` layers the resume bookmark on top; the manifest backfill
    uses it to map file N -> link N.
    """
    return [link for link, _favorited_at in load_all_favorites(file_path)]


def read_last_downloaded_link(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            last_link = f.read().strip()
    except FileNotFoundError:
        last_link = None
    return last_link


def write_last_downloaded_link(file_path, last_link):
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(last_link)
    except Exception as e:
        logging.error(f"Error writing last downloaded link: {e}")


def read_video_links(file_path):
    modified_lines = load_all_links(file_path)

    last_downloaded_link = read_last_downloaded_link(config.LAST_DOWNLOADED_LINK_FILE)
    if last_downloaded_link:
        try:
            last_link_index = modified_lines.index(last_downloaded_link)
            return modified_lines[last_link_index + 1:]
        except ValueError:
            return modified_lines
    return modified_lines
