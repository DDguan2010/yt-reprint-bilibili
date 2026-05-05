from __future__ import annotations

from common import load_config, now_iso, read_json, write_json


def main() -> None:
    config = load_config()
    runtime = config.get("runtime", {})
    selected = read_json(runtime.get("selected_file", "data/selected.json"), [])
    uploaded = read_json(runtime.get("upload_result_file", "data/upload-result.json"), [])
    successful_ids = {item.get("id") for item in uploaded if item.get("ok")}
    posted = read_json(runtime.get("posted_file", "data/posted.json"), [])
    existing = {item.get("id") if isinstance(item, dict) else item for item in posted}

    for item in selected:
        video_id = item.get("id")
        if not video_id or video_id in existing or video_id not in successful_ids:
            continue
        posted.append(
            {
                "id": video_id,
                "url": item.get("url"),
                "title": item.get("title"),
                "channel": item.get("channel"),
                "keyword": item.get("keyword"),
                "posted_at": now_iso(),
            }
        )
        existing.add(video_id)

    write_json(runtime.get("posted_file", "data/posted.json"), posted)
    write_json(runtime.get("latest_log_file", "logs/latest.json"), {"ok": True, "stage": "update_state", "posted_count": len(posted)})
    print(f"Posted state contains {len(posted)} video(s)")


if __name__ == "__main__":
    main()
