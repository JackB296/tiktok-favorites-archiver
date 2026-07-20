"""Single catalog of Archive run workers, actions, pipelines, and eligibility."""
from dataclasses import dataclass

from core import analysis, discovery, enrich, identify, sidecars, snapshots, storage, store, sync, verify


def _run_verify(conn, download_dir, control=None):
    result = verify.verify_archive(conn, download_dir)
    if control is not None:
        control.progress({
            "event": "verify", "completed": result["favorites"],
            "total": result["favorites"], "missing": result["missing"]["count"],
        })
    return result


@dataclass(frozen=True)
class RunSpec:
    kind: str
    action: object
    worker: object
    pipeline: tuple
    label: str
    description: str
    resumable: bool = False


_SPECS = {
    "sync": RunSpec("sync", "start", sync.run_sync, ("sync", "enrich", "identify", "analyze"), "Sync", "Download pending Favorites."),
    "backfill": RunSpec("backfill", "backfill", sync.run_backfill, ("backfill",), "Asset backfill", "Restore slideshow source assets.", True),
    "index": RunSpec("index", "reindex", sync.run_index, ("index",), "Gallery index", "Rebuild thumbnails and media facts.", True),
    "sidecars": RunSpec("sidecars", "sidecars", sidecars.run_sidecars, ("sidecars",), "Media sidecars", "Write media-server metadata.", True),
    "enrich": RunSpec("enrich", "enrich", enrich.run_enrichment, ("enrich",), "Search metadata", "Fetch missing captions and creator names.", True),
    "identify": RunSpec("identify", "identify", identify.run_identification, ("identify",), "Song identification", "Identify songs in archived media.", True),
    "analyze": RunSpec("analyze", "analyze", analysis.run_analysis, ("analyze",), "Local analysis", "Generate local speech and on-screen text.", True),
    "storage-copy": RunSpec("storage-copy", None, storage.run_copy, ("storage-copy",), "Storage copy", "Copy and verify selected media.", True),
    "storage-move": RunSpec("storage-move", None, storage.run_move, ("storage-move",), "Storage move", "Copy, verify, then remove local media.", True),
    "storage-restore": RunSpec("storage-restore", None, storage.run_restore, ("storage-restore",), "Storage restore", "Restore verified external media.", True),
    "snapshot": RunSpec("snapshot", None, snapshots.run_create, ("snapshot",), "Archive snapshot", "Create a verified Archive snapshot.", True),
    "snapshot-restore": RunSpec("snapshot-restore", None, snapshots.run_restore_snapshot, ("snapshot-restore",), "Snapshot restore", "Apply a validated Archive snapshot."),
    "discovery-backfill": RunSpec("discovery-backfill", "discovery", discovery.run_backfill, ("discovery-backfill",), "Discovery backfill", "Index Creator and Hashtag identities.", True),
    "verify": RunSpec("verify", None, _run_verify, ("verify",), "Archive verification", "Check durable media and database integrity.", True),
}
_ACTIONS = {spec.action: spec.kind for spec in _SPECS.values() if spec.action}


def kinds():
    return tuple(_SPECS)


def get(kind):
    try:
        return _SPECS[kind]
    except KeyError:
        raise ValueError(f"unknown Archive run kind: {kind}")


def kind_for_action(action):
    try:
        return _ACTIONS[action]
    except KeyError:
        raise ValueError(f"unknown Archive run action: {action}")


SYNC_FOLLOW_UPS = ("enrich", "identify", "analyze", "sidecars", "index")


def validate_pipeline(kind, phases):
    get(kind)
    if kind != "sync":
        if list(phases) != [kind]:
            raise ValueError(f"{kind} is not configurable")
        return (kind,)
    if not isinstance(phases, (list, tuple)) or not phases or phases[0] != "sync":
        raise ValueError("Sync must be the first pipeline phase")
    follow_ups = phases[1:]
    if len(set(follow_ups)) != len(follow_ups) or any(
        phase not in SYNC_FOLLOW_UPS for phase in follow_ups
    ):
        raise ValueError("pipeline contains an unsupported or duplicate follow-up")
    return tuple(phases)


def pipeline_for(kind, phases=None):
    return validate_pipeline(kind, phases) if phases is not None else get(kind).pipeline


def public_catalog():
    return [
        {
            "kind": spec.kind, "label": spec.label,
            "description": spec.description,
            "resumable": spec.resumable,
            "configurable_follow_up": spec.kind in SYNC_FOLLOW_UPS,
        }
        for spec in _SPECS.values()
    ]


def default_runners():
    return {kind: spec.worker for kind, spec in _SPECS.items()}


def has_work(conn, kind, download_dir=None):
    """Whether an optional pipeline stage has eligible work."""
    get(kind)  # validate first
    if kind == "enrich":
        return bool(enrich.items_needing_enrichment(conn))
    if kind == "identify":
        return bool(store.get_library_settings(conn)["song_id_enabled"]) \
            and bool(store.items_needing_identification(conn))
    if kind == "analyze":
        return bool(
            download_dir is not None
            and analysis.items_needing_analysis(conn, download_dir)
        )
    if kind == "discovery-backfill":
        state = discovery.ensure_backfill(conn)
        return state["status"] != "completed"
    return True
