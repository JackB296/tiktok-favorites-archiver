# Performance log

Running log of measured optimizations. All timings are against the real
production archive (≈18.5k favorites, 2.06 GB `archive.db` with 12,363 comment
snapshots / 3.43 M saved comments) running in Docker Desktop on Windows, where
`appdata/` and `downloads/` are bind mounts — every page of database I/O
crosses the gRPC-FUSE file-sharing boundary, which is what makes redundant
reads so expensive.

## 2026-08-26 — Stats page: 27 s → 0.72 s (37×)

`GET /api/stats` took **26.9 s**; profiling showed 23.7 s in the conversation
section alone and the rest spread over eight full scans of `item`.

1. **Covering index for comment-history aggregation** (`core/store.py`,
   `idx_comment_snapshot_stats`). The stats query only needs
   `item_id, id, saved_count, added_count, removed_count, changed_count`, but
   the count columns are stored *after* the multi-KB `comments_json` blob in
   each record, so reading them walked every snapshot's overflow pages —
   effectively the whole 787 MB table. The covering index answers the query
   from a few MB of index pages.
   **Measured: 23.65 s → 0.02 s (~1,200×).**
2. **Single-scan item aggregates** (`core/stats.py`, `_item_aggregates`). The
   hero/watcher/reach/discovery-lag/quality/health sections each ran their own
   full scan of `item` (~0.35 s per scan over the bind mount). They now share
   one `WITH scan AS (SELECT …)` pass computing all ~40 aggregates; NULL
   operands make each predicate NULL, which `SUM` skips, preserving the old
   per-query `WHERE … IS NOT NULL` semantics exactly.
   **Measured: endpoint 2.76 s → 0.72 s after the index fix (8 scans → 1).**

End-to-end: **26.9 s → 0.72 s** on a cold per-request connection.

## 2026-08-26 — App startup: ~95 s → ~15 s (6.4×)

`init_db` runs at every boot and was re-reading the big comment tables:

1. **`missing_entry_snapshots` anti-join** (`core/store.py`). The old
   `LEFT JOIN … GROUP BY … HAVING COUNT = 0` selected `comments_json` for all
   12k snapshots before discarding them — 787 MB of reads to return 0 rows.
   Now a `NOT EXISTS` anti-join over the covering index finds candidate ids
   without touching the blob column, and JSON is fetched per candidate only.
   **Measured: 25.65 s → 1.17 s (22×).**
2. **`latest_comments` adoption query** rewritten from a correlated
   `MAX(id)` subquery over the table to a `GROUP BY` over the
   `(item_id, id)` index, again fetching JSON per adopted row only.
   **Measured: 2.10 s → 1.03 s.**
3. **FTS5 row counts from `*_docsize` shadow tables.** `COUNT(*)` on an FTS5
   virtual table walks the full-text index: 6.6 s for `comment_search`,
   13.2 s for `comment_entry_search` (3.4 M rows). The `_docsize` shadow
   table has exactly one row per document (columnsize is on for all our FTS
   tables), so counting it is equivalent.
   **Measured: 19.8 s → 1.3 s combined (15×).**

End-to-end container start to first successful request: **~95 s → ~15 s.**

4. **One-time adoption marker** (`core/store.py` + `migrations.mark_completed`).
   Even the fast versions of the comment-search adoption and normalization
   checks re-scanned the comment tables every boot (~6.6 s) to conclude
   "nothing to do". Snapshot saves index themselves, so the reconciliation
   only has work on pre-feature databases: it now records completion in
   `backfill_state` (`comment-search-adoption-v1`) and is skipped forever
   after.
   **Measured: startup ~15 s → 2 s steady-state (one 9 s first boot).**

Total: **~95 s → 2 s (47×).**

## 2026-08-26 — Hashtags/Creators tabs: 3.9 s → 0.08 s (~50×)

`GET /api/hashtags` ranked 22,233 hashtags by running three correlated
subqueries per row; the latest-favorite subquery probed `item` rows through
the rowid tree, thrashing the 2 MB default page cache (7.5 s alone).

