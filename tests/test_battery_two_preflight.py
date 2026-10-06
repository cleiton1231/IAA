import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_launcher_preflight_reports_missing_non_executable_and_accepts_executable(
    tmp_path: Path,
) -> None:
    check = ROOT / "scripts" / "check_launchers.sh"
    missing = tmp_path / "missing-launcher.sh"

    missing_result = subprocess.run(
        ["bash", str(check), str(missing)], capture_output=True, text=True, check=False
    )
    assert missing_result.returncode != 0
    assert "launcher ausente" in missing_result.stderr
    assert not missing.exists()

    non_executable = tmp_path / "non-executable.sh"
    non_executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    non_executable_result = subprocess.run(
        ["bash", str(check), str(non_executable)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert non_executable_result.returncode != 0
    assert "não executável" in non_executable_result.stderr

    executable = tmp_path / "executable.sh"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    assert subprocess.run(["bash", str(check), str(executable)], check=False).returncode == 0


def test_battery_two_preflights_all_launchers_before_creating_outputs_or_stopping() -> None:
    script = (ROOT / "scripts" / "battery_two.sh").read_text(encoding="utf-8")
    preflight = script.index("./scripts/check_launchers.sh")

    assert preflight < script.index("mkdir -p")
    assert preflight < script.index("./scripts/stop_llama.sh")
