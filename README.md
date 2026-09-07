# ACHERON

Binary Analysis & Decompilation Platform

**Created by cirrune.**

Desktop 0.4 opens any readable regular file for bounded inspection: text, strings,
metadata, archive entries and raw bytes. Word/PowerPoint XML text and Excel shared
text can be previewed in ZIP-based Office documents. Windows x86 (32-bit PE32)
and x64 (64-bit PE32+) also get decoding, CFG, AIR and recovered pseudocode.
Other formats use file inspection; this does not claim universal decompilation.
CHARON can explain extracted file content with byte-offset evidence.

Use `acheron inspect FILE --output results.txt` for a plain report from the CLI.
`acheron.open(path, inspect_fallback=True)` enables the same fallback in Python.

Two portable editions are available: **ACHERON Base** and **ACHERON // CHARON**.
Both start in **Easy mode** (formerly Dumbass mode): fewer controls and a plain
language overview. Toggle it in the toolbar or with Ctrl+Shift+D. **Download
results** saves recovered code, extracted file details and AI explanations in one
readable `.txt` file. Choose the whole file or just the selected function.

In CHARON, select **AI help**, choose a ready-made question and click **Explain**.
Read the answer overview, then select a hypothesis for its supporting code.
**Save explanation** downloads a text copy. The included model loads automatically.

The Base desktop uses a compact shared design system: claim-specific entry
confidence, source-address gutters, normal text selection, code search, keyboard
navigation, contextual actions and optional evidence/log panels. Detailed effects
stay available without dominating the primary code view. See
[design system and CHARON workflow](docs/design-system.md),
[third-party components](THIRD_PARTY.md) and [provenance](docs/provenance/README.md).

ACHERON // CHARON — AI-Assisted Binary Investigation Environment — Created by
cirrune. CHARON now performs real, bounded AI investigation of the selected
function. The full portable package includes **Qwen2.5-Coder 7B Instruct Q4_K_M**
and official llama.cpp CPU/Vulkan runtimes. AI settings also downloads verified 1.5B
and 14B coding models, and supports optional OpenAI Responses models with a
session-only API key. Findings retain evidence, model provenance and limitations
as separate hypotheses. [CHARON guide](docs/charon-quickstart.txt).

**To run: double-click `ACHERON Base` or `ACHERON CHARON` in the project folder**,
or open `outputs/ACHERON-Base-0.4/ACHERON.exe` or
`outputs/ACHERON-CHARON-0.4/ACHERON-CHARON.exe`.
Click **Open file** for any readable regular file, or **Explore sample** for a
known-source program. File > Explore 32-bit sample demonstrates x86 support. You can also drag a file into the window.

The portable Windows app bundles Python, Qt and the decoder. It needs no Python
installation, terminal commands or internet connection. Keep the executable with
its `_internal` folder. The separate downloads are
`outputs/ACHERON-Base-Windows.zip` and `outputs/ACHERON-CHARON-Windows.zip`.
CHARON's full ZIP also includes `runtime/` and 4.68 GB of model weights under
`data/models/`. Extract all files to a writable folder before running.

The native desktop interface includes a file picker, searchable function list,
imports/exports, synchronized pseudocode/disassembly/AIR, evidence and data flow,
navigable references, interactive CFG/call graphs, project save/reload and exports.
Analysis runs in a separate process with a working Cancel button.

The automated suite includes desktop integration tests. The packaged executable also
passed its own end-to-end check using the bundled sample and a separate analyzer
process. No target binary is ever executed.

See [desktop instructions](docs/desktop-quickstart.txt). For development, install
`python -m pip install -e ".[desktop,test,build]"`, start the source app with
`python -m acheron.desktop` or `python -m acheron.desktop --charon`.
Fetch the pinned official runtimes with `python tools/fetch_ai_runtime.py`, then
rebuild with `python tools/build_desktop.py --with-model` and package with
`python tools/package_portable.py`. The model-inclusive build requires the 7B model
to be downloaded and verified in source CHARON first; omit `--with-model` to ship
the application with its in-app model downloader instead.

## Analysis engine and CLI

A real, bounded static-analysis foundation for Windows PE/x86 and PE/x64 binaries. It loads
PE metadata, decodes reachable instructions, discovers candidate functions,
builds basic blocks and CFGs, lifts a scalar subset to AIR-L, computes register
data flow and emits conservative, source-mapped C-style pseudocode.

**This is an early analysis engine, not a full source decompiler.** Reconstructed
code is not original source. Unsupported instructions remain explicit opaque
operations. No analyzed binary is executed or modified.

## Install and try it

