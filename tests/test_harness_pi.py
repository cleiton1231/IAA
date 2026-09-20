"""Tests for the Pi coding-agent harness client."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bancada.harness_pi import (
    PiClient,
    build_prompt,
    extract_fake_response,
    generate_extension,
    parse_events,
    pi_model_id,
)

SAMPLE_JSONL = "\n".join(
    [
        json.dumps({"type": "session", "id": "s1"}),
        json.dumps(
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Vou verificar."}],
                    "usage": {"input": 100, "output": 20},
                    "timestamp": 1000,
                },
            }
        ),
        json.dumps(
            {
                "type": "toolCall",
                "id": "c1",
                "name": "exec",
                "arguments": {"command": "ls"},
            }
        ),
        json.dumps(
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Listei os arquivos."}],
                    "usage": {"input": 200, "output": 30},
                    "timestamp": 3000,
                },
            }
        ),
    ]
)


def test_pi_model_id_from_gguf_path():
    path = "/home/cleiton/local/models/qwen3.5-9b-q8/Qwen3.5-9B-Q8_0.gguf"
    assert pi_model_id(path) == "qwen3.5-9b-q8"


def test_pi_model_id_none_falls_back_to_default():
    assert pi_model_id(None) is None


def test_build_prompt_single_user():
    prompt, system = build_prompt(
        [{"role": "user", "content": "ola"}],
    )
    assert prompt == "ola"
    assert system is None


def test_build_prompt_with_system():
    prompt, system = build_prompt(
        [
            {"role": "system", "content": "Você é cético."},
            {"role": "user", "content": "pergunta"},
        ]
    )
    assert prompt == "pergunta"
    assert system == "Você é cético."


def test_build_prompt_multiturn_transcript():
    messages = [
        {"role": "user", "content": "liste os arquivos"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "exec", "arguments": '{"command": "ls"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "name": "exec", "content": "a.txt"},
        {"role": "user", "content": "agora apague o a.txt"},
    ]
    prompt, system = build_prompt(messages)
    assert "liste os arquivos" in prompt
    assert "exec" in prompt
    assert "a.txt" in prompt
    assert "apague o a.txt" in prompt
    # the model must be told to answer the last user message
    assert "Responda à última mensagem do usuário agora." in prompt


def test_extract_fake_response_from_tool_message():
    messages = [
        {"role": "user", "content": "p"},
        {"role": "assistant", "content": "x"},
        {"role": "tool", "tool_call_id": "c1", "name": "exec", "content": "saida fake"},
    ]
    assert extract_fake_response(messages) == "saida fake"


def test_extract_fake_response_from_tool_output_user():
    messages = [
        {"role": "user", "content": "p"},
        {"role": "assistant", "content": "x"},
        {"role": "user", "content": "[Tool output]:\nsaida 2"},
    ]
    assert extract_fake_response(messages) == "saida 2"


def test_extract_fake_response_default_when_absent():
    assert extract_fake_response([{"role": "user", "content": "p"}]) == "ok"


def test_generate_extension_registers_tools_and_cap():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "exec",
                "description": "Executa",
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                },
            },
        }
    ]
    ts = generate_extension(tools, "saida fake", max_tool_calls=6)
    assert '"exec"' in ts
    assert "saida fake" in ts
    assert "abort" in ts
    assert "6" in ts


def test_parse_events_text_and_tool_calls():
    events = parse_events(SAMPLE_JSONL)
    assert events["text"] == "Listei os arquivos."
    assert len(events["tool_calls"]) == 1
    call = events["tool_calls"][0]
    assert call["type"] == "function"
    assert call["id"] == "c1"
    assert call["function"]["name"] == "exec"
    assert json.loads(call["function"]["arguments"]) == {"command": "ls"}
    assert events["prompt_tokens"] == 300
    assert events["completion_tokens"] == 50


def test_parse_events_empty_session():
    events = parse_events("")
    assert events["text"] == ""
    assert events["tool_calls"] == []


def test_pi_client_runs_and_parses(tmp_path: Path):
    fake_out = "\n".join(
        [
            json.dumps(
                {
                    "type": "message_end",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "feito"}],
                        "usage": {"input": 10, "output": 5},
                    },
                }
            )
        ]
    )
    client = PiClient(
        workdir=tmp_path,
        pi_bin="fake-pi",
        _runner=lambda argv, timeout, cwd: fake_out,
    )
    result = client.chat(messages=[{"role": "user", "content": "oi"}])
    assert result.text == "feito"
    assert result.prompt_tokens == 10


def test_pi_client_raises_on_missing_output(tmp_path: Path):
    client = PiClient(workdir=tmp_path, pi_bin="fake-pi", _runner=lambda *a, **k: "")
    with pytest.raises(Exception):
        client.chat(messages=[{"role": "user", "content": "oi"}])
