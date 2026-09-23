# ADR 0001: Provider account control plane

Status: accepted

## Context

GitHub and GitLab provider identities were previously resolved from deployment secret
paths. That made account discovery part of secret storage, coupled provider runtimes to a
specific secret backend, and made multi-account selection awkward. GitLab also needs
first-class self-hosted instances with per-account URL/TLS configuration.

MCP Bridge is a modular application whose private runtimes are separate processes. Sharing
one SQLite file directly between provider containers would create hidden persistence
ownership and couple provider code to SQLAlchemy.

## Decision

MCP Bridge owns a private `control-plane` runtime in the same source repository.

- SQLite is the persistence engine and only the control-plane process opens it.
- SQLAlchemy is the persistence adapter and Alembic is the migration authority.
- Provider credentials are encrypted with Fernet before persistence; the master key is a
  deployment bootstrap secret and is never stored in SQLite.
- GitHub and GitLab runtimes use a provider-neutral authenticated HTTP client to list and
  resolve accounts. They never import control-plane implementation or SQLAlchemy models.
- Every provider operation selects an explicit `account_id`; both stable UUID and unique
  human-readable alias are valid selectors.
- GitHub accounts are GitHub App identities with `development` or `reviewer` roles.
- GitLab accounts are token identities with per-account `base_url`, TLS verification and
  optional custom CA PEM, including self-hosted installations under a URL prefix.
- Starlette Admin is an outer presentation adapter for account management and basic
  telemetry. It is not part of domain/application contracts.
- FastMCP middleware records bounded, best-effort invocation metadata without argument
  values. Telemetry failure must not delay or fail MCP tool execution.
- Deployment environment contains bootstrap/configuration only; dynamic provider accounts
  are data, not environment variables.

## Consequences

Provider account management no longer depends on Infisical. Account onboarding and
credential replacement happen through the private admin surface. Provider runtimes now
require the control plane to resolve credentials, but control-plane outages do not make
telemetry a blocking dependency for calls that already have their account client cached.

SQLite is sufficient for the expected account/telemetry scale and keeps deployment small.
If storage requirements outgrow SQLite, the repository/application ports allow replacing
SQLAlchemy's database backend without changing provider MCP contracts.

GitHub Enterprise Server API URLs are intentionally not supported by this first account
contract; GitHub provider accounts currently target `https://api.github.com`. Self-hosted
GitLab is explicitly supported.
