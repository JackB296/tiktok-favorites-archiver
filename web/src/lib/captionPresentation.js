const HASHTAG = /#[\p{L}\p{N}_]+/gu;

export function cleanMetadataText(value) {
  if (!value) return "";
  return value
    .replace(/[\u0000-\u001f\u007f-\u009f]/g, " ")
    .replace(/[\ufff0-\uffff]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function captionParts(caption) {
  const parts = [];
  let cursor = 0;
  for (const match of caption.matchAll(HASHTAG)) {
    const index = match.index ?? 0;
    if (index > cursor) parts.push({ text: caption.slice(cursor, index), hashtag: null });
    parts.push({ text: match[0], hashtag: match[0] });
    cursor = index + match[0].length;
  }
  if (cursor < caption.length) parts.push({ text: caption.slice(cursor), hashtag: null });
  return parts;
}

export function hashtagGalleryUrl(hashtag) {
  return `/gallery?q=${encodeURIComponent(hashtag)}`;
}
