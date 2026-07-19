import type { ImportComparisonCounts } from "./types";

export function importSummary(counts: ImportComparisonCounts | null | undefined): string;
export function importDisplayDate(value: string): string;
export function archiveItemUrl(itemId: number): string;
