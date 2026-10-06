"""Flask application for browsing saved runs on the local machine."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from flask import Flask, render_template, request, url_for

from bancada.gui.metrics import case_passed, compare_runs, run_metrics
from bancada.gui.reader import DatabaseReadError, read_page, read_run
from bancada.models import Run

_PAGE_SIZE = 25
_PORT_MIN = 1
_PORT_MAX = 65535
_TIME_ZONE = ZoneInfo("America/Sao_Paulo")
_CONFIG_LABELS = {
    "seed": "seed",
    "suite_versions": "versões das suítes",
    "temperature": "temperatura",
    "max_tokens": "limite de tokens",
    "timeout": "timeout",
    "harness": "harness",
}


def _timestamp(value: int | None) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "sem registro"
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).astimezone(_TIME_ZONE).strftime(
            "%d/%m/%Y %H:%M"
        )
    except (OverflowError, OSError, ValueError):
        return "data inválida"


def _percent(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "indisponível"
    return f"{_number(value * 100, 1)}%"


def _number(value: float | int | None, places: int = 1) -> str:
    if value is None:
        return "indisponível"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "indisponível"
    if isinstance(value, float) and not math.isfinite(value):
        return "indisponível"
    return f"{value:,.{places}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _config_value(run: Run, field: str) -> Any:
    value = getattr(run, field)
    if field not in run.model_fields_set or value is None or value == "":
        return None
    if field == "suite_versions" and not value:
        return None
    return value


def _run_configuration(run: Run) -> list[dict[str, str]]:
    fields = (
        ("endpoint", "endpoint"),
        ("suite_versions", "versões das suítes"),
        ("seed", "seed"),
        ("temperature", "temperatura"),
        ("max_tokens", "limite de tokens"),
        ("timeout", "timeout"),
        ("harness", "harness"),
    )
    rows = []
    for field, label in fields:
        value = _config_value(run, field)
        if field == "suite_versions" and value is not None:
            value = ", ".join(f"{name} v{version}" for name, version in value.items())
        rows.append(
            {
                "field": field,
                "label": label,
                "value": "não registrado" if value is None else str(value),
            }
        )
    return rows


def _quality_speed_points(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str, str]:
    eligible = [
        item
        for item in entries
        if item.get("metrics") is not None
        and item["metrics"]["machine_rate"] is not None
        and item["metrics"]["tps_p50"] is not None
    ]
    if not eligible:
        return [], "0", "0"
    speeds = [float(item["metrics"]["tps_p50"]) for item in eligible]
    low, high = min(speeds), max(speeds)
    points = []
    for item in eligible:
        rate = float(item["metrics"]["machine_rate"])
        speed = float(item["metrics"]["tps_p50"])
        x = 52 + rate * 538
        fraction = 0.5 if high == low else (speed - low) / (high - low)
        y = 260 - fraction * 205
        points.append(
            {
                "id": item["entry"].id,
                "model": item["entry"].model_id,
                "rate": _percent(rate),
                "speed": _number(speed),
                "cx": f"{x:.1f}",
                "cy": f"{y:.1f}",
                "url": url_for("run_detail", run_id=item["entry"].id),
            }
        )
    return points, _number(low), _number(high)


def _case_latency(result: Any) -> float | None:
    if result.error or "total_ms" not in result.model_fields_set:
        return None
    value = result.total_ms
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        latency = float(value)
    except OverflowError:
        return None
    return latency if math.isfinite(latency) and latency >= 0 else None


def _case_details(result: Any) -> dict[str, str]:
    return {
        "prompt": result.prompt,
        "reply": result.reply,
        "turn1_reply": result.turn1_reply or "",
        "tool_calls": json.dumps(result.tool_calls, ensure_ascii=False, indent=2),
        "turn1_tool_calls": json.dumps(
            result.turn1_tool_calls or [], ensure_ascii=False, indent=2
        ),
    }


def _judge_reason(run: Run, case_id: str) -> str:
    scores = run.judge_scores or {}
    cases = scores.get("cases", []) if isinstance(scores, dict) else []
    if not isinstance(cases, list) or case_id not in {result.case_id for result in run.results}:
        return ""
    for item in reversed(cases):
        if not isinstance(item, dict) or item.get("id") != case_id:
            continue
        score = item.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            continue
        try:
            numeric_score = float(score)
        except OverflowError:
            continue
        if not math.isfinite(numeric_score) or not 0 <= numeric_score <= 3:
            continue
        reason = item.get("reason")
        return reason if isinstance(reason, str) else ""
    return ""


def create_app(db_path: Path) -> Flask:
    """Create the read-only dashboard and validate its database before serving."""
    database = Path(db_path).expanduser().resolve()
    read_page(database, page=1)
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = database
    app.add_template_filter(_timestamp, "timestamp")
    app.add_template_filter(_percent, "percent")
    app.add_template_filter(_number, "number")

    @app.get("/")
    def history():
        page_text = request.args.get("page", "1")
        seed_text = request.args.get("seed", "").strip()
        try:
            page_number = int(page_text)
            if page_number < 1:
                raise ValueError
        except ValueError:
            return _error("Parâmetro inválido", "A página deve ser um número maior que zero.", 400)
        if seed_text:
            try:
                seed = int(seed_text)
            except ValueError:
                return _error("Parâmetro inválido", "O seed deve ser um número inteiro.", 400)
        else:
            seed = None
        model = request.args.get("model", "").strip()
        suite = request.args.get("suite", "").strip()
        if len(model) > 200 or len(suite) > 100:
            return _error("Parâmetro inválido", "O filtro informado é longo demais.", 400)
        try:
            page = read_page(
                app.config["DATABASE_PATH"],
                page=page_number,
                model=model,
                suite=suite,
                seed=seed,
            )
        except DatabaseReadError:
            return _error(
                "Banco indisponível",
                "O SQLite ficou indisponível. Atualize a página para tentar novamente.",
                503,
            )
        entries = []
        for entry in page.entries:
            if entry.run is None:
                entries.append({"entry": entry, "error": entry.error})
                continue
            metrics = run_metrics(entry.run)
            entries.append(
                {
                    "entry": entry,
                    "metrics": metrics,
                    "judge_mean": metrics["judge_mean"],
                }
            )
        points, speed_min, speed_max = _quality_speed_points(entries)
        page_count = max(1, math.ceil(page.total / _PAGE_SIZE))
        compare_choices = [item["entry"] for item in entries if item.get("metrics")]
        return render_template(
            "index.html",
            entries=entries,
            points=points,
            speed_min=speed_min,
            speed_max=speed_max,
            page=page,
            page_count=page_count,
            model=model,
            suite=suite,
            seed=seed_text,
            compare_choices=compare_choices,
        )

    @app.get("/runs/<run_id>")
    def run_detail(run_id: str):
        outcome = request.args.get("outcome", "all")
        sort = request.args.get("sort", "sequence")
        suite_filter = request.args.get("suite", "").strip()
        if outcome not in {"all", "pass", "fail"}:
            return _error("Parâmetro inválido", "Escolha todos, aprovados ou reprovados.", 400)
        if sort not in {"sequence", "latency_desc"}:
            return _error("Parâmetro inválido", "A ordenação informada não é válida.", 400)
        if len(suite_filter) > 100:
            return _error("Parâmetro inválido", "O filtro de suíte é longo demais.", 400)
        try:
            entry = read_run(app.config["DATABASE_PATH"], run_id)
        except DatabaseReadError:
            return _error(
                "Banco indisponível",
                "O SQLite ficou indisponível. Atualize a página para tentar novamente.",
                503,
            )
        if entry is None:
            return _error("Run não encontrado", "Não existe um run com esse ID.", 404)
        if entry.run is None:
            return _error(
                "Erro ao ler run",
                f"Os dados desse run não puderam ser lidos: {entry.error or 'payload inválido'}.",
                422,
            )
        run = entry.run
        metrics = run_metrics(run)
        selected = []
        for index, result in enumerate(run.results):
            passed = case_passed(result)
            latency = _case_latency(result)
            if suite_filter and result.suite != suite_filter:
                continue
            if outcome == "pass" and not passed or outcome == "fail" and passed:
                continue
            selected.append(
                {
                    "sequence": index + 1,
                    "result": result,
                    "passed": passed,
                    "latency": latency,
                    "judge": metrics["judge_by_case"].get(result.case_id),
                    "judge_reason": _judge_reason(run, result.case_id),
                    "details": _case_details(result),
                }
            )
        if sort == "latency_desc":
            selected.sort(
                key=lambda item: (
                    item["latency"] is None,
                    -(item["latency"] or 0),
                    item["sequence"],
                )
            )
        return render_template(
            "run.html",
            entry=entry,
            run=run,
            metrics=metrics,
            configuration=_run_configuration(run),
            cases=selected,
            suite=suite_filter,
            outcome=outcome,
            sort=sort,
        )

    @app.get("/compare")
    def comparison():
        run_a_id = request.args.get("a", "").strip()
        run_b_id = request.args.get("b", "").strip()
        if not run_a_id or not run_b_id or run_a_id == run_b_id:
            return _error(
                "Seleção inválida",
                "Escolha dois IDs de run diferentes para comparar.",
                400,
            )
        try:
            entry_a = read_run(app.config["DATABASE_PATH"], run_a_id)
            entry_b = read_run(app.config["DATABASE_PATH"], run_b_id)
        except DatabaseReadError:
            return _error(
                "Banco indisponível",
                "O SQLite ficou indisponível. Atualize a página para tentar novamente.",
                503,
            )
        if entry_a is None or entry_b is None:
            return _error("Run não encontrado", "Um dos runs selecionados não existe.", 404)
        if entry_a.run is None or entry_b.run is None:
            return _error(
                "Erro ao ler run",
                "Os dados de um dos runs não puderam ser lidos. Confira o histórico.",
                422,
            )
        run_a, run_b = entry_a.run, entry_b.run
        try:
            comparison_data = compare_runs(run_a, run_b)
        except ValueError as exc:
            return _error("Comparação indisponível", str(exc), 422)
        return render_template(
            "compare.html",
            entry_a=entry_a,
            entry_b=entry_b,
            run_a=run_a,
            run_b=run_b,
            metrics_a=run_metrics(run_a),
            metrics_b=run_metrics(run_b),
            configuration_a=_run_configuration(run_a),
            configuration_b=_run_configuration(run_b),
            comparison=comparison_data,
            config_labels=_CONFIG_LABELS,
        )

    @app.errorhandler(404)
    def page_not_found(_error: Any):
        return _error_page("Página não encontrada", "O endereço solicitado não existe.", 404)

    return app


def _error(title: str, message: str, status: int):
    return _error_page(title, message, status), status


def _error_page(title: str, message: str, status: int) -> str:
    return render_template("error.html", title=title, message=message, status=status)


def serve(db_path: Path, port: int = 8765) -> None:
    """Start the dashboard on IPv4 loopback only."""
    if isinstance(port, bool) or not isinstance(port, int) or not _PORT_MIN <= port <= _PORT_MAX:
        raise ValueError("port must be between 1 and 65535")
    app = create_app(Path(db_path))
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
