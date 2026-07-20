const suites = [
  "test-virtual-grid.mjs", "test-viewer-shortcuts.mjs", "test-ui-behavior.mjs",
  "test-feed-items.mjs", "test-loading-presentation.mjs", "test-legacy-bootstrap.mjs",
  "test-media-layout.mjs", "test-song-links.mjs", "test-gallery-filters.mjs",
  "test-saved-list.mjs", "test-feed-window.mjs", "test-feed-sources.mjs",
  "test-channel-playback.mjs", "test-stats-presentation.mjs", "test-storage-presentation.mjs",
  "test-snapshot-presentation.mjs", "test-smart-collection-presentation.mjs",
  "test-schedule-presentation.mjs", "test-discovery-presentation.mjs",
  "test-lens-presentation.mjs", "test-history-presentation.mjs",
  "test-memory-presentation.mjs", "test-navigation.mjs",
];

for (const suite of suites) {
  await import(`./${suite}`);
}

console.log(`PASS ${suites.length} frontend behavior suites`);
