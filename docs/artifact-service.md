# Artifact service architecture

Koba's artifact service is the common binary-data plane for every MCP workflow.

## Identity

Every file is addressed by its SHA-256 content identity:

```text
sha256:<64-hex-digest>
```

Names and MIME types are metadata. Re-uploading identical bytes does not create a
second stored object.

## Agent ingress

For chat/client attachments, `artifact_ingest_file` is the primary ingress.
Its `file` input is explicitly advertised through
`_meta["openai/fileParams"]`. ChatGPT therefore resolves the attachment into a
structured file payload with `download_url`, `file_id`, and optional
`mime_type`/`file_name`. Koba fetches the authorized URL server-side, streams
it directly to temporary storage, verifies optional expected size/SHA-256, and
commits the resulting immutable artifact. Attachment bytes do not pass through
model-visible base64.

The generic fallback is a resumable MCP protocol. An agent creates a session with
`artifact_upload_begin`, sends bounded base64 chunks with
`artifact_upload_write`, and commits with `artifact_upload_finish`.
`artifact_upload_status` returns the exact server-confirmed offset so an
interrupted transfer can continue without restarting.

Upload sessions are durable server state. They are independent from Ghidra and
from every other consumer. The agent never supplies a server filesystem path.
`artifact_upload_list` and `artifact_upload_status` let an agent recover after
a disconnect, while `artifact_upload_cleanup` removes stale session metadata and
unfinished staged bytes by age without deleting committed artifacts.
Successful commit returns the immutable content identity used by all subsequent
operations.

The server validates sequential offsets, declared total size, chunk limits, and
an optional expected SHA-256 before admitting the object into canonical storage.
Completed sessions are retained as idempotent commit receipts until cleanup, so a
retry after a lost response returns the same artifact instead of duplicating work.
Identical content is deduplicated automatically.

## Storage

The persistent volume contains an internal object tree and SQLite metadata index.
Neither is part of the public API. Backends receive artifact IDs and resolve
physical paths only inside trusted server-side adapters.

## Collections

`artifact_extract` accepts a tar or zip artifact. Every regular member is
content-addressed independently and a deterministic collection manifest maps
archive-relative paths to artifact IDs. Traversal paths and unsupported member
types are rejected. Collections have their own lifecycle: deleting a collection
removes only its manifest relationships, after which unreferenced member/source
artifacts become eligible for garbage collection.

## References and cleanup

Consumers create durable references such as:

```text
artifact_id -> ghidra-project -> project_name -> source
```

Referenced objects cannot be normally deleted. `artifact_gc` only collects
objects with no consumer reference and no collection relationship.

## Ghidra

`ghidra_import_artifact` imports a source object into the open project and
records the source reference. Ghidra's project database remains independent from
the source store. Deleting transient upload state therefore cannot invalidate an
already imported Ghidra program, while the canonical source remains available
for reproducibility.

GZF and GAR outputs are registered back into the same artifact service by the
Ghidra export adapter.
