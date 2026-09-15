// Streaming links for an identified song. Shazam sometimes hands us a direct
// Spotify/Apple URL; when it doesn't, we fall back to a search link built from
// the title and artist, so every identified song is always clickable.

// Only http(s) may become an anchor; a stored javascript: or data: URL from a
// hostile upstream must fall through to the generated search link instead.
// Kept local rather than importing format.ts so this .js module stays
// dependency-free (the test loads it verbatim via a data: URL).
function safeHttp(url) {
  return typeof url === "string" && /^https?:\/\//i.test(url) ? url : null;
}

export function songSearchQuery(song) {
  return [song.title, song.artist].filter(Boolean).join(" ");
}

export function spotifyUrl(song) {
  return safeHttp(song.spotify_url) || `https://open.spotify.com/search/${encodeURIComponent(songSearchQuery(song))}`;
}

export function appleMusicUrl(song) {
  return safeHttp(song.apple_url) || `https://music.apple.com/search?term=${encodeURIComponent(songSearchQuery(song))}`;
}

export function youtubeUrl(song) {
  return `https://www.youtube.com/results?search_query=${encodeURIComponent(songSearchQuery(song))}`;
}

// The single best "listen" link: a direct provider URL when Shazam gave one,
// else the canonical Shazam page, else a Spotify search.
export function primarySongUrl(song) {
  return (
    safeHttp(song.spotify_url) ||
    safeHttp(song.apple_url) ||
    safeHttp(song.shazam_url) ||
    spotifyUrl(song)
  );
}

// A short display label, e.g. "Blinding Lights · The Weeknd".
export function songLabel(song) {
  return song.artist ? `${song.title} · ${song.artist}` : song.title;
}
