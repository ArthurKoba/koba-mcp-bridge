#!/bin/sh
set -eu

FASTMCP_DIR="${FASTMCP_HOME:-/data/fastmcp}"
FILE_DIR="${FILE_ROOT:-/files}"
MANAGEMENT_DIR="/management"

mkdir -p \
  "${FASTMCP_DIR}" \
  "${FILE_DIR}/objects/sha256" \
  "${FILE_DIR}/tmp" \
  "${MANAGEMENT_DIR}" \
  /home/bridge

chown -R 1000:1000 "${FASTMCP_DIR}" "${FILE_DIR}" "${MANAGEMENT_DIR}" /home/bridge

exec gosu 1000:1000 "$@"
