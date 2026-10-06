# Revisão final — 2026-10-06

O coordenador **GPT-6.1 Sol médio** julgou as evidências de três investigadores
**Luna high**, separados por GUI, benchmarks e integração. Um worker Luna high
implementou as correções; Sol aprovou especificação e qualidade no commit
`ab223155d92e679dbdfe7289c2d44ff01042fe1d`, após as regressões e revisões dos
ajustes. Não restou bloqueio crítico ou importante confirmado no escopo revisado.
O trabalho seguiu as skills de revisão, diagnóstico e verificação do Superpowers.

## Correções aprovadas

| Área | Comportamento final |
| --- | --- |
| Identidade das notas | `ingest-scores` e `save_scores` rejeitam `run_id` declarado inválido ou de outro run antes de alterar o banco. A CLI também verifica a identidade das notas existentes antes de mesclar. Arquivos legados sem `run_id` continuam aceitos. |
| Estatísticas da GUI | O detalhe exibe risco, utilidade e indicador de resultado suspeito, com cobertura e evidência insuficiente explícitas. As fórmulas existentes foram preservadas. |
| Checks de cron | `tool_field` verifica a ferramenta e o argumento correto, data ISO válida e instante esperado. Rejeita datas relativas, componentes inválidos de offset e overflow sem abortar o caso. Conteúdo JSON/XML dentro de argumentos não é promovido a uma chamada independente; chamadas irmãs válidas continuam aceitas. |
| Endpoint efetivo | A prioridade é flag explícita, variável `BANCADA_ENDPOINT` não vazia e default local. Cliente injetado mantém prioridade; resume usa o endpoint efetivo normalizado. |
| Scripts de bateria | O preflight verifica launchers executáveis antes de criar saídas ou parar/iniciar servidores. O launcher Ornith precisa existir localmente, conforme o README. A bateria não foi executada nesta revisão. |

A suíte `tools` passou à versão **7** porque seu contrato de avaliação mudou.
As demais identidades permanecem `code` 6, `obsidian` 6, `skepticism` 5 e
`imported/code` 1. Metadados e resultados históricos não foram reescritos.

## Evidência de validação

A verificação independente do coordenador principal, no código aprovado, executou:

- `pytest`: **282 testes passaram em 6,36 s**, sem falhas ou skips.
- `ruff check src tests`, `pip check`, `git diff --check` e `bash -n` dos dois
  scripts alterados: passaram.
- Comparação com o checkpoint pré-GUI: IDs, prompts, schemas de ferramentas,
  respostas simuladas, prompts do segundo turno e limites de tokens preservados.
  O orçamento segue em **53 casos manuais + 12 importados, até 70 chamadas e
  24.064 tokens de saída**, com limite global de 512.

Sol executou separadamente 13 regressões selecionadas e uma matriz com sete
negativos rejeitados e nove formatos válidos aceitos, usando os checks reais da
suíte carregada. Essas seleções se sobrepõem à suíte completa; não são somadas
aos 282 testes.

Um wheel novo foi construído a partir do código aprovado, contendo cinco
templates e dois arquivos estáticos, e instalado fora do checkout. SHA-256:

```text
791bbf419b196560b99e5a63e20a7c8c80274b3d96d7ff72befe1ea12424893b
```

No pacote instalado, fixtures confirmaram rejeição de notas de outro run,
compatibilidade legada, valores dos agregados, endpoint e os limites de cron.
As regressões anteriores de Host e JSON profundamente aninhado também passaram:
seis caminhos HTTP normais responderam 200; os mesmos caminhos com Host externo
responderam 400; registros com JSON inválido mantiveram histórico/filtro 200 e
detalhe/comparação 422.

Chromium abriu o detalhe afetado em desktop e celular de **390 px**. Os três
agregados foram encontrados, não houve erros JavaScript e a largura do documento
móvel permaneceu 390 px. As duas capturas foram inspecionadas visualmente.
Os bancos usados eram sintéticos, seus bytes foram preservados e os servidores
iniciados pela validação foram encerrados e recolhidos, com as portas fechadas.

## Limites e próximos ganhos

Não houve inferência, inicialização de modelo, medição de GPU ou uso do banco
real. O orçamento preservado não demonstra velocidade real de execução.
Os checks estruturais não substituem julgamento semântico; o fallback textual
não é um parser geral ou sandbox de execução.

A [auditoria anterior de segurança e recursos](security-audit.md) mantém seus
limites: ensaio de memória finito, auxiliares SQLite WAL possíveis, histórico
percorrendo metadados de todos os runs e fechamento explícito do cliente CLI como
melhoria futura. Esta rodada não repetiu o ensaio de memória nem uma exploração
real de DNS rebinding.

As [recomendações do README](../README.md#recomendações-de-avaliação) priorizam
fixtures sem inferência e comparação de histórico antes de remover casos
possivelmente redundantes. A revisão não demonstrou que esses casos são inúteis.
A consulta e comparação atuais atendem ao escopo aprovado; não foram ampliadas.

O checkpoint pré-GUI continua sendo `48203b0`; o estado anterior a esta revisão é
`fabf23f`. Os commits são locais. Os backups desta entrega preservam ambos; não
houve push ou merge remoto.
