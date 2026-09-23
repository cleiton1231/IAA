# AGENTS.md — Bancada

Constituição do agente neste repo. O humano **só sobe / troca os modelos** (`llama-server`). Você (agente) roda benches, lê packets, otimiza suítes/código e devolve vereditos.

Branch de trabalho: `feat/bancada`. Workspace: este diretório.

---

## Divisão de trabalho

| Quem | Faz |
|------|-----|
| **Humano** | Sobe `llama-server` em `127.0.0.1:8080` (e opcional 8081/8082). Troca GGUF. Confirma `curl -s 127.0.0.1:8080/v1/models`. |
| **Agente / OpenCode** | `pytest`, `bancada health/run/list/export/ingest/diff/fetch`, julgar packets compactos, melhorar suítes/scorers/CLI, commits atômicos. |

**Não** suba o modelo você mesmo a menos que o humano peça. **Não** bind `0.0.0.0`. **Não** chame API xAI/Grok de dentro do app — o juiz operacional é o **OpenCode** (LLM local) lendo o packet compacto.

---

## Setup rápido

```bash
cd /home/cleiton/Vibe_coding/grok
pip install -e '.[dev]'
pytest
curl -sS -m 3 http://127.0.0.1:8080/v1/models
python -m bancada.cli health --endpoint http://127.0.0.1:8080/v1
python -m bancada.cli smoke --endpoint http://127.0.0.1:8080/v1
```

Protocolo de bench: `temperature=0`, `seed=42` (override: `BANCADA_TEMP`, `BANCADA_SEED`). Scripts `start_llama_*.sh` e `practical_run.sh` já passam isso.

Se `health` falhar: pare e peça ao humano para ativar o modelo. Não invente endpoint.

---

## Testes automatizados (sempre antes de “pronto”)

```bash
pytest
ruff check src tests
```

- Fixtures em `tests/fixtures/` — **nenhum teste bate na rede**.
- TDD: comportamento novo → teste que falha → código mínimo → verde.
- Commits: `feat:`, `fix:`, `test:`, `docs:`.

---

## Teste prático contra o modelo

```bash
./scripts/practical_run.sh
# HumanEval (cap 12) entra por default quando a lista inclui code.
# Forçar off: BANCADA_IMPORTED=0 ./scripts/practical_run.sh
```

```bash
python -m bancada.cli run \
  --endpoint http://127.0.0.1:8080/v1 \
  --suites skepticism,code,obsidian,tools \
  --imported --imported-cap 12 \
  --db data/bancada.sqlite \
  --timeout 90 \
  --max-tokens 512 \
  --temperature 0 \
  --seed 42

python -m bancada.cli export-judge RUN_ID --db data/bancada.sqlite --out reports/packet-RUN_ID.md
# gera também reports/scores-RUN_ID-auto.json
```

Resumo: `pass N/M (XX%) | p50…` + linhas `enem_score` / `suspeito` / `fails: …`.

### Flags críticas

| Flag | Default | Por quê |
|------|---------|---------|
| `--temperature` | `0` | Determinismo |
| `--seed` | `42` | Determinismo (também no llama-server) |
| `--max-tokens` | `512` | Teto global; YAML por caso (código 384, texto 256, 2-turn 512) |
| `--timeout` | `60` (script usa `90`) | Por caso |
| `--no-imported` | — | Só manuais (v5, ~53 casos) |
| `--imported-cap` | `12` com `code` | Só o HumanEval. Não passar `--cap`: ele corta o YAML manual no começo |

---

## Suítes e Categorias

| Categoria | Suíte Manual | Suíte Importada | Mede |
|---|---|---|---|
| `codigo` | `code` | `humaneval` (cap 12) | Funções Python + `python_test` |
| `humanas` | `obsidian` | — | Nota limpa, `[[wikilinks]]` |
| `agentico` | `tools` | bfcl desabilitado | cron/exec; recusas; 2 turnos fake |
| `ceticismo` | `skepticism` | truthfulqa/falseqa off | Premissa falsa, sycophancy, controles |

```bash
python -m bancada.cli fetch   # só HumanEval por default
python -m bancada.cli run --suites code --imported --imported-cap 12
```

---

## Julgar um run (OpenCode)

1. Leia `JUDGE.md`.
2. Packet **compacto** (default): fails + `needs_judge`; auto-score já preenchido.
3. Pontue só `needs_judge` (0–3).
4. Mescle com `scores-<RUN>-auto.json` → `ingest-scores`.
5. Feche com as 5 linhas do `JUDGE.md` (sem nanobot).

```bash
python -m bancada.cli ingest-scores RUN_ID scores.json
python -m bancada.cli diff RUN_A RUN_B
```

`export-judge --full` = packet antigo completo (debug).

---

## Otimizar (escopo permitido)

1. Suítes manuais — gabaritos, tools schemas, `tool_args`.
2. Scorers — `python_test`, `tool_name`, `tool_args`, glob tmp.
3. CLI UX — progresso, tok/s, packet compacto.
4. HumanEval cap / smoke.
5. Comparar dois modelos — humano troca GGUF; você roda + `diff`.

Fora do escopo sem pedido: UI React, API Grok, MMLU/SWE-bench, sandbox real de exec, nanobot.

---

## Checklist ao “rodar bancada”

- [ ] `pytest` verde
- [ ] `curl` / `bancada health` OK
- [ ] `./scripts/practical_run.sh` (temp=0 seed=42)
- [ ] Log até `saved <id>`
- [ ] `export-judge` → OpenCode pontua → `ingest-scores`
- [ ] Commits atômicos se mudou código/suítes

Nunca declare “bench passou” sem `saved` + packet (ou `list`) colado.
