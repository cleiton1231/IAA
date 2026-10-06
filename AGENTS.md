# AGENTS.md — Bancada

Constituição do agente neste repo. O humano **só sobe / troca os modelos** (`llama-server`). Você (agente) roda benches, lê packets, otimiza suítes/código e devolve vereditos.

Branch de trabalho: `feat/bancada`. Workspace: este diretório.

## Preferências do usuário — GUI local e Superpowers

- Use o plugin **Superpowers** nas tarefas deste projeto, aplicando as skills pertinentes antes de agir. Esta preferência foi registrada a pedido do usuário nesta sessão.
- Subagentes **Luna** são workers de implementação: esforço **high** por padrão, **max** quando necessário. Revisões e julgamentos são sempre responsabilidade de **Sol**; use **medium** nas revisões simples. Não delegue julgamento a Luna.
- O usuário autorizou uma GUI em **localhost** para consultar e comparar runs existentes no SQLite e suas estatísticas. Esse pedido amplia o escopo abaixo para incluir essa interface; a primeira versão não inicia benchmarks pelo navegador.
- Hardware informado: **Radeon RX 9060 XT, 16 GB de VRAM**, geração típica de **~30 tokens/s**. Preserve um orçamento curto para os benchmarks; priorize melhorar a cobertura dos casos existentes e testes automatizados sem inferência antes de aumentar a bateria de prompts.
- O modelo continua sob responsabilidade do humano. A GUI deve usar apenas loopback, e não iniciar `llama-server` nem ocupar VRAM para inferência.

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
pip install -e '.[dev,gui]'
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
| `--no-imported` | — | Só manuais (53 casos: code 17, tools 15, obsidian 8, skepticism 13) |
| `--workers` | `1` | Paralelismo só quando solicitado explicitamente e suportado pelo servidor |
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

### Painel local (somente leitura)

Instale o extra opcional com `pip install -e '.[dev,gui]'` e execute
`bancada gui --db data/bancada.sqlite --port 8765`. A GUI escuta apenas em
`127.0.0.1`; abra `http://127.0.0.1:8765` manualmente e encerre com Ctrl+C.
O caminho do SQLite é escolhido na CLI. Banco ausente causa erro e não é criado;
banco válido vazio mostra estado vazio. Não há migração automática de schema.

O histórico exibe o timestamp gravado no banco, não a duração ou conclusão do
run. A aprovação automática exige checks existentes aprovados e nenhum erro; isso
não prova qualidade semântica. Nota do juiz mostra cobertura, risco é uma taxa de
aprovação das categorias correspondentes e categoria ausente conta zero para
utilidade. Velocidade usa medidas armazenadas e amostras identificadas; latência
acumulada não representa duração real com workers paralelos. O `ttft_ms` legado
representa processamento do prompt. Nos casos de dois turnos, tokens são somados,
mas a velocidade gravada é a do segundo turno. Payload gerado é mostrado como
texto escapado; a interface não executa modelos, SQL ou conteúdo do run.

Em bancos antigos, versões ou campos de configuração ausentes deixam a
comparabilidade inconclusiva. O mapa atual de versões é `code` 6, `tools` 7,
`obsidian` 6, `skepticism` 5; HumanEval é `imported/code` 1 e mantém
suíte/categoria `code`.
Metadados históricos não são reescritos. `--resume` só seleciona runs que gravaram
modelo, endpoint, mapa completo de versões, seed, temperatura, limite de tokens,
timeout e harness compatíveis; config ausente em banco antigo não autoriza retomada.

## Otimizar (escopo permitido)

1. Suítes manuais — gabaritos, tools schemas, `tool_args`.
2. Scorers — `python_test`, `tool_name`, `tool_args`, glob tmp.
3. CLI UX — progresso, tok/s, packet compacto.
4. HumanEval cap / smoke.
5. Comparar dois modelos — humano troca GGUF; você roda + `diff`.

Fora do escopo sem pedido: UI React, API Grok, MMLU/SWE-bench, sandbox real de exec, nanobot.

---

## Checklist ao “rodar bancada”

- [ ] `pytest` verde (instale `.[dev,gui]`, pois a suíte também valida a GUI)
- [ ] `curl` / `bancada health` OK
- [ ] `./scripts/practical_run.sh` (temp=0 seed=42)
- [ ] Log até `saved <id>`
- [ ] `export-judge` → OpenCode pontua → `ingest-scores`
- [ ] Commits atômicos se mudou código/suítes

Nunca declare “bench passou” sem `saved` + packet (ou `list`) colado.

### Recomendações e recuperação

Esta entrega não acrescenta prompts. O teto segue em 65 casos, até 70 chamadas e
24.064 tokens de saída no limite de 512 (aproximadamente 13,4 minutos a 30 tok/s,
sem processamento de prompt, retries ou demais custos); não é medição de GPU.
Investigue `skepticism.fato-plantado`/`skepticism.riscv-1990` e
`skepticism.notes-contradict`/`skepticism.contradict-short` como candidatos a
redundância, mas mantenha-os até comparar histórico real por caso. Priorize
fixtures para variantes de calendário, JSON de ferramentas e factualidade; use
seeds pareadas e follow-up seletivo para regressões. Os checks atuais não medem
automaticamente fidelidade ou semântica e fixture sintética não é bench real.

O ponto de retorno pré-GUI é `48203b0edbfe6657eb6f881cfa3c02777eeb20f6`.
Inspecione com `git show 48203b0`; para executá-lo, use `git switch --detach
48203b0` após deixar a working tree limpa. Nunca exclua o SQLite para recuperar.