1. **`idx_item_id_dates` covering index + `INDEXED BY`** (`core/store.py`,
   `core/discovery.py`). The probes only need `favorited_at`/`favorite_order`,
   so a `(id, favorited_at, favorite_order)` index answers them from ~200 KB
   of index pages. SQLite's planner prefers the rowid tree (fewer pages in
   theory), so the discovery queries name the index explicitly.
   **Measured: latest-favorite pass 7.5 s → 0.13 s (58×).**
2. **`first_item_id` moved outside the ranking query** so it is computed for
   the ~50 returned rows instead of all 22k ranked rows.

## 2026-08-26 — Comment search: 14.6 s worst case → <0.2 s

`GET /api/comments/search` ordered FTS5 matches by `ce.id DESC`, which
materialized and joined *every* match before sorting — 4,917 rows for "cat"
(1.0 s), ~2 M-postings words like "the" took 14.6 s. Ordering by the FTS
table's own rowid (`ces.rowid DESC`, same value) lets FTS5 stream matches
newest-first and stop at the LIMIT.
**Measured: "the" 14.65 s → <0.01 s raw query; endpoint ≤0.2 s.**

## 2026-08-26 — Warm shared read connection: dashboard ~5× faster

Every request opened a fresh SQLite connection, so every request re-read its
working set through the bind mount. Read-only handlers (stats, coverage,
library-stats, gallery/feed listings, discovery, suggest, songs, comment
search) now share one app-lifetime connection (`store.connect_readonly`,
`PRAGMA query_only=ON` so any accidental write fails loudly; sqlite3
threadsafety 3 makes cross-thread sharing safe) with a 32 MB page cache
(`PRAGMA cache_size=-32000`, also applied to regular connections).
**Measured: stats 0.72 s → 0.13 s; coverage 0.43 s → 0.04 s; library-stats
0.41 s → 0.015 s. Costs ~32 MB of resident cache — the one deliberate
RAM-for-speed trade in this pass.**

## 2026-08-26 — Idle/after-run RAM

- **`MALLOC_ARENA_MAX=2`** (Dockerfile + docker-compose.yml): glibc keeps one
  malloc arena per thread (up to 8×cores) and rarely returns freed arena
  memory, so the Python process's RSS stayed at its high-water mark after
  analysis/download runs. Two arenas keep idle RSS near the true working set.
- **`%USERPROFILE%\.wslconfig`** created with
  `[experimental] autoMemoryReclaim=gradual`: the WSL2 VM (which hosts Docker
  Desktop) otherwise holds Linux file-cache pages from streaming media and the
  2 GB database through bind mounts, which Windows reports as gigabytes "used
  by Docker" at idle. Gradual reclaim returns cached-but-unused memory to
  Windows. Takes effect after `wsl --shutdown`.
- Baseline for reference: the app container idles at ~70–85 MiB (of which
  ~32 MiB is the deliberate shared read cache), Cobalt at ~45 MiB.

## Endpoint sweep after this pass (production archive, warm)

| Endpoint | Before | After |
|---|---|---|
| `/api/stats` | 26.9 s | 0.15 s |
| `/api/hashtags` | 3.87 s | 0.08 s |
| `/api/comments/search?q=the` | ~14 s | 0.20 s |
| `/api/coverage` | 0.43 s | 0.04 s |
| `/api/library-stats` | 0.38 s | 0.015 s |
| `/api/creators` | 0.22 s | 0.06 s |
| app startup | ~95 s | 2 s |

Everything else measured ≤0.2 s. Remaining known bottleneck: the database
lives on a Windows bind mount (gRPC-FUSE). Benchmarked against a copy of the
same 2 GB database on a named Docker volume (ext4 inside the VM, cold
connections each time):

