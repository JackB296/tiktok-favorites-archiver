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
  favorited_at: string | null;
  has_assets: boolean;
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
  running: boolean;
  counts: Partial<Record<Status, number>>;
}

/** Event pushed over SSE from a running sync/backfill. */
export interface ProgressEvent {
  id?: number;
  status?: Status;
  kind?: Kind;
  has_assets?: number;
  event?: "complete" | "error" | "indexing";
  error?: string;
  indexed?: number;
  failed?: number;
  completed?: number;
  total?: number;
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

export interface GalleryPresetFilters {
  search?: string;
  kind?: string;
  status?: string;
  order?: string;
  minDuration?: string;
  maxDuration?: string;
  minSize?: string;
  maxSize?: string;
  dateFrom?: string;
  dateTo?: string;
  orientation?: string;
  include?: string;
  exclude?: string;
}

export interface GalleryPreset {
  id: number;
  name: string;
  filters: GalleryPresetFilters;
}
