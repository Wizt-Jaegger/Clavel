# E0002 · Provider and runtime discovery

Source revision `eeb62d368ef35091d7c0033d926a4bed93d159b8`.
The [E0002 execution log](../log/CODEX_LOG.md) records the discovery commands.

| Evidence | Sanitized result | Scope |
| --- | --- | --- |
| `ollama --version` | `0.40.13` | Live discovery host CLI |
| Loopback HTTP `GET /api/version` | `{"version":"0.40.13"}` | Live discovery host service, request sent without credentials |
| `ollama list` with `OLLAMA_HOST` unset | `qwen2.5-coder:1.5b`, `qwen2.5-coder:3b`, `qwen2.5-coder:7b`, `qwen2.5-coder:14b`, `qwen2.5:latest`, `qwen:0.5b` | Live local inventory, with tags reported as installed |

The tracked-source search at the revision above returned no Jeff, Ollama, or
Qwen matches in the searched files. The search excluded logs, agent
instructions, and automation patches.

| Open fact | Status | Evidence needed |
| --- | --- | --- |
| Jeff accountable owner | Unresolved | Owner confirmation from the project |
| Jeff provider and target environment | Unresolved | Owner-approved provider and environment identification |
| Jeff API and protocol version | Unresolved | Provider documentation or a sanitized protocol and version response |
| Jeff authentication | Unresolved | Documented authentication scheme and access requirements |
| Intended Ollama target and its version | Unresolved | Confirmation of target identity and a sanitized version check there |
| Qwen tag approved for use and available on that target | Unresolved | Owner-approved tag and matching `ollama list` evidence from the target |

Next step is to obtain the owner and provider evidence, then verify the runtime
version and selected model on the confirmed target.
