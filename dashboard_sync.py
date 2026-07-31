"""Export the bot's newest backtests into the connected dashboard repository."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DASHBOARD_DIR = BASE_DIR / "dashboard"
EXPORTER = DASHBOARD_DIR / "scripts" / "export_backtests.py"


def main() -> int:
    if not (DASHBOARD_DIR / ".git").exists():
        raise SystemExit(
            "Dashboard repository is not initialized. Run "
            "'git submodule update --init --recursive' first."
        )
    if not EXPORTER.exists():
        raise SystemExit(f"Dashboard exporter not found: {EXPORTER}")
    command = [
        sys.executable,
        str(EXPORTER),
        "--results-root",
        str(BASE_DIR / "results"),
        "--output",
        str(DASHBOARD_DIR / "data" / "backtests.json"),
    ]
    return subprocess.run(command, cwd=DASHBOARD_DIR, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
