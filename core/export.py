"""Parse a TikTok data export into Favorites (stdlib only)."""
import json
import re
import logging

from core import config


class ExportError(ValueError):
    """The export file exists but is not a readable TikTok export.

    The typed error at this module's seam: callers (the /import route, the
    legacy bootstrap) map it to their own user-facing failures without knowing
    this parser's exception zoology.
    """


def load_all_favorites(file_path):
    """Return ``[(link, favorited_at), ...]`` for every favorite, in processing order.

    The full, un-filtered list (oldest-first, after reversing the export). ``link``
    has ``tiktokv.com`` normalized to ``tiktok.com``; ``favorited_at`` is the
    export's ``Date`` for that item (``None`` if absent).

    Raises :class:`ExportError` for unusable content — invalid JSON, a payload
    that is not the TikTok export shape, or non-string links. A *missing* file
    stays a soft empty result so the CLI keeps working without an export file.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as json_file:
            data = json.load(json_file)
    except FileNotFoundError:
        logging.error(f"Video links file not found: {file_path}")
        return []
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ExportError(f"the file is not valid JSON ({exc})") from exc

    if not isinstance(data, dict):
        raise ExportError("the file must contain a JSON object")

    # TikTok has used both section names for the same export payload. Older
    # exports put favorites below ``Activity``; current exports put them below
    # ``Likes and Favorites``. Keep accepting both so a schema-label change
    # cannot silently turn a valid upload into an empty import.
    item_favorite_list = None
    found_section = False
    for section_name in ("Likes and Favorites", "Activity"):
        section = data.get(section_name)
        if not isinstance(section, dict):
            continue
        videos = section.get("Favorite Videos")
        if not isinstance(videos, dict):
            continue
        found_section = True
        candidate = videos.get("FavoriteVideoList")
        if isinstance(candidate, list):
            item_favorite_list = candidate
            if candidate:
                break
    if item_favorite_list is None:
        if found_section:
            raise ExportError("the favorites list in the export is malformed")
        raise ExportError(
            "no favorites section found — upload the JSON `user_data_tiktok.json` from a TikTok data export"
        )

    try:
        return [
            (re.sub(r"tiktokv\.com", "tiktok.com", item["Link"]), item.get("Date"))
            for item in item_favorite_list
            if isinstance(item, dict) and "Link" in item
        ][::-1]
    except TypeError as exc:  # a non-string Link
        raise ExportError("favorite entries must carry string links") from exc

