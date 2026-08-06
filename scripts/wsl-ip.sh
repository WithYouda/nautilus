#!/usr/bin/env bash
set -euo pipefail

candidate="$(
ip -4 route get 1.1.1.1 2>/dev/null \
    | awk '{for (i = 1; i <= NF; i += 1) if ($i == "src") {print $(i + 1); exit}}' \
    | head -n 1
)"

if [[ -n "$candidate" ]]; then
  printf '%s\n' "$candidate"
  exit 0
fi

hostname -I 2>/dev/null | awk '{for (i = 1; i <= NF; i += 1) if ($i !~ /^127\./) {print $i; exit}}'
