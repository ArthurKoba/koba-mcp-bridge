# Component catalog

| Package / service | Ownership | External dependencies |
| --- | --- | --- |
| `mcp_bridge` / gateway | OAuth, aggregate routing, dedicated public facades | Infisical, private MCP runtimes |
| `mcp_common` | runtime annotations/helpers, Infisical resolver | Infisical |
| `github_mcp` | GitHub App development + independent reviewer workflows | GitHub, Infisical |
| `gitlab_mcp` | GitLab account/profile routing, repositories, MRs, CI | GitLab, Infisical |
| `files_mcp` | immutable Files storage, uploads, collections, references | `files-data` volume |
| `http_mcp` | HTTP requests, downloads and stream capture | Internet, `files-data` |
| `analysis_mcp` | analysis/recovery adapter workflows | `files-data`, native Ghidra MCP |
| native Ghidra | upstream/native reverse-engineering backend | Ghidra workers/projects |

## Boundary rules

`mcp_bridge` must stay small. Provider clients and provider-specific policy are not
gateway responsibilities.

`mcp_common` must stay provider-neutral. It currently owns only shared runtime
primitives and secret resolution.

Files are the shared persistent data plane. GitHub/GitLab provider credentials are
resolved from Infisical rather than copied into Coolify provider-specific variables.

The raw Ghidra service remains unchanged. `analysis_mcp` translates between the Files
model and native Ghidra staging/import/export contracts.
