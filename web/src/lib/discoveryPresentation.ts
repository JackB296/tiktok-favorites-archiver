export function discoveryGalleryUrl(kind: "creator" | "hashtag", key: string): string {
  return `/gallery?${kind}=${encodeURIComponent(key)}`;
}

export function discoveryFeedUrl(kind: "creator" | "hashtag", key: string, firstItemId: number): string {
  return `/?${kind}=${encodeURIComponent(key)}&item=${firstItemId}`;
}

