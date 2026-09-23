# Component catalog

| Source module | Runtime service | Responsibility |
| --- | --- | --- |
| `bridge` | `gateway` | OAuth, aggregate routing, dedicated public facades |
| `common` | — | shared runtime helpers and Infisical resolver |
| `modules.github` | `github` | GitHub App development and reviewer workflows |
| `modules.gitlab` | `gitlab` | GitLab profiles, repositories, MRs and CI |
| `modules.files` | `files` | immutable Files storage, uploads, collections and references |
| `modules.curl` | `curl` | HTTP requests, downloads and stream capture |
| `modules.analysis` | `analysis` | analysis adapter over Files and native Ghidra |

The gateway stays small. Provider-specific implementation belongs only to its module.
Shared code belongs in `common` only when it is genuinely provider-neutral.
