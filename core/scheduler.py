"""In-process daily/weekly Archive-run scheduler with DST-safe occurrences."""
from datetime import date, datetime, time, timedelta, timezone
import re
import threading
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core import migrations, run_catalog, store


_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def validate(values):
    if not isinstance(values, dict):
        raise ValueError("schedule must be an object")
    name = values.get("name")
    if not isinstance(name, str) or not (name := name.strip()) or len(name) > 80:
        raise ValueError("name must be between 1 and 80 characters")
    kind = values.get("run_kind")
    if run_catalog.get(kind).action is None:
        raise ValueError("that run requires an interactive preview and cannot be scheduled")
    cadence = values.get("cadence")
    if cadence not in ("daily", "weekly"):
        raise ValueError("cadence must be daily or weekly")
    local_time = values.get("local_time")
    if not isinstance(local_time, str) or _TIME.fullmatch(local_time) is None:
        raise ValueError("local_time must be HH:MM")
    weekday = values.get("weekday")
    if cadence == "weekly":
        if type(weekday) is not int or weekday not in range(7):
            raise ValueError("weekly schedules need weekday 0 through 6")
    else:
        weekday = None
    zone_name = values.get("timezone")
    if not isinstance(zone_name, str):
        raise ValueError("timezone must be an IANA timezone")
    try:
        ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("timezone must be an IANA timezone")
    enabled = values.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    return {
        "name": name, "run_kind": kind, "cadence": cadence,
        "local_time": local_time, "weekday": weekday,
        "timezone": zone_name, "enabled": enabled,
    }


def _as_utc(value):
    if value.tzinfo is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _occurrence_on(schedule, local_date):
    """The first valid instant at/after the wall time on a local date.

    A spring-forward gap advances to the first valid minute. An autumn repeat
    uses fold 0, so the local date can never be scheduled twice.
    """
    hours, minutes = map(int, schedule["local_time"].split(":"))
    zone = ZoneInfo(schedule["timezone"])
    naive = datetime.combine(local_date, time(hours, minutes))
    for offset in range(181):
        candidate = naive + timedelta(minutes=offset)
        aware = candidate.replace(tzinfo=zone, fold=0)
        if aware.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == candidate:
            return aware.astimezone(timezone.utc)
    raise ValueError("could not resolve scheduled local time")


def _matches(schedule, local_date):
    return schedule["cadence"] == "daily" or local_date.weekday() == schedule["weekday"]


def due_occurrence(schedule, now):
    """Most recent due occurrence, or ``None``; missed runs do not accumulate."""
    if not schedule["enabled"]:
        return None
    now_utc = _as_utc(now)
    local_today = now_utc.astimezone(ZoneInfo(schedule["timezone"])).date()
    lookback = 1 if schedule["cadence"] == "daily" else 7
    for days in range(lookback + 1):
        local_date = local_today - timedelta(days=days)
        if not _matches(schedule, local_date):
            continue
        instant = _occurrence_on(schedule, local_date)
        if instant <= now_utc:
            if schedule.get("last_local_date") == local_date.isoformat():
                return None
            return {"local_date": local_date.isoformat(), "instant": instant}
    return None


def next_occurrence(schedule, after):
    after_utc = _as_utc(after)
    local_today = after_utc.astimezone(ZoneInfo(schedule["timezone"])).date()
    for days in range(9):
        local_date = local_today + timedelta(days=days)
        if not _matches(schedule, local_date):
            continue
        instant = _occurrence_on(schedule, local_date)
        if instant > after_utc and schedule.get("last_local_date") != local_date.isoformat():
            return instant
    raise ValueError("could not calculate next occurrence")


def prepare(values, now):
    validated = validate(values)
    preview = {**validated, "last_local_date": values.get("last_local_date")}
    validated["next_due_at"] = (
        next_occurrence(preview, now).isoformat() if validated["enabled"] else None
    )
    return validated


class Scheduler:
    """Small lifecycle wrapper; ``tick`` is deterministic and testable."""

    def __init__(self, db_path, jobs, clock=None, interval=30.0):
        self.db_path = db_path
        self.jobs = jobs
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self._active_schedule_id = None

    def tick(self):
        now = _as_utc(self.clock())
        conn = store.connect(self.db_path)
        try:
            if self._active_schedule_id is not None and not self.jobs.is_running():
                history = store.list_run_history(conn, 1)
                outcome = history[0]["outcome"] if history else "failed"
                store.set_schedule_outcome(conn, self._active_schedule_id, outcome or "failed")
                self._active_schedule_id = None
            if self.jobs.is_running():
                return False
            state = migrations.get_backfill(conn, "discovery-identities-v1")
            if state is not None and state["status"] != "completed":
                if self.jobs.start("discovery-backfill"):
                    return True
            for schedule in store.list_run_schedules(conn):
                occurrence = due_occurrence(schedule, now)
                if occurrence is None:
                    continue
                if self.jobs.start(schedule["run_kind"]):
                    updated = {**schedule, "last_local_date": occurrence["local_date"]}
                    following = next_occurrence(updated, occurrence["instant"])
                    store.mark_schedule_started(
                        conn, schedule["id"],
                        local_date=occurrence["local_date"],
                        started_at=now.isoformat(),
                        next_due_at=following.isoformat(),
                    )
                    self._active_schedule_id = schedule["id"]
                    return True
            return False
        finally:
            conn.close()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop():
            while not self._stop.wait(self.interval):
                self.tick()

        self._thread = threading.Thread(target=loop, name="run-scheduler", daemon=True)
        self._thread.start()
        self.tick()  # one startup catch-up after the app is ready

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=min(self.interval + 1, 5))
