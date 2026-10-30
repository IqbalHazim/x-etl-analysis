"""Run manifest: one JSON file per run recording what each step did, for reproducibility."""

import json
import subprocess
from datetime import UTC, datetime
from typing import Any

from xetl import __version__
from xetl.config import Settings


def git_sha(settings: Settings) -> str:
    if settings.git_sha != "unknown":
        return settings.git_sha
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def record_step(settings: Settings, run: str, step: str, **details: Any) -> None:
    path = settings.data_dir / "manifests" / f"{run}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = json.loads(path.read_text()) if path.exists() else []
    entries.append(
        {
            "step": step,
            "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "xetl_version": __version__,
            "git_sha": git_sha(settings),
            **details,
        }
    )
    path.write_text(json.dumps(entries, indent=2, default=str))
