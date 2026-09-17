#!/usr/bin/env sh
set -eu
DATA_DIR="${DATA_DIR:-/data}"
TTL_HOURS="${TEMP_FILE_TTL_HOURS:-24}"
mkdir -p "$DATA_DIR/uploads"
find "$DATA_DIR/uploads" -type f -mmin "+$((TTL_HOURS * 60))" -delete
