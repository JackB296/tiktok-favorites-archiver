"""Single-range parsing for Archive media responses."""


class RangeNotSatisfiable(ValueError):
    pass


def parse_byte_range(value, size):
    """Return an inclusive ``(start, end)`` pair for one HTTP byte range."""
    if value is None:
        return None
    if type(size) is not int or size < 0:
        raise ValueError("size must be a non-negative integer")
    if not value.startswith("bytes=") or "," in value:
        raise RangeNotSatisfiable("only one byte range is supported")
    bounds = value[len("bytes="):].strip()
    if bounds.count("-") != 1:
        raise RangeNotSatisfiable("byte range is malformed")
    start_text, end_text = bounds.split("-", 1)
    if not start_text:
        if not end_text.isdigit() or int(end_text) <= 0 or size == 0:
            raise RangeNotSatisfiable("byte suffix range is invalid")
        length = min(int(end_text), size)
        return size - length, size - 1
    if not start_text.isdigit() or (end_text and not end_text.isdigit()):
        raise RangeNotSatisfiable("byte range is malformed")
    start = int(start_text)
    if start >= size:
        raise RangeNotSatisfiable("byte range starts beyond the file")
    end = size - 1 if not end_text else min(int(end_text), size - 1)
    if end < start:
        raise RangeNotSatisfiable("byte range ends before it starts")
    return start, end
