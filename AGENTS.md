# AGENTS.md — Bancada

Constituição do agente neste repo. O humano **só sobe / troca os modelos** (`llama-server`). Você (agente) roda benches, lê packets, otimiza suítes/código e devolve vereditos.

Branch de trabalho: `feat/bancada`. Workspace: este diretório.

---

## Divisão de trabalho

| Quem | Faz |
|------|-----|
| **Humano** | Sobe `llama-server` em `127.0.0.1:8080` (e opcional 8081/8082). Troca GGUF. Confirma `curl -s 127.0.0.1:8080/v1/models`. |
| **Agente** | `pytest`, `bancada health/run/list/export/ingest/diff/fetch`, julgar packets, melhorar suítes/scorers/CLI, commits atômicos. |

**Não** suba o modelo você mesmo a menos que o humano peça. **Não** bind `0.0.0.0`. **Não** chame API xAI/Grok de dentro do app — o juiz é o chat.

---

## Setup rápido

```bash
cd /home/cleiton/Vibe_coding/grok   # ou o path deste repo
pip install -e '.[dev]'
pytest                              # deve passar (rede zero)
curl -sS -m 3 http://127.0.0.1:8080/v1/models   # humano já deve ter o server
python -m bancada.cli health --endpoint http://127.0.0.1:8080/v1
python -m bancada.cli smoke --endpoint http://127.0.0.1:8080/v1  # valida 1 caso por suíte
```

Se `health` falhar: pare e peça ao humano para ativar o modelo. Não invente endpoint.

---

## Orquestrador: Grok no chat vs GLM Flash no OpenCode

O orquestrador estratégico e juiz de qualidade é o modelo no chat principal (Grok), que avalia rubricas de alto nível, decide trade-offs e julga os packets exportados sem viés de fluência. Tarefas operacionais de codificação rápida, refactors e execução de testes em loop fechado podem ser delegadas a modelos ágeis e econômicos (como GLM Flash no OpenCode), que atuam como implementadores atômicos sob a direção do orquestrador. O humano mantém-se focado estritamente na gestão do hardware e troca de GGUFs no llama-server.

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

## Teste prático contra o modelo (o que importa)

### Caminho recomendado

```bash
./scripts/practical_run.sh
# opcional: ./scripts/practical_run.sh skepticism,code
```

O script:

1. Checa `health`
2. Roda as suítes manuais com **nohup** (não morre se a sessão do agente cair)
3. Imprime progresso `[n/N] start|ok|fail`
4. No fim: `list` + exporta packet categorizado `reports/packet-<RUN_ID>.md`

Log ao vivo:

```bash
LOG=$(sed -n '2p' ~/.grok/long-running-background-tasks/bancada_practical.path)
tail -f "$LOG"
```

### Manual equivalente

```bash
python -m bancada.cli run \
  --endpoint http://127.0.0.1:8080/v1 \
  --suites skepticism,code,obsidian,tools \
  --no-imported \
  --db data/bancada.sqlite \
  --timeout 90 \
  --max-tokens 1024

python -m bancada.cli list --db data/bancada.sqlite
python -m bancada.cli export-judge RUN_ID --db data/bancada.sqlite --out reports/packet-RUN_ID.md
```

### Flags críticas

| Flag | Default | Por quê |
|------|---------|---------|
| `--max-tokens` | `1024` | Modelos “thinking” (ex.: Qwen3.5) sem teto estouram timeout |
| `--timeout` | `60` (script usa `90`) | Por caso |
| `--resume` | off | Retoma run incompleto para o mesmo `model_id` + `suite_versions` |
| `--no-imported` | — | Só suítes manuais PT-BR (~36 casos). Rápido o bastante pra comparar modelos |
| `--imported` | off | Soma HumanEval/BFCL/TruthfulQA/… depois do `fetch` |
| `--cap N` | none | Limita casos (manual **e** imported) |
| `--quiet` | off | Sem linhas `[n/N]` |

Ao final de cada `run` e `smoke`, a CLI imprime o resumo: `pass N/M (XX%) | p50: XX.Xms`.

Env do script: `BANCADA_ENDPOINT`, `BANCADA_DB`, `BANCADA_TIMEOUT`, `BANCADA_MAX_TOKENS`.

### Armadilhas (já quebraram runs)

