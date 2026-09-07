"""Readable, portable exports of analysis and separately labeled AI hypotheses."""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class ReportOptions:
    function_address: int | None = None
    code: bool = True
    metadata: bool = True
    ai: bool = True
    instructions: bool = False


class ReportCancelled(Exception):
    pass


def report_chunks(project, options=ReportOptions()):
    """Yield one section at a time; never change the project or read its source file."""
    if project.image.get('kind') == 'file':
        yield from inspection_report(project, options)
        return
    functions = project.functions if options.function_address is None else [project.function(options.function_address)]
    hypotheses = list(project.hypotheses)
    runs = [a['value'] for a in list(project.annotations) if a.get('kind') == 'charon-run' and isinstance(a.get('value'), dict)]
    yield (f"ACHERON — Analysis report\nCreated by cirrune\n\n"
           f"File: {project.binary['filename']}\nSHA-256: {project.binary['sha256']}\n"
           f"Scope: {'Whole file' if options.function_address is None else 'Selected function ' + hex(options.function_address)}\n"
           f"Functions included: {len(functions)}\n\n"
           "HOW TO READ THIS FILE\n"
           "KNOWN = read from the file. INFERRED = reconstructed by static analysis.\n"
           "HYPOTHESIZED = an AI interpretation, not verified. UNKNOWN = not recovered.\n"
           "Recovered code is pseudocode, not the original source or a runnable program.\n"
           "Static analysis may miss code and behavior. Input files are never executed.\n\n")
    if options.metadata:
        yield (f"EXTRACTED FILE DETAILS — KNOWN\nSize: {project.binary.get('size', 'unknown')} bytes\n"
               f"Architecture: {project.image.get('architecture', 'unknown')}\n"
               f"Entry address: {project.image.get('entry', 0):#x}\n\n")
        for key in ('sections', 'imports', 'exports'):
            rows = project.image.get(key, [])
            yield key.upper() + f" ({len(rows)})\n"
            for row in rows:
                yield "  " + "; ".join(f"{k}: {v}" for k, v in row.items()) + "\n"
            if not rows:
                yield "  None recorded.\n"
            yield "\n"
        yield "DISCOVERED FUNCTIONS — INFERRED\n"
        for function in functions:
            yield f"  {function.address:#x}  {function.name}\n"
        yield "\n"
    for function in functions:
        yield f"{'=' * 64}\nFUNCTION: {function.name} at {function.address:#x}\n"
        yield (f"INFERRED entry evidence: {function.confidence * 100:.0f}/100 (heuristic, not decompilation accuracy).\n"
               "UNKNOWN: original variable names, types and signature.\n")
        for diagnostic in function.diagnostics:
            yield f"Analysis limit: {diagnostic}\n"
        if options.code:
            yield "\nRECOVERED CODE — INFERRED\n" + function.decompile() + "\n"
        if options.instructions:
            yield "\nDECODED INSTRUCTIONS — original bytes with inferred instruction boundaries\n"
            for block in function.blocks:
                for instruction in block.instructions:
                    yield f"  {instruction.address:#x}  {instruction.raw}  {instruction.text}\n"
        if options.ai:
            findings = [f for f in hypotheses if f.get('function_address') == function.address and f.get('binary_sha256') == project.binary['sha256']]
            answers = [r for r in runs if r.get('function_address') == function.address and r.get('binary_sha256') == project.binary['sha256']]
            yield "\nAI EXPLANATIONS — HYPOTHESIZED, NOT VERIFIED\n"
            if not findings and not answers:
                yield "No AI explanation has been generated for this function.\n"
            seen = set()
            for answer in [*answers, *findings]:
                key = answer.get('run_id') or answer.get('summary', '')
                if key in seen:
                    continue
                seen.add(key)
                yield (f"\nModel: {answer.get('model', 'unknown')} ({answer.get('provider', 'unknown')})\n"
                       f"Generated: {answer.get('created_at', 'unknown')}\n"
                       f"Question: {answer.get('question', 'Not recorded')}\n"
                       f"{answer.get('summary', '')}\n")
                for limit in answer.get('limitations', []):
                    yield f"Limit: {limit}\n"
            for finding in findings:
                yield (f"\nHypothesis: {finding.get('title', 'Untitled')}\n{finding.get('suggestion', '')}\n"
                       f"Model confidence: {finding.get('confidence_label', 'unknown')} (uncalibrated, not a probability).\n"
                       f"Review: {finding.get('review', 'unreviewed')}\n"
                       f"Evidence check: {finding.get('validation_status', 'unknown')} — interpretation not verified.\n")
                for row in finding.get('evidence', []):
                    yield f"  {row.get('id', '?')}  {row.get('address', '?')}  {row.get('assembly', '')}\n"
                if not finding.get('evidence'):
                    yield "  No valid instruction evidence linked.\n"
                for ref in finding.get('unresolved_evidence', []):
                    yield f"  Unresolved model citation: {ref}\n"
                yield f"Model: {finding.get('model', 'unknown')}; prompt SHA-256: {finding.get('prompt_sha256', 'unknown')}\n"
        yield "\n"
    if project.diagnostics:
        yield "FILE ANALYSIS LIMITS\n" + "\n".join(str(d) for d in project.diagnostics) + "\n"


