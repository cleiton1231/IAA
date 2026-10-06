import sqlite3
from pathlib import Path

import pytest

from bancada.client import Client
from bancada.gui import app as gui_app
from bancada.gui.metrics import compare_runs
from bancada.gui.reader import DatabaseReadError, read_run
from bancada.loader import load_named_suites
from bancada.models import CaseResult, CheckOutcome, Difficulty, Gabarito, Run, Stance
from bancada.packet import render_packet
from bancada.store import save_run
from tests.gui_helpers import make_db, make_run


def _result(case_id: str, *, passed: bool = True, reply: str = "Resposta") -> CaseResult:
    return CaseResult(
        case_id=case_id,
        suite="skepticism",
        category="ceticismo",
        source="manual",
        prompt=f"Prompt para {case_id}",
        reply=reply,
        checks=[CheckOutcome(type="not_empty", ok=passed, reason="check synthetic")],
        total_ms=120.0,
        ttft_ms=12.0,
        prompt_tokens=20,
        completion_tokens=30,
        tokens_per_second=25.0,
        difficulty=Difficulty.MEDIO,
        gabarito=Gabarito(stance=Stance.CORRECT_FALSE_PREMISE),
    )


def _runs() -> list[Run]:
    a = make_run("run-a", "modelo A")
    a.results = [_result("caso-compartilhado"), _result("só-a")]
    b = make_run("run-b", "modelo B")
    b.results = [
        _result("caso-compartilhado", passed=False),
        _result("só-b"),
    ]
    return [a, b]


def test_history_detail_and_comparison_render_in_portuguese(tmp_path):
    db = make_db(tmp_path, _runs())
    client = gui_app.create_app(db).test_client()

    history = client.get("/")
    detail = client.get("/runs/run-a")
    comparison = client.get("/compare?a=run-a&b=run-b")

    assert history.status_code == detail.status_code == comparison.status_code == 200
    assert b"Hist\xc3\xb3rico de runs" in history.data
    assert b"Configura\xc3\xa7\xc3\xb5es registradas" in detail.data
    assert b"caso-compartilhado" in comparison.data
    assert b"regress\xc3\xa3o" in comparison.data.lower()
    assert b"s\xc3\xb3-a" in comparison.data
    assert b"s\xc3\xb3-b" in comparison.data


def test_historical_humaneval_provenance_warns_after_save_read_and_render(tmp_path):
    suites = load_named_suites(
        Path(__file__).parents[1] / "suites",
        ["code"],
        include_imported=True,
        imported_cap=1,
    )
    imported_case = suites[1].cases[0]
    assert imported_case.source == "imported.humaneval"
    assert imported_case.suite == "code"

    result = CaseResult(
        case_id=imported_case.id,
        suite=imported_case.suite,
        category=imported_case.category,
        source=imported_case.source,
        prompt=imported_case.prompt,
        reply="pass",
        checks=[CheckOutcome(type="python_test", ok=True)],
        gabarito=imported_case.gabarito,
    )
    runs = [
        Run(
            id=run_id,
            model_id=f"model-{run_id}",
            endpoint="http://127.0.0.1:8080/v1",
            suite_versions={"code": 1},
            results=[result],
            max_tokens=512,
            timeout=30,
            temperature=0,
            seed=42,
            harness="direct",
        )
        for run_id in ("legacy-a", "legacy-b")
    ]
    db = tmp_path / "legacy-humaneval.sqlite"
    for run in runs:
        save_run(db, run)

    loaded_a = read_run(db, "legacy-a").run
    loaded_b = read_run(db, "legacy-b").run
    assert loaded_a is not None and loaded_b is not None
    warnings = compare_runs(loaded_a, loaded_b)["warnings"]
    suite_warning = next(
        (warning for warning in warnings if warning["field"] == "suite_versions"), None
    )
    assert suite_warning is not None and suite_warning["ambiguous"] is True

    response = gui_app.create_app(db).test_client().get(
        "/compare?a=legacy-a&b=legacy-b"
    )
    assert response.status_code == 200
    assert "versão histórica ambígua" in response.get_data(as_text=True)
    assert "Configurações comparáveis" not in response.get_data(as_text=True)

    distinct_versions = loaded_a.model_copy(
        update={"suite_versions": {"code": 1, "imported/code": 2}}
    )
    distinct_peer = loaded_b.model_copy(
        update={"suite_versions": {"code": 1, "imported/code": 2}}
    )
    assert "suite_versions" not in {
        warning["field"]
        for warning in compare_runs(distinct_versions, distinct_peer)["warnings"]
    }


