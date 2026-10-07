# GUI local da Bancada e confiabilidade das avaliações

## Intenção e limites aprovados

O usuário usa a Bancada localmente para comparar modelos em uma Radeon RX 9060 XT
com 16 GB de VRAM e geração típica de aproximadamente 30 tokens/s. Quer consultar
o SQLite pelo navegador, entender estatísticas e comparar runs sem aumentar
substancialmente a duração dos benchmarks. Escolheu explicitamente uma primeira
versão somente para consulta e comparação e aprovou o desenho em conversa.

Superpowers deve orientar as tarefas deste projeto. Antes de modificar o produto,
foi criado o commit de segurança `48203b0edbfe6657eb6f881cfa3c02777eeb20f6`.
Nesse commit, `pytest` executou 146 testes com sucesso e `ruff check src tests`
passou. A ativação do modelo continua sendo responsabilidade do humano.

Esta especificação registra o desenho aprovado para revisão antes do plano de
implementação. Não representa uma GUI já implementada ou validada.

## Escopo

1. GUI local, somente leitura, para histórico, detalhe e comparação de runs.
2. Correções nos cinco pontos reproduzidos na revisão: validação do primeiro
   turno, formatos Obsidian, calendário, identidade das versões e retomada.
3. Testes automatizados com fixtures e banco temporário, sem modelo ou rede externa.
4. Documentação de instalação, uso e ponto de retorno.

Não serão adicionados prompts à bateria padrão, novos datasets, inferência pela
GUI, alteração automática de workers, exclusão de runs ou edição de SQL pelo
navegador. Os candidatos a redundância permanecem na bateria até uma avaliação
com histórico real demonstrar que vale removê-los. Os adaptadores desativados
permanecem disponíveis.

## Arquitetura

Usar Flask 3 como dependência opcional `gui`, com templates HTML e CSS/JavaScript
locais. Instalação: `pip install -e '.[dev,gui]'`. Não exigir Node, React, CDN,
acesso a APIs ou uma segunda instância de modelo. A CLI existente continua
funcionando sem instalar o extra; `gui` explica como instalá-lo quando ausente.

Entrada: `bancada gui --db data/bancada.sqlite --port 8765`. O comando resolve
o caminho do banco no início e inicia o servidor somente em `127.0.0.1`, sem
debug ou reloader. Não haverá opção de escutar em `0.0.0.0`. O navegador é aberto
manualmente; Ctrl+C encerra o servidor. Banco inexistente causa erro claro, sem
criar um arquivo vazio. Banco válido sem runs mostra estado vazio.

Separar três responsabilidades:

- Leitura: módulo específico abre SQLite com URI `mode=ro`, consulta parametrizada
  e conexão curta por requisição. Não chamar `_connect()` do store atual, que
  cria tabelas e pode executar migrações mesmo nas funções de consulta.
- Métricas: funções puras calculam resumos, agrupamentos e comparações, reutilizando
  `summarize_run` e os contratos Pydantic quando apropriado.
- Apresentação: aplicação Flask, templates e arquivos estáticos. A CLI importa
  essa aplicação somente quando o subcomando `gui` é escolhido.

Arquivos previstos: `src/bancada/gui/` com módulos de leitura, métricas e aplicação,
templates e estáticos; integração pequena em `cli.py`; extra em `pyproject.toml`;
testes específicos em `tests/`; instruções em `README.md`. Correções de avaliação
ficam nos módulos e suítes existentes relacionados a cada problema.

## Telas e navegação

### Histórico

Tabela paginada, 25 runs por página, ordenada pelo timestamp armazenado e ID.
Filtros por modelo, presença de uma suíte e seed; seleção de dois runs para comparar.
Colunas: modelo, ID abreviado, timestamp, casos registrados, aprovação automática,
nota do juiz quando disponível, velocidade mediana e seed. O ID completo permanece
visível no detalhe. Filtros e paginação usam parâmetros de URL.

O timestamp é identificado como o valor registrado pelo banco: o store atual usa
`INSERT OR REPLACE`, portanto o timestamp histórico não prova o início da execução.
Não inferir que um run terminou somente pela existência de resultados; mostrar
"casos registrados", pois o banco também recebe checkpoints e não tem status final.

