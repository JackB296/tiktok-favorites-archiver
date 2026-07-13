const TARGET_RMS = 0.22;

export function readPlaybackVolume(raw) {
  if (raw === null || raw === "") return 1;
  const value = Number(raw);
  return Number.isFinite(value) && value >= 0 && value <= 1 ? value : 1;
}

/** Convert the current signal RMS into a safe, bounded leveling multiplier. */
export function normalizationGain(rms) {
  if (!Number.isFinite(rms) || rms <= 0) return 1;
  return Math.max(0.35, Math.min(2.5, TARGET_RMS / rms));
}

export function formatAutoGain(gain) {
  const safe = Number.isFinite(gain) ? Math.max(0, gain) : 1;
  return `Auto ${safe.toFixed(2)}×`;
}
