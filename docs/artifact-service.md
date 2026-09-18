# Artifact service architecture

Koba's artifact service is the common binary-data plane for every MCP workflow.

## Identity

Every file is addressed by its SHA-256 content identity:

```text
sha256:<64-hex-digest>
```

Names and MIME types are metadata. Re-uploading identical bytes does not create a
second stored object.

## Browser ingress

The `file_manager` MCP App provides drag-and-drop upload. The browser sends the
selected bytes directly through the MCP App backend tool; the LLM does not carry
the file contents in its context. Koba persists the payload in the shared object
store and returns artifact metadata.

## Storage

The persistent volume contains an internal object tree and SQLite metadata index.
Neither is part of the public API. Backends receive artifact IDs and resolve
physical paths only inside trusted server-side adapters.

## Collections

`artifact_extract` accepts a tar or zip artifact. Every regular member is
content-addressed independently and a deterministic collection manifest maps
archive-relative paths to artifact IDs. Traversal paths and unsupported member
types are rejected.

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
