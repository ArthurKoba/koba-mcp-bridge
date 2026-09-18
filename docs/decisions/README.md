# Architecture decisions

Significant architectural choices should be recorded as Architecture Decision Records (ADRs).

This directory is intentionally only a placeholder today. An ADR should be added when a decision would otherwise be repeatedly re-litigated or is difficult to infer safely from code.

Suggested initial ADR topics:

- secret manager selection;
- modular runtime/service boundaries;
- aggregate gateway compatibility policy;
- public Files naming versus internal artifact terminology;
- control-plane ownership and secret references;
- common IdP/SSO adoption;
- connector profile identity model;
- Camera Manager boundary.

Suggested filename convention:

```text
0001-short-decision-title.md
0002-next-decision.md
```

A minimal ADR should state context, decision, consequences and status.
