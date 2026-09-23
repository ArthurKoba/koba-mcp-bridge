# Architecture decisions

Significant architectural choices should be recorded as Architecture Decision Records (ADRs).

This directory is intentionally lightweight. Add an ADR when a decision would otherwise be repeatedly re-litigated or cannot be inferred safely from code.

Current ADR candidates:

- Infisical deployment and machine identity model;
- modular runtime/service boundaries;
- aggregate gateway compatibility policy;
- public Files naming versus internal file terminology;
- connector profile identity model.

Suggested filename convention:

```text
0001-short-decision-title.md
0002-next-decision.md
```

A minimal ADR should state context, decision, consequences and status.
