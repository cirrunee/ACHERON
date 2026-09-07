"""CLI for inspectable static-analysis artifacts. Output files are create-only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .model import AnalysisError, Limits, plain
from .project import CAPABILITIES, open_project
from .pseudocode import cfg_dot, render_with_map


def address(value: str) -> int:
    try:
        result = int(value, 0)
        if not 0 <= result < 1 << 64:
            raise ValueError
        return result
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected a nonnegative 64-bit VA, e.g. 0x140001000") from exc


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="acheron", description="File inspection and static Windows x86/x64 analysis. Never executes input.")
    root.add_argument("--version", action="version", version="ACHERON 0.4.0")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("inspect", "analyze", "functions", "disasm", "decompile", "air", "cfg", "callgraph"):
        command = commands.add_parser(name)
        command.add_argument("input", type=Path, help="Any file for inspect; PE binary or saved project for code analysis")
        command.add_argument("--seed", type=address, action="append", default=[], help="Explicit candidate function VA")
        command.add_argument("--json", action="store_true", help="Emit machine-readable stage results")
        command.add_argument("--output", type=Path, help="Create a new UTF-8 output file")
        command.add_argument("--max-instructions", type=int, default=Limits().max_instructions)
        if name in ("analyze", "inspect"):
            command.add_argument("--project", type=Path, help="Create a reloadable SQLite project")
        if name in ("disasm", "decompile", "air", "cfg"):
            command.add_argument("--function", type=address, required=True)
    commands.add_parser("capabilities")
    return root


def run(args: argparse.Namespace) -> str:
    if args.command == "capabilities":
        return json.dumps(CAPABILITIES, indent=2)
    project = open_project(args.input, seeds=tuple(args.seed), limits=Limits(max_instructions=args.max_instructions), inspect_fallback=args.command == 'inspect')
    function = project.function(args.function) if hasattr(args, "function") else None
    if args.command in ("analyze", "inspect"):
        if args.project:
            project.save(args.project)
        result = project.snapshot()
        if args.command == 'inspect' and not args.json:
            from .report import report_chunks
            return ''.join(report_chunks(project))
        if not args.json:
            instruction_count = sum(len(b.instructions) for f in project.functions for b in f.blocks)
            unsupported = sum(not op.supported for f in project.functions for b in f.blocks for op in b.air)
            lines = [f"ACHERON 0.4.0 | {project.binary['filename']} | {project.image['architecture']}",
                     f"SHA-256: {project.binary['sha256']}",
                     f"Functions: {len(project.functions)} | Instructions: {instruction_count} | Opaque AIR operations: {unsupported}",
                     "Static reconstruction; original source and complete function coverage are not claimed."]
            lines += [f"Note: {d}" for d in project.diagnostics]
            lines += [f"{f.address:#x}: {d}" for f in project.functions for d in f.diagnostics]
            return "\n".join(lines)
    elif args.command == "functions":
        result = [{"address": f.address, "name": f.name, "confidence": f.confidence, "evidence": plain(f.evidence),
                   "blocks": len(f.blocks), "recovery_diagnostics": f.diagnostics} for f in project.functions]
        if not args.json:
            return "\n".join(["ADDRESS             NAME                           CONFIDENCE  BLOCKS",
                             *(f"{f.address:#018x}  {f.name:30.30} {f.confidence:10.2f}  {len(f.blocks)}" for f in project.functions)])
    elif args.command == "disasm":
        result = [plain(i) for b in function.blocks for i in b.instructions]
        if not args.json:
            return "\n".join(f"{i.address:#018x}  {i.raw:30}  {i.text}" for b in function.blocks for i in b.instructions)
    elif args.command == "decompile":
        text, mapping = render_with_map(function)
        result = {"text": text, "source_map": mapping, "diagnostics": function.diagnostics}
        if not args.json:
            return text
    elif args.command == "air":
        result = {"level": "AIR-L", "blocks": [{"address": b.address, "operations": plain(b.air)} for b in function.blocks],
                  "dataflow": function.dataflow}
        if not args.json:
            return "\n".join(f"{op.id}: {op.opcode} {', '.join(o.name or o.kind for o in op.operands)}" for b in function.blocks for op in b.air)
    elif args.command == "cfg":
        result = {"function": function.address, "blocks": [{"address": b.address, "edges": plain(b.edges)} for b in function.blocks]}
        if not args.json:
            return cfg_dot(function)
    else:
        result = project.references
        if not args.json:
            lines = ["digraph calls {"]
            lines += [f'  f{f.address:x} [label="{f.name}\\n{f.address:#x}"];' for f in project.functions]
            for ref in project.references:
                target = f"f{ref['target']:x}" if ref["target"] is not None else f"unknown_{ref['address']:x}"
                lines.append(f'  f{ref["function"]:x} -> {target} [label="{ref["address"]:#x}"];')
            return "\n".join([*lines, "}"])
    return json.dumps(result, indent=2, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        # Validate destinations before potentially creating a project.
        destinations = [getattr(args, key, None) for key in ("output", "project")]
        paths = [p.resolve() for p in destinations if p]
        if len(set(paths)) != len(paths):
            raise AnalysisError("Project and text output paths must differ")
        if any(p.exists() for p in paths):
            raise AnalysisError("Output already exists; choose a new path")
        text = run(args)
        if getattr(args, "output", None):
            with args.output.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(text + "\n")
        else:
            print(text)
        return 0
    except (AnalysisError, OSError, ValueError) as exc:
        print(f"acheron: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
