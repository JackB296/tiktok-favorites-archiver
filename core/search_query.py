"""Small, shared parser for local archive field-search syntax."""
from dataclasses import dataclass
import re


_TOKEN = re.compile(
    r"(?P<negative>-)?(?:(?P<field>[A-Za-z_][A-Za-z0-9_-]*):)?"
    r"(?P<value>\"[^\"]+\"|[^\s]+)"
)
_COMPARISON = re.compile(r"^(>=|<=|>|<|=)?([0-9]+)$")


@dataclass(frozen=True)
class SearchToken:
    value: str
    negative: bool = False
    phrase: bool = False


@dataclass(frozen=True)
class ParsedSearch:
    terms: tuple[SearchToken, ...]
    fields: dict[str, tuple[SearchToken, ...]]


def parse(value):
    text = value if isinstance(value, str) else ""
    terms = []
    fields = {}
    for match in _TOKEN.finditer(text):
        raw = match.group("value")
        phrase = len(raw) >= 2 and raw.startswith('"') and raw.endswith('"')
        cleaned = raw[1:-1] if phrase else raw
        cleaned = cleaned.strip()
        if not cleaned:
            continue
        token = SearchToken(cleaned, bool(match.group("negative")), phrase)
        field = (match.group("field") or "").lower().replace("-", "_")
        if field:
            fields.setdefault(field, []).append(token)
        else:
            terms.append(token)
    return ParsedSearch(tuple(terms), {key: tuple(items) for key, items in fields.items()})


def fts_query(tokens):
    """Compile bounded user tokens to an FTS5 expression."""
    positive = []
    negative = []
    for token in tokens:
        words = re.findall(r"[\w@.-]+", token.value, flags=re.UNICODE)[:20]
        if not words:
            continue
        expression = '"' + " ".join(word.replace('"', '""') for word in words) + '"'
        if not token.phrase:
            expression += "*"
        (negative if token.negative else positive).append(expression)
    if not positive:
        return None
    query = " AND ".join(positive)
    if negative:
        query += " NOT " + " NOT ".join(negative)
    return query


def comparison(value):
    match = _COMPARISON.fullmatch(value.strip()) if isinstance(value, str) else None
    if match is None:
        raise ValueError(f"invalid numeric comparison: {value!r}")
    operator = match.group(1) or "="
    return operator, int(match.group(2))
