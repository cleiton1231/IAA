#!/usr/bin/env bash
# Run Bancada against a live llama-server without dying under tool timeouts.
# Usage: ./scripts/practical_run.sh [suites]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SUITES="${1:-skepticism,code,obsidian,tools}"
ENDPOINT="${BANCADA_ENDPOINT:-http://127.0.0.1:8080/v1}"
DB="${BANCADA_DB:-data/bancada.sqlite}"
DIR="${HOME}/.grok/long-running-background-tasks"
mkdir -p "$DIR" reports data
LOG="$DIR/bancada_practical_$$.log"
PIDFILE="$DIR/bancada_practical.pid"

echo "health…"
python -m bancada.cli health --endpoint "$ENDPOINT"

# stop previous practical run if still alive
if [[ -f "$PIDFILE" ]]; then
  old="$(cat "$PIDFILE" || true)"
  if [[ -n "${old:-}" ]] && kill -0 "$old" 2>/dev/null; then
    kill "$old" 2>/dev/null || true
    sleep 1
    kill -9 "$old" 2>/dev/null || true
  fi
fi

echo "starting run suites=$SUITES log=$LOG"
# nohup so the tool wrapper timeout cannot kill the bench
nohup python -m bancada.cli run \
  --endpoint "$ENDPOINT" \
  --suites "$SUITES" \
  --no-imported \
  --db "$DB" \
  --timeout "${BANCADA_TIMEOUT:-90}" \
  --max-tokens "${BANCADA_MAX_TOKENS:-1024}" \
  >"$LOG" 2>&1 &
echo $! >"$PIDFILE"
PID="$(cat "$PIDFILE")"
printf '%s\n%s\n' "$PID" "$LOG" >"$DIR/bancada_practical.path"
echo "pid=$PID"

LAST=""
# wait until saved line appears or process dies
while true; do
  if grep -qE '^saved [0-9a-f]+$' "$LOG" 2>/dev/null; then
    RUN_ID="$(grep -E '^saved [0-9a-f]+$' "$LOG" | tail -1 | awk '{print $2}')"
    echo "DONE saved $RUN_ID"
    python -m bancada.cli list --db "$DB"
    OUT="reports/packet-${RUN_ID}.md"
    python -m bancada.cli export-judge "$RUN_ID" --db "$DB" --out "$OUT"
    echo "packet=$OUT"
    echo "$RUN_ID" >"$DIR/bancada_practical.last_run"
    exit 0
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "FAILED: process $PID exited before saved"
    tail -50 "$LOG" || true
    exit 1
  fi
  LINE="$(tail -1 "$LOG" 2>/dev/null || true)"
  if [[ -n "$LINE" && "$LINE" != "$LAST" ]]; then
    echo "$LINE"
    LAST="$LINE"
  fi
  sleep 10
done
