export type Kind = "video" | "slideshow" | "unknown" | "unresolved";

export type Status =
  | "pending"
  | "resolving"
  | "downloading"
  | "done"
  | "failed"
  | "skipped"
  | "expired"
  | "ignored";

export type RunState = "idle" | "running" | "paused" | "stopping" | "stopped" | "failed";

export type SongStatus = "identified" | "no_match" | "error";
export type SongSource = "auto" | "manual";

/** A track identified for a favorite (many favorites can share one song). */
export interface Song {
  title: string;
  artist: string | null;
  album: string | null;
  art_url: string | null;
  shazam_url: string | null;
  apple_url: string | null;
  spotify_url: string | null;
}

/** A Shazam catalog search result for the manual "match it myself" flow. */
export interface SongCandidate extends Song {
  key: string | null;
}

/** A distinct identified song for the Music view: its DB id, how many favorites
 * use it, and (capped) which ones, so it can open a Feed queue. */
export interface SongSummary extends Song {
  id: number;
  uses: number;
  item_ids: number[];
}

export interface SongPlaylist {
  id: number;
  name: string;
  song_ids: number[];
}

export interface Item {
  id: number;
  link: string;
  caption: string | null;
  author: string | null;
  creator: DiscoveryIdentity | null;
  hashtags: DiscoveryIdentity[];
  kind: Kind;
  status: Status;
  error: string | null;
  attempt_count: number;
  last_attempt_at: string | null;
  archive_missing: boolean;
  offloaded: boolean;
  favorited_at: string | null;
  has_assets: boolean;
  duration_s: number | null;
  media_width: number | null;
  media_height: number | null;
  media_codec: string | null;
  media_size: number | null;
  has_audio: boolean | null;
  audio_silent: boolean | null;
  song: Song | null;
  song_status: SongStatus | null;
  song_source: SongSource | null;
  video_url: string | null;
  images: string[];
  audio: string | null;
  thumbnail_url: string | null;
}

export interface DiscoveryIdentity {
  id: number;
  key: string;
  display: string;
}

export interface DiscoveryEntity extends DiscoveryIdentity {
  count: number;
  latest_at: string | null;
  first_item_id: number | null;
  trend?: Array<{ month: string; count: number }>;
}

export interface DiscoveryPage {
  items: DiscoveryEntity[];
  next_cursor: number | null;
}

export interface ItemPage {
  items: Item[];
  next_cursor: number | null;
}

export interface RunStatus {
  state: RunState;
  phase: string | null;
  concurrency: number;
  running: boolean;
  counts: Partial<Record<Status, number>>;
}

/** Event pushed over SSE from a running sync/backfill. */
export interface ProgressEvent {
  run_id?: number | null;
  id?: number;
  status?: Status;
  kind?: string | null;
  item_kind?: Kind | "transient";
  phase?: string | null;
  has_assets?: number;
  event?: "complete" | "error" | "indexing" | "sidecars" | "enrichment" | "identification" | "verify" | "backfill" | "transfer";
  error?: string;
  indexed?: number;
  failed?: number;
  completed?: number | null;
  total?: number | null;
  enriched?: number;
  unavailable?: number;
  identified?: number;
  no_match?: number;
  errors?: number;
  recovered?: number;
  files?: number;
  title?: string | null;
}

export interface ImportResult {
  favorites: number;
  existing_files: number;
  manifest_rows: number;
}