### Detalhe

Mostrar configuração gravada (endpoint, versões, seed, temperatura, limite de tokens,
timeout e harness), métricas gerais, distribuição por categoria/dificuldade e motivos
de falha. Tabela de casos com filtros por suíte e resultado, ordenável por latência.
Ao abrir um caso: prompt, resposta, chamadas de ferramentas, primeiro turno quando
presente, verificações e justificativas do juiz. Conteúdo gerado é exibido como
texto escapado, sem executar HTML, Markdown arbitrário, Python ou comandos.

Gráficos simples locais para aprovação por categoria e qualidade versus velocidade,
com tabelas equivalentes, legendas e estados sem dados. Interface em português,
legível em desktop e telas menores, com foco e navegação por teclado.

### Comparação

Comparar configurações lado a lado e alinhar os resultados pelo ID do caso.
Exibir acertos mantidos, regressões, melhorias e casos presentes em apenas um run.
Calcular diferenças de qualidade sobre os casos em comum; manter também os resumos
individuais com seus denominadores. Não tratar casos ausentes como falha.

Destacar diferenças de seed, suítes/versões, temperatura, limites, timeout e harness.
Modelos diferentes são a comparação pretendida. Versões históricas potencialmente
sobrescritas ou configuração ausente geram aviso de comparabilidade não verificável.
Não impedir inspeção exploratória, nem apresentar configurações diferentes como
comparação controlada.

## Semântica das estatísticas

- Aprovação automática exige verificações existentes, todas aprovadas e nenhum erro.
  Uma verificação de formato aprovada não prova qualidade semântica.
- ENEM, risco, utilidade e suspeito preservam a definição atual. A interface explica
  que "risco" atualmente é uma taxa de aprovação das categorias correspondentes,
  e que categorias ausentes contribuem zero para utilidade.
- Nota do juiz mostra média e cobertura dos casos efetivamente pontuados; não
  transforma notas ausentes em zero. Identifica notas automáticas quando o payload
  tiver essa informação.
- Velocidade usa apenas medidas gravadas e apresenta p50 com número de amostras.
  Métricas ausentes aparecem como indisponíveis. Não estimar tokens com texto.
- Latência mostra p50/p95 do tempo por caso sem erro. Soma de tempos é identificada
  como tempo acumulado dos casos, não duração real do run com workers paralelos.
- Tokens somam contagens presentes, indicando cobertura quando parcial. Em casos
  de dois turnos a contagem já é somada, mas a velocidade existente corresponde
  ao segundo turno; identificar essa limitação.
- O campo legado `ttft_ms` recebe `prompt_ms`: exibir como tempo de processamento
  do prompt, não como tempo até o primeiro token. Não inventar TTFT verdadeiro.

## Compatibilidade e falhas

A GUI detecta colunas opcionais antes de consultá-las, usa defaults dos contratos
para campos históricos ausentes e não migra bancos antigos. Banco sem tabelas
esperadas ou corrompido produz mensagem compreensível. Payload inválido é indicado
como erro de leitura, sem ser contado como aprovado ou silenciosamente descartado.
Run desconhecido retorna 404; indisponibilidade temporária do banco pede nova
tentativa. O caminho do banco é definido na CLI, nunca recebido em uma requisição.
Não disponibilizar SQL arbitrário ou caminhos de arquivos via HTTP.

## Correções de avaliação, sem novas chamadas ao modelo

### Primeiro turno

Os cinco casos com saída fake de ferramenta passam a declarar verificações do
primeiro turno: ferramenta esperada, operação de leitura apropriada e ausência
de comandos destrutivos/escritas quando proibidos no prompt. Introduzir um campo
opcional de verificações iniciais no contrato de Case, com default vazio.
Verificar a resposta inicial antes de avaliar a final. As verificações iniciais
e finais entram no resultado agregado; nenhuma aprovação final pode esconder uma
falha inicial. Marcar a origem do turno nos checks novos para apresentação.
Manter mensagens nativas/fallback e a quantidade atual de chamadas. Runs históricos
sem esses checks não são reavaliados nem anunciados como cobertos no primeiro turno.

