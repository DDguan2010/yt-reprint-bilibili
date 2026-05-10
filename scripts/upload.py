from __future__ import annotations

import os
import shlex
import time
from pathlib import Path

from common import fail_with_log, load_config, read_json, root_path, run_command, sanitize_text, write_json, write_text


def prepare_cover(cover_file: str) -> str:
    if not cover_file:
        return ""
    cover_path = Path(cover_file)
    if not cover_path.exists():
        return ""
    if cover_path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        return str(cover_path)

    from PIL import Image

    jpg_path = cover_path.with_suffix(".jpg")
    with Image.open(cover_path) as image:
        image.convert("RGB").save(jpg_path, "JPEG", quality=95)
    return str(jpg_path)


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
    rendered = template.format(
        **{key: str(value) if key.endswith("_arg") else shlex.quote(str(value)) for key, value in values.items()}
    )
    return shlex.split(rendered)


def run_upload_with_retries(command: list[str], retries: int = 3) -> tuple[bool, str]:
    outputs: list[str] = []
    for attempt in range(1, retries + 1):
        print(f"biliup upload attempt {attempt}/{retries}")
        result = run_command(command)
        output = result.stdout or ""
        outputs.append(f"--- attempt {attempt}, exit {result.returncode} ---\n{output}")
        if output.strip():
            print(output[-4000:])
        if result.returncode == 0:
            return True, "\n".join(outputs)
        if attempt < retries:
            time.sleep(20 * attempt)
    return False, "\n".join(outputs)


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
        cover_file = prepare_cover(str(item.get("cover_file", "")))

        values = {
            "cookie_file": str(cookie_file),
            "video_file": str(video_file),
            "cover_file": cover_file,
            "cover_arg": f"--cover {shlex.quote(cover_file)}" if cover_file else "",
            "title": title,
            "desc": desc,
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

        ok, output = run_upload_with_retries(command)
        if not ok and cover_file:
            print("biliup upload failed with cover; retrying once without cover")
            no_cover_values = {**values, "cover_file": "", "cover_arg": ""}
            no_cover_command = build_command(str(bili_cfg.get("upload_command_template")), no_cover_values)
            ok, no_cover_output = run_upload_with_retries(no_cover_command, retries=1)
            output = f"{output}\n--- retry without cover ---\n{no_cover_output}"
            result_payload["fallback_command"] = no_cover_command
        if not ok:
            print(output[-8000:])
            fail_with_log(config, f"biliup upload failed for {item.get('id')}", {"output": output[-8000:]})
        results.append({**result_payload, "ok": True, "output": output[-4000:]})

    write_json(runtime.get("upload_result_file", "data/upload-result.json"), results)
    write_json(runtime.get("latest_log_file", "logs/latest.json"), {"ok": True, "stage": "upload", "results": results})
    print(f"Uploaded {len(results)} video(s)" if not dry_run else f"Prepared {len(results)} upload(s)")


if __name__ == "__main__":
    main()
