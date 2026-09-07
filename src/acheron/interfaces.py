"""API v1 extension contracts; registration is explicit, never project-driven."""
from __future__ import annotations

from typing import Any, Protocol
from .model import AirOp, Instruction, Limits

PLUGIN_API_VERSION = 1


class BinaryImage(Protocol):
    architecture: str
    image_base: int
    entry: int

    def executable(self, address: int) -> bool: ...
    def read_va(self, address: int, size: int) -> bytes: ...
    def code_bytes(self, address: int, maximum: int = 15) -> bytes: ...


class Loader(Protocol):
    def load(self, data: bytes, limits: Limits) -> BinaryImage: ...


class Architecture(Protocol):
    name: str

    def decode(self, image: BinaryImage, address: int) -> Instruction: ...
    def lift(self, instruction: Instruction) -> AirOp: ...


class AnalysisPass(Protocol):
    name: str
    revision: int
    requires: tuple[str, ...]

    def run(self, artifacts: dict[str, Any], limits: Limits) -> dict[str, Any]: ...


class SymbolProvider(Protocol):
    def symbols(self, image: BinaryImage) -> list[dict[str, Any]]: ...


class SemanticModel(Protocol):
    def suggest(self, facts: dict[str, Any]) -> list[dict[str, Any]]:
        """Return hypotheses with confidence/evidence/addresses/validation status."""
        ...


class Exporter(Protocol):
    def export(self, snapshot: dict[str, Any]) -> str | bytes: ...


class Demangler(Protocol):
    def demangle(self, symbol: str) -> str | None: ...


class Decompiler(Protocol):
    def reconstruct(self, function_artifact: dict[str, Any]) -> dict[str, Any]:
        """Return text/AST, source map and unsupported-feature diagnostics."""
        ...


class UIExtension(Protocol):
    def views(self) -> tuple[str, ...]: ...
    def selection_changed(self, address: int, artifact_id: str) -> None: ...
