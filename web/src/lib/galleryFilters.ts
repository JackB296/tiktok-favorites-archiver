import type { GalleryPresetFilters } from "./types";

export type GalleryOrder = "latest" | "archive" | "size_desc" | "duration_desc" | "duration_asc" | "favorite_date_desc" | "favorite_date_asc" | "attempts_desc" | "last_attempt_desc" | "author_asc" | "audio_missing" | "random";

/** Every Gallery filter as one value object. Strings mirror the raw input text;
    `recovery` is the only boolean. `order` always holds a sort (never ""). */
export interface GalleryFiltersState {
  search: string;
  kind: string;
  status: string;
  order: GalleryOrder;
  minDuration: string;
  maxDuration: string;
  minSize: string;
  maxSize: string;
  minWidth: string;
  maxWidth: string;
  minHeight: string;
  maxHeight: string;
  minAttempts: string;
  maxAttempts: string;
  recovery: boolean;
  codec: string;
  dateFrom: string;
  dateTo: string;
  orientation: string;
  assets: string;
  audio: string;
  offloaded: string;
  indexState: string;
  include: string;
  exclude: string;
  creator: string;
  hashtag: string;
}

export type GalleryFilterKey = keyof GalleryFiltersState;
type FilterValue = string | boolean;

/** One row per filter. Adding a filter means adding a row here (plus its input
    in Gallery.tsx and its mapping in filtersToPageQuery below) — URL hydration,
    URL writing, presets, chips, and the effect key all derive from this table. */
export interface GalleryFilterField {
  key: GalleryFilterKey;
  /** Param name in the Gallery URL (?q=…&sort=…). */
  urlParam: string;
  /** Param name in the object api.itemPage receives (min_duration, index_state, …). */
  queryParam: string;
  default: FilterValue;
  /** Serialized URL value, or undefined to omit the param. */
  toUrl(value: FilterValue | undefined): string | undefined;
  fromUrl(raw: string): FilterValue;
  fromPreset(value: FilterValue | undefined): FilterValue;
  /** Active-filter chip text, or null when the field is inactive. */
  chipLabel(value: FilterValue): string | null;
}

/** A plain text field: active when non-empty, carried verbatim in the URL. */
function text(key: GalleryFilterKey, urlParam: string, queryParam: string, chip: (value: string) => string): GalleryFilterField {
  return {
    key, urlParam, queryParam, default: "",
    toUrl: (value) => (value ? String(value) : undefined),
    fromUrl: (raw) => raw,
    fromPreset: (value) => (value as string | undefined) ?? "",
    chipLabel: (value) => (value ? chip(String(value)) : null),
  };
}

/** Table order is the canonical state/preset/chip order (matches the old
    currentFilters() key order and addFilter() chip order byte for byte). */
