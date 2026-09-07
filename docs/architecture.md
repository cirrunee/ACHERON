# ACHERON architecture decision — v0.1

Status: accepted design, 2026-09-07. Implementation status is tracked in the README.

Desktop follow-up: the user requested a double-clickable application. A PySide6
workbench now wraps the same engine with synchronized source views and graphs.
The PyInstaller portable folder bundles its runtime. `desktop/worker.py` runs
analysis in a QProcess child and communicates through a temporary SQLite artifact
and atomic status JSON. Cancel terminates only this child. The desktop retains
the previous project on failed/cancelled analysis. No UI action executes a target
binary. This is process isolation, not a security sandbox. Advanced AIR-M/AIR-H,
type inference and AI remain future work.

ACHERON reconstructs representations supported by binary evidence. It cannot
recover information erased by compilation and never labels output original source.

## Language and boundaries

Use Python 3.11+ with typed dataclasses and protocols for the first analysis core,
CLI and scripting API. Use the MIT-licensed, Rust-backed iced-x86 decoder, pinned
to 1.21.0. Python offers memory-safe parsing, straightforward graph algorithms,
inspection and a native scripting interface. Its object overhead and GIL are real
limits: enforce budgets, measure before expanding workloads, and move hot passes
to Rust behind the same serialized contracts when justified. Do not implement a
partial home-grown x86 decoder. No native binary is ever loaded as a DLL or run.

## Repository and pipeline

```
src/acheron/
  model.py          evidence, limits, instructions, CFG and AIR records
  interfaces.py     loader, decoder, analysis and future extension protocols
  pe.py             bounded PE32/PE32+ loader and metadata extraction
  x64.py            iced-x86 adapter and conservative AIR-L lifting
  discovery.py      seeds, recursive traversal, blocks, CFG, call references
  dataflow.py       register liveness and reaching definitions
  pseudocode.py     source-mapped C-style rendering from AIR-L
  project.py        orchestration, Python API and SQLite persistence
  cli.py            CLI and JSON/DOT exports
tests/              parser, decoder, transformation and integration tests
fixtures/           redistributable source, compiler recipe and PE fixtures
docs/               architecture, AIR specification, validation and limitations
```

Read-only bytes -> PE image -> x64 instructions -> evidence-backed function seeds
-> recursive traversal -> basic blocks / CFG -> AIR-L -> simple data flow ->
source-mapped pseudocode. Every result is a serializable stage artifact accessible
to clients. Later stages add AIR-M/SSA, type and variable constraints, aggregate
layouts, CFG structuring, semantic hypotheses, AIR-H/AST and a richer renderer.

Function evidence combines entry point, exports, x64 runtime-function records,
explicit user seeds and recursively reached direct-call targets. Executable
mapping gates every seed and decode. Metadata ranges are boundaries, not proof
that a compiler source function has been recovered. No unconditional linear sweep
or prologue speculation by default. Indirect targets, exception edges and
unreachable code are reported as incomplete rather than guessed.

## Contracts and plugins

Loader: bytes + Limits -> Image, or a typed AnalysisError. Decoder: image + VA ->
Instruction, or a diagnostic. Architecture owns register aliases and lifter.
AnalysisPass: immutable input artifacts + context -> a new artifact with revision,
provenance and diagnostics. Exporter consumes records without re-decoding.

Interfaces are Python protocols versioned as API v1; persistence uses plain data,
never pickle. Plugins are explicitly registered by a host, never auto-imported
from the analyzed binary or project. Future loader/architecture/symbol/semantic/UI
extensions negotiate capabilities; missing capability is an error. Python protocol
compatibility is not a stable native ABI. ELF, Mach-O, ARM64, .NET, demangling,
PDB, UI extensions and semantic providers are contracts, not v0.1 implementations.

## Evidence and global knowledge

Use KNOWN (bytes/metadata), INFERRED (deterministic recovery), HYPOTHESIZED
(semantic suggestions) and UNKNOWN. Evidence includes rule/source, addresses,
confidence and explanation; confidence is a heuristic score, not a probability.
Instruction source spans survive lifting and rendering. Function records retain
all seed evidence. A project contains functions, call references, imports, exports
and stage diagnostics, forming the first global knowledge index.

