import sqlite3

import pytest

from bancada.client import Client
from bancada.gui import app as gui_app
from bancada.gui.reader import DatabaseReadError
from bancada.models import CaseResult, CheckOutcome, Difficulty, Gabarito, Run, Stance
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
        _result("lento", passed=True),
        _result("rapido", passed=False),
    ]
    run.results[0].total_ms = 300.0
    run.results[1].total_ms = 20.0
    client = gui_app.create_app(make_db(tmp_path, [run])).test_client()

    response = client.get("/runs/a?suite=skepticism&outcome=fail&sort=latency_desc")

    assert response.status_code == 200
    assert b"rapido" in response.data
    assert b"lento" not in response.data
    assert b"latency_desc" in response.data


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
