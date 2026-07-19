export function readStoryQueue(value) {
  return Array.from(new Set((value || "").split(",").map(Number)))
    .filter((id) => Number.isSafeInteger(id) && id > 0)
    .slice(0, 100);
}

export function moveStoryChapter(chapters, from, direction) {
  const to = from + direction;
  if (from < 0 || from >= chapters.length || to < 0 || to >= chapters.length) {
    return chapters;
  }
  const copy = [...chapters];
  [copy[from], copy[to]] = [copy[to], copy[from]];
  return copy;
}

export function storyDuration(chapters, items) {
  const durations = new Map(items.map((item) => [item.id, item.duration_s]));
  return chapters.reduce((total, chapter) => {
    const end = chapter.end_s ?? durations.get(chapter.item_id);
    return total + (typeof end === "number" && end > chapter.start_s
      ? end - chapter.start_s
      : 0);
  }, 0);
}
