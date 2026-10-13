from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    commands = [
        ["pytest", "-q"],
        ["ruff", "check", "src", "tests", "scripts"],
        ["ruff", "format", "--check", "src", "tests", "scripts"],
        ["mypy", "src"],
        ["pip", "check"],
    ]
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    checks = []
    for arguments in commands:
        command = [sys.executable, "-m", *arguments]
        result = subprocess.run(
            command,
            cwd=root,
            env=environment,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        checks.append(
            {
                "command": command,
                "exitCode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        print(f"{'PASS' if result.returncode == 0 else 'FAIL'}: {' '.join(arguments)}")
        print(result.stdout.strip())
    files = sorted(
        [
            *root.glob("src/**/*.py"),
            *root.glob("tests/**/*.py"),
            *root.glob("scripts/**/*.py"),
            root / "pyproject.toml",
            root / "config.example.json",
            root / "requirements-lock.txt",
        ]
    )
    report = {
        "completedAt": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "executable": sys.executable,
        "workingDirectory": str(root),
        "mockOnly": True,
        "checks": checks,
        "fileSha256": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files
        },
    }
    (root / "validation-results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    sys.exit(1 if any(check["exitCode"] for check in checks) else 0)


if __name__ == "__main__":
    main()
