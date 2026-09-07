import hashlib
import json

import pytest

from acheron import analyze
from .air_oracle import evaluate
from .test_analysis import FIXTURES


def test_fixture_hashes_and_build_provenance():
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    assert manifest["compiler"].startswith("Zig 0.13.0")
    for binary in manifest["binaries"]:
        assert hashlib.sha256((FIXTURES / binary["file"]).read_bytes()).hexdigest() == binary["sha256"]


@pytest.mark.parametrize("optimization", [0, 1])
def test_compiled_add_matches_known_source(optimization):
    project = analyze(FIXTURES / f"known_O{optimization}.exe")
    function = next(f for f in project.functions if f.name == "add_pair")
    for a in (-10000, -1, 0, 1, 1024, 0x70000000):
        for b in (-10, 0, 1, 99):
            assert evaluate(function, a, b) == (a + b) & 0xFFFFFFFF


def test_compiled_conditional_matches_source_on_both_paths_and_boundaries():
    project = analyze(FIXTURES / "known_O0.exe")
    function = next(f for f in project.functions if f.name == "choose")
    values = [-2147483648, -1000, -1, *range(16), 0x7FFFFFFF]
    for x in values:
        expected = x - 3 if x > 4 else x + 7
        assert evaluate(function, x) == expected & 0xFFFFFFFF
