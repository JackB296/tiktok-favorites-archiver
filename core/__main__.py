"""``python -m core`` entry point.

    python -m core sync      [opts]   Run the DB-driven concurrent sync engine.
    python -m core backfill  [opts]   Recover raw slideshow assets for past favorites.
    python -m core enrich    [opts]   Fetch captions/authors via oEmbed.
"""
import sys


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    command = args[0] if args else None
    if command == "sync":
        from core.sync import run_cli
        run_cli(args[1:])
    elif command == "backfill":
        from core.sync import run_backfill_cli
        run_backfill_cli(args[1:])
    elif command == "enrich":
        from core.enrich import run_cli
        run_cli(args[1:])
    else:
        raise SystemExit("usage: python -m core {sync|backfill|enrich} [options]")


if __name__ == "__main__":
    main()
