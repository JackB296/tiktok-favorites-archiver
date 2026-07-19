export const DEFAULT_GALLERY_DETAILS = Object.freeze({
  archiveNumber: true,
  duration: true,
  resolution: false,
  author: true,
  caption: true,
  technical: false,
});

export function readGalleryDetails(raw) {
  if (!raw) return { ...DEFAULT_GALLERY_DETAILS };
  try {
    const value = JSON.parse(raw);
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid preferences");
    return Object.fromEntries(
      Object.entries(DEFAULT_GALLERY_DETAILS).map(([key, fallback]) => [
        key,
        typeof value[key] === "boolean" ? value[key] : fallback,
      ]),
    );
  } catch {
    return { ...DEFAULT_GALLERY_DETAILS };
  }
}

export const GALLERY_HOVER_PREVIEW_DELAY_MS = 650;
export const GALLERY_HOVER_PREVIEW_DURATION_S = 6;

/** Hover previews are deliberately opt-in; only the exact stored true value enables them. */
export function readGalleryHoverPreviews(raw) {
  return raw === "true";
}

/** The first request (including React Strict Mode's repeated mount effect) is immediate.
    Later query changes keep the existing debounce so typing does not issue a request
    for every keypress. */
export function galleryPageRequestDelay(previousKey, nextKey) {
  return previousKey === null || previousKey === nextKey ? 0 : 200;
}

export function galleryHoverPreviewUrl(videoUrl) {
  return `${videoUrl.split("#", 1)[0]}#t=0,${GALLERY_HOVER_PREVIEW_DURATION_S}`;
}

export function shouldStopGalleryPreview(currentTime) {
  return Number.isFinite(currentTime) && currentTime >= GALLERY_HOVER_PREVIEW_DURATION_S;
}
