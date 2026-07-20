"""Reproducibility checks for the Docker Python dependency lock."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _package_names(filename):
    names = set()
    with open(os.path.join(ROOT, filename), encoding="utf-8") as source:
        for raw in source:
            line = raw.split("#", 1)[0].strip()
            match = re.match(r"([A-Za-z0-9_.-]+)", line)
            if match:
                names.add(match.group(1).lower().replace("_", "-"))
    return names


def _exact_constraint_names():
    names = set()
    with open(os.path.join(ROOT, "constraints.txt"), encoding="utf-8") as source:
        for raw in source:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)==[^=\s]+", line)
            assert match is not None, f"constraint is not exact: {line}"
            names.add(match.group(1).lower().replace("_", "-"))
    return names


def test_every_direct_requirement_has_an_exact_constraint():
    direct = _package_names("requirements.txt") | _package_names("requirements-web.txt")
    constrained = _exact_constraint_names()
    assert direct <= constrained, f"missing exact pins: {sorted(direct - constrained)}"


def test_httpx2_and_its_required_transport_dependencies_are_pinned():
    constrained = _exact_constraint_names()
    assert {"httpx2", "httpcore2", "truststore"} <= constrained


if __name__ == "__main__":
    test_every_direct_requirement_has_an_exact_constraint()
    test_httpx2_and_its_required_transport_dependencies_are_pinned()
    print("PASS test_every_direct_requirement_has_an_exact_constraint")
    print("PASS test_httpx2_and_its_required_transport_dependencies_are_pinned")
