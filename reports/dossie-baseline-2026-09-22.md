# Dossiê Baseline — Modelos via API (OpenRouter) vs Histórico Local (sem harness)

Data: 2026-09-22 · temp 0 / seed 42 · 3 rodadas por modelo · **thinking OFF**
Suíte API: `cloud` v1 (8 casos genéricos + 12 HumanEval = 20) — **nenhum gabarito
v4 mandado para a API** (provedor retém prompts); histórico local = suítes manuais v1–v4.

---

## 1. API — média e mediana de 3 rodadas (suíte cloud, 20 casos)

| Modelo (API) | pass | enem (média / mediana) | HumanEval 12 | tok/s efetivo (média / mediana) |
|---|---|---|---|---|
| **qwen/qwen3.5-9b** (Venice) | 15/15/15 | **0,750 / 0,750** | 9/12 (×3 idêntico) | **91,0 / 98,1** |
| **prism-ml/ternary-bonsai-2-27b** (nt) | 16/16/13 | 0,750 / 0,796 | 10/10/9 de 12 | 21,5 / 17,5 |
| **google/gemma-3-12b-it** | 13/13/13 | 0,659 / 0,659 | 8/12 (×3 idêntico) | 25,9 / 26,2 |
| qwen/qwen3.8-27b:free | **abortado** (20/20 erros, 429) | — | — | — |

Referências fora da série:
- **Bonsai com thinking:** enem 0,295 (5/20) — reasoning come o cap → `empty×9`. **No-think é obrigatório.**
- Bonsai rodada 3 caiu para 13/20 por **3 erros de rate-limit** (única variância relevante; as outras duas rodadas de todos os modelos foram **idênticas ao dígito** — temp 0 + seed 42 entrega determinismo real na API).

**Estabilidade observada:** gemma e qwen3.5-Venice = ±0 entre rodadas. Bonsai = ±2 pass (rate limit).
Free tier = inutilizável (429 desde a sonda).

## 2. Histórico local sem harness — todos os runs (≥30 casos)

### Ornith-1.5-9B-Q8 (8 runs)
| run | casos | pass | enem |
|---|---:|---:|---:|
| 3c09c648 | 34 | 31 | 0,912 |
| 66a77a6c | 36 | 29 | 0,806 |
| f5f69fdc | 36 | 28 | 0,778 |
| 432fb74f | 36 | 29 | 0,806 |
| 75b1f32b | 53 | 43 | 0,811 |
| 722b5bc9 | 53 | 42 | 0,792 |
| fb80a746 | 53 | 46 | 0,868 |
| 2a020aff | 78 | 58 | 0,763 |

**média 0,817 · mediana 0,806**

### Qwen3.5-9B-Q8 (6 runs)
| run | casos | pass | enem | nota |
|---|---:|---:|---:|---|
| be544517 | 36 | 16 | 0,444 | think ON (v1) |
| 3972e29f | 36 | 29 | 0,806 | think OFF |
| c5c1a480 | 53 | 48 | 0,906 | |
| df7ef2b4 | 53 | 49 | 0,924 | campeão local |
| d372bb36 | 53 | 47 | 0,887 | temp0+seed |
| 9c569897 | 78 | 70 | 0,902 | v4+HE |

**média 0,811 · mediana 0,895** (sem o think-ON: média 0,885)

### Qwen3-14B-Q4 (6 runs)
| run | casos | pass | enem |
|---|---:|---:|---:|
| 8668ad5f | 36 | 28 | 0,778 |
| 41330bf5 | 36 | 28 | 0,778 |
| e22effe7 | 53 | 45 | 0,849 |
| e3d03ee9 | 53 | 46 | 0,868 |
| 503089ea | 53 | 46 | 0,868 |
| d11e95f2 | 78 | 70 | 0,902 |

**média 0,840 · mediana 0,859** — o mais estável de todos (subida monotônica com a régua v4)

### Resumo das médias/medianas locais (sem harness)
| Modelo local | média enem | mediana enem | último (v4, 78c) |
|---|---:|---:|---:|
| Qwen3.5-9B Q8 | 0,811* | 0,895* | **0,902** |
| Qwen3-14B Q4 | 0,840 | 0,859 | **0,902** |
| Ornith-1.5-9B Q8 | 0,817 | 0,806 | 0,763 |

\* sem o run think-ON v1.

## 3. Âncora comum — HumanEval 12 (único comparável entre mundos)

| Modelo | backend | HE 12 |
|---|---|---:|
| Qwen3-14B Q4 | local Vulkan | **11/12** |
| Bonsai-2-27B nt | API OpenRouter | **10/12, 10/12, 9/12** (média 9,7) |
| Qwen3.5-9B Q8 | local Vulkan | 9/12 |
| Qwen3.5-9B | API Venice | 9/12 ×3 |
| Gemma-3-12B-it | API | 8/12 ×3 |
| Ornith-1.5-9B | local (direto) | 1/12 (vazios — cai p/ ~8 com harness) |
| Bonsai (think ON) | API | 0/12 |
| Qwen3.8-27b:free | API | — (429) |

## 4. Velocidade (tok/s de geração/efetivo)

| Modelo | backend | tok/s | TTFT/obs |
|---|---|---:|---|
| Ornith / Qwen3.5 / 14B | local Vulkan | 31–32 | p50 2–8s/caso |
| Qwen3.5-9B | **API Venice** | **91 (mediana 98)** | TTFT 0,66–0,9s — o mais rápido do baseline |
| Gemma-3-12B-it | API | 26 | TTFT ~2s |
| Bonsai-2-27B nt | API | 21,5 (mediana 17,5) | TTFT 5–6s engole requests curtos |
| Bonsai-2-27B | local Vulkan | 5,2 | + `--no-repack`; sem kernel |
| Bonsai-2-27B | local Vulkan (PQ2) | 2,0 | fallback CPU |

## 5. Custo (bateria de 20 casos)

| Modelo | custo/run | 3 rodadas |
|---|---:|---:|
| Bonsai-2-27b | ~$0,0017 | ~$0,005 |
| Qwen3.5 Venice ($0,10/$0,15) | ~$0,0007 | ~$0,002 |
| Gemma-3-12B | ~$0,0004–0,001 | ~$0,003 |

## 6. Conclusões

1. **Venice/Qwen3.5 é o melhor custo-velocidade do baseline:** 15/20, HE 9/12 (igual ao local Q8),
   **91 tok/s efetivo** (5x o local, 4x o Bonsai API) a 0,7s de TTFT por ~$0,0007/run.
2. **Bonsai 27B via API entrega 27B por 9,7/12 no HE** — atrás só do 14B local — mas paga TTFT;
   rodada 3 variou por rate-limit. Think ON é inutilizável sob caps.
3. **Gemma-3-12B é o mais fraco dos utilizáveis** (13/20, 8/12 HE) mas determinístico e barato.
4. **Free tier (qwen3.8-27b:free) não serve** — 429 total.
5. **Determinismo de API confirmado:** 5 de 7 rodadas idênticas ao dígito com temp 0/seed 42.
6. **Local segue o topo absoluto no HE** (14B 11/12) e na estabilidade histórica (14B mediana 0,859,
   Qwen3.5 mediana 0,895), mas a **Venice API approxima o Qwen3.5 local com 5x a velocidade**.

Run IDs — API: bonsai `f53e387e` `8c55180d` `93b5bb9f` · gemma `6f618833` `76c89caa` `9d089eaa` ·
venice `c934a93e` `11407f92` `f2ff6c51` · free `dec2e2d6` (abort) · think `8b11b809`.
