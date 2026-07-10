export type Kind = "video" | "slideshow" | "unknown" | "unresolved";

export type Status =
  | "pending"
  | "resolving"
  | "downloading"
  | "done"
  | "failed"
  | "skipped"
  | "expired";

export type RunState = "idle" | "running" | "paused" | "stopping" | "stopped" | "failed";

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
  favorited_at: string | null;
  has_assets: boolean;
  duration_s: number | null;
  media_width: number | null;
  media_height: number | null;
  media_codec: string | null;
  media_size: number | null;
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
  event?: "complete" | "error" | "indexing" | "sidecars" | "enrichment" | "verify";
  error?: string;
  indexed?: number;
  failed?: number;
  completed?: number;
  total?: number;
  enriched?: number;
}

export interface ImportResult {
  favorites: number;
  existing_files: number;
  manifest_rows: number;
}

export interface LibrarySettings {
  index_enabled: number;
  thumbnail_width: 320 | 480;
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
