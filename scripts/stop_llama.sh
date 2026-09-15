#!/usr/bin/env bash
# Para todo llama-server e espera a porta 8080 ficar livre.
set -euo pipefail
PORT=8080
DIR="${HOME}/.grok/long-running-background-tasks"
mkdir -p "$DIR"

echo "Parando instâncias de llama-server..."
pkill -9 -f 'llama-server' 2>/dev/null || true
sleep 2

# mata PIDs sobreviventes registrados em pidfiles
for pf in "${DIR}"/llama_*.pid; do
  [[ -e "$pf" ]] || continue
  pid="$(cat "$pf" 2>/dev/null || true)"
  if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "Matando PID sobrevivente $pid ($pf)..."
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$pf"
done
sleep 1

# espera a porta ficar livre (curl deve falhar)
for i in {1..20}; do
  if ! curl -sf -m 2 "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; then
    echo "Porta ${PORT} livre."
    exit 0
  fi
  echo "Porta ${PORT} ainda ocupada, tentativa $i/20..."
  pkill -9 -f 'llama-server' 2>/dev/null || true
  sleep 1
done

echo "ERRO: porta ${PORT} continua ocupada após stop."
exit 1
