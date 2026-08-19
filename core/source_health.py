"""Bounded operational samples that reveal upstream extraction regressions."""
import json
from datetime import datetime, timezone


def record(conn, source, *, attempted, succeeded, empty=0, failed=0,
           details=None, observed_at=None):
    values = [int(attempted), int(succeeded), int(empty), int(failed)]
    if any(value < 0 for value in values) or sum(values[1:]) > values[0]:
        raise ValueError("source health counts are inconsistent")
    observed_at = observed_at or datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO source_health_sample "
        "(source, observed_at, attempted, succeeded, empty_count, failed, details_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (source, observed_at, *values, json.dumps(details or {}, separators=(",", ":"))),
    )
    # Bound long-lived archives without losing recent trend context.
    conn.execute(
        "DELETE FROM source_health_sample WHERE source = ? AND id NOT IN "
        "(SELECT id FROM source_health_sample WHERE source = ? ORDER BY id DESC LIMIT 500)",
        (source, source),
    )
    conn.commit()


def report(conn):
    sources = [row[0] for row in conn.execute(
        "SELECT DISTINCT source FROM source_health_sample ORDER BY source"
    )]
    output = []
    for source in sources:
        rows = conn.execute(
            "SELECT * FROM source_health_sample WHERE source = ? ORDER BY id DESC LIMIT 6",
            (source,),
        ).fetchall()
        current = rows[0]
        previous = rows[1:]
        current_rate = current["succeeded"] / current["attempted"] if current["attempted"] else 1.0
        base_attempted = sum(row["attempted"] for row in previous)
        baseline = sum(row["succeeded"] for row in previous) / base_attempted if base_attempted else current_rate
        drop = baseline - current_rate
        severity = "ok"
        message = "Source is operating normally."
        if current["attempted"] >= 5 and drop >= .3:
            severity = "error"
            message = f"Success rate dropped {round(drop * 100)} percentage points from its recent baseline."
        elif current["attempted"] >= 5 and (drop >= .15 or current["empty_count"] / current["attempted"] >= .4):
            severity = "warning"
            message = "Extraction quality is below its recent baseline or returning unusually empty results."
        output.append({
            "source": source, "severity": severity, "message": message,
            "current_rate": round(current_rate, 4), "baseline_rate": round(baseline, 4),
            "observed_at": current["observed_at"],
            "current": {"attempted": current["attempted"], "succeeded": current["succeeded"], "empty": current["empty_count"], "failed": current["failed"]},
        })
    return {"sources": output, "alerts": sum(entry["severity"] != "ok" for entry in output)}
