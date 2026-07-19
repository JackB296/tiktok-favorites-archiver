export interface GalleryDetails {
  archiveNumber: boolean;
  duration: boolean;
  resolution: boolean;
  author: boolean;
  caption: boolean;
  technical: boolean;
}

export const DEFAULT_GALLERY_DETAILS: Readonly<GalleryDetails>;
export function readGalleryDetails(raw: string | null): GalleryDetails;
export const GALLERY_HOVER_PREVIEW_DELAY_MS: 650;
export const GALLERY_HOVER_PREVIEW_DURATION_S: 6;
export function readGalleryHoverPreviews(raw: string | null): boolean;
export function galleryPageRequestDelay(previousKey: string | null, nextKey: string): number;
export function galleryHoverPreviewUrl(videoUrl: string): string;
export function shouldStopGalleryPreview(currentTime: number): boolean;
