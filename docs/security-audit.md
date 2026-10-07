# Auditoria da GUI local — 2026-10-06

A investigação começou depois da conclusão funcional e da aprovação da revisão
geral, no commit `cb9e5af8ba6f24fbdcda7b85f04af3b4a5c82b0e`. Três investigadores
**Luna MAX**, com contextos separados para web, dados e recursos, apresentaram
evidências ao coordenador **GPT-6.1 Sol médio**. Luna não deu o julgamento final.
Um worker Luna high implementou as correções; Sol aprovou especificação e
qualidade no commit `4fd4c27cceed50e5b92a0f186c9d3aaf99ce163a`.

## Achados corrigidos

| Achado | Julgamento Sol | Correção |
| --- | --- | --- |
| Host externo recebia conteúdo de runs, apesar do bind em loopback | Médio: exposição condicional por DNS rebinding | Antes dos handlers e das leituras SQLite, aceitar apenas `localhost` ou `127.0.0.1`, com porta decimal válida opcional; rejeitar demais autoridades e ignorar `X-Forwarded-Host` |
| JSON salvo com 10.000 níveis escapava do tratamento de erros | Baixo: disponibilidade diante de conteúdo inválido no SQLite escolhido localmente | Tratar `RecursionError` em resultados, notas do juiz, versões e filtro de suíte, mantendo registros inválidos visíveis |

Histórico continua respondendo 200 com erros por registro; detalhe e comparação
de registros inválidos respondem 422. O teste de Host demonstrou aceitação
indevida por requisições sintéticas, não exploração real de DNS rebinding.
Exploração depende de navegação, DNS, porta e proteções do navegador.
Requisições comuns entre origens seguem a política de mesma origem, sem CORS
permissivo. Não foi encontrada rota HTTP para escrever payloads, escolher outro
banco, executar comandos ou inferência.

## Verificação das correções

- Ciclo RED/GREEN para Host e JSON. Correção da descrição do worker: `-k host`
  selecionou **17**, não todos os 18 casos de autoridade; o caso
  `127.0.0.1.evil.invalid` ficou fora desse RED. Sol executou a seleção completa
  de autoridade e JSON: **23 passaram**.
- Verificação independente: `pytest` — **253 passaram em 5,99 s**;
  `ruff check src tests`, `pip check` e `git diff --check` passaram.
- Wheel novo instalado fora do checkout: seis caminhos HTTP normais responderam
  200; os mesmos seis com Host externo responderam 400, inclusive com cabeçalho
  encaminhado de localhost. Resultados, versões e notas profundamente aninhados
  preservaram histórico/filtro 200 e detalhe/comparação 422. Bytes dos bancos
  sintéticos permaneceram iguais. O servidor do teste foi encerrado e recolhido,
  e sua porta ficou fechada.
- Wheel: `bancada-0.1.0-py3-none-any.whl`; SHA-256
  `fa6514a46cdd466b607ec7264e5914793ecb76bf2f5d43ff66bd90d37551b5eb`.
  Build a partir de `4fd4c27`, sem baixar dependências de build; cinco templates
  e dois arquivos estáticos no pacote. Documentação posterior não altera código.

A GUI foi validada antes em Chromium, incluindo histórico, detalhe, comparação e
largura móvel de 390 px; veja [a validação funcional](development-validation.md).
Estas correções não alteram o layout; essa rodada de browser não foi repetida.

## Memória e recursos

Ensaio na versão auditada inicial: SQLite sintético de 502 runs, 11.001 resultados
e 9.342.976 bytes; 20 requisições de aquecimento e 400 de medição, incluindo sucesso
e erro 422. Quatro caminhos instrumentados do leitor fecharam as conexões,
inclusive no erro de schema.

| Medida | Resultado observado |
| --- | --- |
| Memória Python viva após GC | 903,3 → 931,4 KiB; aumento de 28,1 KiB com incrementos decrescentes em cinco lotes |
| RSS | 47.140 → 47.156 KiB; estável nos cinco lotes |
| Descritores abertos | 4 em todas as medições |
| Métricas de run com 1.000 resultados | 30 chamadas, mediana 12,67 ms, p95 16,93 ms; exclui leitura e renderização |

Não foi confirmado vazamento prejudicial nesse ensaio. Ele não prova ausência
de vazamento em execução longa. Uma primeira medição que retinha registros do
instrumento foi descartada. Streams do cliente HTTP simulado foram fechados em
sucesso e erro. Timeout de subprocesso inofensivo ocorreu em aproximadamente
2,005 s, sem aumento de descritores.

## Limites e melhorias futuras

- Fixtures com HTML malicioso foram escapadas; travessias estáticas testadas
  retornaram 404. Lookup de ID foi parametrizado, arquivos ausentes não foram
  criados e nomes com espaços, `?` e `#` funcionaram. Evidência limitada aos casos.
- SQLite em modo WAL pode criar auxiliares `-wal` e `-shm` mesmo em conexão
  somente leitura; dados e schema principal não mudaram. Não se adotou
  `immutable`, que poderia prejudicar leitura de WAL ativo. Escritores
  concorrentes e frames WAL ativos não foram medidos.
- Histórico carrega payloads apenas da página de 25 runs, mas percorre todos os
  metadados para filtrar. Otimize se o histórico crescer; a amostra atual não
  justifica uma reformulação.
- Helpers CLI existentes não fecham explicitamente os clientes que criam.
  O término da CLI de um comando limita o efeito. Melhoria futura para uso
  embutido repetido; não foi demonstrado vazamento de sockets.
- O scorer Python existente executa código gerado com os privilégios do usuário.
  `-I`, diretório temporário e timeout **não são um sandbox de sistema operacional**.
  A GUI não chama esse executor; isolamento exigiria outro escopo.
- Não houve modelo, GPU, inferência, banco real, teste prolongado, exploração DNS
  real, matriz Flask 3.0 ou varredura abrangente de CVEs. Compatibilidade Flask 3.0
  usa APIs antigas; a execução foi com Flask 3.1.3. Orçamento permanece em
  53 casos manuais + 12 HumanEval, até 70 chamadas, sem prompts novos.

Relatórios completos, reproduções e julgamento original estão no pacote de
evidências da entrega. Novos testes baratos e candidatos a redundância permanecem
no [README](../README.md#recomendações-de-avaliação). Nenhum caso foi excluído sem
evidência de runs reais.
