#!/usr/bin/env bash
# Coletor leve de sensores da GPU AMD (RX 9060 XT) durante o bench.
# Amostra a cada INTERVAL s (default 5), escreve CSV, controlado por DURAÇÃO (s) ou até matar.
# Uso: gpu_sensors.sh <arquivo.csv> [intervalo_s] [duracao_s]
set -euo pipefail

OUT="${1:?arquivo csv}"
INTERVAL="${2:-5}"
DUR="${3:-0}"   # 0 = até morrer
CARD="/sys/class/drm/card1/device"

ts() { date +%s.%N; }
read_sys() { cat "$1" 2>/dev/null | tr -d ' \n' || echo "NA"; }

# métricas do lm-sensors (edge/junction/mem/fan/PPT)
sens() {
  sensors amdgpu-pci-0300 2>/dev/null
}

echo "ts,gpu_busy_pct,vram_gib,gtt_gib,edge_c,junction_c,mem_c,fan_rpm,ppt_w,vddgfx_mv" > "$OUT"
start=$(date +%s)
while :; do
  T=$(ts)
  BUSY=$(read_sys "$CARD/gpu_busy_percent")
  VRAM=$(awk '{printf "%.2f", $1/1073741824}' < "$CARD/mem_info_vram_used" 2>/dev/null || echo NA)
  GTT=$(awk '{printf "%.2f", $1/1073741824}' < "$CARD/mem_info_gtt_used" 2>/dev/null || echo NA)
  S=$(sens)
  EDGE=$(echo "$S" | awk -F'+' '/^edge:/ {gsub("[^0-9.]","",$2); print $2+0}' | head -1)
  JUNC=$(echo "$S" | awk -F'+' '/^junction:/ {gsub("[^0-9.]","",$2); print $2+0}' | head -1)
  MEMT=$(echo "$S" | awk -F'+' '/^mem:/ {gsub("[^0-9.]","",$2); print $2+0}' | head -1)
  FAN=$(echo "$S" | awk '/^fan1:/ {gsub("[^0-9]","",$2); print $2}' | head -1)
  PPT=$(echo "$S" | awk '/^PPT:/ {gsub("[^0-9.]","",$2); print $2+0}' | head -1)
  VDD=$(echo "$S" | awk '/^vddgfx:/ {print $2}' | head -1)
  echo "$T,$BUSY,${VRAM:-NA},${GTT:-NA},${EDGE:-NA},${JUNC:-NA},${MEMT:-NA},${FAN:-NA},${PPT:-NA},$VDD" >> "$OUT"
  [ "$DUR" != "0" ] && [ $(( $(date +%s) - start )) -ge "$DUR" ] && break
  sleep "$INTERVAL"
done
