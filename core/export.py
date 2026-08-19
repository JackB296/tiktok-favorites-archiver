"""Parse saved-video lists from a TikTok data export (stdlib only)."""
import json
import logging
import re


class ExportError(ValueError):
    """The export file exists but is not a readable TikTok export."""


EXPORT_SELECTIONS = ("favorites", "likes", "both")

_LIST_SPECS = {
    "favorites": (
        ("Favorite Videos", "FavoriteVideoList"),
        ("Favorites", "FavoriteVideoList"),
    ),
    "likes": (
        ("Like List", "ItemFavoriteList"),
        ("Liked Videos", "LikedVideoList"),
        ("Liked Videos", "ItemFavoriteList"),
    ),
}


def _saved_list(data, kind):
    """Return one newest-first export list, or ``None`` when absent."""
    malformed = False
    for section_name in ("Likes and Favorites", "Activity"):
        section = data.get(section_name)
        if not isinstance(section, dict):
            continue
        for group_name, list_name in _LIST_SPECS[kind]:
            group = section.get(group_name)
            if not isinstance(group, dict):
                continue
            candidate = group.get(list_name)
            if isinstance(candidate, list):
                return candidate
            malformed = True
    if malformed:
        raise ExportError(f"the {kind} list in the export is malformed")
    return None


def _parse_entries(entries, kind):
    try:
        return [
            (re.sub(r"tiktokv\.com", "tiktok.com", item["Link"]), item.get("Date"))
            for item in entries
            if isinstance(item, dict) and "Link" in item
        ][::-1]
    except TypeError as exc:
        raise ExportError(f"{kind} entries must carry string links") from exc


def _combine(oldest_first_lists):
    """Merge saved lists chronologically, keeping one row per link."""
    by_link = {}
    position = 0
    for entries in oldest_first_lists:
        for link, saved_at in entries:
            previous = by_link.get(link)
            if previous is None or (previous[0] is None and saved_at is not None):
                by_link[link] = (saved_at, position)
            position += 1
    rows = [(link, saved_at, order) for link, (saved_at, order) in by_link.items()]
    rows.sort(key=lambda row: (row[1] is None, str(row[1] or ""), row[2]))
    return [(link, saved_at) for link, saved_at, _order in rows]


def load_saved_videos(file_path, selection="favorites"):
    """Return selected saved videos in oldest-first processing order.

    ``selection`` is ``favorites`` (the backward-compatible default), ``likes``,
    or ``both``. TikTok has used both ``Activity`` and ``Likes and Favorites``
    as the enclosing section, so both are accepted.
    """
    if selection not in EXPORT_SELECTIONS:
        raise ExportError("selection must be favorites, likes, or both")
    try:
        with open(file_path, "r", encoding="utf-8") as json_file:
            data = json.load(json_file)
    except FileNotFoundError:
        logging.error("Video links file not found: %s", file_path)
        return []
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ExportError(f"the file is not valid JSON ({exc})") from exc

    if not isinstance(data, dict):
        raise ExportError("the file must contain a JSON object")

    requested = ("favorites", "likes") if selection == "both" else (selection,)
    parsed = []
    missing = []
    for kind in requested:
        entries = _saved_list(data, kind)
        if entries is None:
            missing.append(kind)
        else:
            parsed.append(_parse_entries(entries, kind))
    if missing:
        names = " and ".join(missing)
        raise ExportError(
            f"no {names} section found — upload the JSON `user_data_tiktok.json` from a TikTok data export"
        )
    return parsed[0] if len(parsed) == 1 else _combine(parsed)


def load_all_favorites(file_path):
    """Backward-compatible favorites/bookmarks-only parser."""
    return load_saved_videos(file_path, selection="favorites")
