"""Parse a TikTok data export into Favorites (stdlib only)."""
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
    """Every favorited link in processing order (drops the dates)."""
    return [link for link, _favorited_at in load_all_favorites(file_path)]
