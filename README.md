# Bancada

Régua pessoal para modelos locais (até ~32B quantizados). Você sobe o `llama-server`, a Bancada dispara as mesmas provas, e o **Grok no chat** pontua com gabarito. Sem leaderboard de desconhecido e sem gastar VRAM com juiz.

## Fluxo

```bash
pip install -e '.[dev]'

# 1. modelo já no ar
curl -s 127.0.0.1:8080/v1/models

bancada health --endpoint http://127.0.0.1:8080/v1

# 2. (opcional) fatias públicas, ~1–2 MB de download, teto 50 MB
bancada fetch

# 3. teste prático completo (recomendado: progresso + nohup)
./scripts/practical_run.sh
# ou manual:
bancada run --endpoint http://127.0.0.1:8080/v1 \
  --suites skepticism,code,obsidian,tools --no-imported \
  --max-tokens 1024

bancada list

# 4. cola o packet no Grok
bancada export-judge RUN_ID --out reports/packet.md

# 5. guarda o JSON que o Grok devolver
bancada ingest-scores RUN_ID scores.json
bancada diff RUN_A RUN_B
```

`bancada run` imprime `[n/N] start|ok|fail` por caso (use `--quiet` para silenciar). `--max-tokens` (default 1024) evita que modelos “thinking” esgotem o timeout.

O juiz lê `JUDGE.md`. Não inventa rubrica.

## Disco

| Fonte | Uso | Tamanho bruto | Cap default |
|-------|-----|---------------|-------------|
| HumanEval | código | ~45 KB gzip | 40 |
| BFCL simple + irrelevance | tools | ~440 KB | 20+20 |
| TruthfulQA | ceticismo | ~500 KB | 20 |
| FalseQA | premissa falsa | ~220 KB | 15 |
| small-llm-blind-spots | falhas de modelo pequeno | ~25 KB | 30 |

Cache típico `data/raw/`: **~1,2 MB**. Teto do manifesto: **50 MB** (`data/manifest.yaml`). Passou disso, o fetch aborta.

**Não baixamos:** SWE-bench, The Stack, APPS, MMLU, LiveCodeBench, 10k sycophancy, nenhum repositório-fonte.

## CLI

| Comando | Função |
|---------|--------|
| `bancada health` | GET `/v1/models` |
| `bancada fetch` | jsonl pinado por sha256 → `suites/imported/` |
| `bancada run --suites a,b [--imported] [--cap N]` | 1 geração por vez |
| `bancada export-judge RUN_ID` | Markdown para o Grok |
| `bancada ingest-scores RUN_ID scores.json` | persiste o veredito |
| `bancada diff A B` | pass-rate de máquina + média do juiz |

Endpoint default: `http://127.0.0.1:8080/v1`. Bind só em localhost.

## Layout

- `suites/*.yaml` — casos manuais (git)
- `suites/imported/` — gerado pelo fetch
- `data/manifest.yaml` — URLs + sha256 + caps
- `data/raw/` — cache gitignored
- `JUDGE.md` / `AGENTS.md` — rubrica do juiz no chat

## Testes

```bash
pytest
```

Fetch e adapters usam fixtures locais. **Nenhum teste bate na rede.**
