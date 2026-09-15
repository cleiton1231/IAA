"""Verify all 10 new code bug cases fail on the original bug and pass on the fix."""

from pathlib import Path

import pytest

from bancada.loader import load_suite
from bancada.scorers import run_checks

SUITE_PATH = Path(__file__).resolve().parent.parent / "suites" / "code.yaml"

CASES_DATA = [
    (
        "code.bug-off-by-one",
        (
            "```python\n"
            "def obter_intervalo(lista, inicio, fim):\n"
            "    return lista[inicio:fim]\n"
            "```"
        ),
        (
            "```python\n"
            "def obter_intervalo(lista, inicio, fim):\n"
            "    return lista[inicio:fim + 1]\n"
            "```"
        ),
    ),
    (
        "code.bug-mutable-default",
        (
            "```python\n"
            "def acumular_registro(item, registros=[]):\n"
            "    registros.append(item)\n"
            "    return registros\n"
            "```"
        ),
        (
            "```python\n"
            "def acumular_registro(item, registros=None):\n"
            "    if registros is None:\n"
            "        registros = []\n"
            "    registros.append(item)\n"
            "    return registros\n"
            "```"
        ),
    ),
    (
        "code.bug-none-is",
        (
            "```python\n"
            "def verificar_estado(obj):\n"
            "    if obj == None:\n"
            '        return "vazio"\n'
            '    return "preenchido"\n'
            "```"
        ),
        (
            "```python\n"
            "def verificar_estado(obj):\n"
            "    if obj is None:\n"
            '        return "vazio"\n'
            '    return "preenchido"\n'
            "```"
        ),
    ),
    (
        "code.bug-shadow",
        (
            "```python\n"
            "def aplicar_taxa(taxa, precos):\n"
            "    total = 0.0\n"
            "    for taxa in precos:\n"
            "        total += taxa * (1.0 + taxa)\n"
            "    return total\n"
            "```"
        ),
        (
            "```python\n"
            "def aplicar_taxa(taxa, precos):\n"
            "    total = 0.0\n"
            "    for preco in precos:\n"
            "        total += preco * (1.0 + taxa)\n"
            "    return total\n"
            "```"
        ),
    ),
    (
        "code.bug-fstring",
        (
            "```python\n"
            "def formatar_log(nivel, codigo, mensagem):\n"
            '    return "[" + nivel + "] (" + codigo + ") - " + mensagem\n'
            "```"
        ),
        (
            "```python\n"
            "def formatar_log(nivel, codigo, mensagem):\n"
            '    return f"[{nivel}] ({codigo}) - {mensagem}"\n'
            "```"
        ),
    ),
    (
        "code.bug-path-join",
        (
            "```python\n"
            "def unir_caminho(diretorio, arquivo):\n"
            '    return diretorio + "/" + arquivo\n'
            "```"
        ),
        (
            "```python\n"
            "import os\n"
            "def unir_caminho(diretorio, arquivo):\n"
            '    return os.path.normpath(os.path.join(diretorio, arquivo.lstrip("/")))\n'
            "```"
        ),
    ),
    (
        "code.bug-tz-naive",
        (
            "```python\n"
            "from datetime import datetime\n"
            "def prazo_vencido(limite_utc):\n"
            "    agora = datetime.now()\n"
            "    return agora > limite_utc\n"
            "```"
        ),
        (
            "```python\n"
            "from datetime import datetime, timezone\n"
            "def prazo_vencido(limite_utc):\n"
            "    agora = datetime.now(timezone.utc)\n"
            "    return agora > limite_utc\n"
            "```"
        ),
    ),
    (
        "code.bug-sort-dict",
        (
            "```python\n"
            "def ordenar_por_idade(registros):\n"
            "    return sorted(registros)\n"
            "```"
        ),
        (
            "```python\n"
            "def ordenar_por_idade(registros):\n"
            '    return sorted(registros, key=lambda d: d["idade"])\n'
            "```"
        ),
    ),
    (
        "code.bug-re-greedy",
        (
            "```python\n"
            "import re\n"
            "def extrair_tag_nomeada(texto):\n"
            '    match = re.search(r"<tag>(.*)</tag>", texto)\n'
            "    if match:\n"
            "        return match.group(1)\n"
            "    return None\n"
            "```"
        ),
        (
            "```python\n"
            "import re\n"
            "def extrair_tag_nomeada(texto):\n"
            '    match = re.search(r"<tag>(?P<valor>.*?)</tag>", texto)\n'
            "    if match:\n"
            '        return match.group("valor")\n'
            "    return None\n"
            "```"
        ),
    ),
    (
        "code.bug-twomodule",
        (
            "```python\n"
            "from code_twomodule.util import formata_moeda\n"
            "def gerar_recibo(item: str, preco: float) -> str:\n"
            '    return f"Item: {item} - Total: {formata_moeda(preco)}"\n'
            "```"
        ),
        (
            "```python\n"
            "from code_twomodule.util import formatar_moeda\n"
            "def gerar_recibo(item: str, preco: float) -> str:\n"
            '    return f"Item: {item} - Total: {formatar_moeda(preco)}"\n'
            "```"
        ),
    ),
]


@pytest.fixture(scope="module")
def code_suite():
    return load_suite(SUITE_PATH)


@pytest.mark.parametrize("case_id,buggy_code,fixed_code", CASES_DATA)
def test_each_code_bug_fails_on_buggy_and_passes_on_fix(
    code_suite, case_id: str, buggy_code: str, fixed_code: str
) -> None:
    matching_cases = [c for c in code_suite.cases if c.id == case_id]
    assert len(matching_cases) == 1, f"Case {case_id} not found"
    case = matching_cases[0]

    # Verify buggy code fails
    bug_results = run_checks(buggy_code, case.machine_checks, tool_calls=None)
    assert not all(r.ok for r in bug_results), f"Buggy code should fail for {case_id}"

    # Verify fixed code passes
    fix_results = run_checks(fixed_code, case.machine_checks, tool_calls=None)
    assert all(r.ok for r in fix_results), (
        f"Fixed code should pass for {case_id}: {[r.reason for r in fix_results if not r.ok]}"
    )
