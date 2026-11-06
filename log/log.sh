#!/usr/bin/env bash
# usage: log/log.sh <ID> <TYPE> "<detail>"
set -e
L="$(dirname "$0")/CODEX_LOG.md"
printf '%s | %s | %s | %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" "$3" >> "$L"
