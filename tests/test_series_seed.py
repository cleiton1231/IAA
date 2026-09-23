"""scripts/series_seed.sh — seed da série: uma por série, igual para todos os modelos."""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "series_seed.sh"


def run(env: dict[str, str], workdir: Path) -> str:
    out = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        cwd=workdir,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout


def seed_from(output: str) -> int:
    for line in output.splitlines():
        if line.startswith("series seed="):
            return int(line.split("=", 1)[1])
    raise AssertionError(f"sem 'series seed=' na saída: {output!r}")


def test_first_call_generates_seed_in_range(tmp_path: Path) -> None:
    out = run({"BANCADA_SERIES_DIR": str(tmp_path)}, tmp_path)
    seed = seed_from(out)
    assert 1000 <= seed <= 2147483647
    assert (tmp_path / "bancada_series.seed").read_text().strip() == str(seed)


def test_same_series_reuses_seed(tmp_path: Path) -> None:
    first = seed_from(run({"BANCADA_SERIES_DIR": str(tmp_path)}, tmp_path))
    second = seed_from(run({"BANCADA_SERIES_DIR": str(tmp_path)}, tmp_path))
    assert first == second


def test_new_series_regenerates_seed(tmp_path: Path) -> None:
    seed_from(run({"BANCADA_SERIES_DIR": str(tmp_path)}, tmp_path))
    (tmp_path / "bancada_series.seed").write_text("424242\n")
    again = run(
        {"BANCADA_SERIES_DIR": str(tmp_path), "BANCADA_NEW_SERIES": "1"}, tmp_path
    )
    new_seed = seed_from(again)
    assert new_seed != 424242
    assert 1000 <= new_seed <= 2147483647
    assert (tmp_path / "bancada_series.seed").read_text().strip() == str(new_seed)


def test_explicit_seed_pins_and_persists(tmp_path: Path) -> None:
    out = run({"BANCADA_SERIES_DIR": str(tmp_path), "BANCADA_SEED": "7"}, tmp_path)
    assert seed_from(out) == 7
    assert (tmp_path / "bancada_series.seed").read_text().strip() == "7"
    # sem BANCADA_SEED na próxima chamada, a série continua na 7
    assert seed_from(run({"BANCADA_SERIES_DIR": str(tmp_path)}, tmp_path)) == 7
