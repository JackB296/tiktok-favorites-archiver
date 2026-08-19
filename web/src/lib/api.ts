import type { Item, ItemPage, DiscoveryPage, RunStatus, ImportResult, ImportRecord, ProfileImportResult, CreatorMonitor, SourceMetadataDetails, SourceComment, MyfaveTTPlan, MyfaveTTImportResult, MemoryResponse, PlayRecord, StorageLocation, StorageTransferPreview, SnapshotResource, SnapshotRestorePlan, ProgressEvent, LibrarySettings, LibraryStatistics, GalleryPreset, GalleryPresetFilters, SmartCollectionSummary, GalleryTermList, PlaybackQueue, VerifyReport, RequeueResult, RunHistoryEntry, RunCatalogEntry, PipelineSettings, RunSchedule, SyncSettings, LegacyBootstrapPreview, LegacyBootstrapResult, LegacyMappingSegment, SearchSuggestions, SongCandidate, SongSummary, SongPlaylist, SpotifyStatus, SpotifyPushReport, Stats, LensStatus, LensTotals, LensSearchResponse, ItemCaptionsResponse, ItemAnnotation, CurateSession, VibeResponse, DuplicateReport, ArchiveChannel, ArchiveChannelItems, CommentSearchPage, CoverageReport, CoverageCategory } from "./types";

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const headers = new Headers(init?.headers);
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    headers.set("X-Archive-Request", "1");
  }
  const res = await fetch(url, { ...init, headers });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${detail ? `: ${detail}` : ""}`);
  }
  return res.json() as Promise<T>;
}

export interface ItemQuery {
  search?: string;
  search_scope?: "posts" | "comments" | "songs" | "analysis" | "all";
  kind?: string;
  status?: string;
  feed?: boolean;
}

export type MarkAction = "offload" | "unoffload" | "ignore" | "unignore";
export type MarkSelector =
  | { ids: number[] }
  | { range: { first_id: number; last_id: number } }
  | { filter: Record<string, string> };
export type MarkResult = { matched: number; changed: number; requeued?: number; dry_run?: boolean };

export type OffloadSuggestion = {
  earliest_local: number | null;
  suggested: { first_id: number; last_id: number } | null;
  range_total: number;
  range_undownloaded: number;
  range_already_offloaded: number;
};

export const api = {
  health: () => json<{ status: string; cobalt_reachable: boolean }>("/api/health"),

  suggest: (q: string) => json<SearchSuggestions>(`/api/suggest?q=${encodeURIComponent(q)}`),

  searchComments: (q: string, history = false, cursor?: number) => {
    const params = new URLSearchParams({ q });
    if (history) params.set("history", "true");
    if (cursor != null) params.set("cursor", String(cursor));
    return json<CommentSearchPage>(`/api/comments/search?${params}`);
  },
  coverage: () => json<CoverageReport>("/api/coverage"),
  repairCoverage: (targets: CoverageCategory["key"][], filter?: Record<string, string>) =>
    json<{ started: boolean; matched: number | null }>("/api/coverage/repair", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ targets, ...(filter ? { filter } : {}) }),
    }),

  stats: () => json<Stats>("/api/stats"),
  lensStatus: () => json<LensStatus>("/api/lens/status"),
  lensSearch: (q: string, source = "") => {
    const params = new URLSearchParams({ q });
    if (source) params.set("source", source);
    return json<LensSearchResponse>(`/api/lens/search?${params}`);
  },
  importLens: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return json<LensTotals>("/api/lens/import", { method: "POST", body });
  },
  creators: (q = "", order = "frequency", cursor = 0) => json<DiscoveryPage>(`/api/creators?q=${encodeURIComponent(q)}&order=${encodeURIComponent(order)}&cursor=${cursor}`),
  hashtags: (q = "", order = "frequency", cursor = 0) => json<DiscoveryPage>(`/api/hashtags?q=${encodeURIComponent(q)}&order=${encodeURIComponent(order)}&cursor=${cursor}`),

  feedIds: (params: URLSearchParams | string) => json<number[]>(`/api/feed/ids?${params}`),

  galleryPresets: () => json<GalleryPreset[]>("/api/gallery-presets"),
  createGalleryPreset: (name: string, filters: GalleryPresetFilters) => json<GalleryPreset>("/api/gallery-presets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, filters }),
  }),
  deleteGalleryPreset: (id: number) => json<{ ok: boolean }>(`/api/gallery-presets/${id}`, { method: "DELETE" }),
  smartCollectionSummary: (id: number) => json<SmartCollectionSummary>(`/api/gallery-presets/${id}/summary`),
  smartCollectionFeedIds: (id: number) => json<{ item_ids: number[] }>(`/api/gallery-presets/${id}/items?feed=true`),
  smartCollectionMark: (id: number, action: MarkAction, dryRun = false) => json<MarkResult>(`/api/gallery-presets/${id}/mark`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, dry_run: dryRun }),
  }),
  smartCollectionInventoryUrl: (id: number) => `/api/gallery-presets/${id}/inventory`,
  galleryTermLists: () => json<GalleryTermList[]>("/api/gallery-term-lists"),
  createGalleryTermList: (name: string, mode: "include" | "exclude", terms: string[]) => json<GalleryTermList>("/api/gallery-term-lists", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, mode, terms }),
  }),
  deleteGalleryTermList: (id: number) => json<{ ok: boolean }>(`/api/gallery-term-lists/${id}`, { method: "DELETE" }),
  playbackQueues: () => json<PlaybackQueue[]>("/api/playback-queues"),
  createPlaybackQueue: (name: string, itemIds: number[]) => json<PlaybackQueue>("/api/playback-queues", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, item_ids: itemIds }),
  }),
  deletePlaybackQueue: (id: number) => json<{ ok: boolean }>(`/api/playback-queues/${id}`, { method: "DELETE" }),

  itemAnnotation: (id: number) => json<ItemAnnotation>(`/api/items/${id}/annotation`),
  updateItemAnnotation: (id: number, annotation: { starred: boolean; note: string; tags: string[]; reviewed: boolean }) =>
    json<ItemAnnotation>(`/api/items/${id}/annotation`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(annotation),
    }),
  curateSession: (source: "unreviewed" | "forgotten", limit = 20) =>
    json<CurateSession>(`/api/curate/session?source=${source}&limit=${limit}`),
  vibeSearch: (query: string, limit = 24) =>
    json<VibeResponse>(`/api/vibes/search?q=${encodeURIComponent(query)}&limit=${limit}`),
  vibeRelated: (id: number, limit = 24) =>
    json<VibeResponse>(`/api/vibes/related/${id}?limit=${limit}`),
  duplicateReport: () => json<DuplicateReport>("/api/duplicates"),
  scanDuplicates: () => json<DuplicateReport>("/api/duplicates/scan", { method: "POST" }),
  channels: () => json<ArchiveChannel[]>("/api/channels"),
  createChannel: (body: { name: string; preset_id: number; shuffle: boolean; prefer_unwatched: boolean }) =>
    json<ArchiveChannel>("/api/channels", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteChannel: (id: number) => json<{ ok: boolean }>(`/api/channels/${id}`, { method: "DELETE" }),
  channelItems: (id: number) => json<ArchiveChannelItems>(`/api/channels/${id}/items`),

  itemPage: (q: ItemQuery & { cursor?: number; limit?: number; order?: "latest" | "archive" | "size_desc" | "duration_desc" | "duration_asc" | "favorite_date_desc" | "favorite_date_asc" | "attempts_desc" | "last_attempt_desc" | "author_asc" | "audio_missing" | "random"; seed?: number; min_duration?: number; max_duration?: number; min_size?: number; max_size?: number; min_width?: number; max_width?: number; min_height?: number; max_height?: number; min_attempts?: number; max_attempts?: number; recovery?: boolean; codec?: string; date_from?: string; date_to?: string; posted_from?: string; posted_to?: string; min_views?: number; min_likes?: number; min_comments?: number; source_info?: "saved" | "unavailable" | "missing"; comments_state?: "saved" | "with_comments" | "missing"; download_source?: "cobalt" | "yt-dlp" | "legacy"; portable_metadata?: "embedded" | "failed" | "missing"; orientation?: string; assets?: "with" | "without"; audio?: "with" | "without"; offloaded?: "with" | "without"; index_state?: "indexed" | "missing" | "failed"; include?: string; exclude?: string; creator?: string; hashtag?: string; song?: number; starred?: boolean; private_tag?: string } = {}) => {
    const p = new URLSearchParams();
    if (q.search) p.set("search", q.search);
    if (q.search_scope) p.set("search_scope", q.search_scope);
    if (q.kind) p.set("kind", q.kind);
    if (q.status) p.set("status", q.status);
    if (q.feed) p.set("feed", "true");
    if (q.cursor) p.set("cursor", String(q.cursor));
    if (q.limit) p.set("limit", String(q.limit));
    if (q.order) p.set("order", q.order);
    if (q.seed != null) p.set("seed", String(q.seed));
    if (q.min_duration != null) p.set("min_duration", String(q.min_duration));
    if (q.max_duration != null) p.set("max_duration", String(q.max_duration));
    if (q.min_size != null) p.set("min_size", String(q.min_size));
    if (q.max_size != null) p.set("max_size", String(q.max_size));
    if (q.min_width != null) p.set("min_width", String(q.min_width));
    if (q.max_width != null) p.set("max_width", String(q.max_width));
    if (q.min_height != null) p.set("min_height", String(q.min_height));
    if (q.max_height != null) p.set("max_height", String(q.max_height));
    if (q.min_attempts != null) p.set("min_attempts", String(q.min_attempts));
    if (q.max_attempts != null) p.set("max_attempts", String(q.max_attempts));
    if (q.recovery) p.set("recovery", "true");
    if (q.codec) p.set("codec", q.codec);
    if (q.date_from) p.set("date_from", q.date_from);
    if (q.date_to) p.set("date_to", q.date_to);
    if (q.posted_from) p.set("posted_from", q.posted_from);
    if (q.posted_to) p.set("posted_to", q.posted_to);
    if (q.min_views != null) p.set("min_views", String(q.min_views));
    if (q.min_likes != null) p.set("min_likes", String(q.min_likes));
    if (q.min_comments != null) p.set("min_comments", String(q.min_comments));
    if (q.source_info) p.set("source_info", q.source_info);
    if (q.comments_state) p.set("comments_state", q.comments_state);
    if (q.download_source) p.set("download_source", q.download_source);
    if (q.portable_metadata) p.set("portable_metadata", q.portable_metadata);
    if (q.orientation) p.set("orientation", q.orientation);
    if (q.assets) p.set("assets", q.assets);
    if (q.audio) p.set("audio", q.audio);
    if (q.offloaded) p.set("offloaded", q.offloaded);
    if (q.index_state) p.set("index_state", q.index_state);
    if (q.include) p.set("include", q.include);
    if (q.exclude) p.set("exclude", q.exclude);
    if (q.creator) p.set("creator", q.creator);
    if (q.hashtag) p.set("hashtag", q.hashtag);
    if (q.song != null) p.set("song", String(q.song));
    if (q.starred) p.set("starred", "true");
    if (q.private_tag) p.set("private_tag", q.private_tag);
    return json<ItemPage>(`/api/items/page?${p}`);
  },

  itemIds: () => json<number[]>("/api/items/ids"),
  itemSelection: (ids: number[]) => json<Item[]>("/api/items/selection", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids }) }),
  itemWindow: (n: number) => json<{ items: Item[] }>(`/api/items/${n}/window`),
  itemCaptions: (n: number) => json<ItemCaptionsResponse>(`/api/items/${n}/captions`),
  replaceItemMedia: (n: number, files: { video?: File; thumbnail?: File }) => {
    const body = new FormData();
    if (files.video) body.append("video", files.video);
    if (files.thumbnail) body.append("thumbnail", files.thumbnail);
    return json<Item>(`/api/items/${n}/media`, { method: "POST", body });
  },

  songs: () => json<{ songs: SongSummary[] }>("/api/songs"),
  songPlaylists: () => json<SongPlaylist[]>("/api/song-playlists"),
  createSongPlaylist: (name: string, songIds: number[]) => json<SongPlaylist>("/api/song-playlists", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, song_ids: songIds }),
  }),
  deleteSongPlaylist: (id: number) => json<{ ok: boolean }>(`/api/song-playlists/${id}`, { method: "DELETE" }),

  searchSongs: (q: string) => json<{ results: SongCandidate[] }>(`/api/songs/search?q=${encodeURIComponent(q)}`),
  setItemSong: (n: number, match: SongCandidate) => json<Item>(`/api/items/${n}/song`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(match),
  }),

  status: () => json<RunStatus>("/api/status"),
  runHistory: () => json<RunHistoryEntry[]>("/api/run-history"),
  runCatalog: () => json<RunCatalogEntry[]>("/api/run-catalog"),
  pipelineSettings: () => json<PipelineSettings>("/api/pipeline-settings"),
  updatePipelineSettings: (phases: string[]) => json<PipelineSettings>("/api/pipeline-settings", {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phases }),
  }),
  retryRun: (id: number) => json<{ started: boolean; retry_of: number }>(`/api/run-history/${id}/retry`, { method: "POST" }),
  runSchedules: () => json<RunSchedule[]>("/api/run-schedules"),
  createRunSchedule: (schedule: Omit<RunSchedule, "id" | "next_due_at" | "last_local_date" | "last_started_at" | "last_outcome">) => json<RunSchedule>("/api/run-schedules", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(schedule),
  }),
  updateRunSchedule: (id: number, schedule: Partial<RunSchedule>) => json<RunSchedule>(`/api/run-schedules/${id}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(schedule),
  }),
  deleteRunSchedule: (id: number) => json<{ ok: boolean }>(`/api/run-schedules/${id}`, { method: "DELETE" }),

  verify: () => json<VerifyReport>("/api/verify"),
  requeueMissing: () => json<{ requeued: number }>("/api/verify/requeue", { method: "POST" }),
  requeueItems: (ids: number[]) => json<RequeueResult>("/api/items/requeue", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  }),
  markItems: (action: MarkAction, selector: MarkSelector, dryRun?: boolean) => json<MarkResult>("/api/items/mark", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, ...selector, ...(dryRun ? { dry_run: true } : {}) }),
  }),
  offloadSuggestion: () => json<OffloadSuggestion>("/api/items/offload-suggestion"),

  librarySettings: () => json<LibrarySettings>("/api/library-settings"),
  libraryStats: () => json<LibraryStatistics>("/api/library-stats"),
  updateLibrarySettings: (settings: { index_enabled?: boolean; thumbnail_width?: 320 | 480; song_id_enabled?: boolean; portable_metadata_enabled?: boolean }) =>
    json<LibrarySettings>("/api/library-settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    }),
  setDefaultAudio: (file: File) => {
    const body = new FormData();
    body.append("audio", file);
    return json<LibrarySettings>("/api/default-audio", { method: "POST", body });
  },
  clearDefaultAudio: () => json<LibrarySettings>("/api/default-audio", { method: "DELETE" }),

  syncSettings: () => json<SyncSettings>("/api/sync-settings"),
  updateSyncSettings: (settings: SyncSettings) => json<SyncSettings>("/api/sync-settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  }),

  howto: async () => {
    const res = await fetch("/api/howto");
    return res.text();
  },

  importExport: (file: File, selection: "favorites" | "likes" | "both" = "favorites") => {
    const body = new FormData();
    body.append("file", file);
    body.append("selection", selection);
    return json<ImportResult>("/api/import", { method: "POST", body });
  },
  importProfile: (username: string, startSync = true, monitor = false, intervalHours = 6, policy: Partial<CreatorMonitor> = {}) => json<ProfileImportResult>("/api/import/profile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, start_sync: startSync, monitor, interval_hours: intervalHours,
      archive_mode: policy.archive_mode ?? "all", keywords: policy.keywords ?? [],
      exclude_reposts: policy.exclude_reposts ?? false, max_backlog_days: policy.max_backlog_days ?? null,
      collect_comments: policy.collect_comments ?? true, analyze_new: policy.analyze_new ?? false,
      identify_songs: policy.identify_songs ?? false }),
  }),
  creatorMonitors: () => json<CreatorMonitor[]>("/api/creator-monitors"),
  updateCreatorMonitor: (id: number, values: Partial<Pick<CreatorMonitor, "enabled" | "interval_hours" | "archive_mode" | "keywords" | "exclude_reposts" | "max_backlog_days" | "collect_comments" | "analyze_new" | "identify_songs">>) => json<CreatorMonitor>(`/api/creator-monitors/${id}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values),
  }),
  checkCreatorMonitor: (id: number) => json<{ queued: boolean; started: boolean }>(`/api/creator-monitors/${id}/check`, { method: "POST" }),
  deleteCreatorMonitor: (id: number) => json<{ ok: boolean }>(`/api/creator-monitors/${id}`, { method: "DELETE" }),
  itemSourceMetadata: (id: number) => json<SourceMetadataDetails>(`/api/items/${id}/source-metadata`),
  refreshItemComments: (id: number) =>
    json<{ item_id: number; comments: SourceComment[]; saved_count: number; reported_count: number | null; changes: { added: number; removed: number; changed: number } }>(
      `/api/items/${id}/comments/refresh`, { method: "POST" },
    ),
  planMyfaveTTImport: (paths: string[]) => json<MyfaveTTPlan>("/api/import/myfavett/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paths }),
  }),
  importMyfaveTTVideo: (videoId: string, sourcePath: string, file: File) => {
    const body = new FormData();
    body.append("video_id", videoId);
    body.append("source_path", sourcePath);
    body.append("video", file);
    return json<MyfaveTTImportResult>("/api/import/myfavett/video", { method: "POST", body });
  },
  imports: () => json<ImportRecord[]>("/api/imports"),
  importDetail: (id: number) => json<ImportRecord>(`/api/imports/${id}`),
  memories: (date?: string) => json<MemoryResponse>(`/api/memories${date ? `?date=${encodeURIComponent(date)}` : ""}`),
  recordPlayed: (id: number) => json<PlayRecord>(`/api/items/${id}/played`, { method: "POST" }),
  storageLocations: () => json<StorageLocation[]>("/api/storage-locations"),
  createStorageLocation: (name: string, path: string) => json<StorageLocation>("/api/storage-locations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, path }),
  }),
  updateStorageLocation: (id: number, changes: { name?: string; path?: string }) => json<StorageLocation>(`/api/storage-locations/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(changes),
  }),
  checkStorageLocation: (id: number) => json<StorageLocation>(`/api/storage-locations/${id}/check`, { method: "POST" }),
  deleteStorageLocation: (id: number) => json<{ ok: boolean }>(`/api/storage-locations/${id}`, { method: "DELETE" }),
  previewStorageTransfer: (action: "copy" | "move" | "restore", locationId: number, ids: number[]) =>
    json<StorageTransferPreview>("/api/storage-transfers/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, location_id: locationId, ids }),
    }),
  startStorageTransfer: (planId: string, confirmation?: string) =>
    json<{ started: boolean; id: string }>("/api/storage-transfers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan_id: planId, ...(confirmation ? { confirmation } : {}) }),
    }),
  snapshots: () => json<SnapshotResource[]>("/api/snapshots"),
  createSnapshot: (locationId: number, name: string, mode: "metadata" | "complete") =>
    json<{ started: boolean }>("/api/snapshots", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ location_id: locationId, name, mode }) }),
  validateSnapshot: (id: string) => json<{ valid: boolean }>(`/api/snapshots/${encodeURIComponent(id)}/validate`, { method: "POST" }),
  previewSnapshotRestore: (id: string) => json<SnapshotRestorePlan>("/api/snapshot-restore/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ snapshot_id: id }) }),
  startSnapshotRestore: (planId: string, confirmation?: string) => json<{ started: boolean }>("/api/snapshot-restore", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ plan_id: planId, confirmation }) }),

  spotifyStatus: () => json<SpotifyStatus>("/api/spotify/status"),
  spotifyConnect: (clientId: string) => json<{ authorize_url: string }>("/api/spotify/connect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_id: clientId }),
  }),
  spotifyDisconnect: () => json<{ connected: boolean }>("/api/spotify/disconnect", { method: "POST" }),
  pushSongPlaylist: (playlistId: number) => json<SpotifyPushReport>(`/api/song-playlists/${playlistId}/push`, { method: "POST" }),

  legacyBootstrapPreview: (oldExport: File, currentExport: File, checkpoint: File, segments?: LegacyMappingSegment[]) => {
    const body = new FormData();
    body.append("old_export", oldExport);
    body.append("current_export", currentExport);
    body.append("checkpoint", checkpoint);
    if (segments) body.append("mapping_segments", JSON.stringify(segments));
    return json<LegacyBootstrapPreview>("/api/import/legacy-preview", { method: "POST", body });
  },

  legacyBootstrapApply: (oldExport: File, currentExport: File, checkpoint: File, previewToken: string, segments?: LegacyMappingSegment[]) => {
    const body = new FormData();
    body.append("old_export", oldExport);
    body.append("current_export", currentExport);
    body.append("checkpoint", checkpoint);
    body.append("preview_token", previewToken);
    body.append("confirmation", "MIGRATE");
    if (segments) body.append("mapping_segments", JSON.stringify(segments));
    return json<LegacyBootstrapResult>("/api/import/legacy-apply", { method: "POST", body });
  },

  syncAction: (action: "start" | "backfill" | "reindex" | "sidecars" | "repair-audio" | "enrich" | "identify" | "analyze" | "pause" | "continue" | "stop", opts?: { recheck?: boolean }) =>
    json<{ started?: boolean; ok?: boolean }>(`/api/sync/${action}${opts?.recheck ? "?recheck=1" : ""}`, { method: "POST" }),

  /** Subscribe to the SSE progress stream. Returns an unsubscribe fn. */
  events: (onEvent: (e: ProgressEvent) => void): (() => void) => {
    const es = new EventSource("/api/events");
    es.onmessage = (msg) => {
      try {
        onEvent(JSON.parse(msg.data) as ProgressEvent);
      } catch {
        /* ignore keep-alive / malformed frames */
      }
    };
    return () => es.close();
  },
};
