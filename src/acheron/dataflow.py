"""Conservative register data flow. No memory alias or value claims are made."""
from __future__ import annotations

from collections import deque
from .model import AnalysisError, Function, Limits


def analyze(function: Function, limits: Limits = Limits()) -> dict:
    blocks = {b.address: b for b in function.blocks}
    if not blocks:
        return {"scope": "registers", "liveness": {}, "reaching_in": {}, "use_def": {}, "def_use": {}}
    universe = {r for b in blocks.values() for i in b.instructions for r in (*i.reads, *i.writes)}
    pred = {a: set() for a in blocks}
    succ = {a: set() for a in blocks}
    external = set()
    for block in blocks.values():
        for edge in block.edges:
            if edge.internal:
                if edge.target not in blocks:
                    raise AnalysisError("CFG invariant failed: edge is not a block entry")
                succ[block.address].add(edge.target)
                pred[edge.target].add(block.address)
            else:
                external.add(block.address)
    uses, defs = {}, {}
    for address, block in blocks.items():
        use, defined = set(), set()
        for ins in block.instructions:
            use.update(set(ins.reads) - defined)
            defined.update(ins.writes)
        uses[address], defs[address] = use, defined
    live_in = {a: set() for a in blocks}
    live_out = {a: set() for a in blocks}
    queue = deque(sorted(blocks, reverse=True))
    queued = set(queue)
    steps = 0
    while queue:
        address = queue.popleft()
        queued.remove(address)
        steps += 1
        if steps > limits.max_flow_steps:
            raise AnalysisError("Liveness work budget exceeded")
        out = set(universe) if address in external else set()
        for target in succ[address]:
            out.update(live_in[target])
        incoming = uses[address] | (out - defs[address])
        changed = incoming != live_in[address]
        live_in[address], live_out[address] = incoming, out
        if changed:
            for parent in sorted(pred[address]):
                if parent not in queued:
                    queue.append(parent)
                    queued.add(parent)

    def definition(address: int, reg: str) -> str:
        return f"{address:#x}:{reg}"

    entry = {r: {f"entry:{r}"} for r in universe}
    incoming_defs = {a: {} for a in blocks}
    outgoing_defs = {a: {} for a in blocks}
    queue, queued = deque(sorted(blocks)), set(blocks)
    stored_links = 0
    while queue:
        address = queue.popleft()
        queued.remove(address)
        incoming: dict[str, set[str]] = {}
        if address == function.address:
            incoming = {r: set(v) for r, v in entry.items()}
        for parent in sorted(pred[address]):
            for reg, values in outgoing_defs[parent].items():
                incoming.setdefault(reg, set()).update(values)
        out = {r: set(v) for r, v in incoming.items()}
        for ins in blocks[address].instructions:
            steps += 1
            if steps > limits.max_flow_steps:
                raise AnalysisError("Reaching-definitions work budget exceeded")
            for reg in ins.writes:
                out[reg] = {definition(ins.address, reg)}
        old_count = sum(len(v) for v in incoming_defs[address].values()) + sum(len(v) for v in outgoing_defs[address].values())
        stored_links += sum(len(v) for v in incoming.values()) + sum(len(v) for v in out.values()) - old_count
        if stored_links > limits.max_definition_links:
            raise AnalysisError("Reaching-definitions storage budget exceeded")
        changed = out != outgoing_defs[address]
        incoming_defs[address], outgoing_defs[address] = incoming, out
        if changed:
            for child in sorted(succ[address]):
                if child not in queued:
                    queue.append(child)
                    queued.add(child)
    use_def, def_use = {}, {}
    link_count = 0
    for address, block in blocks.items():
        state = {r: set(v) for r, v in incoming_defs[address].items()}
        for ins in block.instructions:
            for reg in ins.reads:
                use = definition(ins.address, reg)
                sources = sorted(state.get(reg, {f"entry:{reg}"}))
                link_count += len(sources)
                if link_count > limits.max_definition_links:
                    raise AnalysisError("Def-use link budget exceeded")
                use_def[use] = sources
                for source in sources:
                    def_use.setdefault(source, []).append(use)
            for reg in ins.writes:
                state[reg] = {definition(ins.address, reg)}
    return {
        "scope": "conservative parent-register analysis; memory/SSA/value propagation unsupported",
        "liveness": {hex(a): {"in": sorted(live_in[a]), "out": sorted(live_out[a])} for a in sorted(blocks)},
        "reaching_in": {hex(a): {r: sorted(v) for r, v in sorted(incoming_defs[a].items())} for a in sorted(blocks)},
        "use_def": dict(sorted(use_def.items())),
        "def_use": {d: sorted(set(u)) for d, u in sorted(def_use.items())},
        "iterations_work": steps,
    }
