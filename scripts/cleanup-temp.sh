#!/usr/bin/env sh
set -eu
DATA_DIR="${DATA_DIR:-/data}"
TTL_HOURS="${TEMP_FILE_TTL_HOURS:-24}"

# Only derived analysis scratch files are disposable.
# /data/uploads contains cloud media attached to tasks and must remain until
# the user explicitly cancels or deletes the cloud task.
mkdir -p "$DATA_DIR/tmp"
find "$DATA_DIR/tmp" -type f -mmin "+$((TTL_HOURS * 60))" -delete
find "$DATA_DIR/tmp" -type d -empty -delete 2>/dev/null || true
