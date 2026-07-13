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
