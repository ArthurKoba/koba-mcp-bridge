# GitHub history and policy surface

The development GitHub App exposes controlled history maintenance without requiring workflow-file mutation or additional `Workflows` permission.

## Commit identity observability

`github_agent_list_commits` and `github_agent_get_commit` report both Git-level identity and GitHub actor metadata when GitHub can resolve it:

- author name, email, date, login, id and actor type;
- committer name, email, date, login, id and actor type;
- verification state/reason, with signature/payload material on the detailed commit response;
- tree SHA on the detailed commit response.

The reviewer read surface receives the same richer commit observations, but no history mutation tool is registered for the reviewer App.

## Branch policy observability

`github_agent_list_branches` distinguishes two independent concepts:

- `github_protected`: GitHub's branch-protection/ruleset result;
- `bridge_reserved`: the branch name is reserved by `GITHUB_AGENT_PROTECTED_BRANCHES` in Koba MCP Bridge.

Each branch also reports `mutation_allowed` and `mutation_denial_reason`. A branch can therefore be `github_protected=false` while still being unavailable for direct Agent mutation because Bridge policy reserves it.

## Capability introspection

`github_agent_capabilities(repository)` reports the Agent App identity, repository metadata, effective installation permissions, whether Contents write access permits ref/history maintenance, the Bridge reserved-branch policy, and whether an independent reviewer identity is configured.

The endpoint is intended to make permission boundaries discoverable before an Agent attempts an operation. In particular, a missing `workflows` permission is reported as `none`; controlled history rewrite does not depend on workflow-file mutation.

## Controlled identity rewrite

`github_agent_rewrite_branch_identity` rewrites a linear first-parent history range so Git author and committer identity come from the currently configured Agent GitHub App. The caller cannot provide an arbitrary Git name or email.

Required safety properties:

- `expected_head_sha` is mandatory;
- Bridge-reserved or GitHub-protected branches are rejected;
- only `identity_source=current_agent_app` is accepted;
- commit messages and trees must be preserved;
- merge commits in the rewrite range are rejected;
- an optional `base_sha` is an exclusive first-parent boundary;
- each rewritten commit is checked for tree, message and identity preservation;
- commit count and final HEAD tree are validated;
- the branch HEAD is checked again immediately before a single forced ref replacement.

`dry_run=true` is the default. To return the exact deterministic `old_sha -> new_sha` mapping, dry-run creates the rewritten Git commit objects but deliberately leaves them unreachable by any branch ref. It does not move the branch. A later real call with the same source history can reuse the same deterministic SHA values when dates and other inputs are preserved.

A successful non-dry-run response returns the old and new HEAD SHA, final tree SHA, commit count, mapping, plan and `ref_updated=true`.

GitHub's ref-update REST endpoint is a single atomic ref replacement, but it does not provide a compare-and-swap parameter. The Bridge therefore performs an explicit second HEAD check immediately before the forced ref update and refuses to update if that check observes a race.
