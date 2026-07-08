"""``python -m core`` entry point.

    python -m core sync      [opts]   Run the DB-driven concurrent sync engine.
    python -m core backfill  [opts]   Recover raw slideshow assets for past favorites.
    python -m core enrich    [opts]   Fetch captions/authors via oEmbed.
    python -m core           [opts]   Legacy single-pass CLI download flow.
"""
import sys


def main():
    args = sys.argv[1:]
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
        from core.cli import main as legacy_main
        legacy_main()


if __name__ == "__main__":
    main()
