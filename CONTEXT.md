# Archive glossary

## Favorite

A TikTok link imported from a user's TikTok data export. A Favorite keeps a
stable archive number and may resolve to a video, slideshow, or unavailable
post.

## Archive item

The durable record for one Favorite: its source link, archive number, media
classification, lifecycle state, metadata, and recovered slideshow assets.

## Archive run

One user-directed pass over Archive items. A Sync run downloads pending or
failed Favorites, then automatically chains its incremental follow-up phases:
Gallery indexing, metadata enrichment, and (when opted in) song
identification. An Asset backfill run recovers slideshow assets for archived
Favorites; further run kinds rebuild the Gallery index, fetch oEmbed metadata,
identify songs, and write media-server sidecars on their own. A run can be
running, paused, stopping, stopped, idle, or failed.

## Archive media

The finished MP4 and, for a slideshow, the raw images and audio stored for an
Archive item.

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
