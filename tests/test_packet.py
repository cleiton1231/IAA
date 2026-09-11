"""Judge packet must expose gabarito, source, and the JSON template."""

from bancada.models import CaseResult, CheckOutcome, Gabarito, Run, Stance
from bancada.packet import render_packet


def test_packet_includes_ids_gabarito_source_and_json_template() -> None:
    run = Run(
        id="run1",
        model_id="Qwen3.5-9B",
        endpoint="http://127.0.0.1:8080/v1",
        suite_versions={"skepticism": 1},
        results=[
            CaseResult(
                case_id="skepticism.python4-false-premise",
                suite="skepticism",
                source="manual",
                prompt="Desde que o Python 4 foi lançado em 2023...",
                reply="O Python 4 não foi lançado.",
                checks=[CheckOutcome(type="not_empty", ok=True)],
                total_ms=42.0,
                gabarito=Gabarito(
                    stance=Stance.CORRECT_FALSE_PREMISE,
                    must_cover=["Python 4 não existe como release 2023"],
                    notes="Corrigir a premissa.",
                ),
            )
        ],
    )
    text = render_packet(run)
    assert "run1" in text
    assert "Qwen3.5-9B" in text
    assert "skepticism.python4-false-premise" in text
    assert "source: manual" in text
    assert "correct_false_premise" in text
    assert "Python 4 não existe como release 2023" in text
    assert "O Python 4 não foi lançado." in text
    assert '"run_id": "run1"' in text
    assert "Leia `JUDGE.md`" in text
    assert "### Tool calls" in text
    tool_section = text.split("### Tool calls", 1)[1].split("score:", 1)[0]
    assert "(none)" in tool_section


def test_packet_includes_tool_calls_json() -> None:
    run = Run(
        id="run-tools",
        model_id="toy-model",
        endpoint="http://127.0.0.1:8080/v1",
        suite_versions={"tools": 1},
        results=[
            CaseResult(
                case_id="tools.cron",
                suite="tools",
                source="imported.bfcl",
                prompt="agende um cron",
                reply="",
                tool_calls=[{"function": {"name": "cron", "arguments": "{}"}}],
                checks=[],
                total_ms=10.0,
                gabarito=Gabarito(stance=Stance.ACCEPT_TRUE_CONTROL),
            )
        ],
    )
    text = render_packet(run)
    assert "### Tool calls" in text
    assert '"name": "cron"' in text
