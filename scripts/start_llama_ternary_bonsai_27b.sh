#!/usr/bin/env bash
# Ternary-Bonsai-2-27B PQ2_0 via fork PrismML, CPU (ternary kernels não têm Vulkan/HIP aqui).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODEL="/home/cleiton/local/models/ternary-bonsai-2-27b-pq2/Ternary-Bonsai-2-27B-PQ2_0.gguf"
PRISM_DIR="/home/cleiton/ai/prism-b10743/llama-prism-b10743-adfffbe"
BIN="$PRISM_DIR/llama-server"
PORT=8080
HOST="127.0.0.1"
TEMP="${BANCADA_TEMP:-0}"
SEED="${BANCADA_SEED:-42}"
# seed da série (aleatória por série, igual para todos os modelos)
source "$(dirname "$0")/series_seed.sh" >/dev/null
SEED="${BANCADA_SEED}"
CTX="${BANCADA_CTX:-8192}"
DIR="${HOME}/.grok/long-running-background-tasks"
LOG="${DIR}/llama_ternary_bonsai_27b.log"
PIDFILE="${DIR}/llama_ternary_bonsai_27b.pid"

if [[ ! -r "$MODEL" ]]; then
  echo "ERRO: modelo não encontrado: $MODEL" >&2
  exit 1
fi
if [[ ! -x "$BIN" ]]; then
  echo "ERRO: llama-server PrismML não encontrado: $BIN" >&2
  exit 1
fi

"$SCRIPT_DIR/stop_llama.sh"
mkdir -p "$DIR"

echo "Iniciando llama-server (fork PrismML, CPU) com Ternary-Bonsai-2-27B PQ2_0 (ctx=$CTX temp=$TEMP seed=$SEED)..."
export LD_LIBRARY_PATH="$PRISM_DIR:${LD_LIBRARY_PATH:-}"
setsid "$BIN" \
  --model "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  --ctx-size "$CTX" \
  --jinja \
  --threads 12 \
  --temp "$TEMP" \
  --seed "$SEED" \
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
