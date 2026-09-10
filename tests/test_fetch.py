"""Fetch never hits the network in tests; sha256 and the 50 MB cap are real."""

import hashlib
from pathlib import Path

import pytest
import yaml

from bancada.fetch import FetchError, fetch_manifest, sha256_file

FIXTURES = Path(__file__).parent / "fixtures"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_fetch_copies_fixture_and_writes_imported_yaml(tmp_path: Path) -> None:
    src = FIXTURES / "humaneval.jsonl"
    dest_name = "humaneval.jsonl"
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "max_bytes": 52428800,
                "seed": "bancada-v1",
                "sources": [
                    {
                        "id": "humaneval",
                        "suite": "code",
                        "adapter": "humaneval",
                        "url": "https://example.invalid/humaneval.jsonl",
                        "sha256": _hash(src),
                        "cap": 2,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def downloader(url: str, dest: Path) -> None:
        assert url.startswith("https://example.invalid/")
        dest.write_bytes(src.read_bytes())

    written = fetch_manifest(
        manifest,
        raw_dir=tmp_path / "raw",
        suites_dir=tmp_path / "suites",
        downloader=downloader,
    )
    assert (tmp_path / "raw" / dest_name).exists()
    imported = tmp_path / "suites" / "imported" / "code.yaml"
    assert imported in written
    payload = yaml.safe_load(imported.read_text(encoding="utf-8"))
    assert payload["suite"] == "code"
    assert len(payload["cases"]) == 2
    assert all(c["id"].startswith("imported.humaneval.") for c in payload["cases"])


def test_fetch_aborts_when_bytes_exceed_cap(tmp_path: Path) -> None:
    src = FIXTURES / "humaneval.jsonl"
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "max_bytes": 10,
                "seed": "bancada-v1",
                "sources": [
                    {
                        "id": "humaneval",
                        "suite": "code",
                        "adapter": "humaneval",
                        "url": "https://example.invalid/x",
                        "sha256": _hash(src),
                        "cap": 2,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def downloader(url: str, dest: Path) -> None:
        dest.write_bytes(src.read_bytes())

    with pytest.raises(FetchError, match="50 MB|max_bytes|too large"):
        fetch_manifest(
            manifest,
            raw_dir=tmp_path / "raw",
            suites_dir=tmp_path / "suites",
            downloader=downloader,
        )


def test_fetch_rejects_sha256_mismatch(tmp_path: Path) -> None:
    src = FIXTURES / "humaneval.jsonl"
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "max_bytes": 52428800,
                "seed": "bancada-v1",
                "sources": [
                    {
                        "id": "humaneval",
                        "suite": "code",
                        "adapter": "humaneval",
                        "url": "https://example.invalid/x",
                        "sha256": "0" * 64,
                        "cap": 2,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def downloader(url: str, dest: Path) -> None:
        dest.write_bytes(src.read_bytes())

    with pytest.raises(FetchError, match="sha256"):
        fetch_manifest(
            manifest,
            raw_dir=tmp_path / "raw",
            suites_dir=tmp_path / "suites",
            downloader=downloader,
        )


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "f.bin"
    path.write_bytes(b"abc")
    assert sha256_file(path) == hashlib.sha256(b"abc").hexdigest()
