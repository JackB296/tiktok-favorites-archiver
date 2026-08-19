import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import source_health, store


def test_source_health_flags_a_material_success_drop_and_empty_results():
    conn = store.init_db(store.connect(":memory:"))
    for day in range(1, 5):
        source_health.record(conn, "source-metadata", attempted=20, succeeded=19, empty=1, failed=0, observed_at=f"2026-07-0{day}T00:00:00Z")
    source_health.record(conn, "source-metadata", attempted=20, succeeded=5, empty=10, failed=5, observed_at="2026-07-05T00:00:00Z")
    health = source_health.report(conn)
    source = health["sources"][0]
    assert source["severity"] == "error"
    assert source["current"]["empty"] == 10
    assert "dropped" in source["message"]


if __name__ == "__main__":
    test_source_health_flags_a_material_success_drop_and_empty_results()
    print("PASS test_source_health_flags_a_material_success_drop_and_empty_results")
