#!/bin/sh
set -eu

FASTMCP_DIR="${FASTMCP_HOME:-/data/fastmcp}"
FILE_DIR="${FILE_ROOT:-/files}"

mkdir -p   "${FASTMCP_DIR}"   "${FILE_DIR}/objects/sha256"   "${FILE_DIR}/tmp"   /home/bridge

chown -R 1000:1000 "${FASTMCP_DIR}"
chown -R 1000:1000 "${FILE_DIR}"
chown 1000:1000 /home/bridge

exec gosu 1000:1000 "$@"
