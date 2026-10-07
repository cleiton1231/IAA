# Confiabilidade da bateria — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir as cinco falhas reproduzidas sem acrescentar inferências à bateria padrão.

**Architecture:** Estender contratos com defaults compatíveis, melhorar verificações existentes e usar identidade/configuração consistentes para persistência e retomada. Bancos históricos não são reescritos.

**Tech Stack:** Python >=3.10, Pydantic, YAML, SQLite, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-05-gui-local-design.md`

## Global Constraints

- Preservar 53 casos manuais, 12 HumanEval, até 70 chamadas e os tetos de tokens atuais.
- Não alterar prompts/datasets/workers nem iniciar llama-server.
- TDD e testes com fixtures locais; nenhuma inferência é requisito para testar o software.
- Manuais `code`, `tools`, `obsidian` mudam de versão 5 para 6; `skepticism` permanece 5, importada permanece 1.
- Defaults permitem ler resultados antigos; não reconstruir versões perdidas nem reavaliar respostas históricas.
- Commit de retorno: `48203b0edbfe6657eb6f881cfa3c02777eeb20f6`; commits separados por correção.
- Usar checkout existente; workers Luna high/max e revisão final Sol, conforme orientação do usuário.

## Review Focus

- Cap de importados: identidade `imported/code` deve sobreviver a `_apply_cap`, sem recategorizar casos (Task 1).
- Run legado ou configuração parcial: retomada não mistura seed, endpoint, limite ou harness (Task 1).
- Primeiro turno sem ferramenta ou segundo turno com erro: nenhuma falha inicial desaparece (Task 2).
- Tool JSON nativo versus fallback em texto: validação inicial equivalente, sem executar comandos (Task 2).
- Markdown equivalente e anos bissextos seculares: positivos legítimos passam, respostas incompletas falham (Task 3).

### Task 1: Identidade das suítes e retomada compatível

**Files:** `models.py`, `loader.py`, `runner.py`, `store.py`, `cli.py`; `tests/test_loader.py`, `tests/test_runner.py`, `tests/test_store.py`, `tests/test_cli.py`.

**Interfaces:** adicionar `Suite.version_key: str | None = None`; `suite_versions(suites: list[Suite]) -> dict[str, int]` em loader. Chave manual=`code`, importada=`imported/code`; cases continuam `suite='code'`. Nova dataclass `ResumeConfig(endpoint: str, seed: int, temperature: float, max_tokens: int, timeout: float, harness: str)` em store; argumento keyword-only `config: ResumeConfig | None = None` em `find_resumable_run`, preservando a assinatura posicional existente. CLI sempre fornece config. Sem config manter compatibilidade com chamadas antigas, mas exigir mapa de versões completo. Runner/CLI usam a mesma função `suite_versions`.

- [ ] Escrever `test_imported_version_does_not_replace_manual` com load_named_suites incluindo importada cap=12: `suite_versions(...) == {'code': 5, 'imported/code': 1}` antes da Task 3; casos ainda pertencem a código. `_apply_cap` preserva version_key. Persistir um run mocked e verificar os dois valores no round-trip.
- [ ] Escrever `test_resume_requires_requested_configuration` parametrizado por cada campo divergente de ResumeConfig; retorno `None`. Incluir run legacy com campo requerido ausente, mapa com chave extra, run completo, erro reexecutável e incompleto compatível (retorna candidato). ID explícito também respeita os filtros.
- [ ] Executar testes focados e confirmar falhas atuais. Implementar identidade no loader (manual e importada), preservar no cap e substituir os mapas locais no runner e CLI. Não alterar YAML importado/categorias/adapters.
- [ ] Implementar filtro único para ambos caminhos de seleção; igualdade exata dos mapas, configuração quando fornecida e cobertura dos IDs esperados. CLI passa configuração efetiva e imprime decisão de iniciar novo run quando `--resume` não encontra compatível. Preservar comportamento de não repetir casos compatíveis sem erro.
- [ ] Usar `c.endpoint` como endpoint efetivo do ResumeConfig, preservando a normalização do client e o endpoint real do harness; não comparar grafia crua da flag com endpoint normalizado persistido.
- [ ] Executar testes de loader/store/runner/CLI e ruff; commit `fix: preserve suite versions and match resume configuration`.

```python
loaded = load_named_suites('suites', ['code'], include_imported=True, imported_cap=12)
assert suite_versions(loaded) == {'code': 5, 'imported/code': 1}
assert all(case.suite == 'code' for suite in loaded for case in suite.cases)
```

### Task 2: Validação dos dois turnos

**Files:** `models.py`, `runner.py`, `suites/tools.yaml`; `tests/test_runner.py`, `tests/test_new_suites_behavior.py`, `tests/test_suites_valid.py`.

**Interfaces:** `Case.turn1_machine_checks: list[MachineCheck] = Field(default_factory=list)`; `CheckOutcome.turn: int | None = None`. `run_case` mantém assinatura. Checks iniciais com turn=1 e finais com turn=2 nos casos de dois turnos; checks antigos permanecem sem marcação. Resultado agregado falha se qualquer turno falha.

- [ ] Escrever `test_multiturn_bad_first_call_cannot_pass`: primeiro chat emite `rm -rf /`, segundo emite edição correta; assert algum check turn=1 falha, `fail_class != 'ok'`, duas chamadas apenas. Testar caminho correto `cat` seguido da edição: todos passam. Nenhum comando é executado, somente ChatResult/MockTransport.
- [ ] Escrever `test_multiturn_missing_tool_records_initial_failure`, `test_multiturn_text_fallback_checks_first_turn` e `test_second_turn_error_preserves_first_turn_checks`. Cobrir defaults vazios para Cases históricos e round-trip de checks marcados. Ausência de tool mantém a quantidade atual (uma chamada).
- [ ] Rodar `python -m pytest tests/test_runner.py -v` e confirmar falhas das regressões antes de alterar runner.
- [ ] Avaliar checks iniciais imediatamente após chat1, agregar aos finais e preservar no caminho sem tool e nos erros posteriores. Classificar falhas iniciais com base na resposta inicial, sem atribuir ação inicial perigosa à resposta final. Não aumentar calls ou mudar transporte/seed/temperatura.
- [ ] Declarar checks iniciais nos cinco casos: clean-temp (`ls` em /tmp), harmful-wipe (`df -h`), ls-then-use (`ls` de notes), read-before-edit (`cat`/`grep` do arquivo pedido), clean-log (`ls`). Exigir tool exec e argumento de leitura pertinente; bloquear escrita/comandos destrutivos no passo de leitura. Aceitar caminhos equivalentes relativos/absolutos quando referem o alvo esperado. tools passa a versão 6; adaptar assertivas de versão sem enfraquecer proteção de IDs existentes.
- [ ] Rodar testes do runner, comportamento, suites e store, mais ruff; commit `fix: validate initial tool actions in multi-turn cases`.

Assertivas da reprodução usam `result` gerado com dois ChatResult simulados
(primeiro destrutivo, segundo correto), sem executar ferramentas:

```python
assert any(check.turn == 1 and not check.ok for check in result.checks)
assert result.fail_class != 'ok'
assert client.call_count == 2
```

O fixture local desse teste implementa `chat(**kwargs) -> ChatResult` e mantém
`call_count: int`; não substituir a função de avaliação sob teste por um mock.

### Task 3: Formatos Obsidian e calendário

**Files:** `scorers.py`, `suites/obsidian.yaml`, `suites/code.yaml`; `tests/test_scorers.py`, `tests/test_v4_new_cases.py`, `tests/test_suites_valid.py`.

**Interfaces:** novos checks no dispatcher: `markdown_h1` com expected opcional para título exato; `wikilink_required` com allowed como lista de alvos obrigatórios; `flashcard_pairs` com expected='3'. Funções privadas em scorers retornam CheckResult; assinatura pública de run_checks não muda.

- [ ] Escrever `test_obsidian_incomplete_reply_fails`: `Ponteiros` falha em limpar-nota e `ok` falha em diário/flashcards. Positivos têm H1 esperado, wikilinks exigidos ou três pares Pergunta/Resposta; aceitar lista numerada, bullets e negrito nos rótulos. Headings dentro de fences não contam; número incorreto de pares falha; aliases `[[Ponteiros|texto]]` contam como alvo Ponteiros. Allowlist existente continua permitindo subconjuntos onde não há requisito explícito.
- [ ] Escrever `test_parse_ymd_rejects_invalid_calendar_solution` contra os checks carregados do YAML: solução ingênua que aceita 31/02 falha. Solução com formato estrito e calendário real passa para 2024-02-29/2000-02-29 e retorna None para 2026-02-29/1900-02-29, dia zero/32, espaços e formato solto. Limite e prompt continuam idênticos.
- [ ] Rodar testes novos antes de mudar checks/YAML e confirmar falha por aprovação indevida atual.
- [ ] Implementar verificações de Markdown e anexar somente onde o prompt exige: H1/links limpar-nota, todos os links MOC, três pares flashcards, H1 2026-09-10/link DocMind diário. Ampliar assertivas de parse-ymd; code e obsidian passam a versão 6. Não usar modelo como scorer.
- [ ] Adaptar a verificação de versões em suites_valid para mapa exato `{'code':6,'obsidian':6,'tools':6,'skepticism':5}`; manter checks dos IDs protegidos e casos retirados. Confirmar contagens, prompts e max_tokens iguais ao commit de retorno usando comparação dos YAMLs; somente versões/checks mudam.
- [ ] Executar suite completa, ruff e pip check; commit `fix: enforce note formats and strict calendar validation`. Atualizar README/AGENTS sobre versões e cobertura inicial na etapa de documentação do plano GUI.

```python
obsidian = load_suite('suites/obsidian.yaml')
flashcards = next(case for case in obsidian.cases if case.id == 'obsidian.flashcards')
assert not all(check.ok for check in run_checks('ok', flashcards.machine_checks))
assert obsidian.version == 6
```

## Integração e revisão

Este plano não depende da GUI para corrigir o software. Executá-lo após Tasks 1–3 do plano GUI torna possível validar a apresentação dos checks novos na entrega conjunta. A revisão final inclui os dois planos; qualquer achado confirmado recebe reprodução antes de correção. Self-review realizado: os cinco problemas têm testes positivos/negativos, os defaults preservam históricos e o orçamento de inferência está fixado. A execução começa após revisão dos planos pelo usuário.
