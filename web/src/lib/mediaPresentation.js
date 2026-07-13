export function audioStatus(hasAudio) {
  if (hasAudio === false) return "No audio";
  if (hasAudio === true) return "Has audio";
  return "Not checked";
}

export function readGalleryDensity(raw) {
  return raw === "compact" ? "compact" : "comfortable";
}

export function formatMediaTime(seconds) {
  const safe = Number.isFinite(seconds) && seconds > 0 ? Math.floor(seconds) : 0;
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}
