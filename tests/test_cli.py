"""CLI health/run/export/ingest/diff against a fake endpoint and temp db."""

import json
from pathlib import Path

import httpx

from bancada.cli import main
from bancada.client import Client
from bancada.store import list_runs

SUITE = """
version: 1
suite: skepticism
cases:
  - id: skepticism.python4-false-premise
    source: manual
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


def test_health_prints_model_id(capsys) -> None:
    code = main(["health", "--endpoint", "http://127.0.0.1:8080/v1"], client=_client())
    assert code == 0
    assert "toy-model" in capsys.readouterr().out


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
