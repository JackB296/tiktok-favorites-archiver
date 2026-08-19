"""Discover every public post from a TikTok username and add it to the archive."""
from dataclasses import dataclass
from datetime import datetime, timezone
import re

from core import source_metadata, store


class ProfileImportError(ValueError):
    pass


_USERNAME = re.compile(r"^[A-Za-z0-9._]{1,32}$")
_PROFILE_URL = re.compile(r"^(?:https?://)?(?:www\.)?tiktok\.com/@([^/?#]+)", re.I)


@dataclass(frozen=True)
class ProfilePost:
    link: str
    posted_at: str | None = None
    caption: str | None = None
    author: str | None = None
    metadata: source_metadata.SourceMetadata | None = None
    is_repost: bool = False


def normalize_username(value):
    if not isinstance(value, str):
        raise ProfileImportError("enter a TikTok username")
    username = value.strip()
    match = _PROFILE_URL.match(username)
    if match:
        username = match.group(1)
    username = username.lstrip("@").strip()
    if not _USERNAME.fullmatch(username):
        raise ProfileImportError("username may contain only letters, numbers, periods, and underscores")
    return username


def _date_from_entry(entry):
    timestamp = entry.get("timestamp")
    if isinstance(timestamp, (int, float)):
        return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    upload_date = entry.get("upload_date")
    if isinstance(upload_date, str) and re.fullmatch(r"\d{8}", upload_date):
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]} 00:00:00"
    return None


def _posts_from_info(info, requested_username):
    entries = info.get("entries") if isinstance(info, dict) else None
    if entries is None:
        raise ProfileImportError("TikTok did not return a public profile feed")
    posts = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        video_id = str(entry.get("id") or "")
        if not video_id.isdigit() or video_id in seen:
            continue
        author = entry.get("uploader") or requested_username
        if not isinstance(author, str) or not _USERNAME.fullmatch(author):
            author = requested_username
        link = entry.get("webpage_url") or entry.get("url")
        if not isinstance(link, str) or not re.search(r"/(?:video|photo)/\d+", link):
            link = f"https://www.tiktok.com/@{author}/video/{video_id}"
        metadata = source_metadata.from_info(entry, fallback_url=link, fallback_username=author)
        posts.append(ProfilePost(
            link=link,
            posted_at=_date_from_entry(entry),
            caption=(entry.get("description") or entry.get("title")) if isinstance(entry.get("description") or entry.get("title"), str) else None,
            author=author,
            metadata=metadata,
            is_repost=bool(entry.get("is_repost") or entry.get("repost")),
        ))
        seen.add(video_id)
    # TikTok/yt-dlp returns newest first; archive allocation is chronological.
    return posts[::-1]


def discover_profile(value, extractor=None, limit=None, collect_comments=True):
    """Return a public profile's posts oldest-first without downloading media."""
    username = normalize_username(value)
    if limit is not None:
        try:
            limit = int(limit)
        except (TypeError, ValueError) as exc:
            raise ProfileImportError("profile limit must be a positive integer") from exc
        if not 1 <= limit <= 100_000:
            raise ProfileImportError("profile limit must be between 1 and 100000")

    if extractor is None:
        try:
            from yt_dlp import YoutubeDL
        except ImportError as exc:
            raise ProfileImportError("profile importing requires the yt-dlp dependency") from exc

        def extractor(url):
            options = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                # Full entries provide original dimensions/thumbnails and the
                # complete source metadata sidecars requested for monitoring.
                "extract_flat": False,
                "ignoreerrors": True,
                "getcomments": bool(collect_comments),
                "socket_timeout": 30,
                "retries": 3,
            }
            if limit is not None:
                options["playlistend"] = limit
            with YoutubeDL(options) as ydl:
                return ydl.extract_info(url, download=False)

    try:
        info = extractor(f"https://www.tiktok.com/@{username}")
    except Exception as exc:
        raise ProfileImportError(f"could not read @{username}'s public videos: {exc}") from exc
    posts = _posts_from_info(info, username)
    if not posts:
        raise ProfileImportError(f"no public videos were found for @{username}")
    return username, posts


