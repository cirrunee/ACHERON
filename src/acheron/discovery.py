"""Multi-signal seeds, bounded recursive traversal, basic blocks and CFG."""
from __future__ import annotations

import heapq
import re

from .interfaces import Architecture
from .model import AnalysisError, Block, Edge, Evidence, Function, Limits, Status
from .pe import PEImage


def safe_name(name: str, address: int) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_]", "_", name)[:128]
    if not candidate or candidate[0].isdigit():
        candidate = f"sub_{address:x}"
    return candidate


class Discovery:
    def __init__(self, image: PEImage, architecture: Architecture, limits: Limits) -> None:
        self.image, self.arch, self.limits = image, architecture, limits
        self.functions: dict[int, Function] = {}
        self.cache = {}
        self.occupied: dict[int, int] = {}
        self.references: set[tuple[int, int, int | None, str]] = set()
        self.diagnostics: list[str] = []
        self.work = 0

    def seed(self, address: int, source: str, confidence: float, name: str = "", end: int | None = None, reference: int | None = None) -> bool:
        if not self.image.executable(address):
            self.diagnostics.append(f"Rejected {source} seed at non-executable address {address:#x}")
            return False
        evidence = Evidence(Status.INFERRED, source, confidence,
                            (address,) if reference is None else (reference, address),
                            "Candidate function entry; boundary recovery is heuristic")
        if address not in self.functions:
            if len(self.functions) >= self.limits.max_functions:
                raise AnalysisError("Function count budget exceeded")
            self.functions[address] = Function(address, safe_name(name, address), [evidence], end, bitness=self.image.bitness)
            return True
        function = self.functions[address]
        if evidence not in function.evidence:
            function.evidence.append(evidence)
        if name:
            function.name = safe_name(name, address)
        if end is not None:
            function.metadata_end = min(function.metadata_end or end, end)
        return False

    def run(self, extra_seeds: tuple[int, ...] = ()) -> list[Function]:
        if self.image.entry:
            self.seed(self.image.entry, "pe-entry", 0.95)
        for export in self.image.exports:
            if export["address"] is not None:
                self.seed(export["address"], "pe-export", 0.98, export["names"][0] if export["names"] else "")
        for start, end, _ in self.image.runtime_functions:
            self.seed(start, "x64-runtime-function", 0.99, end=end)
        for address in sorted(set(extra_seeds)):
            if not self.seed(address, "user-seed", 0.8) and address not in self.functions:
                raise AnalysisError(f"User seed is not executable: {address:#x}")
        pending = list(self.functions)
        heapq.heapify(pending)
        visited = set()
        while pending:
            address = heapq.heappop(pending)
            if address in visited:
                continue
            visited.add(address)
            for target in self._recover(self.functions[address]):
                if target not in visited:
                    heapq.heappush(pending, target)
        # New call seeds can divide earlier traversals. Rebuild once with the final
        # seed set to make function ownership independent of discovery order.
        self.references.clear()
        for function in sorted(self.functions.values(), key=lambda f: f.address):
            self._recover(function, discover_calls=False)
        return sorted(self.functions.values(), key=lambda f: f.address)

    def _recover(self, function: Function, discover_calls: bool = True) -> list[int]:
        function.diagnostics = []
        decoded = {}
        successors: dict[int, list[tuple[int | None, str]]] = {}
        pending = [function.address]
        discovered = []
        while pending:
            address = heapq.heappop(pending)
            if address in decoded:
                continue
            if address != function.address and address in self.functions:
                continue
            if function.metadata_end is not None and not function.address <= address < function.metadata_end:
                continue
            if not self.image.executable(address):
                continue
            if len(decoded) >= self.limits.max_function_instructions:
                raise AnalysisError(f"Instruction budget exceeded in function {function.address:#x}")
            self.work += 1
            if self.work > self.limits.max_flow_steps:
                raise AnalysisError("Traversal work budget exceeded")
            owner = self.occupied.get(address)
            if owner is not None and owner != address:
                function.diagnostics.append(f"Overlapping instruction target at {address:#x}; decode stopped")
                continue
            try:
                ins = self.cache.get(address)
                if ins is None:
                    if len(self.cache) >= self.limits.max_instructions:
                        raise AnalysisError("Global instruction budget exceeded")
                    ins = self.arch.decode(self.image, address)
                    if any(self.occupied.get(b, address) != address for b in range(address, ins.end)):
                        function.diagnostics.append(f"Overlapping instruction at {address:#x}; decode stopped")
                        continue
                    self.cache[address] = ins
                    for b in range(address, ins.end):
                        self.occupied[b] = address
            except AnalysisError as exc:
                if "budget" in str(exc):
                    raise
                function.diagnostics.append(str(exc))
                continue
            if function.metadata_end is not None and ins.end > function.metadata_end:
                function.diagnostics.append(f"Instruction crosses metadata boundary at {address:#x}")
                continue
            decoded[address] = ins
            next_edges = []
            if ins.flow in ("call", "indirect_call"):
                self.references.add((function.address, address, ins.target, ins.flow))
                if ins.target is not None and discover_calls:
                    if self.seed(ins.target, "direct-call", 0.85, reference=address):
                        discovered.append(ins.target)
                next_edges = [(ins.end, "fallthrough")]
                if ins.target is None:
                    function.diagnostics.append(f"Unresolved indirect call at {address:#x}")
            elif ins.flow == "next":
                next_edges = [(ins.end, "fallthrough")]
            elif ins.flow == "branch":
                next_edges = [(ins.target, "true"), (ins.end, "false")]
            elif ins.flow == "jump":
                next_edges = [(ins.target, "jump")]
            elif ins.flow == "indirect_jump":
                next_edges = [(None, "indirect")]
                function.diagnostics.append(f"Unresolved indirect jump at {address:#x}")
            elif ins.flow == "stop":
                next_edges = [(None, "stop")]
                function.diagnostics.append(f"Exceptional/unsupported control transfer at {address:#x}")
            successors[address] = next_edges
            for target, _ in next_edges:
                if target is not None and target not in decoded:
                    heapq.heappush(pending, target)
        leaders = {function.address}
        predecessors: dict[int, set[int]] = {}
        for address, edges in successors.items():
            ins = decoded[address]
            for target, _ in edges:
                if target in decoded:
                    predecessors.setdefault(target, set()).add(address)
                    if ins.flow != "next":
                        leaders.add(target)
        for target, pred in predecessors.items():
            if len(pred) > 1:
                leaders.add(target)
        assigned = set()
        blocks = []
        for start in sorted(decoded):
            if start in assigned:
                continue
            instructions = []
            current = start
            while current in decoded and current not in assigned:
                ins = decoded[current]
                instructions.append(ins)
                assigned.add(current)
                if ins.flow != "next" or ins.end in leaders or ins.end not in decoded:
                    break
                current = ins.end
            last = instructions[-1]
            edges = [Edge(start, target, kind, target in decoded) for target, kind in successors[last.address]]
            for edge in edges:
                if not edge.internal and edge.target is not None:
                    label = "Function boundary transfer" if edge.target in self.functions else "Unresolved/out-of-range edge"
                    function.diagnostics.append(f"{label} at {last.address:#x} to {edge.target:#x}")
            blocks.append(Block(start, instructions, edges, [self.arch.lift(i) for i in instructions]))
        function.blocks = blocks
        function.diagnostics = sorted(set(function.diagnostics))
        return discovered
