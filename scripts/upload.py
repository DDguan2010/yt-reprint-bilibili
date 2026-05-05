from __future__ import annotations

import os
import shlex
from pathlib import Path

from common import fail_with_log, load_config, read_json, root_path, run_command, sanitize_text, write_json, write_text


def render_template(template: str, item: dict) -> str:
    values = {
        "id": item.get("id", ""),
        "url": item.get("url", ""),
        "title": item.get("title", ""),
        "channel": item.get("channel", ""),
        "upload_date": item.get("upload_date", ""),
        "keyword": item.get("keyword", ""),
    }
    return template.format(**values)


def build_command(template: str, values: dict[str, str]) -> list[str]:
    rendered = template.format(**{key: shlex.quote(str(value)) for key, value in values.items()})
    return shlex.split(rendered)


def main() -> None:
    config = load_config()
    runtime = config.get("runtime", {})
    bili_cfg = config.get("bilibili", {})
    selected = read_json(runtime.get("selected_file", "data/selected.json"), [])
    if not selected:
        fail_with_log(config, "No selected videos to upload")

    cookie_file = root_path(runtime.get("cookie_file", "cookies.json"))
    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
    if not dry_run and not cookie_file.exists():
        fail_with_log(config, f"Bilibili login file not found: {cookie_file}")
    results: list[dict] = []
    for item in selected:
        video_file = Path(item.get("video_file", ""))
        if not video_file.exists():
            fail_with_log(config, f"Video file not found: {video_file}")

        raw_title = render_template(str(bili_cfg.get("title_template", "{title}")), item)
        title = sanitize_text(raw_title, 80)
        desc = render_template(str(bili_cfg.get("desc_template", "原视频：{url}")), item)
        desc_file = video_file.parent / "bilibili-desc.txt"
        write_text(desc_file, desc)
        tags = ",".join(str(tag) for tag in bili_cfg.get("default_tags", []) if str(tag).strip())

        values = {
            "cookie_file": str(cookie_file),
            "video_file": str(video_file),
            "cover_file": str(item.get("cover_file", "")),
            "title": title,
            "desc_file": str(desc_file),
            "source": str(item.get("url", "")),
            "tid": str(bili_cfg.get("tid", 171)),
            "tags": tags,
            "copyright": str(bili_cfg.get("copyright", 2)),
        }
        command = build_command(str(bili_cfg.get("upload_command_template")), values)
        result_payload = {"id": item.get("id"), "title": title, "command": command, "dry_run": dry_run}
        if dry_run:
            results.append({**result_payload, "ok": True, "output": "dry run"})
            continue

        result = run_command(command)
        if result.returncode != 0:
            fail_with_log(config, f"biliup upload failed for {item.get('id')}", {"output": result.stdout[-4000:]})
        results.append({**result_payload, "ok": True, "output": result.stdout[-4000:]})

    write_json(runtime.get("upload_result_file", "data/upload-result.json"), results)
    write_json(runtime.get("latest_log_file", "logs/latest.json"), {"ok": True, "stage": "upload", "results": results})
    print(f"Uploaded {len(results)} video(s)" if not dry_run else f"Prepared {len(results)} upload(s)")


if __name__ == "__main__":
    main()
