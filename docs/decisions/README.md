# Architecture decisions

Significant architectural choices should be recorded as Architecture Decision Records (ADRs).

This directory is intentionally lightweight. Add an ADR when a decision would otherwise be repeatedly re-litigated or cannot be inferred safely from code.

Accepted ADRs:

- [ADR 0001: Provider account management](0001-account-management.md)

Remaining ADR candidates:

- modular runtime/service boundaries;
- aggregate gateway and dedicated public surface policy;
- Files data-plane ownership and cross-runtime access model;
- explicit provider `account_id` identity model.

Suggested filename convention:

```text
0001-short-decision-title.md
0002-next-decision.md
```

A minimal ADR should state context, decision, consequences and status.
