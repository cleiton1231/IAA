"""Command-line interface for Bancada."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bancada.client import Client
from bancada.loader import load_named_suites
from bancada.models import Run
from bancada.packet import render_packet
from bancada.runner import run_many
from bancada.store import list_runs, load_run, save_run, save_scores

DEFAULT_ENDPOINT = "http://127.0.0.1:8080/v1"


def main(argv: list[str] | None = None, client: Client | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args, client)
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bancada")
    sub = parser.add_subparsers(dest="cmd", required=True)

    health = sub.add_parser("health")
    health.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    health.set_defaults(func=_cmd_health)

    run = sub.add_parser("run")
    run.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    run.add_argument("--suites", required=True, help="comma-separated suite names")
    run.add_argument("--suites-dir", default="suites")
    run.add_argument("--db", default="data/bancada.sqlite")
    run.add_argument("--imported", action="store_true")
    run.add_argument("--no-imported", action="store_true")
    run.add_argument("--cap", type=int, default=None)
    run.add_argument("--timeout", type=float, default=60.0)
    run.add_argument(
        "--max-tokens",
        type=int,
        default=1024,
        help="cap generation length (important for thinking models)",
    )
    run.add_argument("--quiet", action="store_true", help="suppress per-case progress")
    run.set_defaults(func=_cmd_run)

    export = sub.add_parser("export-judge")
    export.add_argument("run_id")
    export.add_argument("--db", default="data/bancada.sqlite")
    export.add_argument("--out", default=None)
    export.set_defaults(func=_cmd_export)

    ingest = sub.add_parser("ingest-scores")
    ingest.add_argument("run_id")
    ingest.add_argument("scores_json")
    ingest.add_argument("--db", default="data/bancada.sqlite")
    ingest.set_defaults(func=_cmd_ingest)

    diff = sub.add_parser("diff")
    diff.add_argument("run_a")
    diff.add_argument("run_b")
    diff.add_argument("--db", default="data/bancada.sqlite")
    diff.set_defaults(func=_cmd_diff)

    fetch = sub.add_parser("fetch")
    fetch.add_argument("--manifest", default="data/manifest.yaml")
    fetch.add_argument("--raw-dir", default="data/raw")
    fetch.add_argument("--suites-dir", default="suites")
    fetch.set_defaults(func=_cmd_fetch)

    listing = sub.add_parser("list")
    listing.add_argument("--db", default="data/bancada.sqlite")
    listing.set_defaults(func=_cmd_list)
    return parser


def _client(args: argparse.Namespace, client: Client | None) -> Client:
    if client is not None:
        return client
    return Client(getattr(args, "endpoint", DEFAULT_ENDPOINT))


def _cmd_health(args: argparse.Namespace, client: Client | None) -> int:
    model_id = _client(args, client).health()
    print(model_id)
    return 0


def _cmd_run(args: argparse.Namespace, client: Client | None) -> int:
    names = [part.strip() for part in args.suites.split(",") if part.strip()]
    include_imported = bool(args.imported) and not args.no_imported
    suites = load_named_suites(
        args.suites_dir,
        names,
        include_imported=include_imported,
        cap=args.cap,
    )
    total = sum(len(suite.cases) for suite in suites)

    def on_progress(event: str, index: int, _total: int, case_id: str, *rest: object) -> None:
        if args.quiet:
            return
        if event == "start":
            print(f"[{index}/{total}] start {case_id}", flush=True)
            return
        machine_ok = bool(rest[0]) if rest else False
        result = rest[1] if len(rest) > 1 else None
        status = "ok" if machine_ok else "fail"
        ms = getattr(result, "total_ms", 0.0) if result is not None else 0.0
        err = getattr(result, "error", None) if result is not None else None
        extra = f" error={err}" if err else ""
        print(f"[{index}/{total}] {status} {case_id} {ms:.0f}ms{extra}", flush=True)

    run = run_many(
        _client(args, client),
        suites,
        case_timeout=args.timeout,
        on_progress=None if args.quiet else on_progress,
        max_tokens=args.max_tokens,
    )
    save_run(Path(args.db), run)
    print(f"saved {run.id}", flush=True)
    return 0


def _cmd_export(args: argparse.Namespace, client: Client | None) -> int:
    del client
    run = load_run(Path(args.db), args.run_id)
    if run is None:
        raise ValueError(f"unknown run {args.run_id}")
    text = render_packet(run)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(str(out))
    else:
        print(text)
    return 0


def _cmd_ingest(args: argparse.Namespace, client: Client | None) -> int:
    del client
    payload = json.loads(Path(args.scores_json).read_text(encoding="utf-8"))
    save_scores(Path(args.db), args.run_id, payload)
    print(f"ingested {args.run_id}")
    return 0


def _cmd_diff(args: argparse.Namespace, client: Client | None) -> int:
    del client
    run_a = load_run(Path(args.db), args.run_a)
    run_b = load_run(Path(args.db), args.run_b)
    if run_a is None or run_b is None:
        raise ValueError("unknown run")
    print(_format_diff(run_a, run_b))
    return 0


def _cmd_fetch(args: argparse.Namespace, client: Client | None) -> int:
    del client
    from bancada.fetch import fetch_manifest

    written = fetch_manifest(
        Path(args.manifest),
        raw_dir=Path(args.raw_dir),
        suites_dir=Path(args.suites_dir),
    )
    for path in written:
        print(path)
    return 0


def _cmd_list(args: argparse.Namespace, client: Client | None) -> int:
    del client
    for run in list_runs(Path(args.db)):
        print(_format_run_line(run))
    return 0


def _machine_pass(run: Run) -> float:
    checks = [c.ok for item in run.results for c in item.checks]
    if not checks:
        return 0.0
    return sum(1 for ok in checks if ok) / len(checks)


def _judge_avg(run: Run) -> float | None:
    scores = run.judge_scores
    if not scores:
        return None
    cases = scores.get("cases") or []
    vals = [c.get("score") for c in cases if isinstance(c.get("score"), (int, float))]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _format_run_line(run: Run) -> str:
    line = (
        f"{run.id}  model={run.model_id}  cases={len(run.results)}  "
        f"machine_pass={_machine_pass(run):.2f}"
    )
    judge = _judge_avg(run)
    if judge is not None:
        line += f"  judge={judge:.2f}"
    return line


def _format_diff(run_a: Run, run_b: Run) -> str:
    def judge_label(run: Run) -> str:
        avg = _judge_avg(run)
        return "n/a" if avg is None else f"{avg:.2f}"

    return (
        f"{run_a.id} model={run_a.model_id} machine_pass={_machine_pass(run_a):.2f} "
        f"judge={judge_label(run_a)}\n"
        f"{run_b.id} model={run_b.model_id} machine_pass={_machine_pass(run_b):.2f} "
        f"judge={judge_label(run_b)}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
