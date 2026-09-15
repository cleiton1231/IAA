#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"$SCRIPT_DIR/stop_llama.sh"

MODEL="/home/cleiton/local/models/ornith-1.5-9b-q8/Ornith-1.5-9B-Q8_0.gguf"
PORT=8080
HOST="127.0.0.1"
CTX=65536
DIR="${HOME}/.grok/long-running-background-tasks"
LOG="${DIR}/llama_ornith.log"
PIDFILE="${DIR}/llama_ornith.pid"

mkdir -p "$DIR"

echo "Iniciando llama-server com Ornith 1.5 9B Q8_0 (ctx=$CTX)..."
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
  < /dev/null > "$LOG" 2>&1 &

PID=$!
echo "$PID" > "$PIDFILE"
echo "Processo iniciado com PID=$PID"
echo "Log: $LOG"

echo "Aguardando endpoint http://$HOST:$PORT/v1/models ficar pronto..."
for i in {1..30}; do
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