### Obsidian

Adicionar verificações determinísticas apenas para requisitos explícitos:
H1 em limpar-nota, H1 da data em diário e exatamente três pares Pergunta/Resposta
em flashcards. Exigir os wikilinks pedidos em limpar-nota, MOC e diário; uma
allowlist sozinha continua permitindo subconjuntos nos casos em que o prompt não
exige todos os links. Preservar o juiz para fidelidade e qualidade textual.
Variantes equivalentes de Markdown não devem ser rejeitadas por ornamentação.

### Calendário

Ampliar assertivas de `code.parse-ymd` com dia zero, dia 32, fevereiro inválido,
29/02 válido e inválido conforme ano bissexto, espaços e formato não estrito.
Não alterar o prompt ou aumentar tokens/chamadas; testar uma solução correta e
soluções inválidas que passam nas assertivas atuais.

### Identidade das versões

Manter a suíte/categoria dos casos importados como código, mas dar às suítes
carregadas uma identidade de versionamento distinta: `code` para manual e
`imported/code` para importada. Usar a mesma construção das identidades na CLI e
no runner para persistência e seleção de retomada. Não reescrever metadados
históricos: a versão manual perdida não pode ser reconstruída com certeza.

### Retomada

Ao usar `--resume`, exigir modelo, endpoint, mapa completo de versões, seed,
temperatura, limite de tokens, timeout e harness compatíveis com o pedido atual.
Não reutilizar run legado cuja configuração necessária esteja ausente. Se não
houver candidato compatível, iniciar um run novo e explicar a decisão. Preservar
reexecução dos casos com erro e evitar repetir casos compatíveis já registrados.

Suítes manuais cujo contrato de avaliação mudar recebem versão nova; a GUI destaca
essa diferença. Atualizar testes existentes que fixam versões para refletir a
mudança deliberada. Comparações antigas continuam disponíveis com aviso.

## Validação e orçamento

Aplicar TDD às alterações: regressões demonstram as falhas antes das correções;
fixtures positivas evitam verificações excessivamente restritas. Validar CLI,
filtros/paginação, estados vazio/erro, comparação com casos ausentes, métricas
parciais, conteúdo escapado e leitura de schema legado. Confirmar que as requisições
não modificam conteúdo/schema do banco, não criam banco inexistente e não chamam
o cliente de inferência. Testar retomada com configurações divergentes e preservar
as versões manual e importada na mesma execução.

Executar `pytest`, `ruff check src tests` e `pip check`. Iniciar a GUI com um banco
temporário contendo runs representativos, fazer requisições HTTP reais de histórico,
detalhe e comparação e inspecionar no navegador quando a capacidade estiver
disponível. Fixtures não são apresentadas como medições de modelos reais.

Não subir llama-server. Benchmark real depende do modelo ativado pelo usuário.
As 53 provas manuais e 12 HumanEval permanecem, com até 70 chamadas. No teto atual,
24.064 tokens de saída equivalem a aproximadamente 13,4 minutos a 30 tokens/s,
excluindo processamento de prompts, verificações, retries e demais custos. Não
prometer aceleração da GPU sem medição local. Novas assertivas e testes do software
não acrescentam inferências à bateria.

## Entrega e recuperação

Manter commits pequenos: dependências/GUI, correções de avaliação e documentação
podem ser revisados separadamente. Informar quais verificações foram executadas e
quais dependem do hardware local. O commit `48203b0` mantém o produto anterior à GUI.
Para inspecioná-lo sem apagar mudanças, o usuário pode usar
`git show 48203b0` ou `git switch --detach 48203b0` com working tree limpa.
Nunca executar reset destrutivo ou excluir o SQLite como parte da recuperação.

Se a GUI for instalada neste ambiente cloud, atualizar as instruções reutilizáveis
de instalação e startup após testar os novos comandos. Salvar o rascunho não
representa publicação; processos devem ser iniciados novamente em futuras tarefas.
