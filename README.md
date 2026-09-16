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
        +-- github_agent_* -> GitHub App development identity
        +-- github_reviewer_* -> optional independent GitHub App reviewer identity
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
GITHUB_AGENT_REQUIRED_REVIEWERS=koba-ai-reviewer[bot]
```

The protected-branch and required-check variables are optional and default to the values shown. `GITHUB_AGENT_REQUIRED_REVIEWERS` is optional and defaults to no identity-specific approval requirement; production PR-only workflows should set it once the independent reviewer App is installed.

Direct file writes, deletes, atomic commits, fast-forwards, branch deletion, and branch renames are rejected for protected branches. Work is expected to happen on feature branches and reach a protected branch through a pull request.

Pull requests are restricted to branches inside the same allowlisted repository. `owner:branch` / fork heads are rejected by the bridge, so the agent cannot use this backend for external contribution PRs.

PR merge supports `merge`, `squash`, and `rebase`. Before merging, every name in `GITHUB_AGENT_REQUIRED_CHECKS` must have a completed successful check-run on the PR head SHA. When `GITHUB_AGENT_REQUIRED_REVIEWERS` is configured, the latest decisive review state for every listed login must also be `APPROVED`. A later `CHANGES_REQUESTED` or dismissed review blocks the merge again.

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
- working-branch merge while protected targets remain blocked;
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
- rich review submission (`COMMENT`, `APPROVE`, `REQUEST_CHANGES`) with inline file/line comments;
- inline review-thread list/reply/update/resolve/unresolve;
- reviewer request/remove operations;
- draft PR ready-for-review transition;
- PR branch update using GitHub GraphQL `MERGE` or true `REBASE` semantics;
- check-run inspection and required-check validation;
- merge with `merge`, `squash`, or `rebase` after required checks and configured independent approvals pass.

Issues and CI:

- list/read/create/update issues;
- issue comments;
- GitHub Actions workflow-run listing;
- workflow job listing.

### Development GitHub App permissions

For the full workflow, configure the development GitHub App with only the repositories that agents are allowed to modify and grant:

- **Contents: Read and write** — files, Git Data objects, refs, tags;
- **Pull requests: Read and write** — PR lifecycle, reviews, merge;
- **Issues: Read and write** — issue lifecycle and comments;
- **Actions: Read-only** — workflow runs/jobs;
- **Checks: Read-only** — required-check gating.

Do not grant organization/administration permissions to the app unless a later feature explicitly requires them. Branch/ruleset administration should remain a human-controlled GitHub setting.

## Independent GitHub reviewer App

A second GitHub App can be configured for independent review identity. This is intentionally separate from the development App so a development agent cannot satisfy an identity-specific approval requirement by approving its own PR as the same bot actor.

Reviewer runtime variables:

```text
GITHUB_REVIEWER_APP_ID=<reviewer GitHub App numeric App ID>
GITHUB_REVIEWER_PRIVATE_KEY_B64=<base64-encoded reviewer private key PEM>
GITHUB_REVIEWER_ALLOWED_REPOSITORIES=ArthurKoba/koba-mcp-bridge,ArthurKoba/anjia-ajl33pq0866-fh8626v100-reverse
```

`GITHUB_REVIEWER_PRIVATE_KEY` is also supported for multiline PEM storage. The reviewer allowlist is mandatory and does not support `*`.

When these variables are absent, no `github_reviewer_*` tools are registered. When configured, the reviewer surface intentionally exposes only read/review operations:

- status and installation validation;
- UTF-8 and base64 file reads;
- directory, branches, tags, code-search, commit-history, commit and ref comparison reads;
- PR list/metadata, changed files, comments, reviews and review-thread reads;
- check-run, workflow-run/job and required-check reads;
- rich review submission with inline comments;
- review-thread replies and resolve/unresolve operations.

It does **not** expose file mutation, branch mutation, tag mutation, issue mutation, PR merge, or protected-branch operations.

Recommended reviewer App permissions:

- **Contents: Read-only**;
- **Pull requests: Read and write**;
- **Checks: Read-only**;
- **Actions: Read-only**;
- **Issues: Read-only** if PR conversation/issue-style metadata access requires it for the repository policy in use.

A separate ChatGPT conversation by itself is not an independent GitHub identity. The second GitHub App is what makes the review actor distinct at GitHub level. A practical workflow is: development chat creates/updates the PR through `github_agent_*`; review chat inspects the diff and CI through `github_reviewer_*`; reviewer App submits `REQUEST_CHANGES` or `APPROVE`; the development App merge gate verifies the required reviewer bot login before allowing merge.

## GitHub-side branch protection

Bridge policy protects `main`/`master` from direct agent mutations, but GitHub itself should also enforce the rule so human tokens and other integrations cannot bypass the workflow. Configure a repository ruleset or branch protection for protected branches that requires:

- changes through a pull request;
- required CI checks such as `test` and `docker`;
- at least one approving review;
- dismissal/re-approval when new commits invalidate review, if desired;
- conversation resolution before merge, if desired.

Keep ruleset/branch-protection administration human-controlled rather than granting repository administration permission to either GitHub App.

## Project status

The bridge is operational as an authenticated MCP gateway with Ghidra, a full GitHub App development workflow, and an optional independent GitHub reviewer identity.

## License

MIT
