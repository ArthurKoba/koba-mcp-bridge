# Component catalog

| Source module | Runtime service | Responsibility |
| --- | --- | --- |
| `bridge` | `gateway` | OAuth, aggregate routing, dedicated public facades |
| `common` | — | shared runtime/config/secrets, HTTP transport and Git-domain primitives |
| `modules.github` | `github` | GitHub App repository, review, history and Actions capabilities |
| `modules.gitlab` | `gitlab` | GitLab profiles, repositories, merge requests, issues and CI |
| `modules.files` | `files` | immutable object storage, metadata, uploads, collections, references and lifecycle |
| `modules.curl` | `curl` | request preparation, curl execution, response parsing, downloads and stream capture |
| `modules.analysis` | `analysis` | dynamic behavior-analysis facade over the native Ghidra MCP catalog |

The gateway stays small. Provider-specific implementation belongs only to its module.

Shared code belongs in `common` only when it is genuinely provider-neutral and reused.
Ghidra itself is not reimplemented or modified by the Analysis module.
