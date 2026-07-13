export type GalleryDensity = "compact" | "comfortable";

export function audioStatus(hasAudio: boolean | null): "No audio" | "Has audio" | "Not checked";
export function readGalleryDensity(raw: string | null): GalleryDensity;
export function formatMediaTime(seconds: number): string;