export const GALLERY_FILTER_FIELDS: GalleryFilterField[] = [
  text("search", "q", "search", (v) => `Search: ${v}`),
  text("kind", "kind", "kind", (v) => (v === "video" ? "Videos" : "Slideshows")),
  text("status", "status", "status", (v) => `Status: ${v}`),
  {
    key: "order", urlParam: "sort", queryParam: "order", default: "latest",
    toUrl: (value) => (value && value !== "latest" ? String(value) : undefined),
    fromUrl: (raw) => raw || "latest",
    fromPreset: (value) => (value as string | undefined) || "latest",
    chipLabel: (value) => (value !== "latest" ? `Sort: ${String(value).replace(/_/g, " ")}` : null),
  },
  text("minDuration", "min_duration", "min_duration", (v) => `≥ ${v}s`),
  text("maxDuration", "max_duration", "max_duration", (v) => `≤ ${v}s`),
  text("minSize", "min_size", "min_size", (v) => `≥ ${v} MB`),
  text("maxSize", "max_size", "max_size", (v) => `≤ ${v} MB`),
  text("minWidth", "min_width", "min_width", (v) => `width ≥ ${v}`),
  text("maxWidth", "max_width", "max_width", (v) => `width ≤ ${v}`),
  text("minHeight", "min_height", "min_height", (v) => `height ≥ ${v}`),
  text("maxHeight", "max_height", "max_height", (v) => `height ≤ ${v}`),
  text("minAttempts", "min_attempts", "min_attempts", (v) => `≥ ${v} attempts`),
  text("maxAttempts", "max_attempts", "max_attempts", (v) => `≤ ${v} attempts`),
  {
    key: "recovery", urlParam: "recovery", queryParam: "recovery", default: false,
    toUrl: (value) => (value ? "1" : undefined),
    fromUrl: (raw) => raw === "1",
    fromPreset: (value) => Boolean(value),
    chipLabel: (value) => (value ? "Recovery inbox" : null),
  },
  text("codec", "codec", "codec", (v) => `Codec: ${v}`),
  text("dateFrom", "from", "date_from", (v) => `After: ${v}`),
  text("dateTo", "to", "date_to", (v) => `Before: ${v}`),
  text("orientation", "orientation", "orientation", (v) => v),
  text("assets", "assets", "assets", (v) => (v === "with" ? "Has raw assets" : "No raw assets")),
  text("audio", "audio", "audio", (v) => (v === "with" ? "Has audio" : "No audio")),
  text("offloaded", "offloaded", "offloaded", (v) => (v === "with" ? "Offloaded" : "Stored locally")),
  text("indexState", "index", "index_state", (v) => `Index: ${v}`),
  text("include", "include", "include", (v) => `Include: ${v}`),
  text("exclude", "exclude", "exclude", (v) => `Exclude: ${v}`),
  text("creator", "creator", "creator", (v) => `Creator: ${v}`),
  text("hashtag", "hashtag", "hashtag", (v) => `Hashtag: #${v.replace(/^#/, "")}`),
];

const FIELD_BY_KEY = Object.fromEntries(GALLERY_FILTER_FIELDS.map((field) => [field.key, field])) as Record<GalleryFilterKey, GalleryFilterField>;

/** URL params keep the exact order the old hand-rolled writer emitted them in
    (codec sat between max_height and min_attempts), so filter URLs — and the
    Feed Back-button restore keys built from them — stay byte-identical. */
const URL_FIELD_ORDER: GalleryFilterKey[] = [
  "search", "kind", "status", "order", "minDuration", "maxDuration", "minSize", "maxSize",
  "minWidth", "maxWidth", "minHeight", "maxHeight", "codec", "minAttempts", "maxAttempts",
  "recovery", "dateFrom", "dateTo", "orientation", "assets", "audio", "offloaded",
  "indexState", "include", "exclude", "creator", "hashtag",
];

export function emptyFilters(): GalleryFiltersState {
  const state: Record<string, FilterValue> = {};
  for (const field of GALLERY_FILTER_FIELDS) state[field.key] = field.default;
  return state as unknown as GalleryFiltersState; // built key-by-key from the table
}

export function filtersFromUrl(params: URLSearchParams): GalleryFiltersState {
  const state: Record<string, FilterValue> = {};
  for (const field of GALLERY_FILTER_FIELDS) state[field.key] = field.fromUrl(params.get(field.urlParam) ?? "");
  return state as unknown as GalleryFiltersState; // built key-by-key from the table
}

export function filtersToSearchParams(filters: GalleryPresetFilters): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of URL_FIELD_ORDER) {
    const field = FIELD_BY_KEY[key];
    const value = field.toUrl(filters[key]);
    if (value) params.set(field.urlParam, value);
  }
  return params;
}

/** The complete filter snapshot a saved preset stores (the old currentFilters()). */
export function filtersToPreset(state: GalleryFiltersState): GalleryPresetFilters {
  const preset: Record<string, FilterValue> = {};
  for (const field of GALLERY_FILTER_FIELDS) preset[field.key] = state[field.key];
  return preset as GalleryPresetFilters;
}

