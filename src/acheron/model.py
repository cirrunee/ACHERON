"""Versioned, JSON-compatible stage records. All addresses are virtual addresses."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class AnalysisError(ValueError):
    """Malformed input, unsupported capability or exhausted resource budget."""


class Status(str, Enum):
    KNOWN = "KNOWN"
    INFERRED = "INFERRED"
    HYPOTHESIZED = "HYPOTHESIZED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Evidence:
    status: Status
    source: str
    confidence: float
    addresses: tuple[int, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class Limits:
    max_file_bytes: int = 64 * 1024 * 1024
    max_sections: int = 96
    max_directory_entries: int = 16384
    max_functions: int = 2048
    max_instructions: int = 100000
    max_function_instructions: int = 8192
    max_flow_steps: int = 1000000
    max_definition_links: int = 1000000
    max_project_bytes: int = 128 * 1024 * 1024

    def __post_init__(self) -> None:
        if any(type(v) is not int or v <= 0 for v in asdict(self).values()):
            raise AnalysisError("All resource limits must be positive integers")


@dataclass(frozen=True)
class Operand:
    kind: str
    width: int = 0
    name: str = ""
    parent: str = ""
    offset: int = 0
    value: int = 0
    base: str = ""
    index: str = ""
    scale: int = 1
    displacement: int = 0
    segment: str = ""
    address_width: int = 64
    text: str = ""


@dataclass(frozen=True)
class Instruction:
    address: int
    size: int
    raw: str
    text: str
    mnemonic: str
    operands: tuple[Operand, ...]
    flow: str
    target: int | None
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    memory: tuple[str, ...]
    opaque_prefix: bool = False

    @property
    def end(self) -> int:
        return self.address + self.size


@dataclass(frozen=True)
class AirOp:
    id: str
    address: int
    opcode: str
    operands: tuple[Operand, ...]
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    memory: tuple[str, ...]
    supported: bool
    evidence: Evidence
    detail: str = ""


@dataclass(frozen=True)
class Edge:
    source: int
    target: int | None
    kind: str
    internal: bool


@dataclass
class Block:
    address: int
    instructions: list[Instruction]
    edges: list[Edge] = field(default_factory=list)
    air: list[AirOp] = field(default_factory=list)


@dataclass
class Function:
    address: int
    name: str
    evidence: list[Evidence]
    metadata_end: int | None = None
    blocks: list[Block] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    dataflow: dict[str, Any] = field(default_factory=dict)
    bitness: int = 64

    @property
    def confidence(self) -> float:
        return max((e.confidence for e in self.evidence), default=0.0)

    @property
    def complete(self) -> bool:
        return not self.diagnostics

    def decompile(self) -> str:
        from .pseudocode import render
        return render(self)


def plain(value: Any) -> Any:
    """Convert a dataclass tree to deterministic JSON-compatible records."""
    if hasattr(value, "__dataclass_fields__"):
        return plain(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value
