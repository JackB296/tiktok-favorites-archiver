# Archive glossary

## Favorite

A TikTok link imported from the default Favorites/bookmarks list in a user's
TikTok data export. The app can also opt in to Likes and public creator
profiles; all of these become Archive items with the same stable numbering and
download behavior.

## Archive item

The durable record for one imported TikTok post: its source link, archive
number, media classification, lifecycle state, metadata, and recovered
slideshow assets. A myfaveTT file with no known source link becomes a
local-only Archive item instead of being discarded.

## Archive run

One user-directed pass over Archive items. A Sync run downloads pending or
failed Favorites, then automatically chains its configured follow-up phases:
Gallery indexing, metadata enrichment, and (when opted in) song
identification. An Asset backfill run recovers slideshow assets for archived
Favorites; further run kinds rebuild the Gallery index, fetch oEmbed metadata,
identify songs, and write media-server sidecars on their own. A run can be
running, paused, stopping, stopped, idle, or failed.

## Archive media

The finished MP4 and, for a slideshow, the raw images and audio stored for an
Archive item.

## Creator monitor

A scheduled, idempotent rescan of one public TikTok username. Its first pass
can archive the creator's complete visible backlog; later passes add only newly
discovered stable post IDs. A monitor can be paused, checked immediately, or
removed without deleting already archived items.

## Source sidecar

A portable file stored beside an Archive item's media: privacy-safe
`.info.json`, full `.description`, source thumbnail, available subtitles or
automatic captions, and best-effort public comments/replies. Expiring signed
media URLs and cookies are not persisted.

## Comment snapshot

A dated, local observation of the public comments and replies available for one
Archive item. Each snapshot stores its comments in SQLite and summarizes which
comments were added, became unavailable, or changed since the prior snapshot.
The latest observation is also kept in the item's portable `.comments.json`.

## Portable media metadata

An opt-in copy of useful Source sidecar fields embedded inside an Archive MP4:
caption, creator, description, post date, source link, poster, and available
subtitles. The Archive copies existing video and audio streams, validates the
new MP4 before atomic publication, and continues keeping the separate sidecars.

## Audio repair

A resumable maintenance run over finished, local Archive media whose index
confirmed a missing or silent audio stream. The run retries the source through
the quality-aware yt-dlp adapter, installs only verified audible media, keeps
the Archive item's number and metadata, and retains the previous MP4 as the
most recent replacement backup.

## Offloaded

A mark on an Archive item whose media is archived externally (for example on
another drive). An offloaded item counts as done and is never re-downloaded or
flagged missing, but its row, archive number, and metadata stay in the archive.
Clearing the mark returns a Favorite with no local file to the download queue.

## Ignored

A user-set "never download" lifecycle state for a pending or failed Favorite.
An ignored item is skipped by Sync but keeps its row and archive number as a
position marker; clearing the mark returns it to pending.

## Saved list

A user-named, saved collection. The archive has four kinds: Gallery presets
(filter snapshots), term lists (include/exclude author-and-hashtag terms),
playback queues (hand-picked Favorites), and song playlists (identified
songs). All four share one lifecycle: create with a unique name, list, delete.

## Smart collection

A Gallery preset whose Archive selection is evaluated against current Archive
items whenever it is opened or acted on. Its membership changes as the archive
changes; a playback queue remains a fixed ordered snapshot.

## Storage location

A user-named filesystem directory mounted into the app where Archive media or
Archive snapshots can be stored. A Storage location is available only while
that mounted directory is reachable.

## Media placement

A recorded copy of one Archive item's media at a Storage location, including
the facts needed to verify that copy. One Archive item may have both a local
Media placement and one or more external Media placements.

## Archive snapshot

A self-describing, point-in-time copy of Archive state, optionally including
Archive media. An Archive snapshot can be validated and restored on another
installation without depending on its original filesystem paths.

## Run schedule

A user-defined daily or weekly instruction to start an Archive run while the
app is running. A missed Run schedule may start once when the app next becomes
available.

## Creator

The normalized identity credited for an Archive item. Multiple spelling or
case variants that normalize to the same identity refer to one Creator.

## Hashtag

The normalized identity of a hashtag found in an Archive item's metadata.
Hashtag matching is Unicode-aware and case-insensitive.
