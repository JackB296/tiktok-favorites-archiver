import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

async function load(relativePath) {
  const source = await readFile(new URL(relativePath, import.meta.url), "utf8");
  return import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
}

const links = await load("../src/lib/songLinks.js");

const withUrls = {
  title: "Blinding Lights", artist: "The Weeknd", album: null, art_url: null,
  shazam_url: "https://www.shazam.com/track/1", apple_url: "https://music.apple.com/x",
  spotify_url: "https://open.spotify.com/track/abc",
};
const bare = {
  title: "Some Viral Sound", artist: null, album: null, art_url: null,
  shazam_url: null, apple_url: null, spotify_url: null,
};

// Direct provider links are preferred when Shazam supplies them.
assert.equal(links.primarySongUrl(withUrls), "https://open.spotify.com/track/abc");
assert.equal(links.spotifyUrl(withUrls), "https://open.spotify.com/track/abc");
assert.equal(links.appleMusicUrl(withUrls), "https://music.apple.com/x");

// Missing provider links fall back to encoded search URLs (never empty).
assert.equal(links.songSearchQuery(withUrls), "Blinding Lights The Weeknd");
assert.equal(links.spotifyUrl(bare), "https://open.spotify.com/search/Some%20Viral%20Sound");
assert.equal(
  links.youtubeUrl(bare),
  "https://www.youtube.com/results?search_query=Some%20Viral%20Sound",
);
assert.equal(links.primarySongUrl(bare), "https://open.spotify.com/search/Some%20Viral%20Sound");

// Label formatting.
assert.equal(links.songLabel(withUrls), "Blinding Lights · The Weeknd");
assert.equal(links.songLabel(bare), "Some Viral Sound");

console.log("test-song-links: OK");
