#!/usr/bin/env bash
# Seed da série Bancada: decidida UMA vez por série, igual para todos os modelos.
#
# Prioridade:
#   1. BANCADA_SEED explícita — fixa a série (persiste no arquivo)
#   2. BANCADA_NEW_SERIES=1 — abre série nova (gera outra e persiste)
#   3. Arquivo $SERIES_DIR/bancada_series.seed existente — reusa
#   4. Nada disso — gera aleatória (1000..2147483647) e persiste
#
# Idempotente: source em qualquer ordem (start scripts e practical_run)
# resolve a MESMA seed dentro da série. A seed usada fica gravada no run (DB).
set -euo pipefail

SERIES_DIR="${BANCADA_SERIES_DIR:-${HOME}/.grok/long-running-background-tasks}"
SEED_FILE="${SERIES_DIR}/bancada_series.seed"
RANGE="${BANCADA_SEED_RANGE:-1000-2147483647}"

mkdir -p "$SERIES_DIR"

_generate() {
  shuf -i "$RANGE" -n 1
}

if [[ -n "${BANCADA_SEED:-}" ]]; then
  : # seed explícita vence e persiste abaixo
elif [[ "${BANCADA_NEW_SERIES:-0}" == "1" ]]; then
  BANCADA_SEED="$(_generate)"
elif [[ -s "$SEED_FILE" ]]; then
  BANCADA_SEED="$(cat "$SEED_FILE")"
else
  BANCADA_SEED="$(_generate)"
fi

echo "$BANCADA_SEED" > "$SEED_FILE"
export BANCADA_SEED
echo "series seed=$BANCADA_SEED"
