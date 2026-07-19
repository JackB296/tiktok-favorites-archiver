export function memoryFeedUrl(itemIds, startId) {
  const unique = Array.from(new Set(itemIds))
    .filter((id) => Number.isSafeInteger(id) && id > 0)
    .slice(0, 100);
  if (!unique.length) return "/";
  const item = unique.includes(startId) ? startId : unique[0];
  const ordered = [item, ...unique.filter((id) => id !== item)];
  const params = new URLSearchParams({
    queue: ordered.join(","),
    item: String(item),
  });
  return `/?${params}`;
}

export function memoryDateLabel(value) {
  const date = new Date(`${value}T12:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(date);
}
