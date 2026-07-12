import type { LegacyMappingSegment } from "./types";

/** Parse compact ``start:offset`` pairs used by the advanced legacy importer. */
export function parseLegacyMappingText(value: string): LegacyMappingSegment[] | undefined {
  if (!value.trim()) return undefined;
  return value.split(/[,\n]+/).map((part) => {
    const match = part.trim().match(/^(\d+)\s*:\s*(-?\d+)$/);
    if (!match) throw new Error("Enter mapping segments as start:offset pairs.");
    const start_id = Number(match[1]);
    const offset = Number(match[2]);
    if (!Number.isSafeInteger(start_id) || start_id < 1) {
      throw new Error("Each mapping segment must start at a positive archive number.");
    }
    if (!Number.isSafeInteger(offset)) throw new Error("Each mapping offset must be an integer.");
    return { start_id, offset };
  });
}
