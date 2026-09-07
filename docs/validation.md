# Validation — ACHERON desktop 0.4 / engine 0.2

The current suite passes **84 cases**. New workflows check whole-file and selected
text reports, content selection, overwrite preservation, cancellation cleanup,
background dialog writing, preset/custom questions, and summary-only AI answers
surviving project reload without changing deterministic artifacts. Normal
(1440×900) and compact (1024×720) views and download previews were inspected.

CHARON additions cover separate persisted
hypotheses, invented evidence IDs, malformed model output, local/cloud payloads,
credential destination and redirect restrictions, resumed downloads, hash failures,
offline model verification, large-function context limits, simple-mode restoration, evidence navigation and
session-only cloud keys. The selected-function excerpt is bounded and has no
local file path. AI never overwrites deterministic artifacts or executes targets.

Live local inference was validated with Qwen2.5-Coder 7B Instruct Q4_K_M through
the official llama.cpp b10809 Vulkan runtime on an RTX 5080 (16 GB). The sample
produced four findings; source navigation and project reload passed. The model's
interpretations are hypotheses, not formally verified semantic recovery. The 1.5B
and 14B options have verified official catalog metadata but were not run live.
No API key was supplied for live OpenAI testing; protocol construction and parsing
are tested independently. Automated Qt checks do not replace human usability or
assistive-technology evaluation.

Both 0.4 portable executables passed their diagnostics. Base covers the real
sample worker and analysis workflow. CHARON additionally passed real packaged
7B inference through its windowed worker pipes, structured findings, artifact
isolation, source navigation, simplified mode and saved-project reload. The new
diagnostics also verify readable text export, the download dialog, default answer
overview and persisted AI run summaries. This validates application behavior,
not model accuracy; the live model can misinterpret branch directions.

The 0.4 checks include a compiled x86 PE32 fixture (five functions and 72
instructions), 32-bit register and stack semantics, partial-register writes,
segmented addresses, and independent AIR evaluation against the included C source.
Native target binaries are never executed. Both x86 and x64 saved projects reload.

Any-file inspection tests cover text, unknown bytes, empty files, image and ELF
headers, malformed PE fallback, UTF-16 strings, archive listings and bounded Office
text previews. File offsets remain distinct from virtual addresses. Scans sample
at most 8 MiB; archives are listed without extracting members to disk. The UI
checks file inspection, byte-offset navigation, background text downloads and
switching back to native code. Packaged CHARON passed real 7B inference for both
x86 code and a text file, with evidence navigation, separate AI artifacts, readable
exports and project reload. Normal and compact rendered views were inspected.

## Previous validation stages

UI/UX and identity revision: **46 cases pass**. The additional workflows verify
keyboard entry-point navigation, function search → callers → CFG, Back/Forward
address and view restoration, source-map-preserving display simplification,
ordinary text selection/copy, code search, compact layout, disclosure defaults,
cirrune attribution and separation of third-party notices. Shared body/secondary
text and evidence-state colors pass automated 4.5:1 contrast checks against all
three standard surfaces. Human analyst sessions and comprehensive assistive-tech
testing remain future work; these automated checks are not presented as those.
The worker also retries brief Windows sharing violations during atomic status
updates; a regression test simulates the UI holding the status file open.
The revised portable executable passed its own sample-worker diagnostic: entry
navigation, Back history, confidence scope, disclosure defaults, cirrune About
attribution, synchronized code, CFG/call graph, export and saved-project reload.
Normal (1440×900), compact (1024×720) and packaged renders were inspected.

The earlier desktop release passed **38 cases**. Five additional Qt integration cases
exercise the real sample worker, synchronized views, call navigation/history,
exports, saved-project reload, failed-input recovery, cancellation cleanup and
Unicode file paths. The Windows portable executable also passed an independent
`--smoke-test` invocation: bundled sample, child-process analysis, 5 functions,
74 instructions, 4 CFG blocks for `choose`, source synchronization, call graph,
pseudocode export and SQLite reload. Screenshots were rendered and inspected for
the welcome page, analysis view and CFG view.

Validated on Windows x64 with Python 3.12.14, iced-x86 1.21.0, pytest 8.3.5 and
fixtures compiled by Zig 0.13.0's Clang/LLD. The original engine suite contained 33
passing cases, including parameterized tests; the current total is 46.

The editable install and built Python wheel were checked. Importing the wheel's
installed package and reopening the saved example project succeeded independently
of source imports. The installed CLI analyzed the O1 fixture and rendered a saved
project. The O0 example contains five functions, 74 instructions and zero opaque
AIR operations; the O1 fixture has 35 instructions and three opaque operations.

## Evidence

* Both compiled fixtures recover five functions, including the four exported
  source functions. O0 conditional and loop CFG shapes are asserted.
* Both optimization levels' `add_pair` AIR agree with known source for 24 input
  pairs each. O0 `choose` agrees for 20 values spanning both paths and signed
  boundaries. This evaluates an independent bounded AIR model in Python, never
  native machine code. Optimized conditional-move lifting remains unsupported.
* Synthetic instruction fixtures check diamond joins, backedges, recursive call
  discovery, unknown-call clobbers, indirect jumps, overlapping instructions,
  register widths, partial writes, RIP-relative loads and opaque SIMD effects.
* Liveness and reaching-definition assertions use known graph answers. Generated
  pseudocode includes width/flag semantics and valid source mappings.
* Parser tests cover PE32/PE32+, virtual-only tails, bounds, overlaps, metadata,
  certificate file offsets, all 2,048 truncation points of a synthetic PE and
  500 deterministic byte-mutation cases with bounded metadata work.
* CLI tests exercise every primary artifact, JSON, error handling and create-only
  output. SQLite tests verify binary hashes remain unchanged, snapshots roundtrip,
  overlays stay separate, no decoder call occurs on reload and the source binary
  is unnecessary for saved analysis.

The included example exports are generated from the actual engine. Reproduce
verification with `python -m pytest -q` from the repository root after installation.

## What these checks do not establish

This corpus is intentionally small. It does not establish coverage of commercial
applications, hostile packers, arbitrary compiler optimizations, all PE variants,
full x86 semantics or original-source recovery. Mutation testing is fuzz smoke,
not coverage-guided fuzzing or a security audit. No formal equivalence proof,
whole-program alias analysis, SSA or type recovery exists yet. Future work
should add compiler/version diversity, continuous fuzzing, performance baselines,
independent decoder differential tests and a substantially wider lifter oracle.

## Primary design references

* Microsoft PE format: https://learn.microsoft.com/en-us/windows/win32/debug/pe-format
* iced-x86 decoder and metadata: https://pypi.org/project/iced-x86/

The implementation uses these specifications and APIs; tests and confidence
scores do not elevate inferred function boundaries into guaranteed facts.
