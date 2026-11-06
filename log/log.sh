#!/bin/sh
# Usage: sh log/log.sh P0001 TYPE "non-sensitive event detail"
set -eu
if [ "$#" -ne 3 ]; then
    echo 'Usage: sh log/log.sh TASK TYPE "detail"' >&2
    exit 2
fi
case "$2" in
    READ|CMD|EDIT|TEST|DECISION|ASSUMPTION|SKIP|BLOCKER|ERROR|COMMIT) ;;
    *) echo 'Invalid event type' >&2; exit 2 ;;
esac
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
printf '%s | %s | %s | %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" "$3" >> "$repo_root/log/CODEX_LOG.md"