Future type facts form constraints with provenance and conflicts, not a single
mutable guess. Hypotheses live in a separate store with affected addresses,
evidence references, model/version and validation status. They never overwrite
deterministic facts. User annotations are another independent overlay.

## Project database

An `.acheron` project is SQLite, schema version 1. `metadata` stores schema,
engine/decoder versions, binary SHA-256, filename, limits and capabilities.
`artifacts` stores canonical JSON stage snapshots; `annotations` and `hypotheses`
are separate tables. Addresses are JSON integers (not lossy JS floats); UI/IPC
must encode them as hexadecimal strings. No pickle, embedded executable or SQL
from a project is executed. Open existing databases read-only, verify schema and
bound snapshot size. Writes are transactional and initially create-only: no silent
overwrite of a binary or existing project. Reloading artifacts does not reanalyze
or require the binary; reanalysis is an explicit future operation. Source bytes
are identified by hash, while instruction bytes are retained for inspection.

## v0.1 acceptance scope

1. Bounded PE32/PE32+ metadata parsing, raw/virtual mapping, executable sections.
2. AMD64 PE32+ and x86 PE32 static decode, with architecture-specific register
   parents, stack widths, branch targets, address widths and flag state.
3. Entry/export/unwind/user/call seed discovery with provenance and confidence.
4. Recursive blocks, typed normal CFG edges and direct-call graph references.
5. Minimal AIR-L for scalar moves, addresses, arithmetic, flags, memory and
   control flow; unsupported effects remain opaque, inspectable barriers.
6. Fixed-point liveness and reaching definitions with def-use/use-def links;
   conservative register alias and unknown-call handling.
7. Basic source-mapped C-style pseudocode, never advertised as compilable C or
   original source. No unproved high-level structures or semantic names.
8. `analyze`, `functions`, `disasm`, `decompile`, `air`, `cfg` CLI commands;
   JSON snapshots, DOT graphs and reloadable SQLite projects; Python API.
9. Unit, malformed-input, bounded fuzz-smoke and known-source integration tests.

## Hardest components and subsequent milestones

* Sound lifting: partial registers, flags, memory aliasing, SIMD, exceptions and
  ABI effects. Unsupported operations must invalidate dependent reasoning.
* Function boundaries: tail calls, thunks, shared epilogues, indirect jumps,
  embedded data and optimization defeat simple heuristics.
* SSA: dominators, dominance frontiers, phi placement/renaming and irreducible
  graphs are manageable; memory SSA and aliasing are substantially harder.
* Type recovery: conflicting widths, pointer/integer ambiguity, prototypes and
  C++ layouts require constraint provenance and cross-function propagation.
* Structuring: preserve branch semantics, signedness and exceptional edges;
  retain gotos when proof is insufficient. Equivalence checks are needed.
* Semantic reconstruction: useful suggestions need evidence, validation and a
  strict separation from deterministic facts; this begins only after v0.1.

v0.2: expand and validate lifter, dominators/register SSA and stack analysis.
v0.3: memory abstraction, ABI/signature constraints, AIR-M and safe structuring.
v0.4: project migration/incremental analysis, AIR-H and synchronized desktop UI.
AI remains optional and follows a tested deterministic substrate.

## Testing and isolation

Use redistributable tiny known-source PE binaries, recording compiler/version,
flags, hashes and source licensing. Never execute a fixture during analysis or
tests. Verify parser offsets and malformed directories, truncation, overlaps,
virtual-only ranges and resource limits. Check block boundaries, both branch
successors, loops, direct/indirect calls, source mappings, partial-register reads
and effects barriers. Assert liveness and reaching definitions on diamonds and
loops, not just snapshots of implementation output. Check CLI failures and
persistence reload without decoder access. Deterministic seeded mutation is a
smoke test, not a substitute for continuous coverage-guided fuzzing.

Static analysis runs in-process in v0.1 with hard input/count/work budgets.
OS process sandboxing, wall-clock cancellation and dynamic analysis are not yet
implemented. Avoid exposing v0.1 as a public upload service. Future untrusted
plugins/dynamic components require separate processes and explicit capabilities.

## Primary references

* Microsoft PE specification: https://learn.microsoft.com/en-us/windows/win32/debug/pe-format
* iced-x86 Python API and dependency license: https://pypi.org/project/iced-x86/
* Windows x64 ABI: https://learn.microsoft.com/en-us/cpp/build/x64-calling-convention
