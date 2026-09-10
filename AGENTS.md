# AGENTS.md — Bancada

Você está neste repositório. A Bancada mede modelos locais. O juiz **é você no chat**, não uma API.

## Quando o usuário colar um `judge-packet.md` ou disser “julga o run”

1. Leia `JUDGE.md` inteiro. Não invente rubrica.
2. Pontue cada caso 0–3 contra o gabarito daquele caso.
3. Devolva o JSON do rodapé do packet, com `score` preenchido.
4. Feche com as 5 linhas de veredito do `JUDGE.md`.
5. Não se impressione com fluência. Não peça critério extra se o gabarito já decide.

## Quando o usuário pedir para rodar bench

Use a CLI: `bancada health`, `bancada run`, `bancada export-judge`, `bancada ingest-scores`, `bancada diff`. Endpoint default `http://127.0.0.1:8080/v1`. Sem bind `0.0.0.0`. Sem chamar API xAI de dentro do app.

## Fetch

`bancada fetch` baixa jsonl pequenos (teto 50 MB). Nunca clone SWE-bench / The Stack / APPS.

## TDD

Comportamento novo: teste que falha primeiro, depois o código.
