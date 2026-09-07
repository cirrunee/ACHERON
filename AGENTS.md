# ACHERON project conventions

The canonical public creator/owner identity is **cirrune**. Use "Created by
cirrune" or "Copyright © cirrune". Never infer author identity from OS accounts,
Git settings, development tools or AI providers. Preserve independent third-party
copyright/license notices. Maintain THIRD_PARTY.md and docs/provenance/.

Product family:
* ACHERON — Binary Analysis & Decompilation Platform.
* ACHERON // CHARON — AI-Assisted Binary Investigation Environment.
* AIR — Acheron Intermediate Representation.
* CHARON — ACHERON's optional AI investigation agent.

Use the shared desktop tokens/primitives and docs/design-system.md. Prioritize
code readability, dense but coherent layouts, keyboard access, predictable
navigation and progressive disclosure. Avoid decorative cards, giant headlines,
unnecessary badges, chatbot-dominated layouts and invented analysis results.

Show KNOWN, INFERRED, HYPOTHESIZED and UNKNOWN distinctly. Confidence applies to
the specific claim and is not a calibrated probability. AI hypotheses cannot
overwrite deterministic evidence. Keep unsupported features explicit.

Test workflows and inspect rendered desktop views at normal and compact sizes.
Build and check the portable executable when changing the application. Never
execute analyzed binaries. Fixtures are compiled from the included MIT source.
