"""Project orchestration, snapshot schema and separate SQLite persistence."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Callable

from .dataflow import analyze as dataflow
from .discovery import Discovery
from .model import AirOp, AnalysisError, Block, Edge, Evidence, Function, Instruction, Limits, Operand, Status, plain
from .pe import PELoader
from .x64 import X64Architecture, X86Architecture

ENGINE_VERSION = "0.2.0"
SCHEMA_VERSION = 1
CAPABILITIES = {
    "implemented": ["pe32-pe32plus-metadata", "x64-decode", "x86-decode", "file-inspection", "function-discovery", "normal-cfg", "air-l-subset",
                    "register-liveness", "reaching-definitions", "def-use", "machine-state-pseudocode", "sqlite-projects", "desktop-ui"],
    "unsupported": ["arm64-decompilation", "elf-decompilation", "mach-o-decompilation", "dotnet-decompilation", "ssa", "air-m", "air-h", "constant-propagation",
                    "copy-propagation", "dce", "stack-variable-recovery", "type-recovery", "class-recovery", "structured-ast",
                    "jump-tables", "exception-edges", "pdb", "semantic-ai", "dynamic-analysis"],
}


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


@dataclass
class Project:
    binary: dict
    image: dict
    functions: list[Function]
    references: list[dict]
    diagnostics: list[str]
    limits: Limits = field(default_factory=Limits)
    annotations: list[dict] = field(default_factory=list)
    hypotheses: list[dict] = field(default_factory=list)

    def function(self, address: int) -> Function:
        for function in self.functions:
            if function.address == address:
                return function
        raise AnalysisError(f"No discovered function at {address:#x}; use analyze --seed for an explicit entry")

    def snapshot(self) -> dict:
        return {"schema": SCHEMA_VERSION, "engine": ENGINE_VERSION, "decoder": "iced-x86 1.21.0",
                "capabilities": CAPABILITIES, "binary": self.binary, "image": self.image,
                "functions": plain(self.functions), "references": self.references,
                "diagnostics": self.diagnostics, "limits": plain(self.limits)}

    def save(self, path: str | Path) -> None:
        path = Path(path)
        payload = canonical_json(self.snapshot())
        if len(payload.encode("utf-8")) > self.limits.max_project_bytes:
            raise AnalysisError("Project snapshot exceeds byte budget")
        if self.binary.get("path") and path.resolve() == Path(self.binary["path"]).resolve():
            raise AnalysisError("Refusing to write project over analyzed binary")
        _validate_overlays(self.annotations, self.hypotheses)
        # Exclusive creation protects both existing projects and source binaries.
        try:
            with path.open("xb"):
                pass
        except FileExistsError as exc:
            raise AnalysisError(f"Output already exists: {path}") from exc
        try:
            connection = sqlite3.connect(path)
            try:
                with connection:
                    connection.execute("PRAGMA user_version=1")
                    connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                    connection.execute("CREATE TABLE artifacts (stage TEXT PRIMARY KEY, payload TEXT NOT NULL)")
                    connection.execute("CREATE TABLE annotations (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
                    connection.execute("CREATE TABLE hypotheses (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
                    connection.executemany("INSERT INTO metadata VALUES (?, ?)", [("schema", "1"), ("engine", ENGINE_VERSION),
                                           ("sha256", self.binary["sha256"]), ("decoder", "iced-x86 1.21.0")])
                    connection.execute("INSERT INTO artifacts VALUES (?, ?)", ("snapshot", payload))
                    for table, values in (("annotations", self.annotations), ("hypotheses", self.hypotheses)):
                        connection.executemany(f"INSERT INTO {table}(payload) VALUES (?)", [(canonical_json(v),) for v in values])
            finally:
                connection.close()
            if path.stat().st_size > self.limits.max_project_bytes:
                raise AnalysisError("Project database exceeds byte budget")
        except Exception as exc:
            path.unlink(missing_ok=True)
            if isinstance(exc, sqlite3.Error):
                raise AnalysisError(f"Unable to save project: {exc}") from exc
            raise

    @classmethod
    def load(cls, path: str | Path, limits: Limits = Limits()) -> Project:
        path = Path(path)
        if path.stat().st_size > limits.max_project_bytes:
            raise AnalysisError("Project database exceeds byte budget")
        connection = None
        try:
            connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, limits.max_project_bytes)
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            remaining = limits.max_flow_steps

            def progress() -> int:
                nonlocal remaining
                remaining -= 1000
                return int(remaining <= 0)

            connection.set_progress_handler(progress, 1000)
            if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise AnalysisError("Unsupported project schema version")
            tables = dict(connection.execute("SELECT name,type FROM sqlite_schema WHERE name IN ('metadata','artifacts','annotations','hypotheses')"))
            if tables != {name: "table" for name in ("metadata", "artifacts", "annotations", "hypotheses")}:
                raise AnalysisError("Invalid project tables")
            row = connection.execute("SELECT payload FROM artifacts WHERE stage='snapshot' LIMIT 1").fetchone()
            if row is None:
                raise AnalysisError("Project snapshot is missing")
            snapshot = json.loads(row[0])
            project = _restore(snapshot, limits)
            for name in ("annotations", "hypotheses"):
                rows = connection.execute(f"SELECT payload FROM {name} ORDER BY id LIMIT ?", (limits.max_directory_entries + 1,)).fetchall()
                if len(rows) > limits.max_directory_entries:
                    raise AnalysisError("Project overlay count budget exceeded")
                setattr(project, name, [json.loads(r[0]) for r in rows])
            _validate_overlays(project.annotations, project.hypotheses)
            return project
        except AnalysisError:
            raise
        except (sqlite3.Error, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError) as exc:
            raise AnalysisError(f"Invalid project database: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()


def _validate_overlays(annotations: list[dict], hypotheses: list[dict]) -> None:
    for value in annotations:
        if not isinstance(value, dict) or not {"address", "kind", "value"} <= value.keys():
            raise AnalysisError("Annotations require address, kind and value")
    for value in hypotheses:
        required = {"status", "confidence", "evidence", "addresses", "validation_status", "suggestion"}
        if not isinstance(value, dict) or not required <= value.keys() or value["status"] != "HYPOTHESIZED":
            raise AnalysisError("Hypotheses require separate status, confidence, evidence, addresses, validation status and suggestion")
        if not isinstance(value["confidence"], (int, float)) or not 0 <= value["confidence"] <= 1:
            raise AnalysisError("Invalid hypothesis confidence")


def _restore(snapshot: dict, limits: Limits) -> Project:
    if snapshot["schema"] != SCHEMA_VERSION or snapshot["engine"] not in ("0.1.0", ENGINE_VERSION):
        raise AnalysisError("Unsupported project schema/engine; migration required")
    if len(snapshot["functions"]) > limits.max_functions:
        raise AnalysisError("Project function budget exceeded")

    def evidence(value: dict) -> Evidence:
        return Evidence(Status(value["status"]), value["source"], value["confidence"], tuple(value["addresses"]), value["detail"])

    functions = []
    instruction_count = 0
    for value in snapshot["functions"]:
        from .discovery import safe_name
        function = Function(value["address"], safe_name(value["name"], value["address"]), [evidence(e) for e in value["evidence"]], value["metadata_end"])
        function.bitness = value.get('bitness', snapshot['image'].get('bitness', 64))
        if function.bitness not in (32, 64) or function.bitness != snapshot['image']['bitness']:
            raise AnalysisError('Invalid persisted function bitness')
        function.diagnostics, function.dataflow = value["diagnostics"], value["dataflow"]
        seen = set()
        for record in value["blocks"]:
            instructions, air = [], []
            for raw in record["instructions"]:
                instruction_count += 1
                if instruction_count > limits.max_instructions:
                    raise AnalysisError("Project instruction budget exceeded")
                raw = dict(raw)
                raw["operands"] = tuple(Operand(**o) for o in raw["operands"])
                for key in ("reads", "writes", "memory"):
                    raw[key] = tuple(raw[key])
                ins = Instruction(**raw)
                if type(ins.address) is not int or not 0 <= ins.address < 1 << 64 or not 1 <= ins.size <= 15 or len(bytes.fromhex(ins.raw)) != ins.size or ins.address in seen:
                    raise AnalysisError("Invalid persisted instruction")
                seen.add(ins.address)
                instructions.append(ins)
            for raw in record["air"]:
                raw = dict(raw)
                raw["operands"] = tuple(Operand(**o) for o in raw["operands"])
                raw["evidence"] = evidence(raw["evidence"])
                for key in ("reads", "writes", "memory"):
                    raw[key] = tuple(raw[key])
                air.append(AirOp(**raw))
            if not instructions or record["address"] != instructions[0].address or [i.address for i in instructions] != [a.address for a in air]:
                raise AnalysisError("Invalid persisted source mapping")
            function.blocks.append(Block(record["address"], instructions, [Edge(**e) for e in record["edges"]], air))
        starts = {b.address for b in function.blocks}
        if len(seen) > limits.max_function_instructions:
            raise AnalysisError("Project function instruction budget exceeded")
        if len(starts) != len(function.blocks) or any(e.internal and e.target not in starts for b in function.blocks for e in b.edges):
            raise AnalysisError("Invalid persisted CFG")
        functions.append(function)
    # Caller-supplied limits govern reload. Never trust larger stored budgets.
    stored = Limits(**snapshot["limits"])
    bounded = Limits(**{key: min(value, getattr(limits, key)) for key, value in plain(stored).items()})
    return Project(snapshot["binary"], snapshot["image"], functions, snapshot["references"], snapshot["diagnostics"], bounded)


def analyze(path: str | Path, *, limits: Limits = Limits(), seeds: tuple[int, ...] = (), progress: Callable[[str], None] | None = None) -> Project:
    report = progress or (lambda message: None)
    path = Path(path)
    report("Reading binary and validating PE metadata")
    with path.open("rb") as stream:
        data = stream.read(limits.max_file_bytes + 1)
    if len(data) > limits.max_file_bytes:
        raise AnalysisError("Input exceeds file byte budget")
    image = PELoader().load(data, limits)
    if (image.architecture, image.bitness) not in (("x86_64", 64), ("x86", 32)):
        raise AnalysisError(f"Code analysis is unavailable for {image.architecture}/PE{image.bitness}. File inspection is available.")
    if image.directories[14][1]:
        raise AnalysisError(".NET/mixed-mode analysis unsupported in v0.1")
    discovery = Discovery(image, X86Architecture() if image.bitness == 32 else X64Architecture(), limits)
    report(f"Decoding {image.bitness}-bit instructions and recovering functions / control flow")
    functions = discovery.run(seeds)
    for index, function in enumerate(functions):
        report(f"Analyzing data flow · {index + 1}/{len(functions)} functions")
        function.dataflow = dataflow(function, limits)
    metadata = {"architecture": image.architecture, "bitness": image.bitness, "image_base": image.image_base,
                "entry": image.entry, "image_size": image.image_size, "sections": plain(image.sections),
                "imports": image.imports, "exports": image.exports, "runtime_functions": plain(image.runtime_functions),
                "directories": plain(image.directories)}
    references = [{"function": f, "address": a, "target": t, "kind": k} for f, a, t, k in sorted(discovery.references, key=lambda r: (r[0], r[1]))]
    diagnostics = [*image.diagnostics, *discovery.diagnostics]
    if not functions:
        diagnostics.append("No functions recovered; provide --seed for an explicit executable entry")
    return Project({"path": str(path.resolve()), "filename": path.name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()},
                   metadata, functions, references, sorted(set(diagnostics)), limits)


def open_project(path: str | Path, *, inspect_fallback=False, **kwargs) -> Project:
    path = Path(path)
    with path.open("rb") as stream:
        signature = stream.read(16)
    if signature == b"SQLite format 3\0":
        if kwargs.get("seeds"):
            raise AnalysisError("--seed applies to binary analysis, not saved project reload")
        if kwargs.get("progress"):
            kwargs["progress"]("Restoring saved analysis")
        try:
            return Project.load(path, kwargs.get("limits", Limits()))
        except AnalysisError:
            if not inspect_fallback or path.suffix.lower() == '.acheron':
                raise
            from .inspection import inspect_file
            return inspect_file(path, progress=kwargs.get('progress'), limits=kwargs.get('limits', Limits()), reason='SQLite file is not an ACHERON project; showing file inspection.')
    if inspect_fallback:
        from .inspection import inspect_file
        if signature[:2] != b'MZ':
            return inspect_file(path, progress=kwargs.get('progress'), limits=kwargs.get('limits', Limits()))
        try:
            return analyze(path, **kwargs)
        except AnalysisError as exc:
            return inspect_file(path, progress=kwargs.get('progress'), limits=kwargs.get('limits', Limits()), reason=f'Code analysis unavailable: {exc}')
    return analyze(path, **kwargs)
