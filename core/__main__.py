"""``python -m core`` entry point.

    python -m core sync [--cobalt-url ... --data-file ... --download-dir ...]
        Run the DB-driven concurrent sync engine.
    python -m core [--cobalt-url ...]
        Run the legacy single-pass CLI download flow.
"""
import sys


def main():
    args = sys.argv[1:]
    if args and args[0] == "sync":
        from core.sync import run_cli
        run_cli(args[1:])
    else:
        from core.cli import main as legacy_main
        legacy_main()


if __name__ == "__main__":
    main()
