#!/bin/sh
set -eu

FASTMCP_DIR="${FASTMCP_HOME:-/data/fastmcp}"
ARTIFACT_DIR="${ARTIFACT_ROOT:-/artifacts}"

mkdir -p   "${FASTMCP_DIR}"   "${ARTIFACT_DIR}/objects/sha256"   "${ARTIFACT_DIR}/tmp"   /home/bridge

chown -R 1000:1000 "${FASTMCP_DIR}"
chown -R 1000:1000 "${ARTIFACT_DIR}"
chown 1000:1000 /home/bridge

exec gosu 1000:1000 "$@"
