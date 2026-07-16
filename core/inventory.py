"""Portable CSV inventory of the local Archive database."""
import csv
import io


FIELDS = (
    "id", "favorited_at", "status", "kind", "attempt_count", "last_attempt_at",
    "archive_missing", "caption", "author", "duration_s", "media_width",
    "media_height", "media_codec", "media_size", "link",
)

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    """Prefix values Excel would execute as formulas (CSV injection guard)."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def csv_lines(rows):
    """Yield a CSV header and one complete CSV line for each SQLite row."""
    def render(values):
        output = io.StringIO(newline="")
        csv.writer(output).writerow(values)
        return output.getvalue()

    yield render(FIELDS)
    for row in rows:
        yield render([safe_cell(row[field]) for field in FIELDS])