export interface StorageLocation {
  id: number;
  name: string;
  path: string;
  available: boolean;
  last_error: string | null;
  last_checked_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface StorageTransferPreview {
  plan_id: string;
  action: "copy" | "move" | "restore";
  items: number;
  files: number;
  bytes: number;
  conflicts?: number;
  already_verified?: number;
  placements?: number;
  missing_verified?: number[];
}

export interface SnapshotResource {
  id: string;
  name: string;
  location_id: number;
  location_name: string;
  state: "complete" | "partial" | "invalid";
  mode?: "metadata" | "complete";
  created_at?: string;
  items?: number;
  error?: string;
}

export interface SnapshotRestorePlan {
  plan_id: string;
  token: string;
  mode: "metadata" | "complete";
  snapshot_items: number;
  target_items: number;
  required_bytes: number;
  conflicts: number;
  requires_replace: boolean;
  confirmation: string | null;
}

export interface LegacyMappingSegment {
  start_id: number;
  offset: number;
}

export interface LegacyMappingSegmentPreview extends LegacyMappingSegment {
  end_id: number;
  first_position: number;
  last_position: number;
}

export interface LegacyBootstrapPreview {
  valid: true;
  token: string;
  offset: number;
  segments: LegacyMappingSegmentPreview[];
  checkpoint: {
    link: string;
    old_position: number;
    current_position: number;
    favorites_after_checkpoint: number;
  };
  exports: { old_favorites: number; current_favorites: number };
  inventory: {
    local_files: number;
    lowest_number: number;
    highest_number: number;
    mapped_old_position_first: number;
    mapped_old_position_last: number;
    physical_gaps: number;
    reused_number_markers: number;
    gaps: number;
  };
  allocation: {
    reserved_physical_first: number;
    reserved_physical_last: number;
    local_segment_first: number;
    local_segment_last: number;
    local_done: number;
    legacy_gaps_ignored: number;
    physical_gaps_ignored: number;
    reused_number_markers: number;
    offloaded_first: number | null;
    offloaded_last: number | null;
    offloaded: number;
    reused_marker_first: number | null;
    reused_marker_last: number | null;
    new_pending_first: number | null;
    new_pending_last: number | null;
    new_pending: number;
    next_archive_number: number;
    total_rows: number;
  };
  samples: Array<{
    archive_number: number;
    old_export_position: number;
    link: string;
    favorited_at: string | null;
  }>;
  warnings: string[];
}

export interface LegacyBootstrapResult {
  items_created: number;
  local_done: number;
  legacy_gaps_ignored: number;
  physical_gaps_ignored: number;
  reused_number_markers: number;
  offloaded: number;
  new_pending: number;
  next_archive_number: number;
}

export interface LibrarySettings {
  index_enabled: number;
  thumbnail_width: 320 | 480;
  song_id_enabled: number;
  default_audio_name: string | null;
  index: { total: number; indexed: number; pending: number; failed: number };
}

export interface SyncSettings {
  concurrency: number;
}

export interface LibraryStatistics {
  favorites: number;
  ready: number;
  videos: number;
  slideshows: number;
  indexed: number;
  duration_s: number;
  media_size: number;
}

export interface GalleryPresetFilters {
  search?: string;
  kind?: string;
  status?: string;
  order?: string;
  minDuration?: string;
  maxDuration?: string;
  minSize?: string;
  maxSize?: string;
  minWidth?: string;
  maxWidth?: string;
  minHeight?: string;
  maxHeight?: string;
  codec?: string;
  dateFrom?: string;
  dateTo?: string;
  orientation?: string;
  assets?: string;
  audio?: string;
  offloaded?: string;
  indexState?: string;
  include?: string;
  exclude?: string;
  minAttempts?: string;
  maxAttempts?: string;
  recovery?: boolean;
  creator?: string;
  hashtag?: string;
}

export interface GalleryPreset {
  id: number;
  name: string;
  filters: GalleryPresetFilters;
}

export interface SmartCollectionSummary {
  id: number;
  name: string;
  count: number;
  first_item_id: number | null;
}

export interface GalleryTermList {
  id: number;
  name: string;
  mode: "include" | "exclude";
  terms: string[];
}

export interface PlaybackQueue {
  id: number;
  name: string;
  item_ids: number[];
}

export interface VerifySection {
  count: number;
  examples: Array<number | string>;
}

export interface VerifyReport {
  favorites: number;
  done: number;
  offloaded: number;
  missing: VerifySection;
  orphans: VerifySection;
  leftovers: VerifySection;
  ok: boolean;
}

export interface RequeueResult {
  requeued: number[];
  skipped: number;
}

export interface RunHistoryEntry {
  id: number;
  kind: string;
  outcome: "completed" | "stopped" | "failed" | null;
  started_at: string;
  finished_at: string | null;
  counts: Partial<Record<Status, number>>;
  pipeline_id: string | null;
  parent_kind: string;
  phase: string;
  phase_index: number | null;
  retry_of: number | null;
  error: string | null;
}

export interface RunCatalogEntry {
  kind: string;
  label: string;
  description: string;
  resumable: boolean;
  configurable_follow_up: boolean;
}

export interface PipelineSettings {
  kind: "sync";
  phases: string[];
  updated_at: string;
}

export interface RunSchedule {
  id: number;
  name: string;
  run_kind: string;
  cadence: "daily" | "weekly";
  local_time: string;
  weekday: number | null;
  timezone: string;
  enabled: boolean;
  next_due_at: string | null;
  last_local_date: string | null;
  last_started_at: string | null;
  last_outcome: string | null;
}

export interface SearchSuggestion {
  value: string;
  count: number;
}

export interface SearchSuggestions {
  creators: SearchSuggestion[];
  hashtags: SearchSuggestion[];
  terms: SearchSuggestion[];
}

/** Spotify connection + push (Music tab). */
export interface SpotifyStatus {
  connected: boolean;
  account_name: string | null;
  client_id: string | null;
  redirect_uri: string;
}

export interface SpotifyPushReport {
  playlist: string;
  url: string;
  created: boolean;
  pushed: number;
  unmatched: Array<{ title: string; artist: string | null }>;
}

/** `/api/stats` — archive analytics for the Stats tab. */
export interface StatsHero {
  total: number;
  videos: number;
  slideshows: number;
  archived: number;
  archived_pct: number;
  watch_seconds: number;
  disk_bytes: number;
  undated: number;
  unindexed: number;
}

export interface StatsMonth {
  month: string; // "YYYY-MM"
  count: number;
}

export interface StatsHeatCell {
  dow: number; // 0 = Sunday, per SQLite %w
  hour: number;
  count: number;
}

export interface StatsBucket {
  label: string;
  count: number;
}

export interface StatsWatcher {
  heatmap: StatsHeatCell[];
  duration_histogram: StatsBucket[];
  median_duration_s: number | null;
  silent: { count: number; of_indexed: number };
}

export interface StatsTopAuthor {
  author: string;
  count: number;
}

export interface StatsTopSong {
  id: number;
  title: string;
  artist: string | null;
  count: number;
}

export interface StatsTopHashtag {
  tag: string;
  count: number;
}

export interface StatsHealth {
  statuses: Partial<Record<Status, number>>;
  missing: number;
  offloaded: number;
  errors: Array<{ error: string; count: number }>;
}

export interface Stats {
  hero: StatsHero;
  growth: { monthly: StatsMonth[] };
  watcher: StatsWatcher;
  top: {
    authors: StatsTopAuthor[];
    songs: StatsTopSong[];
    hashtags: StatsTopHashtag[];
  };
  health: StatsHealth;
}
