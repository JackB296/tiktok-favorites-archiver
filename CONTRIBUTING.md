# Contributing

Thanks for looking under the hood. This is a personal project I maintain in my spare time, so issues and small, focused PRs are the easiest things for me to act on.

## Ground rules

- **Open an issue before a big PR.** The app has strong opinions (SQLite only, stdlib-first tests, no telemetry, local-by-default networking) and I'd rather talk an idea through than turn down finished work.
- **Bug reports**: include what you did, what happened, and the app log (`docker compose logs app`). If it's an import or sync problem, say roughly how large your export is — scale bugs are real.
- **No new runtime dependencies without discussion.** Part of the point of this project is a small, auditable footprint.

## Development setup

Backend tests are stdlib-only — nothing to install:

```bash
for f in tests/test_*.py; do python3 "$f"; done
```

Each test file also runs on its own (`python3 tests/test_store.py`). Installing `requirements-web.txt` additionally enables the HTTP-level suite in `tests/test_api_http.py`, which self-skips otherwise.

Frontend (Node 20.19+, see `web/.nvmrc`):

```bash
cd web
npm ci
npm run dev    # SPA on :5173, proxies /api and /media to :8080
npm test       # behavior scripts over web/src/lib
npm run build  # type-check + production build
```

CI runs all of the above plus a Docker image build on every PR, so `git push` tells you what I'll see.

`GLOSSARY.md` at the repo root is a short glossary of domain terms (favorite, archive item, run, offloaded…) that the code uses consistently — worth two minutes before touching `core/`.

## Style

Match what's around you. Python is plain and explicit (no type-checker in CI, docstrings explain *why*), TypeScript is strict. Comments earn their place by recording constraints the code can't express.
