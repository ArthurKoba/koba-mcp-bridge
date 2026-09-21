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

## Documentation

The documentation entry point is [docs/README.md](docs/README.md). It links the current
architecture map, component catalog, repository map, roadmap, existing technical notes,
and future architecture decision records.

The documentation intentionally separates the current implementation from the target
modular runtime direction so incremental migrations can be reviewed without treating
the roadmap as already implemented.

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

## Artifact service

Koba provides one universal persistent file service for every backend and worker.
Files are immutable and content-addressed. The public identifier is:

```text
sha256:<digest>
```

Physical storage paths are private implementation details and are never used as
cross-service identifiers.

For client/chat attachments, agents should call `artifact_ingest_file` with the
attachment/file argument itself. The tool marks `file` in
`_meta["openai/fileParams"]`, so ChatGPT supplies a structured file payload
containing `download_url`, `file_id`, and optional MIME/name metadata. Koba
streams the authorized temporary URL directly into canonical storage and returns
`artifact_id`. Attachment bytes never need to be serialized through
model-visible base64.

For generic MCP clients that cannot provide a file-capable argument, Koba also
provides a resumable fallback protocol:

- `artifact_upload_begin` creates an upload session from file metadata;
- `artifact_upload_write` appends one bounded base64 chunk at the exact next offset;
- `artifact_upload_list` enumerates open/completed sessions for autonomous recovery;
- `artifact_upload_status` resumes interrupted transfers from the server-confirmed offset;
- `artifact_upload_finish` verifies size and optional SHA-256, commits the immutable
  object, and returns its `artifact_id`;
- `artifact_upload_cleanup` previews or removes stale upload-session state by age without deleting committed artifacts;
- `artifact_upload_cancel` discards a specific unfinished transfer.

The protocol is transport-only. The agent does not choose a Koba filesystem path
and no backend-specific directory participates in upload. After commit, every
consumer receives only the immutable `artifact_id`.

The generic artifact surface also provides:

- `artifact_status`, `artifact_list`, `artifact_info`, `artifact_read`;
- `artifact_create_text`;
- `artifact_extract`, `artifact_collection_list`,
  `artifact_collection_resolve`, `artifact_collection_delete`;
- `artifact_references`, `artifact_release_reference`;
- `artifact_delete`, `artifact_gc`.

Archive extraction creates a collection manifest whose members are themselves
immutable artifacts. The same object can therefore be reused by multiple
projects, workers, and backends without copying it again in the artifact store.

Consumers hold durable references to source artifacts. Normal deletion refuses
to remove referenced objects; garbage collection only targets objects with no
consumer or collection references.

## Curl HTTP client

The structured curl tools use the `chrome-desktop` HTTP header preset by
default. This applies to `curl_request`, `curl_download`, and
`curl_stream_capture`, so ordinary requests present a current desktop Chrome
User-Agent and matching browser navigation headers unless the caller selects a
different preset.

Use `preset="curl"` for native curl-style defaults, `preset="json-api"` for
JSON APIs, or `preset="none"` when only explicitly supplied headers should be
sent. Caller-provided headers always override preset headers.

Browser presets reproduce HTTP request headers only. They do not emulate Chrome
JavaScript execution, cookies/session state beyond what the caller supplies,
TLS fingerprints, or browser HTTP/2 settings.

## Ghidra integration

Ghidra is a consumer of the artifact service, not the owner of uploaded files.
`ghidra_import_artifact(artifact_id, ...)` resolves the immutable object
internally, imports it into the currently open Ghidra project, and records a
durable `ghidra-project` source reference.

After import, Ghidra stores the program in its own project database under
`/projects`. The canonical source artifact remains independently available for
re-import, verification, or use by another backend. `ghidra_project_sources`
lists the retained source objects for the current project.

Ghidra outputs can be brought back into the same universal artifact store with:

- `ghidra_export_program_artifact` for GZF;
- `ghidra_archive_project_artifact` for GAR.

Set the runtime variable below to mount the internal Ghidra MCP server:

