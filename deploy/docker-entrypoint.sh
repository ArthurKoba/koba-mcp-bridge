#!/bin/sh
set -eu

FASTMCP_DIR="${FASTMCP_HOME:-/data/fastmcp}"
ARTIFACT_DIR="${ARTIFACT_ROOT:-/artifacts}"

mkdir -p   "${FASTMCP_DIR}"   "${ARTIFACT_DIR}/inbox"   "${ARTIFACT_DIR}/exports"   "${ARTIFACT_DIR}/scripts"   /home/bridge

# Persistent FastMCP state may have been created by older root-running images.
# Normalize it before dropping privileges so OAuth state survives upgrades.
chown -R 1000:1000 "${FASTMCP_DIR}"

# Both Koba Bridge and Ghidra run application code as uid/gid 1000.
# Only normalize shared directory ownership; existing artifact files are left intact.
chown 1000:1000   /home/bridge   "${ARTIFACT_DIR}"   "${ARTIFACT_DIR}/inbox"   "${ARTIFACT_DIR}/exports"   "${ARTIFACT_DIR}/scripts"

exec gosu 1000:1000 "$@"
