#!/usr/bin/env bash
# Gemma-4-12B agentic fable5 composer2.5 v2 (Q6_K) via mainline llama-server (Vulkan).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"$SCRIPT_DIR/stop_llama.sh"

MODEL="/home/cleiton/local/models/gemma4-v2-q6/gemma4-v2-Q6_K.gguf"
PORT=8080
HOST="127.0.0.1"
TEMP="${BANCADA_TEMP:-0}"
SEED="${BANCADA_SEED:-42}"
CTX="${BANCADA_CTX:-8192}"
DIR="${HOME}/.grok/long-running-background-tasks"
LOG="${DIR}/llama_gemma4_v2.log"
PIDFILE="${DIR}/llama_gemma4_v2.pid"

mkdir -p "$DIR"

LLAMA_LIBS="$(ls -d "$HOME"/Projetos/llama.cpp/build*/bin 2>/dev/null | head -1)"
if [ -n "$LLAMA_LIBS" ]; then
  export LD_LIBRARY_PATH="$LLAMA_LIBS${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

echo "Iniciando llama-server com Gemma-4-12B v2 Q6_K (ctx=$CTX temp=$TEMP seed=$SEED)..."
RADV_PERFTEST=nogttspill setsid /usr/local/bin/llama-server \
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
