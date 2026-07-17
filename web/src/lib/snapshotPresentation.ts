export const REPLACE_CONFIRMATION = "REPLACE ARCHIVE";

export function snapshotSize(bytes: number): string {
  if (bytes >= 1_000_000_000) return `${(bytes / 1_000_000_000).toFixed(1)} GB`;
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}

export function restoreDisclosure(plan: {
  snapshot_items: number; target_items: number; required_bytes: number; conflicts: number;
}): string {
  return `${plan.snapshot_items} snapshot Favorites replace ${plan.target_items} current Favorites · ${snapshotSize(plan.required_bytes)} media · ${plan.conflicts} conflicts`;
}
