# CHARON model and runtime provenance

ACHERON // CHARON — AI-Assisted Binary Investigation Environment.
Created by cirrune. Independent model/runtime ownership is preserved.

The catalog uses official Qwen GGUF repositories, pinned revisions and SHA-256
hashes from their published LFS metadata. Downloads are verified before loading.

| Model | Official source | Revision |
|---|---|---|
| Qwen2.5-Coder 1.5B Instruct Q4_K_M | [Qwen](https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF) | f86cb2c1fa58255f8052cc32aeede1b7482d4361 |
| Qwen2.5-Coder 7B Instruct Q4_K_M | [Qwen](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF) | 13fb94bfda8c8cf22497dc57b78f391a9acb426a |
| Qwen2.5-Coder 14B Instruct Q4_K_M | [Qwen](https://huggingface.co/Qwen/Qwen2.5-Coder-14B-Instruct-GGUF) | d0a692ef765eefbf2fabb130b3cb2e8917e3d225 |

All three model cards identify Apache-2.0. Only 7B weights are included in the
full portable package. Other weights download on demand; they are not claimed
to be installed or tested live until that has happened.

CPU and Vulkan runtimes come from the official
[llama.cpp b10809 release](https://github.com/ggml-org/llama.cpp/releases/tag/b10809).
The catalog pins release SHA-256 values. Original MIT and LLVM OpenMP notices are
distributed with the runtime. The local server binds only to 127.0.0.1 and uses
a fresh per-session token. It receives bounded text evidence, not target binaries.

Cloud support uses the official [OpenAI Responses API](https://developers.openai.com/api/docs/guides/text)
and [structured output](https://developers.openai.com/api/docs/guides/structured-outputs),
with account-specific choices from [List models](https://developers.openai.com/api/reference/resources/models/methods/list).
No cloud credentials were supplied for live provider testing. Request construction,
output parsing, host restrictions and no-storage settings are covered by tests.

Each saved hypothesis records model/provider, timestamp, original binary hash,
exact supplied evidence rows, context scope and prompt hash. Reference resolution
is deterministic; the model's interpretation and confidence remain unverified.
