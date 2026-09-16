# koba-mcp-bridge

Extensible MCP gateway for AI agents, local tools, isolated compute workers, development automation, and reverse-engineering workflows.

## Purpose

`koba-mcp-bridge` is the single authenticated MCP entry point for tools and workloads running on user-owned infrastructure.

The project is designed around a few core ideas:

- expose local and self-hosted tools through one MCP endpoint;
- aggregate other MCP servers behind a single OAuth boundary;
- keep long-running or compute-heavy work outside the chat process;
- persist task state, logs, artifacts, and errors so work can survive interrupted sessions;
- isolate workers and constrain CPU, memory, storage, network, and filesystem access;
- make integrations modular so new development and analysis tools can be added over time.

## Architecture

```text
AI client / MCP client
        |
        | OAuth + MCP
        v
koba-mcp-bridge
        |
        +-- local bridge_* tools
        +-- github_agent_* -> GitHub App installation API
        +-- ghidra_* -> optional Ghidra MCP backend
        +-- future mounted MCP backends
        +-- task/state management
        +-- workers / artifacts / automation
```

Mounted MCP backends are optional. The public bridge starts normally when none are configured. FastMCP proxy providers connect lazily, so a temporarily unavailable backend does not prevent the gateway itself from starting.

## Ghidra backend

Set the runtime variable below to mount an internal Ghidra MCP server:

```text
GHIDRA_MCP_URL=http://ghidra-mcp:8081/mcp
```

The mounted backend is namespaced as `ghidra`, so its tools are exposed through the public gateway with `ghidra_` prefixes. Ghidra itself does not need to be exposed publicly; it should share a private Docker network with this bridge.

## GitHub OAuth

OAuth is disabled by default so a deployment can be upgraded before credentials are configured. When `OAUTH_ENABLED=true`, the bridge requires all of the following runtime environment variables:

- `OAUTH_GITHUB_CLIENT_ID`
- `OAUTH_GITHUB_CLIENT_SECRET`
- `OAUTH_JWT_SIGNING_KEY`
- `OAUTH_ALLOWED_GITHUB_USERS`

The public OAuth base URL defaults to:

```text
https://mcp.koba-nexus.ru
```

and can be changed with `OAUTH_BASE_URL`.

The GitHub OAuth application callback URL is:

```text
https://mcp.koba-nexus.ru/auth/callback
```

OAuth client registrations and token state are stored below `FASTMCP_HOME`, which defaults to `/data/fastmcp` in the container. Production deployments should mount `/data/fastmcp` as persistent storage before enabling OAuth.

Secrets belong in runtime environment variables or the deployment secret store. They must not be committed to the repository or injected at image build time.

## GitHub App development backend

The `github_agent_*` tools authenticate as a GitHub App installation. Automated repository activity is therefore attributed to the app identity rather than the human account used to log into the MCP bridge.

Required runtime variables:

```text
GITHUB_AGENT_APP_ID=<GitHub App numeric App ID>
GITHUB_AGENT_PRIVATE_KEY_B64=<base64-encoded GitHub App private key PEM>
GITHUB_AGENT_ALLOWED_REPOSITORIES=ArthurKoba/koba-mcp-bridge,ArthurKoba/anjia-ajl33pq0866-fh8626v100-reverse
```

`GITHUB_AGENT_PRIVATE_KEY` can be used instead of the base64 form when the deployment system can safely store multiline PEM values. The allowlist is mandatory and intentionally does not support `*`.

Repository access is gated twice: the GitHub App installation must include the repository and the repository must also appear in `GITHUB_AGENT_ALLOWED_REPOSITORIES`.

### Workflow policy

The bridge has an additional development policy layer:

```text
GITHUB_AGENT_PROTECTED_BRANCHES=main,master
GITHUB_AGENT_REQUIRED_CHECKS=test,docker
```

Both variables are optional; the values above are the defaults.

Direct file writes, deletes, atomic commits, fast-forwards, branch deletion, and branch renames are rejected for protected branches. Work is expected to happen on feature branches and reach a protected branch through a pull request.

Pull requests are restricted to branches inside the same allowlisted repository. `owner:branch` / fork heads are rejected by the bridge, so the agent cannot use this backend for external contribution PRs.

PR merge supports `merge`, `squash`, and `rebase`. Before merging, every name in `GITHUB_AGENT_REQUIRED_CHECKS` must have a completed successful check-run on the PR head SHA.

### Development surface

Core repository/files:

- repository installation/status checks;
- UTF-8 file read/write/delete;
- directory listing;
- binary file read/write using base64;
- repository-scoped code search;
- atomic multi-file commits through Git Data blobs/trees/commits;
- optimistic branch-head verification with `expected_head_sha`.

Branches, commits, and tags:

- branch list/create/delete/rename;
- non-force fast-forward of non-protected branches;
- ref comparison;
- commit history filtered by ref/path;
- individual commit metadata, patches, and changed-file statistics;
- lightweight and annotated tag creation;
- tag list/delete.

Pull requests and review:

- list/read/create/update same-repository PRs;
- changed-file patches;
- conversation comments;
- submitted review list;
- review submission (`COMMENT`, `APPROVE`, `REQUEST_CHANGES`);
- update a PR branch from its base;
- check-run inspection and required-check validation;
- merge with `merge`, `squash`, or `rebase` after required checks pass.

Issues and CI:

- list/read/create/update issues;
- issue comments;
- GitHub Actions workflow-run listing;
- workflow job listing.

### GitHub App permissions

For the full workflow, configure the GitHub App with only the repositories that agents are allowed to modify and grant:

- **Contents: Read and write** — files, Git Data objects, refs, tags;
- **Pull requests: Read and write** — PR lifecycle, reviews, merge;
- **Issues: Read and write** — issue lifecycle and comments;
- **Actions: Read-only** — workflow runs/jobs;
- **Checks: Read-only** — required-check gating.

Do not grant organization/administration permissions to the app unless a later feature explicitly requires them. Branch/ruleset administration should remain a human-controlled GitHub setting.

A review submitted by the same GitHub App identity is not an independent reviewer identity. If branch protection is configured to require an independent approving review, use a separate reviewer GitHub App or a human reviewer identity; a separate ChatGPT conversation alone does not change the GitHub actor identity.

## Browser MCP GitHub write probe

The bridge still contains the narrow `github_write_probe` mutation tool that was used to verify browser ChatGPT write-action support. It writes only to a server-configured probe repository/branch. Once the GitHub App backend has been fully validated in production, remove `GITHUB_WRITE_PROBE_TOKEN` and retire this temporary tool.

## Project status

The bridge is operational as an authenticated MCP gateway with Ghidra and GitHub App development workflows.

## License

MIT