| Query | Bind mount | Named volume |
|---|---|---|
| full stats payload, cold connection | 0.74 s | 0.13 s |
| `COUNT(*)` over `comment_entry` (3.4 M rows) | 1.78 s | 0.03 s |
| hashtag ranking without the `INDEXED BY` hint | 7.5 s | 0.05 s |

Moving `appdata/` to a named volume would make cold reads equal warm reads
everywhere (and speed up sync/index writes similarly), at the cost of the DB
file no longer being directly visible in Explorer — a user decision.

## 2026-08-26 (second pass) — Database migrated to a named volume

Done, based on the benchmark above. The database was copied into the
`tiktok-favorites-archiver_archive-data` volume with the SQLite backup API
(row counts verified, `PRAGMA quick_check` ok); the pre-migration
`appdata/archive.db` is untouched as a frozen backup, `./appdata` is now
mounted at `/app/backups` for Explorer-visible exports, and
`appdata/README-DATABASE-MOVED.md` documents the export/restore commands.
**Measured: cold `/api/stats` 0.74 s → 0.16 s (4.6×); comment search "the"
cold 0.20 s → 0.08 s; every cold endpoint now equals its warm time.**

## 2026-08-26 (second pass) — `PRAGMA synchronous=NORMAL` for WAL writes

Commits were fsyncing the WAL every time (`FULL`). `NORMAL` is the
recommended WAL pairing — fsync at checkpoint only, corruption-safe; an OS
crash can lose at most the last moments of work, which for this archive
means re-syncing a handful of items.
**Measured: 2.9 ms → ~0.02 ms per commit (~150×). Sync/index/enrich runs
commit per item, so this removes minutes of pure fsync time from long runs.**

## 2026-08-26 (second pass) — HTTP transfer efficiency

- **Selective gzip** (`server/main.py`): JSON and static responses ≥1 KB are
  now gzipped; `/media` is excluded so Content-Length/Content-Range and
  streaming stay byte-exact.
  **Measured: `/api/songs` 776 KB → 188 KB (−76%), `/api/items/ids` 112 KB →
  39 KB (−65%).** Biggest effect on LAN/Tailscale access.
- **Conditional GET for media**: `/media` now answers `If-Modified-Since`
  with `304 Not Modified` (0-byte body) and sends
  `Cache-Control: public, max-age=3600`, so re-opening the Gallery reuses
  cached thumbnails for an hour and revalidates for ~200 bytes afterwards.
  Range requests are untouched (verified 206 + correct Content-Range).

## 2026-08-26 (third pass) — Comment snapshot JSON compressed at rest

`comment_snapshot.comments_json` was 787 MB of uncompressed JSON — the
single largest thing in the database. Snapshots are written once and read
rarely (the searchable/normalized copies live in `comment_entry` and the FTS
tables), which is the textbook case for store-compressed blobs. Payloads are
now zlib-deflated on write (`_pack_comments`) and transparently accepted in
either format on read (`_unpack_comments` — BLOB = deflated, TEXT = legacy).
A one-time startup migration converts legacy rows (idempotent and resumable:
conversion state is the row's own storage type) and VACUUMs once.

**Measured: database 2.06 GB → 1.48 GB (−28%, 582 MB reclaimed; the
snapshot table itself shrank ~5×). Migration boot took 33 s including the
VACUUM; the round-trip (viewer, diffing, adoption) is byte-identical and the
full test suite shows zero regressions.** Smaller file = fewer pages for the
VM's cache to hold (idle RAM) and 28% faster backups/exports.

Steady state after all three passes: app container ~86 MiB idle, process RSS
~88 MB, every measured endpoint ≤0.2 s warm and cold.

## 2026-08-26 — Evaluated and rejected: 8 KB page size

Benchmarked on scratch copies of the real database (VACUUM INTO with
`page_size=8192`): stats cold 0.125 s → 0.115 s, full `comment_entry` scan
0.41 s → 0.38 s, file *grew* 0.7%. A ≤8% gain inside measurement noise does
not justify rewriting the live database; the default 4096 stays. Recorded so
this isn't re-investigated.
