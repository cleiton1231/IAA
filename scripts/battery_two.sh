#!/usr/bin/env bash
# Bateria: ornith → qwen35-9b-q8, smoke + practical_run + diff.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
DIR="${HOME}/.grok/long-running-background-tasks"
SUITES="skepticism,code,obsidian,tools"
mkdir -p "$DIR" reports data

declare -A SCRIPT=(
  [ornith]="start_llama_ornith.sh"
  [qwen35-9b-q8]="start_llama_qwen35_9b_q8.sh"
)

declare -A GGUF=(
  [ornith]="/home/cleiton/local/models/ornith-1.5-9b-q8/Ornith-1.5-9B-Q8_0.gguf"
  [qwen35-9b-q8]="/home/cleiton/local/models/qwen3.5-9b-q8/Qwen3.5-9B-Q8_0.gguf"
)

# checa GGUFs antes de qualquer coisa
for id in ornith qwen35-9b-q8; do
  if [[ ! -f "${GGUF[$id]}" ]]; then
    echo "ERRO: GGUF não existe: ${GGUF[$id]}"
    exit 1
  fi
done

declare -A RUNIDS=()
FAILED_MODELS=()

for id in ornith qwen35-9b-q8; do
  echo ""
  echo "=== MODELO $id ==="
  ./scripts/stop_llama.sh || { echo "FALHA: stop_llama"; FAILED_MODELS+=("$id"); continue; }
  ./scripts/"${SCRIPT[$id]}" || { echo "FALHA: start $id"; FAILED_MODELS+=("$id"); continue; }

  echo "--- health $id ---"
  if ! python -m bancada.cli health --endpoint http://127.0.0.1:8080/v1; then
    echo "FALHA: health $id — não sigo para o run longo"
    FAILED_MODELS+=("$id")
    continue
  fi

  echo "--- smoke $id ---"
  if ! python -m bancada.cli smoke --endpoint http://127.0.0.1:8080/v1 --suites "$SUITES"; then
    echo "FALHA: smoke $id — não sigo para o run longo"
    FAILED_MODELS+=("$id")
    continue
  fi

  echo "--- practical_run $id ---"
  if ./scripts/practical_run.sh "$SUITES"; then
    rid="$(cat "$DIR/bancada_practical.last_run" 2>/dev/null || true)"
    RUNIDS[$id]="$rid"
    echo "RUN_ID[$id]=$rid"
  else
    echo "FALHA: run $id (sem saved)"
    FAILED_MODELS+=("$id")
  fi
done

echo ""
echo "=== LIST ==="
python -m bancada.cli list --db data/bancada.sqlite

R_ORN="${RUNIDS[ornith]:-}"
R_QWEN="${RUNIDS[qwen35-9b-q8]:-}"
if [[ -n "$R_ORN" && -n "$R_QWEN" ]]; then
  echo ""
  echo "=== DIFF $R_ORN vs $R_QWEN ==="
  python -m bancada.cli diff "$R_ORN" "$R_QWEN"
else
  echo "ERRO: run(s) incompleto(s): ornith=$R_ORN qwen=$R_QWEN"
fi

if [[ ${#FAILED_MODELS[@]} -gt 0 ]]; then
  echo ""
  echo "AVISO: modelos com falha no meio da bateria: ${FAILED_MODELS[*]}"
  exit 1
fi
exit 0
