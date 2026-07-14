export function audioStatus(hasAudio, audioSilent) {
  if (audioSilent) return "Silent";
  if (hasAudio === false) return "No audio";
  if (hasAudio === true) return "Has audio";
  return "Not checked";
}

export function readGallerySize(raw) {
  return raw === "s" || raw === "m" || raw === "l" || raw === "xl" ? raw : "m";
}

export function formatMediaTime(seconds) {
  const safe = Number.isFinite(seconds) && seconds > 0 ? Math.floor(seconds) : 0;
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}
