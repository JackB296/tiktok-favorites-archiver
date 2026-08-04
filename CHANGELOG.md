# Changelog

Notable changes, newest first. Versions follow [SemVer](https://semver.org/); the Docker image on GHCR is tagged to match.

## 1.0.0 — 2026-08-03

First public release. Everything below shipped during pre-release development and is included.

- **Sync engine**: TikTok data-export import, self-hosted Cobalt resolution, bounded worker pool with rate limiting and 429 backoff, resumable runs, `.part`-then-rename downloads, per-item live progress over Server-Sent Events.
- **Photo slideshows** rebuilt into MP4s with their original audio; raw images kept for the in-app carousel.
- **Feed** (vertical TikTok-style scroll with preloading, shuffle, keyboard controls) and **Gallery** (virtualized searchable grid, advanced filters, Smart collections, saved queues, hover previews, recovery inbox).
- **Local Lens**: in-container speech transcription (whisper.cpp) and on-screen text OCR (Tesseract), searchable with jump-to-moment, optional Feed captions.
- **Music**: opt-in Shazam song identification, playlists, push-to-Spotify (your own free client ID, PKCE).
- **Stats, Discover, Memory Lane, Archive Time Machine, Curator Deck, Vibe Atlas, Duplicate Radar, Archive Channels.**
- **Storage & Backups**: managed storage locations with checksummed copy/move/restore, portable `.tiktok-archive` snapshots with guarded replace.
- **Plex/Jellyfin/Kodi** `.nfo` + poster sidecars.
- **Remote access**: `ALLOWED_HOSTS` lets the app answer on LAN, Tailscale, or reverse-proxy names; loopback-only remains the default.
- **Prebuilt multi-arch Docker image** (amd64 + arm64) published to GHCR; compose pulls it by default, `docker-compose.build.yml` builds from source.
- Legacy CLI migration with guarded preview/apply, headless `python -m core sync` command.
