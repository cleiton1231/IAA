"""Download pinado de jsonl pequenos e conversão para suítes importadas."""

from __future__ import annotations

import hashlib
import random
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

from bancada.adapters.bfcl import adapt_bfcl
from bancada.adapters.blind_spots import adapt_blind_spots
from bancada.adapters.falseqa import adapt_falseqa
from bancada.adapters.humaneval import adapt_humaneval
from bancada.adapters.truthfulqa import adapt_truthfulqa
from bancada.models import Case, Suite

ADAPTERS = {
    "humaneval": adapt_humaneval,
    "bfcl": adapt_bfcl,
    "truthfulqa": adapt_truthfulqa,
    "falseqa": adapt_falseqa,
    "blind_spots": adapt_blind_spots,
}


class FetchError(Exception):
    """Manifest, checksum, or size-budget failure."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_downloader(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as response:
        if response.status_code != 200:
            raise FetchError(f"download HTTP {response.status_code} for {url}")
        with dest.open("wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)


def fetch_manifest(
    manifest_path: Path | str,
    raw_dir: Path | str,
    suites_dir: Path | str,
    downloader=default_downloader,
) -> list[Path]:
    manifest_path = Path(manifest_path)
    raw_dir = Path(raw_dir)
    suites_dir = Path(suites_dir)
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise FetchError("manifest must be a mapping")
    max_bytes = int(raw.get("max_bytes") or 52_428_800)
    seed = str(raw.get("seed") or "bancada-v1")
    sources = raw.get("sources") or []
    raw_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    by_suite: dict[str, list[Case]] = {}
    for source in sources:
        url = source["url"]
        dest = raw_dir / _filename(source["id"], url)
        downloader(url, dest)
        size = dest.stat().st_size
        total += size
        if total > max_bytes:
            dest.unlink(missing_ok=True)
            raise FetchError(f"download too large: {total} bytes exceeds max_bytes={max_bytes}")
        expected = str(source.get("sha256") or "")
        actual = sha256_file(dest)
        if expected.lower() != actual.lower():
            raise FetchError(
                f"sha256 mismatch for {source['id']}: expected {expected} got {actual}"
            )
        adapter = ADAPTERS[source["adapter"]]
        cases = adapter(dest)
        cases = _sample(cases, cap=int(source.get("cap") or 0), seed=seed)
        by_suite.setdefault(source["suite"], []).extend(cases)

    written: list[Path] = []
    imported_dir = suites_dir / "imported"
    imported_dir.mkdir(parents=True, exist_ok=True)
    for suite_name, cases in by_suite.items():
        suite = Suite(name=suite_name, version=1, cases=cases)
        path = imported_dir / f"{suite_name}.yaml"
        path.write_text(_dump_suite(suite), encoding="utf-8")
        written.append(path)
    return written


def _filename(source_id: str, url: str) -> str:
    name = Path(urlparse(url).path).name
    if name:
        return name
    return f"{source_id}.jsonl"


def _sample(cases: list[Case], cap: int, seed: str) -> list[Case]:
    ordered = sorted(cases, key=lambda case: case.id)
    rng = random.Random(seed)
    rng.shuffle(ordered)
    if cap and cap > 0:
        return ordered[:cap]
    return ordered


def _dump_suite(suite: Suite) -> str:
    payload = {
        "version": suite.version,
        "suite": suite.name,
        "cases": [case.model_dump(mode="json") for case in suite.cases],
    }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
