#!/usr/bin/env bash
# Ternary-Bonsai-2-27B PQ2_0 via binário pré-compilado do fork PrismML (Vulkan).
# Não rebuild, não ROCm. Binário separado de /usr/local/bin (mainline Vulkan).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"$SCRIPT_DIR/stop_llama.sh"

MODEL="/home/cleiton/local/models/ternary-bonsai-2-27b-ptq1/Ternary-Bonsai-2-27B-PTQ1_0.gguf"
BIN="/home/cleiton/local/prism-bin/llama-prism-b10685-7dffb15/llama-server"
PORT=8080
HOST="127.0.0.1"
CTX=8192
DIR="${HOME}/.grok/long-running-background-tasks"
LOG="${DIR}/llama_ternary_bonsai_ptq1.log"
PIDFILE="${DIR}/llama_ternary_bonsai_ptq1.pid"

mkdir -p "$DIR"

echo "Iniciando llama-server (fork PrismML b10685, Vulkan) com Bonsai-2-27B PQ2_0 (ctx=$CTX)..."
export LD_LIBRARY_PATH="/home/cleiton/local/prism-bin/llama-prism-b10685-7dffb15:${LD_LIBRARY_PATH:-}"
RADV_PERFTEST=nogttspill setsid "$BIN" \
  --model "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  -ngl 99 \
  --ctx-size "$CTX" \
  --jinja \
  --no-repack \
  < /dev/null > "$LOG" 2>&1 &

PID=$!
echo "$PID" > "$PIDFILE"
echo "Processo iniciado com PID=$PID"
echo "Log: $LOG"

echo "Aguardando endpoint http://$HOST:$PORT/v1/models ficar pronto..."
for i in {1..90}; do
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
