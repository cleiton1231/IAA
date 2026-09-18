#!/usr/bin/env bash
# Ternary-Bonsai-2-27B PQ2_0 via fork PrismML, CPU (ternary kernels não têm Vulkan/HIP aqui).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"$SCRIPT_DIR/stop_llama.sh"

MODEL="/home/cleiton/local/models/ternary-bonsai-2-27b-pq2/Ternary-Bonsai-2-27B-PQ2_0.gguf"
BIN="/home/cleiton/local/prism-llama.cpp/build/bin/llama-server"
PORT=8080
HOST="127.0.0.1"
CTX=16384
DIR="${HOME}/.grok/long-running-background-tasks"
LOG="${DIR}/llama_ternary_bonsai_27b.log"
PIDFILE="${DIR}/llama_ternary_bonsai_27b.pid"

mkdir -p "$DIR"

echo "Iniciando llama-server (fork PrismML, CPU) com Ternary-Bonsai-2-27B PQ2_0 (ctx=$CTX)..."
setsid "$BIN" \
  --model "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  --ctx-size "$CTX" \
  --jinja \
  --threads 12 \
  < /dev/null > "$LOG" 2>&1 &

PID=$!
echo "$PID" > "$PIDFILE"
echo "Processo iniciado com PID=$PID"
echo "Log: $LOG"

echo "Aguardando endpoint http://$HOST:$PORT/v1/models ficar pronto..."
for i in {1..120}; do
  if curl -sf -m 2 "http://$HOST:$PORT/v1/models" >/dev/null 2>&1; then
    echo "Pronto em ${i}s!"
    exit 0
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "ERRO: O processo $PID morreu precocemente. Últimas linhas do log:"
    tail -n 30 "$LOG"
    exit 1
  fi
  sleep 1
done

echo "ERRO: Timeout aguardando inicialização."
tail -n 30 "$LOG"
exit 1