def inspection_report(project, options):
    data = project.image['inspection']
    yield f"ACHERON — File inspection report\nCreated by cirrune\n\nFile: {project.binary['filename']}\nSHA-256: {project.binary['sha256']}\nScope: Whole file inspection\nFormat: {data['format']}\n\n"
    yield 'KNOWN = extracted content. HYPOTHESIZED = AI interpretation, not verified.\nNo code was decompiled in this file inspection. Original file content was never executed.\n\n'
    if options.metadata:
        yield 'FILE DETAILS\n' + '\n'.join(f'{k}: {v}' for k, v in data.get('properties', {}).items()) + '\n\n'
        if data.get('entries'):
            yield 'ARCHIVE CONTENTS — listed, not executed or unpacked to disk\n'
            for row in data['entries']:
                yield f"{row['name']} | {row['size']} bytes | compressed: {row['compressed']} | encrypted: {row['encrypted']}\n"
            yield '\n'
    if options.code:
        yield 'READABLE TEXT — bounded extracted preview\n' + (data.get('text') or 'No readable text extracted.') + '\n\n'
        yield 'EXTRACTED STRINGS — file byte offsets, not virtual addresses\n'
        for row in data.get('strings', []):
            yield f"{row['offset']:#x} | {row['encoding']} | {row['text']}" + (' [shortened]' if row.get('truncated') else '') + '\n'
        yield '\n'
    if options.instructions:
        yield 'RAW BYTES — first 64 KB at most\n'
        raw = bytes.fromhex(data.get('hex', ''))
        for offset in range(0, len(raw), 16):
            yield f'{offset:08x}  ' + raw[offset:offset + 16].hex(' ') + '\n'
    if options.ai:
        yield '\nAI EXPLANATIONS — HYPOTHESIZED, NOT VERIFIED\n'
        answers = [a['value'] for a in list(project.annotations) if a.get('kind') == 'charon-run' and isinstance(a.get('value'), dict) and a['value'].get('function_address') is None and a['value'].get('binary_sha256') == project.binary['sha256']]
        findings = [f for f in list(project.hypotheses) if f.get('function_address') is None and f.get('binary_sha256') == project.binary['sha256']]
        seen = set()
        for answer in [*answers, *findings]:
            key = answer.get('run_id') or answer.get('summary', '')
            if key in seen:
                continue
            seen.add(key)
            yield f"\nModel: {answer.get('model', 'unknown')} ({answer.get('provider', 'unknown')})\nQuestion: {answer.get('question', 'not recorded')}\n{answer.get('summary', '')}\n"
            for limit in answer.get('limitations', []):
                yield f'Limit: {limit}\n'
        for finding in findings:
            yield f"\nHypothesis: {finding.get('title', '')}\n{finding.get('suggestion', '')}\nModel confidence: {finding.get('confidence_label', 'unknown')} (uncalibrated)\nReview: {finding.get('review', 'unreviewed')}\n"
            for row in finding.get('evidence', []):
                yield f"  {row['id']} | file offset {row['address']} | {row['assembly']}\n"
            for ref in finding.get('unresolved_evidence', []):
                yield f'Unresolved model citation: {ref}\n'
            yield f"Model: {finding.get('model', 'unknown')}; prompt SHA-256: {finding.get('prompt_sha256', 'unknown')}\n"
        if not answers and not findings:
            yield 'No AI explanation generated.\n'
    yield '\nINSPECTION LIMITS\n' + '\n'.join(project.diagnostics) + '\n'


def write_report(project, destination, options=ReportOptions(), cancelled: Callable[[], bool] = lambda: False):
    path = Path(destination)
    # Exclusive creation protects source binaries, previous exports and saved projects.
    stream = path.open('x', encoding='utf-8', newline='\n')
    try:
        with stream:
            for chunk in report_chunks(project, options):
                if cancelled():
                    raise ReportCancelled()
                stream.write(chunk)
            if cancelled():
                raise ReportCancelled()
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path