Python 3.11+ on Windows x64, Linux x64 or macOS with an iced-x86 wheel available.
Windows x64 / Python 3.12 was validated for this delivery; other hosts are untested.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
acheron analyze fixtures/known_O0.exe
acheron functions fixtures/known_O0.exe
acheron disasm fixtures/known_O0.exe --function 0x401020
acheron decompile fixtures/known_O0.exe --function 0x401020
acheron air fixtures/known_O0.exe --function 0x401020 --json
acheron cfg fixtures/known_O0.exe --function 0x401020 --output choose.dot
acheron callgraph fixtures/known_O0.exe --output calls.dot
python -m pytest -q
```

`python -m acheron` is equivalent to the installed `acheron` command. Addresses
are preferred-image virtual addresses, not file offsets or RVAs. The addresses
above refer to the included fixture; use `functions` for another binary.
`--seed 0x...` adds an explicit executable entry. `--max-instructions` changes
the global decode budget. Budget exhaustion is an error with exit code 2.

## Preserve and inspect analysis

```powershell
acheron analyze fixtures/known_O0.exe --project sample.acheron
acheron functions sample.acheron
acheron decompile sample.acheron --function 0x401020 --json
acheron analyze sample.acheron --json --output snapshot.json
acheron capabilities
```

Output files and databases are create-only. Saved projects retain metadata,
functions, instructions, CFGs, AIR, data flow and evidence. Reloading requires no
binary and no instruction decoding. Pseudocode is rendered from saved AIR, and
`decompile --json` includes original-address to output-line mappings. JSON
addresses are integers; JavaScript consumers should convert large addresses with
a lossless JSON parser. DOT is an export; the desktop application also displays
interactive graphs directly from these analysis records.

The `examples/` directory contains generated analysis, CFG, pseudocode and source
mappings for the included unoptimized fixture. Generate a reloadable project with
the `--project` command above.

## Python API

```python
import acheron

project = acheron.open("example.exe")
for function in project.functions:
    print(hex(function.address), function.name, function.confidence)
    print(function.decompile())
    print(function.dataflow["liveness"])
    for block in function.blocks:
        print(block.address, block.edges, block.air)

project.annotations.append({
    "address": project.functions[0].address,
    "kind": "comment",
    "value": "Investigate this function",
})
project.save("example.acheron")
```

`project.references` exposes direct and unresolved indirect call sites. Imports,
exports, sections and runtime-function records are in `project.image`.
`project.snapshot()` returns inspectable stage records. Annotation/hypothesis
overlays persist separately and do not automatically rename or alter facts.

## Scope and limits

| Area | Implemented in this release | Explicitly unsupported |
|---|---|---|
| Loader | Bounded PE32/PE32+ headers, sections, imports, exports, x64 runtime ranges | Relocation application, TLS callback recovery, resources, PDB, CLR interpretation |
| Decoder | iced-x86 x86/AMD64 instruction decoding and effects | ARM64, ELF, Mach-O and managed-code decompilation |
| Discovery | Entry, exports, runtime ranges, user seeds, recursive direct calls | Prologue speculation, jump tables, reliable tail-call or shared-code ownership |
| CFG | Reachable blocks, normal branches, loops, call references, DOT | Exceptional edges, resolved indirect branches, structured loops/switches |
| AIR-L | Scalar copy/load/store/LEA, register arithmetic, comparisons, stack push/pop, calls/branches/returns | Most SIMD/FPU/atomic/privileged operations, memory-destination arithmetic |
| Data flow | Parent-register liveness, reaching definitions, def-use/use-def | SSA, memory aliasing, constants/copies/DCE, stack-variable/type/class recovery |
| Presentation | Native desktop UI, interactive graphs, machine-state pseudocode, CLI, JSON, source mappings, optional CHARON explanations | Source prototypes, semantic variable names, structured AST |

Known metadata and decoded bytes are distinct from inferred function candidates.
Confidence scores rank discovery evidence and are not calibrated probabilities.
Opaque AIR operations and function diagnostics are separate: a CFG can be fully
traversed while containing instructions whose semantic lifting is unsupported.

Default budgets: 64 MiB input, 96 sections, 16,384 metadata entries, 2,048
functions, 100,000 decoded instructions, 8,192 instructions per function,
1,000,000 traversal/data-flow work steps per analysis scope, 1,000,000 definition
links, 128 MiB project file. Python object and intermediate JSON memory can exceed
serialized sizes. The GUI isolates analysis in a cancellable child process; there
is no OS security sandbox or hard RSS/time limit yet.
This release is intended for local research, not an untrusted public upload service.

## Design and validation

* [Architecture, language decision, interfaces, database and roadmap](docs/architecture.md)
* [AIR-L, AIR-M and AIR-H contracts](docs/air.md)
* [Pseudocode helper semantics](docs/pseudocode.md)
* [Validation results and limitations](docs/validation.md)
* [Known fixture source](fixtures/known_source.c), [compiler flags and hashes](fixtures/manifest.json)

The fixtures are MIT-licensed freestanding C compiled with Zig 0.13.0's Clang/LLD
for Windows x64 at O0/O1 and x86 at O0. Rebuild with `python -m pip install ziglang==0.13.0`
then `python fixtures/build.py`. Tests use the included binaries and do not require
the compiler. Fixtures are never loaded or run as native programs. A bounded,
test-only AIR interpreter checks sampled arithmetic and branch behavior against
the known C source; this is not a formal equivalence proof.

ACHERON is MIT licensed. iced-x86 is an external MIT dependency and is installed
from its pinned wheel; the decoder is not vendored.
