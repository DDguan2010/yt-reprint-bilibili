from __future__ import annotations

from pathlib import Path

from common import fail_with_log, load_config, read_json, root_path, run_command, write_json


def main() -> None:
    config = load_config()
    runtime = config.get("runtime", {})
    download_cfg = config.get("download", {})
    selected = read_json(runtime.get("selected_file", "data/selected.json"), [])
    if not selected:
        fail_with_log(config, "No selected videos to download")

    work_dir = root_path(runtime.get("work_dir", "downloads"))
    work_dir.mkdir(parents=True, exist_ok=True)
    archive_file = root_path(runtime.get("archive_file", "data/download-archive.txt"))
    archive_file.parent.mkdir(parents=True, exist_ok=True)
    youtube_cookie_file = root_path(runtime.get("youtube_cookie_file", "youtube-cookies.txt"))

    downloaded: list[dict] = []
    failures: list[dict] = []
    max_uploads = int(config.get("search", {}).get("max_uploads_per_run", 1))
    for item in selected:
        if len(downloaded) >= max_uploads:
            break
        video_id = item["id"]
        video_dir = work_dir / video_id
        video_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(video_dir / "%(id)s.%(ext)s")

        args = [
            "yt-dlp",
            "--no-playlist",
            "--download-archive",
            str(archive_file),
            "--js-runtimes",
            str(download_cfg.get("js_runtimes", "deno")),
            "--remote-components",
            str(download_cfg.get("remote_components", "ejs:npm")),
            "--extractor-args",
            str(download_cfg.get("extractor_args", "youtube:player_client=tv,web")),
            "--retries",
            "10",
            "--fragment-retries",
            "10",
            "-f",
            str(download_cfg.get("format", "bv*+ba/b")),
            "--merge-output-format",
            str(download_cfg.get("merge_output_format", "mp4")),
            "--write-info-json",
            "-o",
            output_template,
        ]
        if download_cfg.get("write_thumbnail", True):
            args.append("--write-thumbnail")
        subtitle_languages = download_cfg.get("subtitle_languages", []) or []
        if subtitle_languages:
            args.extend(["--write-subs", "--write-auto-subs", "--sub-langs", ",".join(subtitle_languages)])
        if youtube_cookie_file.exists():
            args.extend(["--cookies", str(youtube_cookie_file)])
        args.append(item["url"])

        result = run_command(args)
        if result.returncode != 0:
            print(f"yt-dlp failed for {video_id}; trying next candidate")
            print(result.stdout[-4000:])
            failures.append({"id": video_id, "title": item.get("title"), "output": result.stdout[-4000:]})
            continue

        video_files = sorted(
            [path for path in video_dir.iterdir() if path.is_file() and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}],
            key=lambda path: path.stat().st_size,
            reverse=True,
        )
        if not video_files:
            print(f"No downloaded video file found for {video_id}; trying next candidate")
            failures.append({"id": video_id, "title": item.get("title"), "output": "no downloaded video file"})
            continue

        cover_files = sorted(
            [path for path in video_dir.iterdir() if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}],
            key=lambda path: path.stat().st_size,
            reverse=True,
        )
        item["video_file"] = str(video_files[0])
        item["cover_file"] = str(cover_files[0]) if cover_files else ""
        downloaded.append(item)

    if not downloaded:
        fail_with_log(config, "No selected candidates could be downloaded", {"failures": failures})

    write_json(runtime.get("selected_file", "data/selected.json"), downloaded)
    write_json(runtime.get("latest_log_file", "logs/latest.json"), {"ok": True, "stage": "download", "downloaded": downloaded, "failures": failures})
    print(f"Downloaded {len(downloaded)} video(s)")


if __name__ == "__main__":
    main()
