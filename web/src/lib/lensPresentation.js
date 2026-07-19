export function lensSnippetParts(value) {
  const text = typeof value === "string" ? value : "";
  const parts = [];
  const pattern = /\[\[(.*?)\]\]/g;
  let cursor = 0;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) {
      parts.push({ text: text.slice(cursor, match.index), highlight: false });
    }
    parts.push({ text: match[1], highlight: true });
    cursor = match.index + match[0].length;
  }
  if (cursor < text.length) {
    parts.push({ text: text.slice(cursor), highlight: false });
  }
  return parts.length ? parts : [{ text, highlight: false }];
}

export function lensSourceLabel(source) {
  return source === "ocr" ? "Text in frame" : "Spoken match";
}

export function readLensStartTime(value) {
  if (value == null || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

export function mediaStartRequest(src, startAtS, duration) {
  if (typeof src !== "string" || startAtS == null
      || !Number.isFinite(startAtS) || startAtS < 0) {
    return null;
  }
  const maximum = Number.isFinite(duration) && duration >= 0
    ? duration
    : startAtS;
  return {
    signature: `${src}:${startAtS}`,
    time: Math.max(0, Math.min(startAtS, maximum)),
  };
}

export function readCaptionPreference(value) {
  return value === "true";
}

export function activeTranscriptCaption(segments, currentTime) {
  if (!Array.isArray(segments) || !segments.length
      || !Number.isFinite(currentTime) || currentTime < 0) {
    return null;
  }

  let low = 0;
  let high = segments.length - 1;
  let activeIndex = -1;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (segments[middle].start_s <= currentTime) {
      activeIndex = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  if (activeIndex < 0) return null;

  const segment = segments[activeIndex];
  const nextStart = segments[activeIndex + 1]?.start_s;
  const end = Number.isFinite(segment.end_s)
    ? segment.end_s
    : Number.isFinite(nextStart)
      ? nextStart
      : segment.start_s + 4;
  return currentTime < end ? segment : null;
}
