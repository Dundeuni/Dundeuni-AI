"""Run text API checks with a separate Python 3.12 interpreter.

The existing Python 3.9 image verification entry point remains unchanged.
No production model, OCR worker, network service, or GPU inference is started.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def run_check(
    arguments: list[str], folder: Path, environment: dict[str, str]
) -> dict[str, Any]:
    """Run one check in text-ai and retain its real exit code and output."""
    completed = subprocess.run(
        arguments,
        cwd=folder,
        env=environment,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    return {
        "command": arguments,
        "workingDirectory": str(folder),
        "exitCode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def main() -> int:
    """Validate the selected interpreter, run checks, and save a new report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python 3.12 text environment executable; no packages are installed",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Optional JSON result path; default is an ignored text-ai/results path",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    folder = root / "text-ai"
    executable = args.python.resolve()
    if not executable.is_file():
        parser.error("The selected text Python executable does not exist")
    if not (folder / "check_package.py").is_file():
        parser.error("Run this entry point from a checkout containing text-ai")

    environment = dict(os.environ)
    environment.update(
        PYTHONUTF8="1",
        PYTHONIOENCODING="utf-8",
        PYTHONDONTWRITEBYTECODE="1",
        AI_TEXT_DEVICE="cpu",
        AI_URL_REPUTATION_ENABLED="0",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
    )
    environment.pop("AI_SERVICE_TOKEN", None)
    environment.pop("AI_WEBRISK_API_KEY", None)
    probe = run_check(
        [str(executable), "-c", "import sys\nprint(sys.version_info[:2])"],
        folder,
        environment,
    )
    if probe["exitCode"] != 0 or probe["stdout"].strip() != "(3, 12)":
        print("FAIL: select a Python 3.12 text environment with --python")
        print(probe["stderr"].strip())
        return 2

    result_folder = folder / "results" / "text-verification"
    result_folder.mkdir(parents=True, exist_ok=True)
    temporary = result_folder / "tmp"
    temporary.mkdir(exist_ok=True)
    environment["TEMP"] = str(temporary)
    environment["TMP"] = str(temporary)
    commands = [
        [str(executable), "-m", "pytest", "tests", "-q"],
        [str(executable), "check_package.py", "--code-only"],
    ]
    checks = [run_check(command, folder, environment) for command in commands]
    for check in checks:
        status = "PASS" if check["exitCode"] == 0 else "FAIL"
        print(f"{status}: {' '.join(check['command'])}")
        print(check["stdout"].strip())
        if check["stderr"].strip():
            print(check["stderr"].strip())

    files = sorted(
        [
            *folder.glob("ai_text/*.py"),
            *folder.glob("tests/*.py"),
            folder / "check_package.py",
            folder / "PACKAGE_MANIFEST.json",
            Path(__file__).resolve(),
        ]
    )
    report = {
        "completedAt": datetime.now(timezone.utc).isoformat(),
        "scope": "CPU tiny models, stub API, mocked devices and code integrity",
        "interpreter": str(executable),
        "pythonVersion": [3, 12],
        "workingDirectory": str(folder),
        "checks": checks,
        "realModelOCRGPUBEExecution": False,
        "historicalValidationRecordsModified": False,
        "fileSha256": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files
        },
    }
    destination = args.report.resolve() if args.report else result_folder / "latest.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Results: {destination}")
    return 1 if any(check["exitCode"] for check in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