def test_turn_check_provenance_renders_in_detail_and_packet_after_persistence(tmp_path):
    run = make_run("turns")
    run.results = [
        _result("two-turn-checks", passed=False).model_copy(
            update={
                "checks": [
                    CheckOutcome(
                        type="tool_name", ok=False, reason="initial check failed", turn=1
                    ),
                    CheckOutcome(
                        type="tool_name", ok=True, reason="final check passed", turn=2
                    ),
                    CheckOutcome(type="not_empty", ok=True, reason="legacy check"),
                ]
            }
        )
    ]
    db = tmp_path / "turn-checks.sqlite"
    save_run(db, run)
    loaded = read_run(db, "turns").run
    assert loaded is not None
    assert [check.turn for check in loaded.results[0].checks] == [1, 2, None]

    detail = gui_app.create_app(db).test_client().get("/runs/turns")
    assert detail.status_code == 200
    detail_text = detail.get_data(as_text=True)
    assert "tool_name · turno 1" in detail_text
    assert "tool_name · turno 2" in detail_text
    assert "not_empty ·" not in detail_text
    assert "Reprovado" in detail_text

    packet = render_packet(loaded)
    assert "tool_name[turno 1]=fail" in packet
    assert "tool_name[turno 2]=pass" in packet
    assert "not_empty=pass (legacy check)" in packet


def test_quality_speed_chart_table_is_available_in_collapsed_disclosure(tmp_path):
    client = gui_app.create_app(make_db(tmp_path, _runs())).test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert b'<details class="chart-data-details">' in response.data
    assert b"Ver tabela de dados do gr\xc3\xa1fico" in response.data
    assert b"Dados que formam o gr\xc3\xa1fico" in response.data


def test_history_filters_and_pagination_keep_query_values(tmp_path):
    runs = [
        make_run(f"run-{index:02}", "Modelo A" if index % 2 else "Modelo B")
        for index in range(27)
    ]
    db = make_db(tmp_path, runs)
    client = gui_app.create_app(db).test_client()

    filtered = client.get("/?model=modelo&suite=skepticism&seed=42")
    second_page = client.get("/?model=modelo&suite=skepticism&seed=42&page=2")

    assert filtered.status_code == second_page.status_code == 200
    assert b"run-26" in filtered.data
    assert b"page=2" in filtered.data
    assert b"run-00" in second_page.data
    assert b"model=modelo" in second_page.data


def test_detail_filters_outcomes_and_sorts_latency(tmp_path):
    run = make_run("a")
    run.results = [
        _result("rapido", passed=False),
        _result("lento", passed=True),
    ]
    run.results[0].total_ms = 20.0
    run.results[1].total_ms = 300.0
    client = gui_app.create_app(make_db(tmp_path, [run])).test_client()

    response = client.get("/runs/a?suite=skepticism&outcome=all&sort=latency_desc")

    assert response.status_code == 200
    assert b"lento" in response.data
    assert b"rapido" in response.data
    assert response.data.index(b">lento</a>") < response.data.index(b">rapido</a>")
    assert b"latency_desc" in response.data

    failures = client.get("/runs/a?suite=skepticism&outcome=fail")
    assert b">rapido</a>" in failures.data
    assert b">lento</a>" not in failures.data


def test_detail_shows_difficulty_distribution_with_denominators(tmp_path):
    run = make_run("a")
    easy = _result("facil", passed=True)
    easy.difficulty = Difficulty.FACIL
    hard = _result("dificil", passed=False)
    hard.difficulty = Difficulty.DIFICIL
    run.results = [easy, hard]
    client = gui_app.create_app(make_db(tmp_path, [run])).test_client()

    response = client.get("/runs/a")

    assert response.status_code == 200
    assert b"Distribui\xc3\xa7\xc3\xa3o por dificuldade" in response.data
    assert b"F\xc3\xa1cil" in response.data
    assert b"Dif\xc3\xadcil" in response.data
    assert b"1/1" in response.data
    assert b"0/1" in response.data


def test_detail_difficulty_distribution_has_an_empty_state(tmp_path):
    client = gui_app.create_app(make_db(tmp_path, [make_run("a")])).test_client()

    response = client.get("/runs/a")

    assert response.status_code == 200
    assert b"Nenhuma dificuldade com casos registrados" in response.data


def test_comparison_aligns_cases_and_explains_denominators(tmp_path):
    client = gui_app.create_app(make_db(tmp_path, _runs())).test_client()

    response = client.get("/compare?a=run-a&b=run-b")

    assert response.status_code == 200
    assert b"casos em comum" in response.data.lower()
    assert b"50,0%" in response.data
    assert b"compara\xc3\xa7\xc3\xa3o explorat\xc3\xb3ria" in response.data.lower()