/** A saved preset applied over a clean slate; missing keys fall back to defaults. */
export function applyPreset(preset: GalleryPresetFilters): GalleryFiltersState {
  const state: Record<string, FilterValue> = {};
  for (const field of GALLERY_FILTER_FIELDS) state[field.key] = field.fromPreset(preset[field.key]);
  return state as unknown as GalleryFiltersState; // built key-by-key from the table
}

export interface GalleryFilterChip { key: GalleryFilterKey; label: string }

export function activeChips(state: GalleryFiltersState): GalleryFilterChip[] {
  const chips: GalleryFilterChip[] = [];
  for (const field of GALLERY_FILTER_FIELDS) {
    const label = field.chipLabel(state[field.key]);
    if (label !== null) chips.push({ key: field.key, label });
  }
  return chips;
}

/** Stable serialization of every filter — one effect dependency instead of a
    26-item list. Equals the Gallery URL query string for this state. */
export function filtersKey(state: GalleryFiltersState): string {
  return filtersToSearchParams(state).toString();
}

/** The params object api.itemPage receives (page size, seed handling, unit and
    date conversions included). The wire mapping is spelled out per field so the
    HTTP query stays byte-identical to the old inline pageQuery. */
export function filtersToPageQuery(state: GalleryFiltersState, randomSeed: number) {
  const num = (s: string) => (s.trim() === "" ? undefined : Number(s));
  return {
    search: state.search, kind: state.kind, status: state.status, limit: 50, order: state.order,
    seed: state.order === "random" ? randomSeed : undefined,
    min_duration: num(state.minDuration),
    max_duration: num(state.maxDuration),
    // Rounded: the server parses byte counts with int(), so "0.1" MB must not
    // reach the wire as a fractional byte count (a 400).
    min_size: state.minSize.trim() === "" ? undefined : Math.round(Number(state.minSize) * 1024 * 1024),
    max_size: state.maxSize.trim() === "" ? undefined : Math.round(Number(state.maxSize) * 1024 * 1024),
    min_width: num(state.minWidth),
    max_width: num(state.maxWidth),
    min_height: num(state.minHeight),
    max_height: num(state.maxHeight),
    min_attempts: num(state.minAttempts),
    max_attempts: num(state.maxAttempts),
    recovery: state.recovery || undefined,
    codec: state.codec || undefined,
    date_from: state.dateFrom || undefined,
    date_to: state.dateTo ? `${state.dateTo}T23:59:59` : undefined,
    orientation: state.orientation || undefined,
    assets: (state.assets === "with" || state.assets === "without" ? state.assets : undefined) as "with" | "without" | undefined,
    audio: (state.audio === "with" || state.audio === "without" ? state.audio : undefined) as "with" | "without" | undefined,
    offloaded: (state.offloaded === "with" || state.offloaded === "without" ? state.offloaded : undefined) as "with" | "without" | undefined,
    index_state: (state.indexState === "indexed" || state.indexState === "missing" || state.indexState === "failed" ? state.indexState : undefined) as "indexed" | "missing" | "failed" | undefined,
    include: state.include, exclude: state.exclude,
    creator: state.creator || undefined,
    hashtag: state.hashtag || undefined,
  };
}

/** The filter selector for "mark all matching" bulk actions: the page query's
    key/value strings minus exactly order/seed/limit/cursor, which the server
    rejects inside a filter (mirrors server/archive_items.py's validation). */
export function filtersToMarkSelector(state: GalleryFiltersState): Record<string, string> {
  const excluded = new Set(["order", "seed", "limit", "cursor"]);
  const filter: Record<string, string> = {};
  Object.entries(filtersToPageQuery(state, 0)).forEach(([key, value]) => {
    if (excluded.has(key) || value == null || value === "") return;
    filter[key] = String(value);
  });
  return filter;
}
