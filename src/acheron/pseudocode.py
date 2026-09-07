"""Render conservative machine-state pseudocode from AIR-L, with source maps.

Output is C-style notation, not compilable C or a recovered source prototype.
Helpers have explicit machine semantics documented in docs/pseudocode.md.
"""
from __future__ import annotations

from .model import Function, Operand
from .x64 import CONDITIONS


def address_expr(operand: Operand) -> str:
    terms = []
    if operand.base:
        terms.append(operand.base)
    if operand.index:
        terms.append(f"{operand.index} * {operand.scale}")
    if operand.displacement or not terms:
        terms.append(str(operand.displacement) if operand.displacement < 0 else hex(operand.displacement))
    expression = " + ".join(terms)
    expression = f"wrap{operand.address_width}({expression})"
    if operand.segment in ("fs", "gs"):
        expression = f"segment_base({operand.segment}) + {expression}"
    return expression


def expr(operand: Operand) -> str:
    if operand.kind == "register":
        if operand.name == operand.parent:
            return operand.name
        return f"bits{operand.width}({operand.parent}, {operand.offset})"
    if operand.kind in ("constant", "address"):
        return hex(operand.value)
    if operand.kind == "memory":
        return f"load{operand.width}({address_expr(operand)})"
    return "unknown_operand()"


def assign(destination: Operand, value: str) -> str:
    if destination.kind == "memory":
        return f"store{destination.width}({address_expr(destination)}, {value});"
    if destination.name == destination.parent:
        return f"{destination.parent} = {value};"
    if destination.width == 32:
        return f"{destination.parent} = zext64({value});"
    return f"{destination.parent} = insert_bits({destination.parent}, {destination.offset}, {destination.width}, {value});"


def render_with_map(function: Function) -> tuple[str, dict[int, list[int]]]:
    flags = 'eflags' if function.bitness == 32 else 'rflags'
    lines = ["/* ACHERON: reconstructed machine-state pseudocode; NOT original source.",
             " * Registers alias state; bitvector helpers preserve widths and flags.",
             " * Prototype, memory types and semantic names remain unknown. */",
             f"void {function.name}(machine_state &state) {{"]
    mapping: dict[int, list[int]] = {}
    if not function.blocks:
        lines.append("    unresolved_entry(state);")
    for block in function.blocks:
        lines.append(f"L_{block.address:x}:")
        for ins, op in zip(block.instructions, block.air, strict=True):
            statements = []
            operands = op.operands
            if op.opcode in ("copy", "load", "store"):
                statements = [assign(operands[0], expr(operands[1]))]
            elif op.opcode == "address":
                # LEA ignores segment bases.
                from dataclasses import replace
                value = f"trunc{operands[0].width}({address_expr(replace(operands[1], segment=''))})"
                statements = [assign(operands[0], value)]
            elif op.opcode in ("add", "sub", "and", "or", "xor"):
                width = operands[0].width
                left, right = expr(operands[0]), expr(operands[1])
                temp = f"t_{ins.address:x}"
                statements = []
                if operands[1].kind == "memory":
                    # A machine memory read occurs once; flags use the same value.
                    source = f"m_{ins.address:x}"
                    statements.append(f"u{width} {source} = {right};")
                    right = source
                statements += [f"u{width} {temp} = {op.opcode}{width}({left}, {right});",
                              f"{flags} = flags_{op.opcode}{width}({flags}, {left}, {right});",
                              assign(operands[0], temp)]
            elif op.opcode in ("compare", "test"):
                helper = "sub" if op.opcode == "compare" else "and"
                statements = [f"{flags} = flags_{helper}{operands[0].width}({flags}, {expr(operands[0])}, {expr(operands[1])});"]
            elif op.opcode == "call":
                target = hex(ins.target) if ins.target is not None else expr(operands[0]) if operands else "unknown_target()"
                statements = [f"call_machine({target}, state); /* unknown prototype/effects */"]
            elif op.opcode == "return":
                adjustment = expr(operands[0]) if operands else "0"
                statements = [f"return_to_caller(state, {adjustment});", "return;"]
            elif op.opcode == "push":
                statements = [f"push{operands[0].width}(state, {expr(operands[0])});"]
            elif op.opcode == "pop":
                temp = f"t_{ins.address:x}"
                statements = [f"u{operands[0].width} {temp} = pop{operands[0].width}(state);", assign(operands[0], temp)]
            elif op.opcode in ("branch", "jump"):
                pass  # Edge rendering below preserves unresolved and external targets.
            elif op.opcode == "nop":
                statements = ["/* nop */"]
            else:
                statements = [f'opaque_instruction("{ins.raw}", state); /* unsupported: {ins.text.replace("*/", "* /")} */']
                if ins.flow == "return":
                    statements.append("unresolved_transfer(state); return;")
            for statement in statements:
                lines.append(f"    {statement} /* {ins.address:#x} */")
                mapping.setdefault(ins.address, []).append(len(lines))
        last = block.instructions[-1]

        def transfer(edge) -> str:
            if edge.internal:
                return f"goto L_{edge.target:x};"
            if edge.target is not None:
                return f"transfer_to({edge.target:#x}, state); return;"
            return "unresolved_transfer(state); return;"

        edge_lines = []
        if last.flow == "branch" and len(block.edges) == 2:
            condition = f"condition_{last.mnemonic[1:]}({flags})" if block.air[-1].opcode == "branch" and last.mnemonic in CONDITIONS else "opaque_branch_decision()"
            edge_lines = [f"if ({condition}) {{ {transfer(block.edges[0])} }}",
                          transfer(block.edges[1])]
        elif block.edges:
            edge_lines = [transfer(block.edges[0])]
        for line in edge_lines:
            lines.append(f"    {line} /* {last.address:#x} */")
            mapping.setdefault(last.address, []).append(len(lines))
    if function.diagnostics:
        lines.append("    /* Recovery limitations:")
        lines.extend(f"     * {d.replace('*/', '* /')}" for d in function.diagnostics)
        lines.append("     */")
    lines.append("}")
    return "\n".join(lines), mapping


def render(function: Function) -> str:
    return render_with_map(function)[0]


def cfg_dot(function: Function) -> str:
    lines = [f'digraph "cfg_{function.address:x}" {{', '  node [shape=box,fontname="Consolas"];']
    for block in function.blocks:
        label = "\\l".join(f"{i.address:x}: {i.text}" for i in block.instructions) + "\\l"
        label = label.replace('"', '\\"')
        lines.append(f'  b{block.address:x} [label="{label}"];')
        for edge in block.edges:
            dest = f"b{edge.target:x}" if edge.internal else f"external_{block.address:x}_{edge.kind}"
            if not edge.internal:
                target = hex(edge.target) if edge.target is not None else "unresolved"
                lines.append(f'  {dest} [label="{target}",style=dashed];')
            lines.append(f'  b{block.address:x} -> {dest} [label="{edge.kind}"];')
    return "\n".join([*lines, "}"])