```text
GHIDRA_MCP_URL=http://ghidra-mcp:8081/mcp
```

The mounted backend is namespaced as `ghidra`. Ghidra itself stays on the
private Docker network.

## Secrets / Infisical

Koba uses self-hosted Infisical as the central provider for provider-specific
credentials and configuration. Runtime workloads authenticate with an Infisical
Machine Identity using Universal Auth and receive a short-lived access token.

Coolify only keeps the Infisical bootstrap and transport configuration:

```text
INFISICAL_HOST=https://secrets.koba-nexus.ru
INFISICAL_PROJECT_ID=<project UUID>
INFISICAL_ENVIRONMENT=prod
INFISICAL_BASE_PATH=/
INFISICAL_CLIENT_ID=<machine identity client id>
INFISICAL_CLIENT_SECRET=<machine identity client secret>
INFISICAL_VERIFY_TLS=true
```

Connectors resolve values by convention below `INFISICAL_BASE_PATH`. Explicit
`env://`, `file://`, and `infisical://` references remain available as
low-level compatibility primitives, but normal connector configuration does not
require per-secret `*_REF` variables.

Deployment and migration instructions are in
[`deploy/infisical/README.md`](deploy/infisical/README.md).

MCP diagnostics expose only provider/configuration status and redacted reference checks;
there is intentionally no MCP tool that returns secret plaintext.

## GitLab connector

GitLab is implemented as a reusable subserver rather than another monolithic block of
gateway-only tools. The same GitLab tool provider is exposed in two ways:

- the normal gateway endpoint at `/mcp`, where tools are namespaced as `gitlab_*`;
- a dedicated GitLab-only endpoint at `/gitlab/mcp`, where the same tools are exposed
  without the `gitlab_` namespace prefix.

Every GitLab operation requires an explicit `profile_id`. There is deliberately no
process-global "current GitLab" or "current account", so concurrent agents can use
different GitLab instances or different accounts on the same instance without switching
each other's context.

GitLab profiles are discovered from Infisical folders below:

```text
/gitlab/accounts/<profile_id>
├── BASE_URL
├── AUTH_TYPE
├── TOKEN
├── LABEL        # optional
├── VERIFY_TLS   # optional, default true
└── CA_FILE      # optional
```

Creating a new account folder makes the profile discoverable without adding Coolify
environment variables. Legacy `GITLAB_PROFILES_FILE` and `GITLAB_PROFILES_JSON`
remain fallback-only during migration.

Supported authentication modes are:

- `private_token` -> GitLab `PRIVATE-TOKEN` header for personal/project/group access tokens;
- `bearer` -> `Authorization: Bearer ...` for OAuth-compatible access tokens;
- `job_token` -> `JOB-TOKEN` for endpoints that support CI/CD job-token authentication.

The connector currently exposes profile/account validation, project discovery, repository
file/tree/code-search operations, atomic commit actions, branches and compare, merge
requests, issues, and CI pipelines/jobs/job traces with retry/cancel controls.

Direct writes to branches listed in `GITLAB_PROTECTED_BRANCHES` are blocked by the bridge
(default: `main,master`). Feature branches can be created from protected branches and
merge requests can target protected branches. GitLab's own protected branch, approval,
role, and token-scope settings remain the authoritative server-side access controls.

## GitHub OAuth

When `OAUTH_ENABLED=true`, GitHub OAuth configuration is resolved from Infisical:

```text
/github/oauth
├── CLIENT_ID
├── CLIENT_SECRET
├── JWT_SIGNING_KEY
└── ALLOWED_USERS
```

Only `OAUTH_ENABLED` and `OAUTH_BASE_URL` remain deployment variables. The
public OAuth base URL defaults to `https://mcp.koba-nexus.ru`.

OAuth client registrations and token state are stored below `FASTMCP_HOME`, which
defaults to `/data/fastmcp` in the container. Production deployments should keep
that directory persistent.

## GitHub App development backend

The `github_agent_*` tools authenticate as a GitHub App installation. Automated repository activity is therefore attributed to the app identity rather than the human account used to log into the MCP bridge.

