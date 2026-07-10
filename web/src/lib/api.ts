import type { Item, ItemPage, RunStatus, ImportResult, ProgressEvent, LibrarySettings, LibraryStatistics, GalleryPreset, GalleryPresetFilters, VerifyReport } from "./types";

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${detail ? `: ${detail}` : ""}`);
  }
  return res.json() as Promise<T>;
}

export interface ItemQuery {
  search?: string;
  kind?: string;
  status?: string;
}

export const api = {
  health: () => json<{ status: string; cobalt_reachable: boolean }>("/api/health"),

  galleryPresets: () => json<GalleryPreset[]>("/api/gallery-presets"),
  createGalleryPreset: (name: string, filters: GalleryPresetFilters) => json<GalleryPreset>("/api/gallery-presets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, filters }),
  }),
  deleteGalleryPreset: (id: number) => json<{ ok: boolean }>(`/api/gallery-presets/${id}`, { method: "DELETE" }),

  items: (q: ItemQuery = {}) => {
    const p = new URLSearchParams();
    if (q.search) p.set("search", q.search);
    if (q.kind) p.set("kind", q.kind);
    if (q.status) p.set("status", q.status);
    const qs = p.toString();
    return json<Item[]>(`/api/items${qs ? `?${qs}` : ""}`);
  },

  itemPage: (q: ItemQuery & { cursor?: number; limit?: number; order?: "latest" | "archive" | "size_desc" | "duration_desc" | "duration_asc" | "favorite_date_desc" | "favorite_date_asc" | "random"; seed?: number; min_duration?: number; max_duration?: number; min_size?: number; max_size?: number; min_width?: number; max_width?: number; min_height?: number; max_height?: number; codec?: string; date_from?: string; date_to?: string; orientation?: string; assets?: "with" | "without"; index_state?: "indexed" | "missing" | "failed"; include?: string; exclude?: string } = {}) => {
    const p = new URLSearchParams();
    if (q.search) p.set("search", q.search);
    if (q.kind) p.set("kind", q.kind);
    if (q.status) p.set("status", q.status);
    if (q.cursor) p.set("cursor", String(q.cursor));
    if (q.limit) p.set("limit", String(q.limit));
    if (q.order) p.set("order", q.order);
    if (q.seed != null) p.set("seed", String(q.seed));
    if (q.min_duration) p.set("min_duration", String(q.min_duration));
    if (q.max_duration) p.set("max_duration", String(q.max_duration));
    if (q.min_size) p.set("min_size", String(q.min_size));
    if (q.max_size) p.set("max_size", String(q.max_size));
    if (q.min_width) p.set("min_width", String(q.min_width));
    if (q.max_width) p.set("max_width", String(q.max_width));
    if (q.min_height) p.set("min_height", String(q.min_height));
    if (q.max_height) p.set("max_height", String(q.max_height));
    if (q.codec) p.set("codec", q.codec);
    if (q.date_from) p.set("date_from", q.date_from);
    if (q.date_to) p.set("date_to", q.date_to);
    if (q.orientation) p.set("orientation", q.orientation);
    if (q.assets) p.set("assets", q.assets);
    if (q.index_state) p.set("index_state", q.index_state);
    if (q.include) p.set("include", q.include);
    if (q.exclude) p.set("exclude", q.exclude);
    return json<ItemPage>(`/api/items/page?${p}`);
  },

  item: (n: number) => json<Item>(`/api/items/${n}`),
  itemIds: () => json<number[]>("/api/items/ids"),
  itemSelection: (ids: number[]) => json<Item[]>("/api/items/selection", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids }) }),
  itemWindow: (n: number) => json<ItemPage>(`/api/items/${n}/window`),

  status: () => json<RunStatus>("/api/status"),

  verify: () => json<VerifyReport>("/api/verify"),
  requeueMissing: () => json<{ requeued: number }>("/api/verify/requeue", { method: "POST" }),

  librarySettings: () => json<LibrarySettings>("/api/library-settings"),
  libraryStats: () => json<LibraryStatistics>("/api/library-stats"),
  updateLibrarySettings: (settings: { index_enabled?: boolean; thumbnail_width?: 320 | 480 }) =>
    json<LibrarySettings>("/api/library-settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    }),

  howto: async () => {
    const res = await fetch("/api/howto");
    return res.text();
  },

  importExport: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return json<ImportResult>("/api/import", { method: "POST", body });
  },

  syncAction: (action: "start" | "backfill" | "reindex" | "sidecars" | "enrich" | "pause" | "continue" | "stop") =>
    json<{ started?: boolean; ok?: boolean }>(`/api/sync/${action}`, { method: "POST" }),

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
