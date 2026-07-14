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
  song: Song | null;
  song_status: SongStatus | null;
  song_source: SongSource | null;
  video_url: string | null;
  images: string[];
  audio: string | null;
  thumbnail_url: string | null;
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
  id?: number;
  status?: Status;
  kind?: Kind;
  has_assets?: number;
  event?: "complete" | "error" | "indexing" | "sidecars" | "enrichment" | "identification" | "verify";
  error?: string;
  indexed?: number;
  failed?: number;
  completed?: number;
  total?: number;
  enriched?: number;
  unavailable?: number;
  identified?: number;
  no_match?: number;
  errors?: number;
  title?: string | null;
}

export interface ImportResult {
  favorites: number;
  existing_files: number;
  manifest_rows: number;
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
}

export interface GalleryPreset {
  id: number;
  name: string;
  filters: GalleryPresetFilters;
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
