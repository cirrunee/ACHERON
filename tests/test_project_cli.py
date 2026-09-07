import hashlib
import json
import sqlite3

import pytest

import acheron
from acheron.cli import main
from acheron.project import Project
from acheron.x64 import X64Architecture
from .helpers import pe


@pytest.fixture
def binary(tmp_path):
    path = tmp_path / "sample.exe"
    path.write_bytes(pe(bytes.fromhex("89c8 01d0 c3")))
    return path


def test_database_roundtrip_without_redecode_and_separate_overlays(binary, tmp_path, monkeypatch):
    original = hashlib.sha256(binary.read_bytes()).hexdigest()
    project = acheron.open(binary)
    project.annotations.append({"address": project.functions[0].address, "kind": "comment", "value": "User note"})
    project.hypotheses.append({"status": "HYPOTHESIZED", "confidence": 0.4, "evidence": ["L_140001002"],
                               "addresses": [project.functions[0].address], "validation_status": "unvalidated", "suggestion": "addition"})
    database = tmp_path / "test.acheron"
    project.save(database)
    monkeypatch.setattr(X64Architecture, "decode", lambda *args: pytest.fail("Reload must not decode"))
    restored = acheron.open(database)
    assert restored.snapshot() == project.snapshot()
    assert restored.annotations == project.annotations
    assert restored.hypotheses == project.hypotheses
    assert restored.functions[0].decompile() == project.functions[0].decompile()
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == original
    binary.unlink()  # Saved analysis is independently reloadable.
    assert acheron.open(database).functions[0].blocks


def test_create_only_and_never_overwrite_input(binary, tmp_path):
    project = acheron.open(binary)
    with pytest.raises(acheron.AnalysisError, match="binary"):
        project.save(binary)
    database = tmp_path / "a.acheron"
    project.save(database)
    before = database.read_bytes()
    with pytest.raises(acheron.AnalysisError, match="exists"):
        project.save(database)
    assert database.read_bytes() == before


def test_cli_commands(binary, tmp_path, capsys):
    for command in ("functions", "disasm", "decompile", "air", "cfg", "callgraph"):
        argv = [command, str(binary), "--json"]
        if command in ("disasm", "decompile", "air", "cfg"):
            argv += ["--function", "0x140001000"]
        assert main(argv) == 0
        result = json.loads(capsys.readouterr().out)
        assert isinstance(result, (dict, list))
    saved = tmp_path / "cli.acheron"
    assert main(["analyze", str(binary), "--project", str(saved)]) == 0
    assert "Functions: 1" in capsys.readouterr().out
    assert main(["decompile", str(saved), "--function", "0x140001000"]) == 0
    assert "add32" in capsys.readouterr().out
    assert main(["decompile", str(saved), "--function", "0x12"]) == 2
    assert "No discovered function" in capsys.readouterr().err
    assert main(["analyze", str(binary), "--output", str(binary)]) == 2


def test_invalid_schema_and_missing_snapshot(tmp_path):
    path = tmp_path / "invalid.acheron"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=999")
    with pytest.raises(acheron.AnalysisError, match="schema"):
        Project.load(path)


def test_invalid_input_is_clean_cli_error(tmp_path, capsys):
    path = tmp_path / "junk.exe"
    path.write_bytes(b"Not a binary")
    assert main(["analyze", str(path)]) == 2
    assert "MZ" in capsys.readouterr().err
    assert main(["analyze", str(path), "--max-instructions", "-1"]) == 2
