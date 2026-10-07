# Bancada

Régua pessoal para modelos locais (até ~32B quantizados). Você sobe o `llama-server`, a Bancada dispara as mesmas provas, e o **OpenCode** pontua o packet compacto. Sem leaderboard de desconhecido e sem gastar VRAM com juiz dedicado.

## Fluxo

```bash
pip install -e '.[dev,gui]'

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
| `bancada run --suites a,b [--imported] [--imported-cap N] [--workers N]` | 1 worker por padrão; `--workers N` habilita paralelismo explicitamente; cap só na suíte importada |
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

Passe o arquivo local em `--db`; caminhos relativos são resolvidos a partir do
diretório em que o comando começa. O servidor não cria um banco ausente. Bancos
antigos podem não ter todos os campos de configuração: a interface indica dados
ausentes e não migra o schema. Configurações ou versões históricas ausentes
impedem confirmar que dois runs são comparáveis.
O timestamp é o valor gravado no banco (o store pode substituir um run e atualizar
esse valor); ele não prova início, conclusão ou duração da execução. Retomada exige
configuração gravada compatível; banco legado sem esses campos não autoriza resume.

As taxas automáticas refletem apenas os checks determinísticos existentes; um
check de formato aprovado não mede fidelidade ou qualidade semântica. A nota do
juiz mostra média e cobertura dos casos pontuados. “Risco” é a taxa de aprovação
das categorias de risco, e categorias ausentes contam como zero para utilidade.
Velocidade usa somente medidas gravadas e mostra p50 com quantidade de amostras.
O tempo acumulado soma latências por caso e não é duração de parede quando há
workers paralelos. O campo legado `ttft_ms` guarda o tempo de processamento do
prompt, não o tempo até o primeiro token. Em casos de dois turnos, tokens incluem
os dois turnos enquanto a velocidade registrada corresponde ao segundo.

O painel rejeita cabeçalhos `Host` externos; use `localhost` ou `127.0.0.1`.
SQLite em modo WAL pode criar arquivos auxiliares mesmo em uma conexão somente
leitura. Resultados e limites da revisão de segurança e memória estão em
[docs/security-audit.md](docs/security-audit.md).
Correções e validação da revisão final de GUI, benchmarks e integração estão em
[docs/final-review.md](docs/final-review.md).

### Cloud (OpenRouter)

O client aceita endpoints API: `BANCADA_ENDPOINT`/`--endpoint` apontando para o provedor, `BANCADA_API_KEY` (chave via env, nunca comitada), `BANCADA_MODEL` e `BANCADA_EXTRA_BODY` (ex.: `{"reasoning":{"exclude":true}}` para no-think). Retry com backoff em 429/5xx embutido. Os provedores podem **ignorar seed** — runs via API não são comparáveis ao local dígito a dígito.

### Scripts

- `scripts/start_llama_*.sh` — sobem o `llama-server` por GGUF (Vulkan, temp/seed da série, ctx 8192)
- `scripts/series_seed.sh` — resolve a seed da série (ver acima)
- `scripts/practical_run.sh` — série completa: não sobe servidor; roda as suítes manuais versionadas + export do packet
- `scripts/battery_two.sh` — requer `scripts/start_llama_ornith.sh` local e executável, que não é distribuído neste repositório; valida ambos os launchers antes de criar diretórios de saída ou parar um servidor
- `scripts/stop_llama.sh` — para o server e libera a porta

## Layout

- `suites/*.yaml` — 53 casos manuais: `code` 17, `tools` 15, `obsidian` 8, `skepticism` 13; versões atuais: `code` 6, `tools` 7, `obsidian` 6, `skepticism` 5
- `suites/imported/` — gerado pelo fetch
- HumanEval importado tem identidade separada `imported/code` versão 1; o resultado continua na suíte/categoria `code`.
- `data/manifest.yaml` — URLs + sha256 + caps + enabled
- `JUDGE.md` / `AGENTS.md` — rubrica do juiz OpenCode
- `data/bancada.sqlite` — runs/resultados (não versionado; backup manual em `.old/`)

## Testes

```bash
pytest
ruff check src tests
```

Instale `.[dev,gui]` para executar a suíte completa; Flask continua opcional para
quem só usa a CLI e não precisa dos testes da interface. Fetch e adapters usam
fixtures locais. **Nenhum teste bate na rede ou inicia modelo.**

## Recomendações de avaliação

As correções desta rodada não fazem novas chamadas ao modelo: verificam o
primeiro turno dos cinco casos com ferramenta simulada, acrescentam checks
estruturais de Markdown/Obsidian e limites de calendário, separam as versões
manual e importada, e exigem a configuração gravada completa antes de retomar.
Runs históricos não são reavaliados; os que não registram configuração suficiente
não autorizam retomada automática.

Esta rodada não adicionou prompts nem aumentou a bateria padrão. O teto documentado
segue em 65 casos e até 70 chamadas, com até 24.064 tokens de saída quando todos
os limites globais são usados (cerca de 13,4 minutos a 30 tokens/s, sem contar
processamento dos prompts, retries, verificações e demais custos). Isso é uma
estimativa de orçamento, não uma medição da GPU ou de um modelo.

Antes de remover casos, compare o histórico por caso e versões de suíte. Dois
candidatos a investigação de redundância são `skepticism.fato-plantado` e
`skepticism.riscv-1990` (mesma afirmação falsa central, com contextos diferentes),
e `skepticism.notes-contradict` e `skepticism.contradict-short` (ambos pedem que
o modelo reconheça datas conflitantes). Eles permanecem ativos enquanto o
histórico real não mostrar que a distinção não agrega cobertura.

O scorer automático ainda verifica sinais explícitos e presença de conteúdo; ele
não julga por conta própria factualidade, fidelidade ou qualidade textual. Para
melhorar essa leitura sem crescer a bateria, priorize fixtures de regressão para
variantes de calendário, JSON de ferramentas e respostas factuais; use avaliação
pareada com seeds iguais e follow-up seletivo apenas nos casos que regredirem.
Não trate fixture sintética como resultado de benchmark real.

## Recuperação

O ponto anterior à GUI é o commit `48203b0edbfe6657eb6f881cfa3c02777eeb20f6`.
Para inspecioná-lo sem alterar a branch atual, use `git show 48203b0`; para
executar esse estado, use `git switch --detach 48203b0` com a working tree limpa.
Não apague o SQLite durante a recuperação. A validação desta instalação está
registrada em `docs/development-validation.md`.