def import_profile(conn, value, extractor=None, limit=None, download_dir=None, fetch=None,
                   policy=None, now=None):
    policy = policy or {}
    collect_comments = bool(policy.get("collect_comments", True))
    username, posts = discover_profile(
        value, extractor=extractor, limit=limit, collect_comments=collect_comments,
    )
    discovered = len(posts)
    archive_mode = policy.get("archive_mode", "all")
    keywords = [str(value).casefold() for value in policy.get("keywords", []) if str(value).strip()]
    if archive_mode not in ("all", "matching") or (archive_mode == "matching" and not keywords):
        raise ProfileImportError("matching creator rules need at least one keyword")
    if archive_mode == "matching":
        posts = [post for post in posts if any(term in (post.caption or "").casefold() for term in keywords)]
    if policy.get("exclude_reposts"):
        posts = [post for post in posts if not post.is_repost]
    max_days = policy.get("max_backlog_days")
    if max_days is not None:
        instant = now or datetime.now(timezone.utc)
        cutoff = instant.astimezone(timezone.utc).timestamp() - int(max_days) * 86400
        def recent(post):
            if not post.posted_at:
                return True
            try:
                posted = datetime.fromisoformat(post.posted_at.replace("Z", "+00:00"))
                if posted.tzinfo is None:
                    posted = posted.replace(tzinfo=timezone.utc)
                return posted.timestamp() >= cutoff
            except ValueError:
                return True
        posts = [post for post in posts if recent(post)]
    before = {row["link"] for row in store.all_items(conn)}
    item_ids = []
    changed = 0
    for post in posts:
        # ``favorited_at`` specifically means the owner's save timestamp in
        # archive statistics. A creator post date is different provenance, so
        # leave it unset while retaining oldest-first allocation.
        existing = store.get_item_by_video_id(conn, post.metadata.post_id) if post.metadata else None
        item_id = existing["id"] if existing is not None else store.upsert_link(conn, post.link)
        is_new = existing is None and post.link not in before
        item_ids.append(item_id)
        row = store.get_item(conn, item_id)
        before_metadata = tuple(row[field] for field in ("caption", "description", "creator_username", "view_count", "like_count", "comment_count"))
        if post.metadata is not None:
            if download_dir is not None:
                source_metadata.archive(
                    conn, download_dir, item_id, post.metadata,
                    fetch=fetch or source_metadata.fetch_resource,
                )
            else:
                store.set_source_metadata(conn, item_id, post.metadata)
        elif post.caption and post.author and not (row["caption"] and row["author"]):
            store.set_metadata(
                conn,
                item_id,
                post.caption or row["caption"] or "",
                post.author or row["author"] or username,
            )
        if is_new and (policy.get("analyze_new") or policy.get("identify_songs")):
            store.request_creator_enrichment(
                conn, item_id, analyze=bool(policy.get("analyze_new")),
                identify=bool(policy.get("identify_songs")),
            )
        if not is_new:
            refreshed = store.get_item(conn, item_id)
            after_metadata = tuple(refreshed[field] for field in ("caption", "description", "creator_username", "view_count", "like_count", "comment_count"))
            changed += before_metadata != after_metadata
    added = sum(1 for post in posts if post.link not in before)
    return {
        "username": username,
        "discovered": discovered,
        "matched": len(posts),
        "added": added,
        "existing": len(posts) - added,
        "item_ids": item_ids,
        "post_ids": [post.metadata.post_id for post in posts if post.metadata],
        "changed": changed,
    }


def monitor_profile(conn, value, download_dir, interval_hours=6, extractor=None,
                    fetch=None, now=None, policy=None):
    """Import the complete current backlog, then remember the creator."""
    username = normalize_username(value)
    result = import_profile(
        conn, username, extractor=extractor, download_dir=download_dir, fetch=fetch,
        policy=policy, now=now,
    )
    store.save_creator_monitor(
        conn, username, interval_hours=interval_hours, enabled=True, now=now,
        seen_post_ids=result["post_ids"], **(policy or {}),
    )
    return result


def run_monitors(conn, download_dir, extractor_factory=None, fetch=None, now=None,
                 progress=None, should_continue=None):
    """Refresh due creators; full-feed discovery makes backlog gaps self-heal."""
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("monitor clock must be timezone-aware")
    instant = instant.astimezone(timezone.utc)
    monitors = store.due_creator_monitors(conn, instant)
    result = {"checked": 0, "added": 0, "failed": 0}
    if progress:
        progress({"event": "creator-monitor", "total": len(monitors), **result})
    for monitor in monitors:
        if should_continue and not should_continue():
            break
        error = None
        added = 0
        changed = missing = 0
        seen_post_ids = None
        try:
            extractor = extractor_factory(monitor["username"]) if extractor_factory else None
            imported = import_profile(
                conn, monitor["username"], extractor=extractor,
                download_dir=download_dir, fetch=fetch, now=instant,
                policy={
                    "archive_mode": monitor["archive_mode"], "keywords": monitor["keywords"],
                    "exclude_reposts": monitor["exclude_reposts"], "max_backlog_days": monitor["max_backlog_days"],
                    "collect_comments": monitor["collect_comments"],
                },
            )
            added = imported["added"]
            changed = imported["changed"]
            seen_post_ids = imported["post_ids"]
            missing = len(set(monitor["last_seen_post_ids"]) - set(seen_post_ids))
            result["added"] += added
        except Exception as exc:
            error = exc
            result["failed"] += 1
        store.mark_creator_monitor_checked(
            conn, monitor["id"], added=added, error=error, now=instant,
            changed=changed, missing=missing, seen_post_ids=seen_post_ids,
        )
        result["checked"] += 1
        if progress:
            progress({
                "event": "creator-monitor", "username": monitor["username"],
                "total": len(monitors), **result,
            })
    if monitors:
        from core import source_health
        source_health.record(
            conn, "creator-monitor", attempted=result["checked"],
            succeeded=result["checked"] - result["failed"], failed=result["failed"],
        )
    return result


def run_monitor_job(conn, download_dir, progress=None, wait=None, control=None):
    from core import runs
    if control is None:
        control = runs.RunControl(conn, progress=progress, wait=wait)
    return run_monitors(
        conn, download_dir, progress=control.progress,
        should_continue=control.should_continue,
    )


def run_monitor_followups(conn, download_dir, progress=None, wait=None, control=None):
    """After monitored media syncs, enrich only posts whose monitor requested it."""
    from core import analysis, identify, runs
    if control is None:
        control = runs.RunControl(conn, progress=progress, wait=wait)
    result = {"analysis": None, "songs": None}
    analysis_ids = store.creator_enrichment_ids(conn, "creator_analyze_requested")
    if analysis_ids:
        result["analysis"] = analysis.run_analysis(
            conn, download_dir, control=control, item_ids=analysis_ids,
        )
        store.clear_creator_enrichment(conn, "creator_analyze_requested", analysis_ids)
    song_ids = store.creator_enrichment_ids(conn, "creator_identify_requested")
    if song_ids and store.get_library_settings(conn)["song_id_enabled"]:
        result["songs"] = identify.run_identification(
            conn, download_dir, control=control, item_ids=song_ids,
        )
        store.clear_creator_enrichment(conn, "creator_identify_requested", song_ids)
    elif song_ids:
        result["songs"] = {"skipped": "Song identification is not enabled; requests remain queued."}
    return result
