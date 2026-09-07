# Third-party components

ACHERON — Binary Analysis & Decompilation Platform. **Created by cirrune.**

This attribution applies to ACHERON's first-party project. Third-party libraries,
algorithms, trademarks and incorporated works retain their respective owners and
license terms. It does not transfer their ownership to cirrune.

| Component | Version used | Role | License/source |
|---|---|---|---|
| iced-x86 | 1.21.0 | x86-64 instruction decoding and effects | MIT; https://github.com/icedland/iced |
| Qt / PySide6 Essentials | 6.8.3 | Desktop widgets and rendering | LGPLv3 option; https://doc.qt.io/qtforpython-6/licenses.html |
| Shiboken | 6.8.3 | Qt Python bindings support | LGPLv3 option; same Qt source distribution |
| Python | 3.12.14 (build runtime) | Bundled interpreter | PSF license; https://www.python.org/downloads/source/ |
| PyInstaller | 6.16.0 | Packaging/bootloader | GPL with bootloader exception; https://pyinstaller.org/en/stable/license.html |
| pytest | 8.3.5 | Development tests; not part of runtime UI | MIT; https://github.com/pytest-dev/pytest |
| Zig / Clang / LLD | Zig 0.13.0 toolchain | Development fixture compilation | Respective toolchain licenses; not included in the portable runtime |
| llama.cpp | b10809 | CHARON CPU and Vulkan inference engines | MIT; https://github.com/ggml-org/llama.cpp/tree/b10809 |
| Qwen2.5-Coder Instruct GGUF | 1.5B, 7B, 14B Q4_K_M | Real local coding models; full CHARON package includes 7B | Apache-2.0; https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF |

The model catalog pins each official revision, byte size and SHA-256 in
`acheron/ai/catalog.json`. Model ownership stays with Qwen; cirrune attribution
does not apply to the weights or runtime. CHARON preserves the original Qwen
Apache-2.0 and llama.cpp MIT texts, plus the runtime's LLVM OpenMP notice.
OpenAI is an optional external API provider, not ACHERON's creator. No cloud
model weights, provider credentials or prearranged API access are bundled.

The build collects original distribution notices under `licenses/`, including the
Python notice, iced-x86 MIT notice and Qt license texts. Qt remains dynamically
linked in `_internal`; no ACHERON license term restricts debugging or replacing
compatible library builds. Source locations are retained in
`docs/third-party-notices.txt`. Do not rewrite notices to name cirrune as their owner.

Public specifications and standard analysis techniques inform the PE parser and
graph/data-flow code. Their documentation, algorithms and trademarks are not
claimed as exclusive ACHERON property. See [provenance](docs/provenance/README.md).
