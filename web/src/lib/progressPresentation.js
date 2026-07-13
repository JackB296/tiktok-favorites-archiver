export function progressLabel(event) {
  if (event.event === "complete") return "Run complete";
  if (event.event === "error") return `Error: ${event.error || "Unknown error"}`;
  if (event.event === "indexing") return `Indexing ${event.completed || 0}/${event.total || 0}`;
  if (event.event === "sidecars") return `Metadata files ${event.completed || 0}/${event.total || 0}`;
  if (event.event === "enrichment") {
    const unavailable = event.unavailable ? ` · ${event.unavailable} unavailable` : "";
    return `Metadata ${event.completed || 0}/${event.total || 0} · ${event.enriched || 0} updated${unavailable}`;
  }
  if (event.event === "verify") return `Verifying ${event.completed || 0}/${event.total || 0}`;
  return null;
}
