#!/usr/bin/env bash
set -euo pipefail

for launcher in "$@"; do
  if [[ ! -f "$launcher" ]]; then
    echo "ERRO: launcher ausente: $launcher" >&2
    exit 1
  fi
  if [[ ! -x "$launcher" ]]; then
    echo "ERRO: launcher não executável: $launcher" >&2
    exit 1
  fi
done
