# Bancada

Régua pessoal para modelos locais (até ~32B quantizados). Você sobe o `llama-server`, a Bancada dispara as mesmas provas, e o **OpenCode** pontua o packet compacto. Sem leaderboard de desconhecido e sem gastar VRAM com juiz dedicado.

## Fluxo

```bash
pip install -e '.[dev]'

curl -s 127.0.0.1:8080/v1/models
bancada health --endpoint http://127.0.0.1:8080/v1

# opcional: só HumanEval (~45 KB), cap 12
bancada fetch

# seed: aleatória por série (series_seed.sh), igual para todos os modelos
# BANCADA_SEED=N fixa uma seed · BANCADA_NEW_SERIES=1 abre série nova
./scripts/practical_run.sh
# (com `code` na lista, importa HumanEval cap 12; BANCADA_IMPORTED=0 para desligar)
# workers paralelos: BANCADA_WORKERS=4 ./scripts/practical_run.sh
# ou:
bancada run --endpoint http://127.0.0.1:8080/v1 \
  --suites skepticism,code,obsidian,tools --imported --imported-cap 12 \
  --temperature 0 --max-tokens 512

bancada list
bancada export-judge RUN_ID --out reports/packet.md
# → reports/packet.md + reports/scores-RUN_ID-auto.json

# OpenCode preenche needs_judge; ingest mescla auto+judge:
bancada ingest-scores RUN_ID scores.json
bancada diff RUN_A RUN_B
```

Defaults de bench: `temperature=0`, `max-tokens=512` (env: `BANCADA_TEMP`, `BANCADA_MAX_TOKENS`). A **seed é por série**: `scripts/series_seed.sh` gera uma aleatória (1000–2³¹−1) e todos os modelos da série usam a mesma; a seed fica gravada no run (`runs.seed`). `BANCADA_SEED=N` fixa a série; `BANCADA_NEW_SERIES=1` abre outra. Cada caso YAML pode ter teto menor (`max_tokens`) e `difficulty` (facil/medio/dificil) para o placar ENEM.

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
| `bancada run --suites a,b [--imported] [--imported-cap N] [--workers N]` | 1 geração por vez; cap só na suíte importada |
| `bancada export-judge RUN_ID [--full]` | packet compacto + auto JSON |
| `bancada ingest-scores RUN_ID scores.json` | mescla auto+judge e persiste |
| `bancada diff A B` | machine_pass + enem + p50 tok/s + juiz + seed |

Endpoint default: `http://127.0.0.1:8080/v1`. Bind só em localhost.

### Painel local de runs

Instale a interface opcional e inicie o servidor somente para consulta:

```bash
pip install -e '.[dev,gui]'
bancada gui --db data/bancada.sqlite --port 8765
```

Abra `http://127.0.0.1:8765` no navegador e encerre com `Ctrl+C`. A interface
usa apenas loopback, lê o SQLite sem migrações e não executa modelos. O histórico
permite filtrar e paginar runs; os detalhes mostram métricas e casos; a comparação
alinha resultados pelo ID do caso e deixa visíveis diferenças de configuração e
denominadores. O extra `gui` não é necessário para os demais comandos da CLI.

### Cloud (OpenRouter)

O client aceita endpoints API: `BANCADA_ENDPOINT`/`--endpoint` apontando para o provedor, `BANCADA_API_KEY` (chave via env, nunca comitada), `BANCADA_MODEL` e `BANCADA_EXTRA_BODY` (ex.: `{"reasoning":{"exclude":true}}` para no-think). Retry com backoff em 429/5xx embutido. Os provedores podem **ignorar seed** — runs via API não são comparáveis ao local dígito a dígito.

### Scripts

- `scripts/start_llama_*.sh` — sobem o `llama-server` por GGUF (Vulkan, temp/seed da série, ctx 8192)
- `scripts/series_seed.sh` — resolve a seed da série (ver acima)
- `scripts/practical_run.sh` — série completa: sobe server? não; roda a régua v5 + export do packet
- `scripts/stop_llama.sh` — para o server e libera a porta

## Layout

- `suites/*.yaml` — casos manuais (git), **version 5** (~53 casos)
- `suites/imported/` — gerado pelo fetch
- `data/manifest.yaml` — URLs + sha256 + caps + enabled
- `JUDGE.md` / `AGENTS.md` — rubrica do juiz OpenCode
- `data/bancada.sqlite` — runs/resultados (não versionado; backup manual em `.old/`)

## Testes

```bash
pytest
ruff check src tests
```

Fetch e adapters usam fixtures locais. **Nenhum teste bate na rede.**
