export const MOVE_CONFIRMATION = "MOVE AND DELETE LOCAL";

export function parseArchiveIds(value: string): number[] {
  const ids = value.split(/[\s,]+/).filter(Boolean).map(Number);
  if (!ids.length || ids.some((id) => !Number.isSafeInteger(id) || id < 1)) {
    throw new Error("Enter one or more positive archive numbers.");
  }
  return Array.from(new Set(ids));
}

export function transferSummary(preview: {
  action: string; items: number; files: number; bytes: number;
  conflicts?: number; already_verified?: number; missing_verified?: number[];
}): string {
  const size = preview.bytes >= 1_000_000_000
    ? `${(preview.bytes / 1_000_000_000).toFixed(1)} GB`
    : `${(preview.bytes / 1_000_000).toFixed(1)} MB`;
  return `${preview.items} Favorites · ${preview.files} files · ${size}`;
}
