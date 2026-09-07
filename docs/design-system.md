# ACHERON product design system

Created by cirrune.

This is a product requirement for ACHERON Base and ACHERON // CHARON. Clarity,
analyst control and traceable evidence take priority over decoration. The shared
implementation lives in `desktop/theme.py`, `primitives.py`, `codeview.py`,
`graph.py` and `presentation.py`. Components use these primitives instead of
independent styles.

## Identity and information hierarchy

ACHERON — Binary Analysis & Decompilation Platform — Created by cirrune.
ACHERON // CHARON — AI-Assisted Binary Investigation Environment — Created by cirrune.
AIR means Acheron Intermediate Representation. CHARON is ACHERON's optional AI
investigation agent. A provider or development tool is not a project creator.

Base hierarchy: function name first; address, signature availability and
claim-specific confidence second; readable code as the dominant work surface;
evidence/references alongside it; effects, data flow and logs disclosed on demand.
The file summary describes the discoveries without competing with the function.

An unknown signature is labeled unknown. Machine-state notation is not passed off
as a recovered ABI. Entry confidence must never be labeled decompilation accuracy.

## Tokens

* UI: Segoe UI, 13 logical pixels; secondary labels 12; function title 20; start
  page title 25. Code: Consolas, 14 logical pixels. Native DPI scaling applies.
* Spacing scale: 4 / 8 / 12 / 16 / 24 logical pixels. Compact rows and toolbars.
* Background #15191f, surface #1b222b, code #121820, text #dde4eb, muted #a2afbd,
  border #34404e, accent #83cfbf, selection #294851.
* KNOWN #95bfe9; INFERRED #dfbd82; HYPOTHESIZED #c1a5e8; UNKNOWN #adb6c2.
  State words are mandatory; color alone never carries meaning. Normal and muted
  text and evidence colors are checked for at least 4.5:1 contrast on their surface.
* Controls have a 3px corner radius. Border use is limited to editable controls,
  table headers and resize boundaries. No gradients, glows or decorative cards.

## Primitives and behavior

| Component | Rule |
|---|---|
| Toolbar/menu | Frequent actions stay visible. File, Navigate, View and Help expose the full command set and shortcuts. |
| Tree/list | Compact rows, stable ordering, visible selection, tooltips for elided values, Enter activates navigable rows. |
| Tabs | Stable ordering; same selected instruction follows across Pseudocode, Assembly and AIR. No analysis recomputation on switching. |
| Context menu | Offers actions for the item clicked: inspect/follow/copy. Unsupported destinations are disabled or explained. |
| Code view | Monospaced text, syntax colors, source-address gutter, normal text selection/copy, wrapped search, original exports retained. |
| Graph | Only real CFG/call edges; pan, zoom, Fit, node navigation and source links. Rendering limits are disclosed. |
| Evidence | Explains the claim, supporting source, affected addresses, scope and limits. Advanced effect sets are collapsed initially. |
| Confidence | Text and score tied to a specific claim. Heuristic entry score is not a probability and not whole-function correctness. |
| Activity | Visible human-readable phase, elapsed time and Cancel. An indeterminate bar makes no fabricated completion percentage. |
| Dialog | Native open/save operations, actionable error text, prior results retained on failure, create-only exports. |
| Panels | Resizable; evidence panel can be hidden from View; log hidden by default and available from toolbar/menu. Session state remains predictable. |
| Empty state | Explains what is absent and offers the next useful action. Never inserts fake findings, functions or statistics. |
| Icons | Small code-native A mark and conventional arrows. All icon actions have descriptive tooltips and accessible names. |

Search preserves the function filter while inspecting a visible match. Following a
destination outside the filter clears it to reveal that destination. Back/Forward
restore the source address and view. Copying code must not be interrupted by
selection synchronization.

## Keyboard contract

