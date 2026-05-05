from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.yml"


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def root_path(path: str | Path) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path
    return ROOT / path


def read_json(path: str | Path, default: Any) -> Any:
    file_path = root_path(path)
    if not file_path.exists():
        return default
    with file_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: str | Path, data: Any) -> None:
    file_path = root_path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def write_text(path: str | Path, content: str) -> None:
    file_path = root_path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def video_id_from_url(url: str) -> str | None:
    patterns = [
        r"[?&]v=([a-zA-Z0-9_-]{6,})",
        r"youtu\.be/([a-zA-Z0-9_-]{6,})",
        r"youtube\.com/shorts/([a-zA-Z0-9_-]{6,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def sanitize_text(value: str, max_len: int) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value[:max_len].rstrip()


def run_command(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    printable = " ".join(shlex.quote(arg) for arg in args)
    print(f"$ {printable}")
    return subprocess.run(args, cwd=cwd or ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def fail_with_log(config: dict[str, Any], message: str, extra: dict[str, Any] | None = None) -> None:
    runtime = config.get("runtime", {})
    payload = {"ok": False, "time": now_iso(), "message": message}
    if extra:
        payload.update(extra)
    write_json(runtime.get("latest_log_file", "logs/latest.json"), payload)
    raise SystemExit(message)


def load_posted_ids(config: dict[str, Any]) -> set[str]:
    posted = read_json(config.get("runtime", {}).get("posted_file", "data/posted.json"), [])
    ids: set[str] = set()
    for item in posted:
        if isinstance(item, str):
            ids.add(item)
        elif isinstance(item, dict) and item.get("id"):
            ids.add(str(item["id"]))
    return ids
