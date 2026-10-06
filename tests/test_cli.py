"""CLI health/run/export/ingest/diff against a fake endpoint and temp db."""

import json
import sqlite3
from pathlib import Path

import httpx
import pytest

import bancada.cli as cli_module
from bancada.cli import main
from bancada.client import Client
from bancada.models import CaseResult, Gabarito, Run, Stance
from bancada.store import list_runs, save_run, save_scores

SUITE = """
version: 1
suite: skepticism
cases:
  - id: skepticism.python4-false-premise
    source: manual
    difficulty: medio
    prompt: Python 4 em 2023?
    gabarito:
      stance: correct_false_premise
      must_cover: ["não foi lançado"]
    machine_checks:
      - type: not_empty
"""


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/models"):
        return httpx.Response(200, json={"data": [{"id": "toy-model"}]})
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": "Python 4 não foi lançado em 2023."}}]},
    )


def _client() -> Client:
    return Client("http://127.0.0.1:8080/v1", transport=httpx.MockTransport(_handler))


def _seed_run(db: Path, run_id: str) -> None:
    save_run(
        db,
        Run(
            id=run_id,
            model_id="toy-model",
            endpoint="http://127.0.0.1:8080/v1",
            results=[
                CaseResult(
                    case_id="same-case",
                    suite="code",
                    source="manual",
                    prompt="p",
                    reply="r",
                    gabarito=Gabarito(stance=Stance.ACCEPT_TRUE_CONTROL),
                )
            ],
        ),
    )


def test_health_prints_model_id(capsys) -> None:
    code = main(["health", "--endpoint", "http://127.0.0.1:8080/v1"], client=_client())
    assert code == 0
    assert "toy-model" in capsys.readouterr().out


def test_cli_endpoint_precedence_for_health_smoke_and_empty_environment(
    monkeypatch, tmp_path: Path
) -> None:
    created: list[str] = []
    real_client = Client

    def tracking_client(endpoint: str, **kwargs) -> Client:
        created.append(endpoint)
        return real_client(endpoint, transport=httpx.MockTransport(_handler), **kwargs)

    monkeypatch.setattr(cli_module, "Client", tracking_client)
    monkeypatch.setenv("BANCADA_ENDPOINT", "http://env.example/v1/")

    assert main(["health"]) == 0
    assert main(["health", "--endpoint", "http://flag.example/v1"]) == 0
    assert created == ["http://env.example/v1/", "http://flag.example/v1"]
    injected = real_client("http://injected.example/v1", transport=httpx.MockTransport(_handler))
    assert main(["health", "--endpoint", "http://flag.example/v1"], client=injected) == 0
    assert created == ["http://env.example/v1/", "http://flag.example/v1"]

    suites = tmp_path / "suites"
    suites.mkdir()
    (suites / "skepticism.yaml").write_text(SUITE, encoding="utf-8")
    smoke_args = [
        "smoke",
        "--endpoint",
        "http://smoke-flag.example/v1",
        "--suites",
        "skepticism",
        "--suites-dir",
        str(suites),
    ]
    assert main(smoke_args) == 0
    assert created[-1] == "http://smoke-flag.example/v1"

    monkeypatch.setenv("BANCADA_ENDPOINT", "")
    assert main(["health"]) == 0
    assert created[-1] == "http://127.0.0.1:8080/v1"


