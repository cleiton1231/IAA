# Bancada

Régua pessoal para modelos locais (até ~32B quantizados). Você sobe o `llama-server`, a Bancada dispara as mesmas provas, e o **OpenCode** pontua o packet compacto. Sem leaderboard de desconhecido e sem gastar VRAM com juiz dedicado.

## Fluxo

```bash
pip install -e '.[dev]'

curl -s 127.0.0.1:8080/v1/models
bancada health --endpoint http://127.0.0.1:8080/v1

# opcional: só HumanEval (~45 KB), cap 12
bancada fetch

./scripts/practical_run.sh
# (com `code` na lista, importa HumanEval cap 12; BANCADA_IMPORTED=0 para desligar)
# ou:
bancada run --endpoint http://127.0.0.1:8080/v1 \
  --suites skepticism,code,obsidian,tools --imported --cap 12 \
  --temperature 0 --seed 42 --max-tokens 512

bancada list
bancada export-judge RUN_ID --out reports/packet.md
# → reports/packet.md + reports/scores-RUN_ID-auto.json

# OpenCode preenche needs_judge; ingest mescla auto+judge:
bancada ingest-scores RUN_ID scores.json
bancada diff RUN_A RUN_B
```

Defaults de bench: `temperature=0`, `seed=42`, `max-tokens=512` (env: `BANCADA_TEMP`, `BANCADA_SEED`, `BANCADA_MAX_TOKENS`). Cada caso YAML pode ter teto menor (`max_tokens`) e `difficulty` (facil/medio/dificil) para o placar ENEM.

O juiz lê `JUDGE.md`. Auto-score cobre `python_test`, replies vazias e recusas com args perigosos. Packet mostra `enem_score` (âncora facil=+3) e flag `suspeito`.

## Disco

| Fonte | Uso | Tamanho bruto | Cap default | Enabled |
|-------|-----|---------------|-------------|---------|
| HumanEval | código | ~45 KB gzip | 12 | sim |
| BFCL / TruthfulQA / FalseQA / blind-spots | — | — | — | **não** (urls no manifesto, fetch ignora) |

Cache típico `data/raw/`: **~45 KB** com só HumanEval. Teto: **50 MB**.

**Não baixamos:** SWE-bench, The Stack, APPS, MMLU, LiveCodeBench, BFCL v4 agentic.

## CLI

| Comando | Função |
|---------|--------|
| `bancada health` | GET `/v1/models` |
| `bancada fetch [--only id]` | fontes `enabled` do manifesto |
| `bancada run --suites a,b [--imported] [--cap N]` | 1 geração por vez |
| `bancada export-judge RUN_ID [--full]` | packet compacto + auto JSON |
| `bancada ingest-scores RUN_ID scores.json` | mescla auto+judge e persiste |
| `bancada diff A B` | machine_pass + enem + p50 tok/s + juiz |

Endpoint default: `http://127.0.0.1:8080/v1`. Bind só em localhost.

## Layout

- `suites/*.yaml` — casos manuais (git), **version 4** (~66 casos)
- `suites/imported/` — gerado pelo fetch
- `data/manifest.yaml` — URLs + sha256 + caps + enabled
- `JUDGE.md` / `AGENTS.md` — rubrica do juiz OpenCode

## Testes

```bash
pytest
ruff check src tests
```

Fetch e adapters usam fixtures locais. **Nenhum teste bate na rede.**
