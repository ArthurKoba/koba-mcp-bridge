# GitHub Actions diagnostics

The selected GitHub account exposes Actions diagnostics through `github_agent_*` tools:

- list workflow runs and jobs;
- read the tail of a job log;
- list workflow files;
- download small file ZIPs as base64 with SHA-256;
- dispatch a `workflow_dispatch` workflow with an explicit ref and inputs;
- re-run one job;
- re-run only failed jobs in a run;
- re-run an entire workflow run;
- cancel an in-progress workflow run.

The App therefore needs **Actions: Read and write** when workflow dispatch, rerun, or cancel tools are required. If Actions permission remains read-only, the read diagnostics continue to work but rerun/cancel operations will be rejected by GitHub.

The optional review-oriented account receives only the read side of this surface: workflow run/job metadata, logs, file listing, and file download. It should keep **Actions: Read-only**.

Job logs and file archives are downloaded through GitHub's signed redirect URLs. The bridge never forwards the GitHub installation token to the redirected host. Log downloads are capped at 8 MiB and return at most 500,000 characters; file downloads are capped at 16 MiB by the MCP safety guard and default to 8 MiB.
