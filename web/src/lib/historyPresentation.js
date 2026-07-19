export function importSummary(counts) {
  if (!counts) return "No comparison available";
  const parts = [
    `${counts.new} new`,
    `${counts.removed} missing`,
    `${counts.unchanged} unchanged`,
  ];
  if (counts.protected) parts.push(`${counts.protected} safely archived`);
  return parts.join(" · ");
}

export function importDisplayDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown date";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function archiveItemUrl(itemId) {
  return `/?item=${encodeURIComponent(itemId)}`;
}