The development identity is resolved from Infisical:

```text
/github/development
├── APP_ID
└── PRIVATE_KEY_PEM
```

Legacy environment variables remain fallback-only during the migration window.

The GitHub App installation is the single source of truth for repository access. There is no duplicated bridge-side repository allowlist. Adding or removing repositories in the GitHub App installation immediately changes the repository set visible to the bridge without changing Coolify environment variables.

`github_agent_list_repositories` discovers the repositories directly from GitHub App installations and returns repository metadata and effective installation permissions. A direct operation against a repository that is not installed for the App is rejected by GitHub installation lookup.

### Workflow policy

The bridge has an additional development policy layer:

```text
GITHUB_AGENT_PROTECTED_BRANCHES=main,master
GITHUB_AGENT_REQUIRED_CHECKS=test,docker
GITHUB_AGENT_REQUIRED_REVIEWERS=koba-ai-reviewer[bot]
```

The protected-branch and required-check variables are optional and default to the values shown. `GITHUB_AGENT_REQUIRED_REVIEWERS` is optional and defaults to no identity-specific approval requirement; production PR-only workflows can set it once the independent reviewer App is installed and validated.

Direct file writes, deletes, atomic commits, fast-forwards, branch deletion, and branch renames are rejected for protected branches. Work is expected to happen on feature branches and reach a protected branch through a pull request.

Pull requests are restricted to branches inside the same repository. `owner:branch` / fork heads are rejected by the bridge, so the agent cannot use this backend for external contribution PRs.

PR merge supports `merge`, `squash`, and `rebase`. Before merging, every name in `GITHUB_AGENT_REQUIRED_CHECKS` must have a completed successful check-run on the PR head SHA. When `GITHUB_AGENT_REQUIRED_REVIEWERS` is configured, the latest decisive review state for every listed login must also be `APPROVED`. A later `CHANGES_REQUESTED` or dismissed review blocks the merge again.

### Development surface

Core repository/files:

- installation-backed repository discovery and repository status checks;
- UTF-8 file read/write/delete;
- directory listing;
- binary file read/write using base64;
- server-side copy/move of existing Git blobs between paths without serializing binary contents through MCP; copy may read from another ref, while atomic move/rename requires `source_ref` to resolve to the destination branch HEAD;
- repository-scoped code search;
- atomic multi-file commits through Git Data blobs/trees/commits;
- atomic commit changes may use `operation: copy` to reuse an existing file blob from another ref without transporting its contents;
- optimistic branch-head verification with `expected_head_sha`.

Branches, commits, and tags:

- branch list/create/delete/rename;
- non-force fast-forward of non-protected branches;
- guarded ancestor-only branch reset with expected-head CAS, dry-run by default, and explicit protected-branch override for intentional history repair;
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
- GitHub Actions workflow-run and job listing;
- job-log diagnostics;
- workflow artifact listing/download;
- dispatch `workflow_dispatch` workflows with explicit refs/inputs;
- rerun one job, rerun failed jobs, rerun a workflow run, and cancel a workflow run.

### Development GitHub App permissions

Configure the development GitHub App with only the repositories that agents are allowed to modify and grant:

- **Contents: Read and write** — files, Git Data objects, refs, tags;
- **Pull requests: Read and write** — PR lifecycle, reviews, merge;
- **Issues: Read and write** — issue lifecycle and comments;
- **Actions: Read and write** — workflow diagnostics plus dispatch/rerun/cancel controls;
- **Checks: Read-only** — required-check gating.

Do not grant organization/administration permissions to the app unless a later feature explicitly requires them. Branch/ruleset administration should remain a human-controlled GitHub setting.

## Independent GitHub reviewer App

A second GitHub App can be configured for independent review identity. This is intentionally separate from the development App so a development agent cannot satisfy an identity-specific approval requirement by approving its own PR as the same bot actor.

The reviewer identity is resolved from Infisical:

```text
/github/reviewer
├── APP_ID
└── PRIVATE_KEY_PEM
```

Legacy environment variables remain fallback-only during the migration window.

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