| Shortcut | Operation |
|---|---|
| Ctrl+O | Open binary/project |
| Ctrl+S | Save new project |
| Ctrl+E | Export pseudocode |
| Ctrl+K | Find function; Enter inspects first match |
| Ctrl+Home | Inspect PE entry point |
| Ctrl+G | Focus address navigation |
| Ctrl+R | Focus callers/calls; Enter follows selection |
| Ctrl+Enter | Follow selected call/branch |
| Alt+Left / Alt+Right | Back / Forward |
| Alt+1 / 2 / 3 / 4 / 5 | Pseudocode / Assembly / AIR / CFG / Calls |
| Ctrl+F; F3; Shift+F3 | Code search; next; previous |
| Ctrl+Shift+C | Copy source address |
| Ctrl+L | Toggle analysis log |
| F1 | Discover shortcuts |

Default Tab focus navigation, visible focus outlines and native Ctrl+C remain
available. Menus and context menus supplement shortcuts; no essential workflow
depends on remembering one.

## CHARON workflow contract

CHARON 0.3 implements a separate portable investigation edition. It reuses the
tokens, evidence states, code/graph views, menus and navigation behavior. Its
workspace presents selected-function findings and an evidence reader. The user
chooses a local coding model or an OpenAI account model in AI setup.

Selecting a finding shows, in order:

1. **What was found:** concise explanation, affected function/range, evidence state.
2. **Why:** reasoning with explicit evidence references, claim-specific confidence,
   unresolved alternatives and validation status.
3. **What ran:** deterministic pass name/revision and scope, separate from model
   suggestions, plus limits or failed checks.
4. **Evidence:** stable binary hash, source addresses, instruction spans and
   artifact IDs. Evidence opens the exact related code selection.

The user can descend Explanation → Finding → Evidence → Pseudocode → AIR →
Assembly and return with history intact. Every finding retains its evidence links
even when the explanation is simplified. Hypotheses can be accepted/rejected as
annotations but cannot rewrite deterministic artifacts. Missing evidence is shown
as missing; a model claim never masquerades as verified analysis.

Proposed finding record: `id`, `title`, `summary`, `state`, `confidence`,
`confidence_scope`, `reasoning`, `evidence_refs`, `addresses`,
`deterministic_passes`, `validation_status`, `limitations`, `model_provenance`.
CHARON stores these concepts in separate project hypotheses with model/provider,
timestamp, prompt hash, binary hash, resolved evidence rows, input scope, limits
and review state. It has no tool-calling agent or whole-program autonomous loop.

## Workflow quality gates

Automated Qt workflows must exercise: open → entry → pseudocode; find function →
callers → CFG; view switching with source selection; copy/search without losing
selection; navigation history; unknown/unsupported destinations; cancellation and
failure recovery. Inspect normal and compact window renders for clipping and
hierarchy. Packaged-app validation must include the real bundled sample worker.

Test CHARON's finding/evidence descent and return navigation,
including conflicting hypotheses, absent evidence and unvalidated claims. Desktop
tests do not substitute for human analyst usability sessions or a full screen-reader
audit; those remain validation work as the product matures.

## Desktop 0.3 simplification

New installations start in Easy mode. Previously saved mode preferences remain
respected. Open file, Download results and (in CHARON) AI settings are the primary
toolbar actions. Project saving stays in File; specialist exports stay in More.

AI help starts with a preset question and one Explain action. Custom questions
remain visible until another preset is selected. Answers start with an overview;
supporting code and review are disclosed for individual hypotheses. Local model
setup uses one Use this model / Download and use action. Cloud transmission
requires the explicit Send to OpenAI & explain button.

Download results (Ctrl+Shift+S) creates UTF-8 text with a bounded preview, whole-file
or selected-function scope, optional content and cancellable background writing.
It never replaces an existing file and removes a cancelled partial report.
AI summaries, including answers with zero findings, persist separately as
charon-run annotations. Deterministic snapshots remain unchanged.

## Desktop 0.4 file inspection

Open accepts any readable regular file. Windows x86/x64 PE code uses the existing
function workbench. Other formats, malformed PE inputs and budget-limited code
analysis fall back to a File contents workspace with explicit limitations. Code
tabs and function controls are hidden there, rather than showing fake functions.
Text, strings, archive members and bytes are separate inspectable views. Offsets
in this workspace are file byte offsets and never presented as virtual addresses.
AI questions, evidence links and download options adapt to file content.

All parsing stays in the worker. Inspection data is bounded, versioned and saved
in projects. Archive members are never extracted to disk or executed. Unknown
formats remain useful byte/string inspections without a universal-decompiler claim.
