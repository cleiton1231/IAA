"""Command-line interface for Bancada."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

from bancada.aggregate import format_enem_lines, summarize_run
from bancada.client import Client
from bancada.loader import load_named_suites
from bancada.models import Run
from bancada.packet import render_packet, render_packet_compact, write_auto_scores
from bancada.runner import run_many
from bancada.store import find_resumable_run, list_runs, load_run, save_run, save_scores

DEFAULT_ENDPOINT = "http://127.0.0.1:8080/v1"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_SEED = 42
DEFAULT_MAX_TOKENS = 512


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

    smoke = sub.add_parser("smoke", help="run 1 case per suite for quick validation")
    smoke.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    smoke.add_argument(
        "--suites",
        default="skepticism,code,obsidian,tools",
        help="comma-separated suite names",
    )
    smoke.add_argument("--suites-dir", default="suites")
    smoke.add_argument("--db", default=None, help="optional sqlite path")
    smoke.add_argument("--timeout", type=float, default=60.0)
    smoke.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    smoke.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    smoke.add_argument("--seed", type=int, default=DEFAULT_SEED)
    smoke.add_argument("--quiet", action="store_true")
    smoke.set_defaults(func=_cmd_smoke)

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
        default=DEFAULT_MAX_TOKENS,
        help="global generation cap (never exceeds per-case YAML max_tokens)",
    )
    run.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    run.add_argument("--seed", type=int, default=DEFAULT_SEED)
    run.add_argument(
        "--harness",
        choices=["direct", "pi"],
        default="direct",
        help="run cases through the pi coding-agent harness",
    )
    run.add_argument(
        "--resume",
        action="store_true",
        help="resume previous incomplete run for this model and suites",
    )
    run.add_argument("--quiet", action="store_true", help="suppress per-case progress")
    run.set_defaults(func=_cmd_run)

    export = sub.add_parser("export-judge")
    export.add_argument("run_id")
    export.add_argument("--db", default="data/bancada.sqlite")
    export.add_argument("--out", default=None)
    export.add_argument(
        "--full",
        action="store_true",
        help="full packet with every reply (debug); default is compact for OpenCode",
    )
    export.add_argument(
        "--split-categories",
        action="store_true",
        help="write one packet MD per category next to --out",
    )
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
    fetch.add_argument(
        "--only",
        default=None,
        help="comma-separated source ids to fetch (overrides enabled flags)",
    )
    fetch.set_defaults(func=_cmd_fetch)

    listing = sub.add_parser("list")
    listing.add_argument("--db", default="data/bancada.sqlite")
    listing.set_defaults(func=_cmd_list)
    return parser


def _client(args: argparse.Namespace, client: Client | None) -> Client:
    if client is not None:
        return client
    return Client(getattr(args, "endpoint", DEFAULT_ENDPOINT))


def _build_client(args: argparse.Namespace, client: Client | None):
    """Return (scoring_client, health_model_id) honoring --harness."""
    direct = _client(args, client)
    health_model = direct.health()
    if getattr(args, "harness", "direct") != "pi":
        return direct, health_model
    from bancada.harness_pi import PiClient

    pi_client = PiClient(endpoint="pi://local")
    return pi_client, health_model


def _p50(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def _format_summary(run: Run) -> str:
    n_total = len(run.results)
    n_pass = sum(
        1 for r in run.results if r.checks and all(chk.ok for chk in r.checks) and not r.error
    )
    pct = (n_pass / n_total * 100) if n_total else 0.0
    latencies = [r.total_ms for r in run.results if r.error is None]
    tps = [r.tokens_per_second for r in run.results if r.tokens_per_second is not None]
    ttfts = [r.ttft_ms for r in run.results if r.ttft_ms is not None]
    parts = [f"pass {n_pass}/{n_total} ({pct:.0f}%)"]
    p50_ms = _p50(latencies)
    if p50_ms is not None:
        parts.append(f"p50: {p50_ms:.1f}ms")
    p50_tps = _p50(tps)
    if p50_tps is not None:
        parts.append(f"p50 tok/s: {p50_tps:.1f}")
    p50_ttft = _p50(ttfts)
    if p50_ttft is not None:
        parts.append(f"p50 ttft: {p50_ttft:.1f}ms")
    summary = summarize_run(run)
    lines = [" | ".join(parts)]
    lines.extend(format_enem_lines(summary))
    return "\n".join(lines)


def _cmd_health(args: argparse.Namespace, client: Client | None) -> int:
    model_id = _client(args, client).health()
    print(model_id)
    return 0


def _cmd_smoke(args: argparse.Namespace, client: Client | None) -> int:
    c = _client(args, client)
    c.health()
    names = [part.strip() for part in args.suites.split(",") if part.strip()]
    suites = load_named_suites(
        args.suites_dir,
        names,
        include_imported=False,
        cap=1,
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
        c,
        suites,
        case_timeout=args.timeout,
        on_progress=None if args.quiet else on_progress,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        seed=args.seed,
    )
    if args.db:
        save_run(Path(args.db), run)
        print(f"saved {run.id}", flush=True)

    print(_format_summary(run), flush=True)
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
    c, health_model = _build_client(args, client)
    model_id = health_model
    versions = {suite.name: suite.version for suite in suites}

    resume_run = None
    if getattr(args, "resume", False):
        all_case_ids = [case.id for suite in suites for case in suite.cases]
        resume_run = find_resumable_run(
            Path(args.db),
            model_id,
            versions,
            expected_case_ids=all_case_ids,
        )
        if resume_run:
            print(
                f"resuming run {resume_run.id} ({len(resume_run.results)} cases loaded)",
                flush=True,
            )

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
        c,
        suites,
        case_timeout=args.timeout,
        on_progress=None if args.quiet else on_progress,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        seed=args.seed,
        resume_run=resume_run,
        db_path=Path(args.db),
        harness=getattr(args, "harness", "direct"),
    )
    save_run(Path(args.db), run)

    print(_format_summary(run), flush=True)
    print(f"saved {run.id}", flush=True)
    return 0


def _cmd_export(args: argparse.Namespace, client: Client | None) -> int:
    del client
    from bancada.packet import render_packets_by_category

    run = load_run(Path(args.db), args.run_id)
    if run is None:
        raise ValueError(f"unknown run {args.run_id}")

    if args.full:
        text = render_packet(run)
    else:
        text = render_packet_compact(run)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(str(out))
        auto_path = out.parent / f"scores-{args.run_id}-auto.json"
        write_auto_scores(auto_path, run)
        print(str(auto_path))
        if args.split_categories:
            for cat, cat_text in render_packets_by_category(run, compact=not args.full):
                cat_path = out.parent / f"{out.stem}-{cat}{out.suffix}"
                cat_path.write_text(cat_text, encoding="utf-8")
                print(str(cat_path))
    else:
        print(text)
    return 0


def _cmd_ingest(args: argparse.Namespace, client: Client | None) -> int:
    del client
    payload = json.loads(Path(args.scores_json).read_text(encoding="utf-8"))
    run = load_run(Path(args.db), args.run_id)
    if run is not None and run.judge_scores:
        payload = _merge_scores(run.judge_scores, payload)
    elif "auto" in payload or "cases" in payload:
        # Merge auto list + judge cases if both present in one file
        payload = _merge_scores(
            {"cases": payload.get("auto") or []},
            {"cases": payload.get("cases") or []},
        ) if payload.get("auto") else payload
    save_scores(Path(args.db), args.run_id, payload)
    print(f"ingested {args.run_id}")
    return 0


def _merge_scores(base: dict, override: dict) -> dict:
    """Merge score lists by case id; override wins. Keeps auto+judge together."""
    by_id: dict[str, dict] = {}
    for key in ("auto", "cases"):
        for item in base.get(key) or []:
            if isinstance(item, dict) and item.get("id"):
                by_id[str(item["id"])] = dict(item)
    for key in ("auto", "cases"):
        for item in override.get(key) or []:
            if isinstance(item, dict) and item.get("id"):
                cid = str(item["id"])
                merged = dict(by_id.get(cid) or {})
                merged.update(item)
                by_id[cid] = merged
    cases = list(by_id.values())
    out = {k: v for k, v in {**base, **override}.items() if k not in ("auto", "cases")}
    out["cases"] = cases
    out["auto_merged"] = True
    return out


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

    only = None
    if args.only:
        only = {part.strip() for part in args.only.split(",") if part.strip()}
    written = fetch_manifest(
        Path(args.manifest),
        raw_dir=Path(args.raw_dir),
        suites_dir=Path(args.suites_dir),
        only=only,
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
    if not run.results:
        return 0.0
    passed_cases = sum(
        1 for item in run.results
        if not item.error and item.checks and all(c.ok for c in item.checks)
    )
    return passed_cases / len(run.results)


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
    tps = [r.tokens_per_second for r in run.results if r.tokens_per_second is not None]
    p50_tps = _p50(tps)
    summary = summarize_run(run)
    line = (
        f"{run.id}  model={run.model_id}  cases={len(run.results)}  "
        f"machine_pass={_machine_pass(run):.2f}  enem={summary['enem_score']:.3f}"
    )
    if summary["suspeito"]:
        line += "  suspeito"
    if getattr(run, "harness", "direct") != "direct":
        line += f"  harness={run.harness}"
    if p50_tps is not None:
        line += f"  p50_tok/s={p50_tps:.1f}"
    judge = _judge_avg(run)
    if judge is not None:
        line += f"  judge={judge:.2f}"
    fr = summary.get("fail_reasons") or {}
    if fr:
        top = ", ".join(f"{k}×{v}" for k, v in list(fr.items())[:4])
        line += f"  fails=[{top}]"
    return line


def _format_diff(run_a: Run, run_b: Run) -> str:
    def judge_label(run: Run) -> str:
        avg = _judge_avg(run)
        return "n/a" if avg is None else f"{avg:.2f}"

    def tps_label(run: Run) -> str:
        vals = [r.tokens_per_second for r in run.results if r.tokens_per_second is not None]
        p = _p50(vals)
        return "n/a" if p is None else f"{p:.1f}"

    sa = summarize_run(run_a)
    sb = summarize_run(run_b)
    lines = [
        (
            f"{run_a.id} model={run_a.model_id} machine_pass={_machine_pass(run_a):.2f} "
            f"enem={sa['enem_score']:.3f} p50_tok/s={tps_label(run_a)} judge={judge_label(run_a)}"
        ),
        (
            f"{run_b.id} model={run_b.model_id} machine_pass={_machine_pass(run_b):.2f} "
            f"enem={sb['enem_score']:.3f} p50_tok/s={tps_label(run_b)} judge={judge_label(run_b)}"
        ),
    ]
    lines.extend(format_enem_lines(sa))
    lines.append("---")
    lines.extend(format_enem_lines(sb))
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
