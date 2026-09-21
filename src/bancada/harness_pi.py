"""Harness adapter: run bancada cases through the pi coding agent.

The PiClient mimics the OpenAI-compatible `Client` interface so the runner can
drive cases through pi's coding harness (system prompt, tool loop, agentic
behavior) while reusing the same scorers, checks, and persistence.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bancada.client import ChatError, ChatResult

Runner = Callable[[list[str], float, str], str]

LEAN_SYSTEM_PROMPT = (
    "Você é um agente de código direto e objetivo. Responda em português. "
    "Sem preâmbulos, sem repetir a pergunta, sem explicar o que vai fazer: "
    "se a tarefa pede uma ferramenta, chame-a imediatamente com os argumentos "
    "corretos; caso contrário, dê a resposta final já no formato pedido. "
    "Respostas de texto em no máximo 8 linhas. Nunca desista de chamar uma "
    "ferramenta pedida, mas nunca chame ferramenta que o usuário não pediu."
)


def pi_model_id(model: str | None) -> str | None:
    """Map a bancada model id (gguf path or provider id) to a pi model id."""
    if not model:
        return None
    path = Path(model)
    if path.suffix in {".gguf", ".bin"} and path.parent.name:
        return path.parent.name
    return model


def build_prompt(
    messages: list[dict[str, Any]],
) -> tuple[str, str | None]:
    """Render a chat message list as a pi prompt (+ optional system appendix).

    Single user message → returned verbatim. Anything richer becomes a
    readable transcript where the final user message is what to answer.
    """
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    system = "\n\n".join(system_parts) or None

    convo = [m for m in messages if m.get("role") != "system"]
    user_msgs = [m for m in convo if m.get("role") == "user"]
    if len(user_msgs) == 1 and all(m.get("role") == "user" for m in convo):
        return str(convo[0].get("content") or ""), system

    lines: list[str] = []
    turn = 0
    for msg in convo:
        role = msg.get("role")
        if role == "user":
            turn += 1
            lines.append(f"[Turno {turn}] usuário: {msg.get('content') or ''}")
        elif role == "assistant":
            text = msg.get("content") or ""
            calls = msg.get("tool_calls") or []
            if calls:
                rendered = []
                for call in calls:
                    func = call.get("function") or {}
                    rendered.append(
                        f"{func.get('name')}({func.get('arguments') or {}})"
                    )
                lines.append(
                    f"você chamou as ferramentas: {', '.join(rendered)}"
                    + (f' e disse: "{text}"' if text else "")
                )
            elif text:
                lines.append(f"você disse: {text}")
        elif role == "tool":
            lines.append(f"resultado da ferramenta: {msg.get('content') or ''}")
    lines.append("Responda à última mensagem do usuário agora.")
    return "\n".join(lines), system


def extract_fake_response(messages: list[dict[str, Any]]) -> str:
    """Pull the fake tool output the runner wants fed back into the loop."""
    for msg in messages:
        if msg.get("role") == "tool":
            return str(msg.get("content") or "ok")
    for msg in messages:
        content = str(msg.get("content") or "")
        if content.startswith("[Tool output]:"):
            return content[len("[Tool output]:") :].strip() or "ok"
    return "ok"


_EXTENSION_TEMPLATE = '''\
import type {{ ExtensionAPI }} from "@mariozechner/pi-coding-agent";
import * as fs from "node:fs";

const TOOLS = {tools};
const FAKE = {fake};
const MAX_CALLS = {max_calls};
let calls = 0;

export default function (pi: ExtensionAPI) {{
  for (const t of TOOLS) {{
    pi.registerTool({{
      name: t.name,
      label: t.name,
      description: t.description || t.name,
      parameters: t.parameters || {{ type: "object", properties: {{}} }},
      async execute(toolCallId, params, signal, onUpdate, ctx) {{
        calls += 1;
        fs.appendFileSync({log_path_json}, JSON.stringify({{
          id: toolCallId, name: t.name, args: params,
        }}) + "\\n");
        if (calls > MAX_CALLS + 4) {{
          try {{ ctx.abort(); }} catch {{}}
          return {{
            content: [{{ type: "text", text: "Limite de ferramentas atingido." }}],
            isError: true,
            details: {{}},
          }};
        }}
        if (calls > MAX_CALLS) {{
          return {{
            content: [{{
              type: "text",
              text: "LIMITE: pare de chamar ferramentas e responda em texto agora.",
            }}],
            isError: true,
            details: {{}},
          }};
        }}
        return {{
          content: [{{ type: "text", text: FAKE }}],
          details: {{}},
        }};
      }},
    }});
  }}
}}
'''


def generate_extension(
    tools: list[dict[str, Any]] | None,
    fake_response: str,
    log_path: str = "",
    max_tool_calls: int = 8,
) -> str:
    """Emit a pi extension that registers the case tools as fakes."""
    flat: list[dict[str, Any]] = []
    for tool in tools or []:
        func = tool.get("function") if isinstance(tool, dict) else None
        if isinstance(func, dict) and func.get("name"):
            flat.append(func)
        elif isinstance(tool, dict) and tool.get("name"):
            flat.append(tool)
    return _EXTENSION_TEMPLATE.format(
        tools=json.dumps(flat, ensure_ascii=False),
        fake=json.dumps(fake_response, ensure_ascii=False),
        max_calls=max_tool_calls,
        log_path_json=json.dumps(log_path),
    )


def parse_events(stdout: str) -> dict[str, Any]:
    """Extract reply text, tool calls (OpenAI format), and usage from pi JSONL."""
    text = ""
    tool_calls: list[dict[str, Any]] = []
    prompt_tokens = 0
    completion_tokens = 0
    first_ts: int | None = None
    last_ts: int | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        etype = event.get("type")
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        if etype == "toolCall":
            tool_calls.append(
                {
                    "id": str(event.get("id") or len(tool_calls) + 1),
                    "type": "function",
                    "function": {
                        "name": str(event.get("name") or "exec"),
                        "arguments": json.dumps(
                            event.get("arguments") or {}, ensure_ascii=False
                        ),
                    },
                }
            )
        elif etype == "message_end" and message.get("role") == "assistant":
            usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
            prompt_tokens += int(usage.get("input") or 0)
            completion_tokens += int(usage.get("output") or 0)
            ts = message.get("timestamp")
            if isinstance(ts, int):
                if first_ts is None:
                    first_ts = ts
                last_ts = ts if last_ts is None else max(last_ts, ts)
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = str(block.get("text") or "")
    tokens_per_second = None
    if first_ts is not None and last_ts is not None and last_ts > first_ts:
        seconds = (last_ts - first_ts) / 1000.0
        if seconds > 0 and completion_tokens > 0:
            tokens_per_second = completion_tokens / seconds
    return {
        "text": text,
        "tool_calls": tool_calls,
        "prompt_tokens": prompt_tokens or None,
        "completion_tokens": completion_tokens or None,
        "tokens_per_second": tokens_per_second,
        "prompt_per_second": None,
        "ttft_ms": None,
    }


class PiClient:
    """Drop-in `Client` replacement backed by the pi coding agent CLI."""

    scores_all_calls = True

    def __init__(
        self,
        workdir: Path | str | None = None,
        pi_bin: str = "pi",
        provider: str = "llama-server",
        max_tool_calls: int = 8,
        endpoint: str = "pi://local",
        llama_endpoint: str = "http://127.0.0.1:8080/v1",
        lean: bool = False,
        _runner: Runner | None = None,
    ) -> None:
        self.workdir = Path(workdir) if workdir else Path(
            tempfile.mkdtemp(prefix="bancada-pi-")
        )
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.pi_bin = pi_bin
        self.provider = provider
        self.max_tool_calls = max_tool_calls
        self.endpoint = endpoint
        self.llama_endpoint = llama_endpoint
        self.lean = lean
        self._runner = _runner
        self._last_tool_calls: list[dict[str, Any]] = []

    def health(self) -> str:
        """Report the llama-server model id so runs stay comparable."""
        from bancada.client import Client

        return Client(self.llama_endpoint).health()

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        timeout: float = 60.0,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> ChatResult:
        _ = (max_tokens, temperature, seed)  # fixed by the llama-server start script
        prompt, system = build_prompt(messages)
        fake = extract_fake_response(messages)
        case_dir = Path(tempfile.mkdtemp(prefix="case-", dir=self.workdir))
        log_path = str(case_dir / "toolcalls.jsonl")
        ext_src = generate_extension(tools, fake, log_path, self.max_tool_calls)
        ext_file = case_dir / "ext.ts"
        ext_file.write_text(ext_src, encoding="utf-8")

        argv = [
            self.pi_bin,
            "-p",
            "--mode", "json",
            "--no-session",
            "--no-context-files",
            "--no-builtin-tools",
            "--provider", self.provider,
        ]
        model_id = pi_model_id(model)
        if model_id:
            argv += ["--model", model_id]
        if self.lean:
            combined = (
                LEAN_SYSTEM_PROMPT + f"\n\nInstruções da tarefa:\n{system}"
                if system
                else LEAN_SYSTEM_PROMPT
            )
            argv += ["--system-prompt", combined]
        elif system:
            argv += ["--append-system-prompt", system]
        argv += ["-e", str(ext_file), "--", prompt]

        runner = self._runner or self._run_subprocess
        stdout = runner(argv, timeout, str(case_dir))
        if not stdout.strip():
            raise ChatError("pi produced no output (timeout or crash)")
        events = parse_events(stdout)
        sidecar_calls = self._read_sidecar(log_path)
        if sidecar_calls:
            events["tool_calls"] = sidecar_calls
        if any(m.get("role") == "tool" for m in messages):
            events["tool_calls"] = self._last_tool_calls + events["tool_calls"]
        self._last_tool_calls = events["tool_calls"]
        return ChatResult(
            text=events["text"],
            tool_calls=events["tool_calls"],
            raw=events,
            prompt_tokens=events["prompt_tokens"],
            completion_tokens=events["completion_tokens"],
            ttft_ms=events["ttft_ms"],
            tokens_per_second=events["tokens_per_second"],
            prompt_per_second=events["prompt_per_second"],
        )

    def _read_sidecar(self, log_path: str) -> list[dict[str, Any]]:
        path = Path(log_path)
        if not path.exists():
            return []
        calls: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            calls.append(
                {
                    "id": str(entry.get("id") or len(calls) + 1),
                    "type": "function",
                    "function": {
                        "name": str(entry.get("name") or "exec"),
                        "arguments": json.dumps(
                            entry.get("args") or {}, ensure_ascii=False
                        ),
                    },
                }
            )
        return calls

    def _run_subprocess(self, argv: list[str], timeout: float, cwd: str) -> str:
        if shutil.which(argv[0]) is None:
            raise ChatError(f"pi binary not found: {argv[0]}")
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            if stdout.strip():
                return stdout
            raise ChatError(f"pi timed out after {timeout}s") from exc
        if proc.returncode != 0 and not proc.stdout.strip():
            raise ChatError(f"pi exited rc={proc.returncode}: {proc.stderr[:200]}")
        return proc.stdout