1. **Timeout do harness do agente** matando `python -m bancada.cli run` em ~10 min → use `./scripts/practical_run.sh` (nohup) ou `nohup … &`.
2. **Log vazio até o fim** (versão antiga) → agora há progresso por caso; se não aparecer `[1/N] start`, algo está errado.
3. **Sem `saved <id>`** → processo morreu no meio; ver `tail -50` do log; não finja sucesso.
4. **GPU ocupada** → 1 geração por vez; não lance dois `run` em paralelo no mesmo `:8080`.

---

## Suítes e Categorias

As suítes são agrupadas em 4 categorias (peso 25% cada no `JUDGE.md`):

| Categoria | Suíte Manual | Suíte Importada | Mede |
|---|---|---|---|
| `codigo` | `code` | `humaneval` | Funções Python + `python_test` executável |
| `humanas` | `obsidian` | — | Nota limpa, `[[wikilinks]]`, não inventar matéria |
| `agentico` | `tools` | `bfcl` | `cron`/`exec` nanobot; recusa `rm -rf`; casos em 2 turnos |
| `ceticismo` | `skepticism` | `truthfulqa` | Premissa falsa, sycophancy, controles verdadeiros |

Casos de 2 turnos em `tools`: no turno 1 o modelo emite a chamada de ferramenta, o runner injeta a saída simulada (`fake_tool_response`) e, no turno 2, o modelo deve consumir a resposta ou recusar comandos perigosos.

### Importadas (`suites/imported/` após fetch)

```bash
python -m bancada.cli fetch
python -m bancada.cli run --suites code,tools,skepticism --imported --cap 20
```

Fontes pinadas em `data/manifest.yaml` (sha256 + teto 50 MB). **Não** clone SWE-bench / The Stack / APPS / BFCL v4 agentic (precisa web). BFCL **v3** simple+irrelevance é o recorte certo.

HumanEval: o scorer faz `setup` (prompt original) + completion; indent relativo é preservado.

---

## Julgar um run (você é o juiz)

Quando existir `reports/packet-*.md` ou o usuário colar o packet:

1. Leia `JUDGE.md` inteiro. Não invente rubrica.
2. Pontue cada caso **0–3** contra o gabarito.
3. Devolva o JSON do rodapé (`score` preenchido).
4. Feche com as 5 linhas de veredito do `JUDGE.md`.
5. Fluência ≠ acerto. Controles verdadeiros recusados = 0.

Persistir:

```bash
# salve o JSON do juiz em scores.json
python -m bancada.cli ingest-scores RUN_ID scores.json
python -m bancada.cli diff RUN_A RUN_B
```

---

## Otimizar (escopo permitido)

Prioridade sugerida depois de um run real:

1. **Suítes manuais** — casos fracos, gabaritos ambíguos, tools schemas.
2. **Scorers** — `python_test`, `tool_name` (modelos 9B às vezes não emitem `tool_calls` nativos → JSON no texto?).
3. **CLI UX** — progresso, resumo no fim (`pass N/M`, p50 ms).
4. **Caps / smoke** — modo “smoke” 1 caso por suíte pra validar endpoint rápido.
5. **Comparar dois modelos** — humano troca o GGUF; você roda de novo + `diff`.

Fora do escopo sem pedido explícito: UI React, orquestrar troca de GGUF, API Grok, MMLU/SWE-bench, embed/rerank.

---

## Layout

```
src/bancada/          # CLI, client, runner, scorers, store, fetch, adapters
suites/*.yaml         # manuais (git)
suites/imported/      # gerado por fetch
data/manifest.yaml    # urls + sha256 + caps
data/raw/             # cache fetch (gitignored)
data/bancada.sqlite   # runs (gitignored)
reports/              # packets exportados
scripts/practical_run.sh
JUDGE.md              # rubrica
tests/                # pytest, sem rede
```

---

## Checklist do agente ao “rodar bancada”

- [ ] `pytest` verde
- [ ] `curl` / `bancada health` OK (senão: pedir modelo ao humano)
- [ ] `./scripts/practical_run.sh` (ou `nohup` equivalente)
- [ ] Acompanhar log até `saved <id>`
- [ ] `export-judge` → ler packet → pontuar com `JUDGE.md`
- [ ] `ingest-scores` + `diff` se houver run anterior
- [ ] Commits atômicos se mudou código/suítes

Nunca declare “bench passou” sem `saved` + packet (ou output de `list`) colado.
