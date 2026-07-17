"""Normalized Archive item selection for page, ordered Feed, and set actions."""
from dataclasses import dataclass
from types import MappingProxyType

from core import store


_SCOPES = {"page", "feed", "set"}
_SET_FORBIDDEN = {"limit", "cursor", "order", "seed", "feed"}


@dataclass(frozen=True)
class ArchiveSelection:
    scope: str
    query: object
    selector: str = "filter"

    @classmethod
    def gallery(cls, query, *, scope):
        if scope not in _SCOPES:
            raise ValueError(f"unknown selection scope: {scope}")
        normalized = dict(query)
        if scope == "set":
            leaked = sorted(_SET_FORBIDDEN & set(normalized))
            if leaked:
                raise ValueError(f"{leaked[0]} is not a filter")
        q, _clauses, _params, fts_query = store._page_query_base(
            normalized, "selection",
        )
        if scope != "set":
            store._page_order(q, fts_query)
        return cls(scope, MappingProxyType(normalized))

    @classmethod
    def bulk(cls, kind, value):
        if kind == "filter":
            return cls.gallery(value, scope="set")
        if kind == "ids":
            if not isinstance(value, list) or any(
                type(item_id) is not int or item_id < 1 for item_id in value
            ):
                raise ValueError("ids must be positive integers")
            return cls("set", tuple(dict.fromkeys(value)), selector="ids")
        if kind == "range":
            if (
                not isinstance(value, dict)
                or type(value.get("first_id")) is not int
                or type(value.get("last_id")) is not int
                or not 1 <= value["first_id"] <= value["last_id"]
            ):
                raise ValueError("range needs integer first_id <= last_id, both >= 1")
            return cls(
                "set",
                (value["first_id"], value["last_id"]),
                selector="range",
            )
        raise ValueError(f"unknown selector kind: {kind}")

    @classmethod
    def smart_collection(cls, conn, preset_id, *, scope, query_from_filters):
        """Resolve an existing Gallery preset live, without changing its storage."""
        preset = store.get_saved_list(conn, "gallery_preset", preset_id)
        if preset is None:
            raise KeyError(preset_id)
        query = query_from_filters(preset["filters"], seed=preset_id)
        if scope == "set":
            query = {
                key: value for key, value in query.items()
                if key not in _SET_FORBIDDEN
            }
        return preset, cls.gallery(query, scope=scope)

    def rows(self, conn):
        if self.scope != "page" or self.selector != "filter":
            raise ValueError("only page selections return rows")
        return store.page_items(conn, **dict(self.query))

    def ids(self, conn):
        if self.selector == "ids":
            return list(self.query)
        if self.selector == "range":
            return store.item_ids_in_range(conn, self.query[0], self.query[1])
        if self.scope == "feed":
            return store.feed_ids(conn, **dict(self.query))
        if self.scope == "set":
            return store.item_ids_matching(conn, **dict(self.query))
        raise ValueError("page selections must be read with rows()")
