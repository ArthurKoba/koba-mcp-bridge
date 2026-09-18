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
```

`GITHUB_AGENT_PRIVATE_KEY` can be used instead of the base64 form when the deployment system can safely store multiline PEM values.

The GitHub App installation is the single source of truth for repository access. There is no duplicated bridge-side repository allowlist. Adding or removing repositories in the GitHub App installation immediately changes the repository set visible to the bridge without changing Coolify environment variables.

`github_agent_list_repositories` discovers the repositories directly from GitHub App installations and returns repository metadata and effective installation permissions. A direct operation against a repository that is not installed for the App is rejected by GitHub installation lookup.

### Workflow policy

The bridge has an additional development policy layer:

```text
GITHUB_PROTECTED_BRANCHES=main,master
GITHUB_REQUIRED_CHECKS=test,docker
```

The neutral protected-branch and required-check variables are optional and default to the values shown. Legacy `GITHUB_AGENT_PROTECTED_BRANCHES` / `GITHUB_AGENT_REQUIRED_CHECKS` remain accepted as compatibility aliases. For repositories with different CI contexts, set `GITHUB_REQUIRED_CHECKS_BY_REPOSITORY` to a JSON map of full repository name to exact check-run names; repository-specific entries take precedence over the global fallback.

Direct file writes, deletes, atomic commits, fast-forwards, branch deletion, and branch renames are rejected for protected branches. Work is expected to happen on feature branches and reach a protected branch through a pull request.

Pull requests are restricted to branches inside the same repository. `owner:branch` / fork heads are rejected by the bridge, so the agent cannot use this backend for external contribution PRs.

Agent PR merge remains available only for non-protected base branches. Any PR targeting `main`/`master` (or another configured protected branch) is rejected by the Agent surface. Protected merge belongs exclusively to the independent Reviewer App.

### Development surface

Core repository/files:

- installation-backed repository discovery and repository status checks;
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
- non-decisive `COMMENT` review feedback with optional inline comments; `APPROVE` / `REQUEST_CHANGES` belong exclusively to the Reviewer role;
- inline review-thread list/reply/update/resolve/unresolve;
- reviewer request/remove operations;
- draft PR ready-for-review transition;
- PR branch update using GitHub GraphQL `MERGE` or true `REBASE` semantics;
- check-run inspection and required-check validation;
- merge non-protected PRs after required checks; protected PR merge is intentionally absent from the Agent role.

Issues and CI:

- list/read/create/update issues;
- issue comments;
- GitHub Actions workflow-run and job listing;
- job-log diagnostics;
- workflow artifact listing/download;
- rerun one job, rerun failed jobs, rerun a workflow run, and cancel a workflow run.

### Development GitHub App permissions

Configure the development GitHub App with only the repositories that agents are allowed to modify and grant:

- **Contents: Read and write** — files, Git Data objects, refs, tags;
- **Pull requests: Read and write** — create/update PRs, comments, reviewer requests and branch updates; protected merge remains blocked by policy;
- **Issues: Read and write** — issue lifecycle and comments;
- **Actions: Read and write** — workflow diagnostics plus rerun/cancel controls;
- **Checks: Read-only** — required-check gating.

Do not grant organization/administration permissions to the app unless a later feature explicitly requires them. Branch/ruleset administration should remain a human-controlled GitHub setting.

## Independent GitHub reviewer App

A second GitHub App can be configured for independent review identity. This is intentionally separate from the development App so a development agent cannot satisfy an identity-specific approval requirement by approving its own PR as the same bot actor.

Reviewer runtime variables:

```text
GITHUB_REVIEWER_APP_ID=<reviewer GitHub App numeric App ID>
GITHUB_REVIEWER_PRIVATE_KEY_B64=<base64-encoded reviewer private key PEM>
```

`GITHUB_REVIEWER_PRIVATE_KEY` is also supported for multiline PEM storage.

The reviewer App installation is also the sole source of repository access. `github_reviewer_list_repositories` discovers its current installation repository set directly from GitHub. No reviewer repository list is duplicated in Coolify.

When reviewer credentials are absent, no `github_reviewer_*` tools are registered. When configured, the reviewer surface intentionally exposes only read/review operations:

- installation-backed repository discovery and status validation;
- UTF-8 and base64 file reads;
- directory, branches, tags, code-search, commit-history, commit and ref comparison reads;
- PR list/metadata, changed files, comments, reviews and review-thread reads;
- check-run, workflow-run/job and required-check reads;
- job-log and workflow artifact diagnostics;
- rich review submission with inline comments;
- review-thread replies and resolve/unresolve operations.

It does **not** expose file mutation, branch mutation, tag mutation, or issue mutation. Its only repository-content mutation is `github_reviewer_merge_pull_request`, and that tool is restricted to protected PR bases after required CI, an APPROVE by the Reviewer App on the exact current HEAD, and zero unresolved non-outdated review threads.

Recommended reviewer App permissions:

- **Contents: Read and write** — required by GitHub’s PR merge endpoint; the bridge does not expose arbitrary content writes to the Reviewer App;
- **Pull requests: Read and write** — review/approval lifecycle;
- **Checks: Read-only**;
- **Actions: Read-only**;
- **Issues: Read-only** if PR conversation/issue-style metadata access requires it for the repository policy in use.

A separate ChatGPT conversation by itself is not an independent GitHub identity. The second GitHub App is what makes the review actor distinct at GitHub level. The enforced workflow is: development Agent creates/updates a feature branch and PR; CI runs; Reviewer inspects the exact current HEAD and submits `REQUEST_CHANGES` or `APPROVE`; only Reviewer may merge a protected-base PR.

## GitHub-side branch protection

Bridge policy protects `main`/`master` from direct Agent mutations, but GitHub itself must also enforce the actor separation. Configure a repository ruleset for protected branches that:

- targets `main`/`master`;
- requires changes through a pull request;
- requires the CI checks configured by `GITHUB_REQUIRED_CHECKS_BY_REPOSITORY` or the global `GITHUB_REQUIRED_CHECKS` fallback;
- dismisses stale approvals when new commits are pushed and requires approval of the most recent reviewable push;
- blocks force pushes and deletions;
- does **not** grant the Agent App bypass;
- grants the Reviewer App bypass only as **For pull requests only** when using `Restrict updates`.

The Reviewer-side bridge gate still checks CI, exact-head approval, and unresolved threads before calling GitHub merge. GitHub rulesets therefore enforce actor separation while the bridge enforces review quality.

The protected branch rules should also require:

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