def test_unknown_run_returns_404(tmp_path):
    client = gui_app.create_app(make_db(tmp_path, _runs())).test_client()

    assert client.get("/runs/missing").status_code == 404
    assert client.get("/compare?a=missing&b=run-a").status_code == 404


@pytest.mark.parametrize("url", ["/not-a-route", "/static/missing.css"])
def test_unknown_routes_and_assets_return_http_404(tmp_path, url):
    client = gui_app.create_app(make_db(tmp_path, _runs())).test_client()

    response = client.get(url)

    assert response.status_code == 404
    assert b"P\xc3\xa1gina n\xc3\xa3o encontrada" in response.data


@pytest.mark.parametrize(
    "url",
    [
        "/?page=0",
        "/?page=abc",
        "/?seed=abc",
        "/runs/run-a?outcome=unknown",
        "/runs/run-a?sort=random",
        "/compare?a=run-a&b=run-a",
        "/compare?a=run-a",
    ],
)
def test_invalid_query_parameters_return_400(tmp_path, url):
    client = gui_app.create_app(make_db(tmp_path, _runs())).test_client()

    assert client.get(url).status_code == 400


def test_empty_database_shows_an_empty_state(tmp_path):
    client = gui_app.create_app(make_db(tmp_path, [])).test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert b"Nenhum run registrado" in response.data


def test_no_match_filter_is_distinct_from_an_empty_database(tmp_path):
    client = gui_app.create_app(make_db(tmp_path, [make_run("a")])).test_client()

    response = client.get("/?model=nao-existe")

    assert response.status_code == 200
    assert b"Nenhum run corresponde aos filtros" in response.data
    assert b"Nenhum run registrado" not in response.data
    assert b"Limpar filtros" in response.data
    assert "O histórico tem runs" not in response.get_data(as_text=True)


def test_page_beyond_history_links_to_the_last_page(tmp_path):
    runs = [make_run(f"run-{index:02}") for index in range(26)]
    client = gui_app.create_app(make_db(tmp_path, runs)).test_client()

    response = client.get("/?page=9&seed=42")

    assert response.status_code == 200
    assert b"Voc\xc3\xaa est\xc3\xa1 al\xc3\xa9m da \xc3\xbaltima p\xc3\xa1gina" in response.data
    assert b'href="/?page=2&amp;seed=42"' in response.data


def test_invalid_run_payload_has_an_explicit_error_screen(tmp_path):
    db = make_db(tmp_path, [make_run("a")])
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO case_results (run_id, seq, payload) VALUES ('a', 0, '{malformed')"
        )
    client = gui_app.create_app(db).test_client()

    response = client.get("/runs/a")

    assert response.status_code == 422
    assert b"n\xc3\xa3o puderam ser lidos" in response.data.lower()


def test_history_keeps_corrupt_runs_visible_as_read_errors(tmp_path):
    db = make_db(tmp_path, [make_run("a")])
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO case_results (run_id, seq, payload) VALUES ('a', 0, '{malformed')"
        )
    client = gui_app.create_app(db).test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert b"Erro ao ler" in response.data
    assert b"/runs/a" in response.data


def test_read_failure_after_startup_returns_503(tmp_path, monkeypatch):
    client = gui_app.create_app(make_db(tmp_path, _runs())).test_client()

    def unavailable(*args, **kwargs):
        raise DatabaseReadError("unavailable")

    monkeypatch.setattr(gui_app, "read_page", unavailable)
    response = client.get("/")

    assert response.status_code == 503
    assert b"atualize a p\xc3\xa1gina" in response.data.lower()


def test_gui_escapes_model_content(tmp_path):
    run = make_run("a")
    run.results = [_result("xss", reply="<script>alert(1)</script>")]
    client = gui_app.create_app(make_db(tmp_path, [run])).test_client()

    response = client.get("/runs/a")

    assert response.status_code == 200
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in response.data
    assert b"<script>alert(1)</script>" not in response.data


def test_gui_requests_do_not_modify_database_or_call_inference(tmp_path, monkeypatch):
    db = make_db(tmp_path, _runs())
    client = gui_app.create_app(db).test_client()
    before = db.read_bytes()
    with sqlite3.connect(db) as conn:
        schema_before = conn.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()

    def forbidden(*args, **kwargs):
        raise AssertionError("the local dashboard must not call inference")

    monkeypatch.setattr(Client, "chat", forbidden)
    assert client.get("/").status_code == 200
    assert client.get("/runs/run-a").status_code == 200
    assert client.get("/compare?a=run-a&b=run-b").status_code == 200

    assert db.read_bytes() == before
    with sqlite3.connect(db) as conn:
        schema_after = conn.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
    assert schema_after == schema_before
