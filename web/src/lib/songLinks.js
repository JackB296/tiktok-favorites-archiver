// Streaming links for an identified song. Shazam sometimes hands us a direct
// Spotify/Apple URL; when it doesn't, we fall back to a search link built from
// the title and artist, so every identified song is always clickable.

export function songSearchQuery(song) {
  return [song.title, song.artist].filter(Boolean).join(" ");
}

export function spotifyUrl(song) {
  return song.spotify_url || `https://open.spotify.com/search/${encodeURIComponent(songSearchQuery(song))}`;
}

export function appleMusicUrl(song) {
  return song.apple_url || `https://music.apple.com/search?term=${encodeURIComponent(songSearchQuery(song))}`;
}

export function youtubeUrl(song) {
  return `https://www.youtube.com/results?search_query=${encodeURIComponent(songSearchQuery(song))}`;
}

// The single best "listen" link: a direct provider URL when Shazam gave one,
// else the canonical Shazam page, else a Spotify search.
export function primarySongUrl(song) {
  return song.spotify_url || song.apple_url || song.shazam_url || spotifyUrl(song);
}

// A short display label, e.g. "Blinding Lights · The Weeknd".
export function songLabel(song) {
  return song.artist ? `${song.title} · ${song.artist}` : song.title;
}
