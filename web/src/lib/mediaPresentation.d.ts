export type GallerySize = "s" | "m" | "l" | "xl";

export function audioStatus(hasAudio: boolean | null): "No audio" | "Has audio" | "Not checked";
export function readGallerySize(raw: string | null): GallerySize;
export function formatMediaTime(seconds: number): string;
