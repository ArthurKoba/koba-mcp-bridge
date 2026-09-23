# Status and remaining work

## Completed

- self-hosted Infisical bootstrap and provider credential conventions;
- independent GitHub, GitLab, Files, HTTP and Analysis runtime services;
- provider code separated into dedicated Python packages;
- thin `mcp_bridge` gateway package;
- shared provider-neutral `mcp_common` package;
- full Files terminology and production SQLite/data migration;
- one production `docker-compose.yaml` at repository root;
- persistent `files-data` and `fastmcp-data` volumes;
- native Ghidra kept outside this repository and consumed through the analysis boundary.

## Remaining

### Analysis vocabulary

The runtime boundary exists, but the current analysis tools still expose some
Ghidra-oriented names. Replace those client-facing names with domain analysis/recovery
vocabulary while keeping the native Ghidra MCP contract unchanged internally.

### Production acceptance

After the modular stack is deployed, verify every dedicated public surface, persistent
Files reads/uploads, GitHub development/reviewer operations, GitLab discovery, HTTP
Files integration, OAuth persistence and analysis-to-Ghidra connectivity.

## Rule

Do not put provider implementation back into `mcp_bridge`. New integrations must get
their own runtime/package or use a genuinely shared primitive from `mcp_common`.
