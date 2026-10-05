#!/usr/bin/env bash
# MiMo-V2.6-Distill-Qwen-9B (Q8_0) via mainline llama-server (Vulkan).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"$SCRIPT_DIR/stop_llama.sh"

MODEL="/home/cleiton/local/models/mimo-v2.6-9b-q8/MiMo-V2.6-Distill-Qwen-9B-Q8_0.gguf"
PORT=8080
HOST="127.0.0.1"
TEMP="${BANCADA_TEMP:-0}"
SEED="${BANCADA_SEED:-42}"
# seed da série (aleatória por série, igual para todos os modelos)
source "$(dirname "$0")/series_seed.sh" >/dev/null
SEED="${BANCADA_SEED}"
CTX="${BANCADA_CTX:-8192}"
DIR="${HOME}/.grok/long-running-background-tasks"
LOG="${DIR}/llama_mimo_v26.log"
PIDFILE="${DIR}/llama_mimo_v26.pid"

mkdir -p "$DIR"

LLAMA_BIN="$HOME/Projetos/llama.cpp/build-vulkan-4da633776/bin/llama-server"

echo "Iniciando llama-server com MiMo-V2.6-Distill-Qwen-9B Q8_0 (ctx=$CTX temp=$TEMP seed=$SEED)..."
RADV_PERFTEST=nogttspill setsid "$LLAMA_BIN" \
  --model "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  -ngl 99 \
  --ctx-size "$CTX" \
  --jinja \
  -fa on \
  -ctk q8_0 \
  -ctv q8_0 \
  --temp "$TEMP" \
  --seed "$SEED" \
  < /dev/null > "$LOG" 2>&1 &

PID=$!
echo "$PID" > "$PIDFILE"
echo "Processo iniciado com PID=$PID"
echo "Log: $LOG"

echo "Aguardando endpoint http://$HOST:$PORT/v1/models ficar pronto..."
for i in {1..60}; do
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
