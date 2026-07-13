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