def test_run_resume_uses_normalized_environment_endpoint(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from bancada.loader import load_suite, suite_versions

    suites = tmp_path / "suites"
    suites.mkdir()
    (suites / "skepticism.yaml").write_text(SUITE, encoding="utf-8")
    suite = load_suite(suites / "skepticism.yaml").model_copy(update={"version_key": "skepticism"})
    endpoint = "http://resume.example/v1/"
    db = tmp_path / "resume.sqlite"
    save_run(
        db,
        Run(
            id="resumable",
            model_id="toy-model",
            endpoint=endpoint.rstrip("/"),
            suite_versions=suite_versions([suite]),
            seed=42,
            temperature=0.0,
            max_tokens=512,
            timeout=60.0,
            harness="direct",
        ),
    )
    monkeypatch.setenv("BANCADA_ENDPOINT", endpoint)
    real_client = Client
    endpoints: list[str] = []

    def tracking_client(client_endpoint: str, **kwargs) -> Client:
        endpoints.append(client_endpoint)
        return real_client(client_endpoint, transport=httpx.MockTransport(_handler), **kwargs)

    monkeypatch.setattr(cli_module, "Client", tracking_client)

    run_args = [
        "run",
        "--suites",
        "skepticism",
        "--suites-dir",
        str(suites),
        "--db",
        str(db),
        "--resume",
        "--no-imported",
    ]
    assert main(run_args) == 0
    assert "resuming run resumable" in capsys.readouterr().out
    assert endpoints == [endpoint]


def test_run_export_ingest_diff(tmp_path: Path, capsys) -> None:
    suites = tmp_path / "suites"
    suites.mkdir()
    (suites / "skepticism.yaml").write_text(SUITE, encoding="utf-8")
    db = tmp_path / "bancada.sqlite"
    reports = tmp_path / "reports"
    client = _client()

    code = main(
        [
            "run",
            "--endpoint",
            "http://127.0.0.1:8080/v1",
            "--suites",
            "skepticism",
            "--suites-dir",
            str(suites),
            "--db",
            str(db),
            "--no-imported",
        ],
        client=client,
    )
    assert code == 0
    run_id = capsys.readouterr().out.strip().split()[-1]

    code = main(
        ["export-judge", run_id, "--db", str(db), "--out", str(reports / "packet.md")],
        client=client,
    )
    assert code == 0
    packet = (reports / "packet.md").read_text(encoding="utf-8")
    assert "skepticism.python4-false-premise" in packet
    assert "correct_false_premise" in packet

    scores = tmp_path / "scores.json"
    scores.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "judge": "grok-chat",
                "cases": [
                    {
                        "id": "skepticism.python4-false-premise",
                        "score": 3,
                        "max": 3,
                        "reason": "corrigiu",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert main(["ingest-scores", run_id, str(scores), "--db", str(db)], client=client) == 0

    second = main(
        [
            "run",
            "--suites",
            "skepticism",
            "--suites-dir",
            str(suites),
            "--db",
            str(db),
            "--no-imported",
        ],
        client=client,
    )
    assert second == 0
    run_b = capsys.readouterr().out.strip().split()[-1]
    assert main(["diff", run_id, run_b, "--db", str(db)], client=client) == 0
    out = capsys.readouterr().out
    assert run_id in out and run_b in out


def test_ingest_rejects_other_run_identity_without_changing_existing_scores(
    tmp_path: Path, capsys
) -> None:
    db = tmp_path / "bancada.sqlite"
    _seed_run(db, "run-a")
    _seed_run(db, "run-b")
    save_scores(db, "run-b", {"run_id": "run-b", "cases": [{"id": "same-case", "score": 2}]})
    before = db.read_bytes()
    incoming = tmp_path / "scores.json"
    incoming.write_text(
        json.dumps({"run_id": "run-a", "cases": [{"id": "same-case", "score": 3}]}),
        encoding="utf-8",
    )

    assert main(["ingest-scores", "run-b", str(incoming), "--db", str(db)]) == 1
    assert "run_id" in capsys.readouterr().err
    assert db.read_bytes() == before


@pytest.mark.parametrize("declared", [None, "", 1, {}, False])
def test_ingest_rejects_invalid_present_run_identity(
    tmp_path: Path, capsys, declared: object
) -> None:
    db = tmp_path / "bancada.sqlite"
    _seed_run(db, "run-a")
    incoming = tmp_path / "scores.json"
    incoming.write_text(json.dumps({"run_id": declared, "cases": []}), encoding="utf-8")

    assert main(["ingest-scores", "run-a", str(incoming), "--db", str(db)]) == 1
    assert "run_id" in capsys.readouterr().err


def test_ingest_accepts_legacy_scores_without_run_id(tmp_path: Path, capsys) -> None:
    db = tmp_path / "bancada.sqlite"
    _seed_run(db, "run-a")
    incoming = tmp_path / "scores.json"
    incoming.write_text(json.dumps({"cases": [{"id": "same-case", "score": 3}]}), encoding="utf-8")

    assert main(["ingest-scores", "run-a", str(incoming), "--db", str(db)]) == 0
    assert "ingested run-a" in capsys.readouterr().out


def test_ingest_rejects_inconsistent_existing_scores_without_rewriting_db(
    tmp_path: Path, capsys
) -> None:
    db = tmp_path / "bancada.sqlite"
    _seed_run(db, "run-a")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO judge_scores (run_id, payload) VALUES (?, ?)",
            ("run-a", json.dumps({"run_id": "old-wrong-run", "cases": []})),
        )
    before = db.read_bytes()
    incoming = tmp_path / "scores.json"
    incoming.write_text(json.dumps({"run_id": "run-a", "cases": []}), encoding="utf-8")

    assert main(["ingest-scores", "run-a", str(incoming), "--db", str(db)]) == 1
    assert "run_id" in capsys.readouterr().err
    assert db.read_bytes() == before


def test_list_prints_runs_newest_first_with_judge(tmp_path: Path, capsys) -> None:
    suites = tmp_path / "suites"
    suites.mkdir()
    (suites / "skepticism.yaml").write_text(SUITE, encoding="utf-8")
    db = tmp_path / "bancada.sqlite"
    client = _client()

    assert (
        main(
            [
                "run",
                "--endpoint",
                "http://127.0.0.1:8080/v1",
                "--suites",
                "skepticism",
                "--suites-dir",
                str(suites),
                "--db",
                str(db),
                "--no-imported",
            ],
            client=client,
        )
        == 0
    )
    run_a = capsys.readouterr().out.strip().split()[-1]
    assert (
        main(
            [
                "run",
                "--suites",
                "skepticism",
                "--suites-dir",
                str(suites),
                "--db",
                str(db),
                "--no-imported",
            ],
            client=client,
        )
        == 0
    )
    run_b = capsys.readouterr().out.strip().split()[-1]

    scores = tmp_path / "scores.json"
    scores.write_text(
        json.dumps(
            {
                "run_id": run_b,
                "judge": "grok-chat",
                "cases": [
                    {
                        "id": "skepticism.python4-false-premise",
                        "score": 3,
                        "max": 3,
                        "reason": "ok",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert main(["ingest-scores", run_b, str(scores), "--db", str(db)], client=client) == 0
    capsys.readouterr()

    assert main(["list", "--db", str(db)], client=client) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 2
    assert [line.split()[0] for line in lines] == [item.id for item in list_runs(db)]
    by_id = {line.split()[0]: line for line in lines}
    assert "model=toy-model  cases=1  machine_pass=1.00" in by_id[run_a]
    assert "model=toy-model  cases=1  machine_pass=1.00" in by_id[run_b]
    assert "judge=3.00" in by_id[run_b]
    assert "judge=" not in by_id[run_a]


def test_smoke_runs_one_case_per_suite(tmp_path: Path, capsys) -> None:
    suites = tmp_path / "suites"
    suites.mkdir()
    (suites / "skepticism.yaml").write_text(SUITE, encoding="utf-8")
    client = _client()

    code = main(
        [
            "smoke",
            "--suites",
            "skepticism",
            "--suites-dir",
            str(suites),
        ],
        client=client,
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "pass 1/1" in out
    assert "p50:" in out


def test_smoke_fails_if_health_fails(tmp_path: Path, capsys) -> None:
    suites = tmp_path / "suites"
    suites.mkdir()
    (suites / "skepticism.yaml").write_text(SUITE, encoding="utf-8")

    def broken_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "server dead"})

    client = Client("http://127.0.0.1:8080/v1", transport=httpx.MockTransport(broken_handler))
    code = main(
        [
            "smoke",
            "--suites",
            "skepticism",
            "--suites-dir",
            str(suites),
        ],
        client=client,
    )
    assert code != 0
    err = capsys.readouterr().err
    assert "error:" in err


def test_run_prints_summary_and_supports_resume(tmp_path: Path, capsys) -> None:
    suites = tmp_path / "suites"
    suites.mkdir()
    suite_two_cases = (
        SUITE
        + """  - id: skepticism.python4-another
    source: manual
    difficulty: medio
    prompt: Python 4 data?
    gabarito:
      stance: correct_false_premise
    machine_checks:
      - type: not_empty
"""
    )
    (suites / "skepticism.yaml").write_text(suite_two_cases, encoding="utf-8")
    db = tmp_path / "bancada.sqlite"
    client = _client()

    from bancada.models import CaseResult, CheckOutcome, Gabarito, Run, Stance
    from bancada.store import save_run

    incomplete = Run(
        id="run-incomplete",
        model_id="toy-model",
        endpoint="http://127.0.0.1:8080/v1",
        suite_versions={"skepticism": 1},
        max_tokens=512,
        timeout=60.0,
        temperature=0.0,
        seed=42,
        harness="direct",
        results=[
            CaseResult(
                case_id="skepticism.python4-false-premise",
                suite="skepticism",
                source="manual",
                prompt="prompt",
                reply="cached",
                checks=[CheckOutcome(type="not_empty", ok=True)],
                gabarito=Gabarito(stance=Stance.CORRECT_FALSE_PREMISE),
            )
        ],
    )
    save_run(db, incomplete)

    # Run with --resume: resumes the incomplete run
    code = main(
        [
            "run",
            "--suites",
            "skepticism",
            "--suites-dir",
            str(suites),
            "--db",
            str(db),
            "--no-imported",
            "--resume",
        ],
        client=client,
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "resuming run run-incomplete" in out
    assert "pass 2/2" in out
    assert "p50:" in out
    assert "saved run-incomplete" in out

    # Second run with --resume: now that run is complete, --resume is a no-op
    code2 = main(
        [
            "run",
            "--suites",
            "skepticism",
            "--suites-dir",
            str(suites),
            "--db",
            str(db),
            "--no-imported",
            "--resume",
        ],
        client=client,
    )
    assert code2 == 0
    out2 = capsys.readouterr().out
    assert "resuming run" not in out2


def test_resume_cli_starts_new_run_when_configuration_differs(
    tmp_path: Path, capsys
) -> None:
    suites = tmp_path / "suites"
    suites.mkdir()
    (suites / "skepticism.yaml").write_text(SUITE, encoding="utf-8")
    db = tmp_path / "bancada.sqlite"
    from bancada.models import Run
    from bancada.store import save_run

    save_run(
        db,
        Run(
            id="wrong-seed",
            model_id="toy-model",
            endpoint="http://127.0.0.1:8080/v1",
            suite_versions={"skepticism": 1},
            max_tokens=512,
            timeout=60.0,
            temperature=0.0,
            seed=41,
            harness="direct",
        ),
    )

    code = main(
        [
            "run",
            "--suites",
            "skepticism",
            "--suites-dir",
            str(suites),
            "--db",
            str(db),
            "--no-imported",
            "--resume",
        ],
        client=_client(),
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "no compatible resumable run found; starting a new run" in out
    assert "resuming run wrong-seed" not in out
    assert len(list_runs(db)) == 2


def test_run_persists_manual_and_capped_imported_version_identities(tmp_path: Path) -> None:
    suites = tmp_path / "suites"
    imported_dir = suites / "imported"
    imported_dir.mkdir(parents=True)
    manual_cases = "".join(
        f"""  - id: code.manual-{index}
    source: manual
    difficulty: medio
    prompt: manual {index}
    gabarito: {{stance: accept_true_control}}
    machine_checks:
      - type: not_empty
"""
        for index in range(2)
    )
    imported_cases = "".join(
        f"""  - id: imported.humaneval-{index}
    source: imported.humaneval
    difficulty: medio
    prompt: imported {index}
    gabarito: {{stance: accept_true_control}}
    machine_checks:
      - type: not_empty
"""
        for index in range(2)
    )
    (suites / "code.yaml").write_text(
        f"version: 6\nsuite: code\ncases:\n{manual_cases}", encoding="utf-8"
    )
    (imported_dir / "code.yaml").write_text(
        f"version: 1\nsuite: code\ncases:\n{imported_cases}", encoding="utf-8"
    )
    db = tmp_path / "bancada.sqlite"

    code = main(
        [
            "run",
            "--suites",
            "code",
            "--suites-dir",
            str(suites),
            "--db",
            str(db),
            "--imported",
            "--imported-cap",
            "1",
            "--quiet",
        ],
        client=_client(),
    )

    assert code == 0
    run = list_runs(db)[0]
    assert run.suite_versions == {"code": 6, "imported/code": 1}
    assert [result.case_id for result in run.results] == [
        "code.manual-0",
        "code.manual-1",
        "imported.humaneval-0",
    ]
