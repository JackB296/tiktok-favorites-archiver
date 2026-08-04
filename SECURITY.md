# Security

## Model

This app is designed to run on a machine you control, for one trusted user, with **no authentication built in**. The defenses it does have:

- Docker binds the port to `127.0.0.1` by default; the app additionally rejects any request whose `Host` header isn't loopback or explicitly named in `ALLOWED_HOSTS` (this is also the DNS-rebinding guard).
- Mutating requests must prove browser intent via a custom header or exact same-origin, so cross-site form/CSRF tricks against a running instance fail.
- Media paths are validated server-side; `/media` cannot traverse outside the downloads directory.
- Outbound traffic is limited to your own Cobalt container, TikTok's public oEmbed endpoint, and — only if you opt in — Shazam (song ID) and Spotify (playlist push). There is no telemetry.

**Do not expose the app directly to the internet.** If you need remote access, use Tailscale or put an authenticating reverse proxy in front (see the README's "Access from other devices" section).

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting ("Report a vulnerability" under the Security tab) rather than a public issue. I'll respond as quickly as a one-person spare-time project honestly can — usually within a week.
