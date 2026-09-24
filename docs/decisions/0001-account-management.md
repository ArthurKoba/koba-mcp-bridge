# ADR 0001: Provider account management

Status: accepted

## Context

Provider identities were previously coupled to deployment secret paths and fixed semantic roles. GitLab also needs first-class self-hosted instances, while GitHub credentials may represent either an App or a token-backed user/account. Management additionally needs operational visibility into MCP calls and persistent Files without introducing another infrastructure service.

## Decision

MCP Bridge owns one private `management` runtime inside the modular monolith.

- Only management opens the SQLite database; SQLAlchemy is the persistence adapter.
- The active deployment starts from an empty database, so current metadata creates the schema directly and no legacy migration compatibility is maintained.
- GitHub and GitLab use separate persistence/admin models. There is no account-role field.
- GitHub supports `github_app` and `github_token` accounts and targets the public GitHub API.
- GitLab supports token authentication with per-account `base_url`, TLS verification and optional custom CA PEM.
- Provider credentials are encrypted with Fernet and plaintext is resolved only for an explicit provider/account selection over the authenticated internal API.
- Every provider operation selects an explicit `account_id`; UUID and provider-local alias are valid selectors.
- Starlette Admin is a presentation adapter for accounts, invocation logs, runtime settings and Files administration.
- FastMCP middleware emits bounded, secret-redacted call payloads best-effort. Logging and payload capture are runtime-configurable and retention is enforced automatically.
- Files administration reuses the canonical Files `FileStore` over the shared `files-data` volume, including reference-aware cleanup.
- Deployment environment contains bootstrap/configuration only; dynamic provider accounts are application data.

## Consequences

Provider account management no longer depends on Infisical. Account onboarding and credential replacement happen through Admin. Account semantics match each provider instead of forcing one shared form.

SQLite is sufficient for the expected management scale. If requirements outgrow it, application ports keep provider runtimes independent from the persistence implementation.

GitHub Enterprise Server API URLs are not enabled by the current contract. Self-hosted GitLab is explicitly supported.
