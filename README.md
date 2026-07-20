<h1 align="center">TikTok Favorites Archive</h1>

<p align="center">
  Turn your TikTok data export into a self-hosted archive of everything you've favorited, then scroll it like TikTok itself.
</p>

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white" alt="Python 3.12"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI"></a>
  <a href="https://react.dev/"><img src="https://img.shields.io/badge/React-20232A?logo=react&logoColor=61DAFB" alt="React"></a>
  <a href="https://www.typescriptlang.org/"><img src="https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white" alt="TypeScript"></a>
  <img src="https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white" alt="SQLite">
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white" alt="Docker"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-3FB950" alt="License: MIT"></a>
</p>

<p align="center">
  <img src="screenshots/feed.png" alt="The Feed: a vertical, TikTok-style scroll of your saved favorites" width="880">
</p>

Videos download as-is. Photo slideshows are rebuilt into MP4s with their original sound. A local web app runs the downloads and browses the results, and Plex handles the TV. Everything runs on your own machine through a self-hosted [Cobalt](https://github.com/imputnet/cobalt) instance, so your favorites never pass through anyone else's server.

## Architecture

<p align="center">
  <img src="screenshots/architecture.svg" alt="System architecture: a TikTok data export flows through a Python download engine and a self-hosted Cobalt resolver into a local SQLite-indexed archive, served by FastAPI to a React web app and to Plex." width="100%">
</p>

The app reads your export, records every favorite in a SQLite database, and works through them with a bounded pool of workers that stays under Cobalt's rate limit. Cobalt resolves each link to real media. Videos download directly. A photo post has its images and audio downloaded, rebuilt into a slideshow MP4 (each image centered on a black canvas sized to the largest image, with no downscaling), and its raw images kept so the web viewer can render them as a carousel.

File numbering is stable: `147.mp4` stays archive item 147 in the database. Favorite chronology is stored separately, so a legacy migration can preserve old filenames without making Feed order wrong. A rerun never renumbers or overwrites what you already have, and Plex keeps its place.

## Highlights

- **Runs entirely on your machine.** The app and its own Cobalt resolver come up together with one `docker compose up`. Nothing you import or download touches a third-party server.
- **Resilient download engine.** A bounded worker pool holds a configurable request rate and backs off on HTTP 429. Progress lives in SQLite, downloads stream to a `.part` file and are renamed into place only when complete, and a rerun resumes exactly where it stopped.
- **Rebuilds photo slideshows.** TikTok photo posts are re-encoded into MP4s with their original audio (FFmpeg via MoviePy), each image centered on a canvas sized to the largest slide, with the raw images kept for the in-app carousel.
- **Scales to a real library.** The Feed and Gallery stay responsive at 11,000+ favorites through row virtualization, media preloading, and range-based streaming from the backend.
- **Identifies songs (opt-in).** Shazam names the track in each favorite and shows it in Feed and Gallery. A Music tab lists every identified song, opens each in Spotify, YouTube, or Apple Music, saves playlists, and can push a saved playlist to your own Spotify account. It stays off until you turn it on; enabling it uploads a short audio clip per video to Shazam, the only time the app sends your media's audio to an outside service.
- **Shows you your own habits.** A Stats tab turns the archive into charts: how it grew over time, when you favorite (a day×hour heatmap), how long your favorites run, your top creators, songs, and hashtags, and archive health — all from data already on disk, no new services.
- **Owns backup and storage.** Configure mounted folders or NAS shares, preview and verify copy/move/restore operations, and create portable metadata or complete Archive snapshots with checksum validation and guarded rollback restore.
- **Automates on your terms.** Saved Gallery presets are live Smart collections, Sync follow-ups are configurable, and daily or weekly runs execute inside the app with timezone/DST-safe catch-up.
- **Finds what you remember.** Local Lens generates timestamped speech and on-screen text inside the app with bundled, CPU-only local tools, then jumps straight to the matching moment. Existing JSON imports remain available as a manual override.
- **Makes the archive feel alive.** Memory Lane resurfaces anniversaries and overlooked favorites, while Archive Time Machine shows exactly what appeared or disappeared between TikTok exports without deleting local media.
- **Builds personal stories.** Turn a saved Gallery queue into an editable sequence, trim and reorder its chapters, then render a private vertical MP4 locally with FFmpeg. Source favorites remain untouched.
- **Built to be operated.** Live per-item progress over Server-Sent Events, an archive integrity check, a one-click recovery inbox, saved and shareable filters, and a portable CSV inventory.
- **Tested and typed.** The download engine is a standalone Python package with a stdlib-first unit suite (the HTTP-tier file additionally self-skips unless FastAPI is installed). The frontend talks to a small typed API and never reaches Cobalt directly.

## Quick start

You need [Docker](https://www.docker.com/).

```bash
git clone https://github.com/JackB296/tiktok-favorites-archiver.git
cd tiktok-favorites-archiver
docker compose up --build
```

Open **http://localhost:8080**. That one command starts the app and its own Cobalt instance together, so there is nothing else to install. Then:

1. Open the **Sync** tab, upload your TikTok data export (the how-to button walks you through getting it), and press Start.
2. Watch each favorite download in real time.
3. Browse them in **Feed** and **Gallery**.

Media is written to `./downloads` on your host. Point Plex at that folder and your favorites play on the TV.

## The app

### Feed

A vertical scroll of your favorites, one at a time. Videos autoplay as they come into view and expose play/pause and seeking controls on hover. Photo posts use a manual image carousel while their original audio keeps playing; slides never advance on their own. An identified song shows as a chip you can open in a music service, and a per-post button lets you search for and set the song by hand.

It opens at your newest favorite, remembers where you left off ("go to last watched"), and has a no-repeat shuffle. Desktop controls are built in: arrow keys change favorites, Space pauses, M toggles sound, F enters or exits fullscreen. The next eight posts preload and the previous video stops the moment navigation begins, so the Feed stays smooth at 11,000+ favorites. Optional loudness leveling is capped at 2.5× to avoid distorted amplification.

### Gallery

A searchable thumbnail grid of everything, ranked best-match first.

- **Search and filter.** Search by caption, hashtag, or author (from TikTok's public oEmbed data). Beyond the All / Videos / Slideshows filter, an advanced panel covers date range, duration, file size, resolution, orientation, codec, download status, and attempt count, plus include/exclude author and tag lists, eleven repeatable sort orders, and a fresh random shuffle.
- **Smart collections and lists.** Save any filter combination as a named Smart collection or share it as a copyable link. Membership is resolved live whenever you open, play, export, or bulk-mark it. Save reusable author/hashtag allow or deny lists (for example "No FYP" or "Gaming") and apply them without clearing terms already entered. Playback queues remain fixed snapshots of the IDs you selected.
- **Recovery and repair.** The one-click Recovery inbox refreshes archive integrity, then surfaces failed downloads, scan-confirmed missing files, and untouched pending favorites. Confirmed-silent videos are flagged on their cards and in Feed. Each post can have its local MP4, thumbnail, or both replaced without changing its archive number, caption, creator, or source link; the previous file is kept in `downloads/.archive/replaced/` so a mistaken upload can be undone.
- **Queues and inspect.** Select up to 100 favorites to start a temporary custom Feed queue, save it as a named queue, or target recovery. Inspect mode opens a favorite's full archive metadata, including retry count and last attempt time, without leaving the grid. Failed favorites show their last error.
- **Performance and previews.** The first page starts loading immediately, later pages arrive near the end of the current results, and only viewport-adjacent thumbnail rows stay mounted. **Hover previews** are on by default in a fresh browser: rest the pointer on a video for about 250 ms to play one muted six-second sample in its card. The toolbar toggle remembers an explicit off choice per browser. Moving away tears the video down, and the Gallery never loads more than one preview at a time.

### Music

Every identified song collects here, most-used first. Each track shows how many favorites use it, opens in Spotify, YouTube, or Apple Music, and can start a Feed of exactly the favorites that share it. Tick songs to save a named playlist. The tab is empty until you enable song identification in Sync and run it.

Connect your own Spotify account (a free developer app's Client ID, one-time) and each saved playlist gains a push button that creates it as a private Spotify playlist, matching each song by its stored link or a search. Pushing again updates the same playlist instead of duplicating, and the app reports exactly which songs it could not confidently match. Nothing reaches Spotify until you connect and press push.

### Stats

A read-only dashboard over data the archive already has. A summary strip (total favorites, video/slideshow mix, total watch-length, disk usage, percent archived) leads into four sections: **Growth** (cumulative favorites and per-month saves), **You as a watcher** (a day-of-week × hour favoriting heatmap, a duration histogram with your median, and the confirmed-silent share), **Top of your archive** (most-favorited creators, most-used songs, and top hashtags, each linking into a filtered Gallery or the Music tab), and **Archive health** (a lifecycle donut and the most common failure reasons). Favorites without a saved date sit out of the time charts and are disclosed, never guessed.

### Discover

Creators and Hashtags become first-class, Unicode-normalized identities. Discover searches and orders both sets by name, use count, or recent activity, then opens an exact Gallery or Feed selection—`@ann` never accidentally includes `@anna`. Existing caption and author fields remain available while an automatic, resumable backfill upgrades older databases.

### Local Lens

Local Lens searches inside a favorite instead of only searching its caption.
The official Docker image includes `whisper.cpp` with the multilingual base
model for speech and Tesseract with English data for text visible in frames.
Both run inside the app container. No media, extracted audio/frame, transcript,
or OCR result is sent to a hosted analysis service.

Local analysis is enabled after Sync by default. New downloads are analyzed
automatically, and **Analyze missing** backfills every eligible MP4 already on
disk. Favorites marked offloaded, missing, or unavailable are skipped even when
a NAS is mounted; the app never restores them just to analyze them. Speech and
screen text complete independently, so a failure in one does not discard the
other, and successful empty results are remembered. The run can be paused,
continued, or stopped from Local Lens.

Transcript segments can also appear as timed captions over Feed videos. Use the
**CC** control to show or hide them; captions start off in a fresh browser and
the choice is remembered on that browser. Only transcript segments are
displayed. OCR stays searchable in Local Lens and is never placed over the
video.

The earlier JSON workflow remains under the closed **Manual import** section.
It is intentionally small and tool-neutral:

```json
{
  "items": [
    {
      "item_id": 147,
      "segments": [
        {
          "source": "transcript",
          "text": "Press the parmesan side down.",
          "start_s": 18.2,
          "end_s": 22.7
        },
        {
          "source": "ocr",
          "text": "400°F · 20 minutes",
          "start_s": 23,
          "end_s": null
        }
      ]
    }
  ]
}
```

`source` must be `transcript` or `ocr`; times are finite non-negative seconds. A
document can contain up to 5,000 favorites and 100,000 total segments within the
64 MB upload limit. The complete document is validated before any indexed text
changes. Imported sources are authoritative and automatic analysis never
overwrites them; an omitted source remains eligible for local generation.

The bundled base model adds about 142 MiB to the image and uses roughly 388 MB
of memory while loaded. Analysis is CPU-intensive and deliberately processes
one favorite at a time. Long initial backfills can run for hours or days,
depending on the archive and CPU; pause or stop them at any time without losing
completed work.

### Memory Lane and Archive Time Machine

Memory Lane creates three private daily shelves from local metadata: favorites saved on this date in earlier years, never or least-recently played favorites, and more finds from the current month's archives. A shelf opens as a fixed Feed queue. The only new activity it records is which favorite becomes active in the local Feed; no watch history leaves the SQLite database.

Every successful export upload also becomes an immutable Time Machine checkpoint. History compares it with the immediately previous upload and reports new, missing, unchanged, and missing-but-safely-archived favorites. "Missing" only describes the newer TikTok export. It never deletes, renumbers, or changes an existing archive item.

### Story Builder

Story Builder turns any saved Gallery playback queue into a chaptered personal reel. Rename chapters, set optional start/end seconds, reorder or remove favorites, preview each cut in Feed, and save the plan without touching source media. Render runs locally through FFmpeg, normalizes every chapter to a vertical H.264/AAC stream, and atomically publishes the result under `downloads/.archive/stories/`. A failed render keeps the previous complete output, records the error, and can be retried.

### Storage and Backups

Storage locations are folders already mounted on the app machine, such as an external drive or NAS bind mount. The app validates that a location is mounted, writable, and outside the active downloads/database paths. Copy and Move always show a read-only preview; both checksum every durable media file before recording a verified placement, and Move deletes local files only after that record is safely persisted. Restore verifies the external copy, recreates local media, and leaves the external copy intact. Legacy rows previously marked Offloaded remain visible but are not claimed as verified until managed storage has evidence for them.

Backups creates a versioned `.tiktok-archive` directory. Metadata snapshots contain a consistent SQLite online backup; complete snapshots add media. Both use sorted relative-path manifests and SHA-256 checksums, publish atomically after validation, and resume partial work. Replacing a non-empty Archive requires typing `REPLACE ARCHIVE` and creates a rollback snapshot first.

### Sync

The control center. Upload your export, then start, pause, resume, or stop a run
and watch per-item status update live over Server-Sent Events. It keeps a
durable phase timeline and retry ancestry. You can enable and reorder supported
post-Sync phases without changing the default
(`Sync → Search metadata → Song identification → Local analysis`), and create
daily or weekly schedules with an explicit IANA timezone. Schedules run only
while the app is running, defer while another Archive job is active, and catch
up at most one missed occurrence after restart.

<p align="center">
  <img src="screenshots/sync.png" alt="The Sync dashboard: upload, run controls, live per-item progress" width="880">
</p>

## Details worth knowing

- **Dead links stay meaningful.** When TikTok reports that an original post is gone, the favorite becomes an unavailable archive marker instead of a recurring failure. Its number and position remain visible in Feed and Gallery, and automatic Sync runs do not retry it.
- **Original slideshow audio.** Photo posts request the full original sound. If TikTok has already deleted it, a bundled default track fills in instead of failing the encode — replaceable with your own MP3 from the Sync tab's media settings.
- **Push playlists to Spotify.** In the Music tab, connect your own free Spotify app once, then push any saved playlist to a private Spotify playlist. Matches come from each song's stored link or a search; unmatched songs are reported rather than guessed, and re-pushing updates the same playlist.
- **Asset backfill.** Already had downloads before this existed? The Sync tab's Backfill re-fetches the raw slideshow images for your existing files so they render in the viewer. Local Lens has its own **Analyze missing** backfill for speech and OCR.
- **Provenance.** `downloads/manifest.csv` maps each file to its source link, type, and status alongside the database.
- **Gallery index.** Sync records duration, dimensions, codec, file size, and whether an audio stream exists, then renders a WebP thumbnail per favorite (480px or 320px), so the Gallery pages instantly instead of decoding video. Indexing runs on a small worker pool and can be rebuilt, paused, or turned off.
- **Search metadata.** Sync can fetch missing captions and creator names from TikTok's public oEmbed endpoint at the configured rate limit, skipping entries already enriched. This powers author, hashtag, and caption search.
- **Song identification (opt-in).** Off by default. When you turn it on, a rate-limited Sync run uploads a short audio clip per video to Shazam and records the match. It remembers the ones Shazam cannot place so a rerun skips them, and a per-post search lets you set or correct a song by hand. Enabling it is the only time the app sends your audio to an outside service.
- **Media-server metadata.** One click writes a `.nfo` title file and `.jpg` poster next to every video, so Plex, Jellyfin, and Kodi show real titles and artwork instead of bare numbers. Your media files are never modified.
- **Integrity check.** Sync can verify the whole archive: finished favorites missing their video (one click re-queues them), stray files no favorite claims, and leftover temp files from interrupted runs.
- **Localhost only.** The app has no login, so Docker binds it to `127.0.0.1`; nothing else on your network can reach it. Plex reads `./downloads` from disk and is unaffected.
- **Backups.** The Backups tab produces validated portable snapshots. A stopped-app copy of `./downloads` plus `./appdata/archive.db` remains a valid manual fallback.

## Project layout

```
core/     download engine: export parsing, Cobalt client, slideshow encoder,
          SQLite store, concurrent sync, oEmbed enrichment, asset backfill,
          Shazam song identification, local speech/OCR analysis
server/   FastAPI backend: REST + Server-Sent Events, background job manager,
          range-capable media streaming
web/      React + Vite + Tailwind SPA: Feed, Gallery, Lens, Memories,
          History, Stories, Storage, Backups, Sync
Dockerfile + docker-compose.yml   the app plus an official Cobalt image
```

The download engine is a standalone Python package with no web dependency, covered by a stdlib-only unit suite. The backend wraps it with job control and live progress. The frontend talks to a small typed API and never reaches Cobalt directly.

## Development

Backend tests are stdlib-only, with nothing to install:

```bash
for f in tests/test_*.py; do python3 "$f"; done
```

`python3 tests/test_store.py` runs one file; every test file is independently runnable.

The web app needs Node 20.19+ for Vite dev/build (see `web/.nvmrc`); the `npm test` behavior scripts run on any recent Node. `npm run dev` serves the SPA with hot reload and proxies `/api` and `/media` to a backend on `localhost:8080`, so start the Docker app (or `uvicorn --factory server.main:create_app --port 8080` — uvicorn defaults to 8000 otherwise) first:

```bash
cd web
npm ci
npm run dev     # SPA on http://localhost:5173, API proxied to :8080
npm run build   # type-check + production bundle
npm test        # behavior scripts over the pure-logic modules in web/src/lib/
```

## Configuration

<details>
<summary>Environment variables and Docker settings</summary>

With Docker, set these on the `app` service in `docker-compose.yml`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `COBALT_API_URL` | `http://cobalt:9000/` | Address of the Cobalt service |
| `DOWNLOAD_DIR` | `/app/downloads` | Where media is saved |
| `CONCURRENCY` | `4` | Simultaneous downloads |
| `RATE_MAX_CALLS` / `RATE_PERIOD` | `8` / `1.0` | Requests allowed per window, in seconds |
| `DB_FILE` | `/app/data/archive.db` | Path of the SQLite archive database |
| `APP_PORT` | `8080` | Port the web app listens on |
| `RETRY_DELAY` | `2.0` | Seconds between download retry attempts |
| `SONG_ID_RATE_MAX_CALLS` / `SONG_ID_RATE_PERIOD` | `1` / `2.0` | Shazam recognitions allowed per window, in seconds |
| `WHISPER_CPP_BIN` | `/usr/local/bin/whisper-cli` | Local speech CLI path |
| `WHISPER_MODEL` | `/opt/whisper/models/ggml-base.bin` | Local multilingual speech model path |
| `TESSERACT_BIN` | `/usr/bin/tesseract` | Local OCR CLI path |
| `ANALYSIS_TIMEOUT` | `900` | Maximum seconds for one local tool subprocess |
| `OCR_INTERVAL_SECONDS` | `2.0` | Seconds between sampled OCR frames |
| `OCR_MAX_FRAMES` | `600` | Maximum OCR frames sampled from one favorite |

If you raise the concurrency and rate, raise Cobalt's `RATELIMIT_MAX` and `RATELIMIT_WINDOW` in the same file to match. If you change `APP_PORT`, update the `ports:` mapping too.

For a mounted Storage location, add a bind mount to the `app` service, rebuild,
then register the container path in **Storage**:

```yaml
services:
  app:
    volumes:
      - ./downloads:/app/downloads
      - ./appdata:/app/data
      - /mnt/archive-nas:/mnt/archive-nas
```

The app does not mount drives itself. Mount the disk/share on the host first,
and keep the container path stable across restarts.

</details>

## Upgrading an existing web archive

Pull the code and run `docker compose up --build` against the same `downloads`
and `appdata` bind mounts. Startup applies additive schema migrations only; it
does not hash, copy, rename, or delete media. Creator/Hashtag discovery then
backfills in bounded, persisted batches when the Archive is idle. It can resume
after interruption. Existing presets become Smart collections with no rewrite,
existing playback queues remain fixed, and old `offloaded = 1` rows retain that
status as unverified legacy placements. Existing Local Lens evidence is
registered as manual and remains unchanged. The migration itself does not
analyze media, but it enables Local analysis once in the Sync pipeline by
default. The next Sync analyzes eligible local favorites, or you can start the
backfill immediately with **Local Lens → Analyze missing**. Removing that
follow-up in the app is remembered on later upgrades.

Before moving an archive between computers, create and validate a metadata or
complete snapshot in **Backups** before disconnecting the old installation.

## Getting your TikTok data

<details>
<summary>How to request and upload your export</summary>

1. In TikTok, open **Settings and privacy → Account → Download your data**.
2. Choose **All data** and the **JSON** format, then submit the request.
3. When TikTok has prepared it, download and unzip the archive.
4. Upload `user_data_tiktok.json` in the Sync tab.

Exports expire. If links stop resolving partway through a run, request a fresh one.

</details>

## Upgrading an archive made by the original CLI

<details>
<summary>Guarded legacy bootstrap for numbered MP4s from the old CLI</summary>

Use the guarded legacy bootstrap if you have numbered MP4s and
`last_downloaded_link.txt`, but no `downloads/manifest.csv` or established
`appdata/archive.db`. It is designed for an unavailable NAS: only the numeric
MP4s currently in `downloads` are required.

On Windows, install and start Docker Desktop first. In GitHub Desktop, fetch
and pull the latest code, then open PowerShell in the repository folder:

```powershell
docker compose down
Test-Path '.\downloads'
Get-ChildItem '.\downloads' -Filter '*.mp4' -File | Select-Object -First 5 Name
Test-Path '.\last_downloaded_link.txt'
Get-ChildItem '.\appdata' -Force -ErrorAction SilentlyContinue
```

Bootstrap deliberately requires a database with no favorite rows. If
`appdata` contains an earlier test database, preserve the whole directory and
start with a new one; do not delete it:

```powershell
if (Test-Path '.\appdata') {
    $backup = ".\appdata-before-legacy-$((Get-Date).ToString('yyyyMMdd-HHmmss'))"
    Rename-Item '.\appdata' $backup
}
New-Item -ItemType Directory -Force '.\appdata'
docker compose up --build -d
```

Open **http://localhost:8080 → Sync → First-time setup from the old CLI** and
choose:

1. **Old export:** the `user_data_tiktok.json` used by the final CLI run.
2. **Current export:** the newest `user_data_tiktok.json` containing the new favorites.
3. **Checkpoint:** the old `last_downloaded_link.txt`.

Press **Preview mapping**. Nothing is written during preview. Check the
inferred offset, local filename range, gap count, number of new downloads, and
several sample link-to-file mappings. Apply is enabled only after you confirm
the samples. Apply writes one atomic SQLite transaction and does not rename,
delete, move, index, or download any media.

If the original CLI was restarted and its numbering changed, use **Mapping
segments** before preview. Enter comma-separated `first-file:offset` pairs.
For example, `20968:5833, 22315:5832` means files #20,968-#22,314 use offset
5,833 and files from #22,315 onward use 5,832. Preview shows each resulting
file and export-position range separately. Any favorite consumed by a failed
run and then hidden by a reused filename is preserved as its own ignored
position marker.

After it succeeds, the result explains how many local files were matched, how
many failed legacy filename slots were preserved, how many inaccessible older
favorites were marked offloaded, and how many truly new favorites are pending.
Only then press **Start sync**. Gallery indexing can run with Sync or be rebuilt
later; it is not part of the migration.

Pulling code through GitHub Desktop does not touch `downloads`, `appdata`, the
export JSON, or `last_downloaded_link.txt`: all are git-ignored local data. The
Docker Compose bind mounts use those same folders on the host, so rebuilding
the image does not copy the media into Docker or erase it.

</details>

## Headless archive command

<details>
<summary>Run the archive without the web app</summary>

The headless Archive command needs its own Cobalt instance (see Cobalt's [run-an-instance guide](https://github.com/imputnet/cobalt/blob/main/docs/run-an-instance.md)) and Python 3.12 with FFmpeg on your `PATH` (older Pythons may need a Rust toolchain to build `shazamio`).

```bash
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m core sync --data-file user_data_tiktok.json
```

Flags: `--cobalt-url`, `--data-file`, `--download-dir`, `--db`, `--concurrency`. Run `python -m core sync --help` for the defaults.

</details>

## Built with

Python · FastAPI · SQLite · MoviePy · React · Vite · TypeScript · Tailwind CSS · Docker · [Cobalt](https://github.com/imputnet/cobalt)

## Disclaimer

Not affiliated with, endorsed by, or sponsored by TikTok or ByteDance Ltd. "TikTok" is a trademark of its respective owner and is used here only to describe what this tool works with.

This is a tool for **privately archiving your own favorited content** from the data export TikTok provides to you. Importing and downloading run entirely on your own machine and send nothing to the author. The one exception is optional song identification: when you enable it, a short audio clip per video is sent to Shazam to name the track, through the unofficial [`shazamio`](https://github.com/shazamio/ShazamIO) client. It is off by default and is not affiliated with or endorsed by Shazam or Apple. You are responsible for complying with [TikTok's Terms of Service](https://www.tiktok.com/legal/), with Shazam's terms when you use identification, and with the copyright of the original creators. Keep downloaded media for personal use and don't redistribute it. The software is provided "as is", without warranty, under the [MIT License](LICENSE).

## License

[MIT](LICENSE) © Jack Bialecki
