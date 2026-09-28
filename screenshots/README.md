# App recordings

Recorded on 2026-09-28 from the app at commit `e82b2da`, after rebuilding the current frontend.

| File | What it shows |
| --- | --- |
| [browse-demo.mp4](browse-demo.mp4) | Gallery search, Mysterious Skin playback, creator filtering, Manchester by the Sea playback, and keyboard navigation to Buffalo ’66. |
| [import-options.mp4](import-options.mp4) | Favorites + likes selection, the creator import form, automatic-checking controls, and creator rules. Setup only; no full-profile Sync was started. |
| [feed.png](feed.png), [gallery.png](gallery.png) | Frames from the current browsing recording. |

The recordings use three public edits from [@jackbialecki](https://www.tiktok.com/@jackbialecki), with the account owner’s permission:

- [Manchester by the Sea](https://www.tiktok.com/@jackbialecki/video/7686564482755153183)
- [Buffalo ’66](https://www.tiktok.com/@jackbialecki/video/7682917294422461727)
- [Mysterious Skin](https://www.tiktok.com/@jackbialecki/video/7620888467446254878)

The sample archive was prepared with bounded `yt-dlp` downloads and the app’s metadata/media helpers. It is separate from the owner’s archive. A real frame from Mysterious Skin supplies its thumbnail because the automatic thumbnail landed on black. No counts, captions, progress, or successful download states were animated or mocked for the recording.

Chrome recorded only the local app tab, without audio or browser chrome. The final files are scaled H.264 MP4s; idle time may be trimmed. Cobalt was not running in this temporary setup, so the import recording honestly shows it as unreachable. These clips demonstrate the current UI and local playback, not an end-to-end Docker installation or live Cobalt Sync.

The older `demo.gif`, `music.png`, `stats.png`, `lens.png`, and `sync.png` are historical synthetic examples and are no longer embedded in the README or user guide. The retained final media are small; temporary source downloads, recordings, and runtime files are removed after verification.
