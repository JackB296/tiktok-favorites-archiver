export interface CaptionPart {
  text: string;
  hashtag: string | null;
}

export function captionParts(caption: string): CaptionPart[];
export function hashtagGalleryUrl(hashtag: string): string;
export function cleanMetadataText(value: string | null | undefined): string;
