#!/usr/bin/env sh
set -eu
DATA_DIR="${DATA_DIR:-/data}"
TTL_HOURS="${TEMP_FILE_TTL_HOURS:-1}"

# This script removes only derived scratch files under /data/tmp.
# Original uploads under /data/uploads are managed by the worker and the
# account-aware maintenance code so an active/paused job is never deleted by
# a blind filesystem sweep.
mkdir -p "$DATA_DIR/tmp"
find "$DATA_DIR/tmp" -type f -mmin "+$((TTL_HOURS * 60))" -delete
find "$DATA_DIR/tmp" -type d -empty -delete 2>/dev/null || true
