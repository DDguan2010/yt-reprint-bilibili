from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from common import fail_with_log, load_config, read_json, root_path, run_command, write_json


def parse_resolution(value: str | None) -> int:
    if not value:
        return 0
    match = re.search(r"(\d+)\s*x\s*(\d+)", str(value))
    if match:
        return int(match.group(1)) * int(match.group(2))
    match = re.search(r"(\d+)p", str(value).lower())
    if match:
        return int(match.group(1))
    return 0


def suffix_from_url(url: str, default: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".mp4", ".mkv", ".webm", ".mov", ".jpg", ".jpeg", ".png", ".webp"}:
        return suffix
    return default


def download_url(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with target.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    fh.write(chunk)


def resolve_ytdown_media_url(media_url: str, timeout_seconds: int = 180) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict | None = None
    while time.monotonic() < deadline:
        response = requests.get(media_url, timeout=60)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "application/json" not in content_type and not response.text.lstrip().startswith("{"):
            return media_url

        payload = response.json()
        last_payload = payload
        status = str(payload.get("status", "")).lower()
        print(f"ytdown worker status: {status or 'unknown'} {payload.get('percent') or payload.get('progress') or ''}".strip())
        file_url = payload.get("fileUrl")
        if status == "completed" and file_url and file_url != "Waiting...":
            return str(file_url)
        if status in {"failed", "error"}:
            raise RuntimeError(f"ytdown worker failed: {payload}")
        time.sleep(5)
    raise TimeoutError(f"ytdown worker did not complete in time: {last_payload}")


def validate_video_file(path: Path, min_size_bytes: int = 1024 * 1024) -> None:
    if not path.exists() or path.stat().st_size < min_size_bytes:
        raise RuntimeError(f"downloaded video is too small: {path.stat().st_size if path.exists() else 0} bytes")
    with path.open("rb") as fh:
        header = fh.read(32)
    if b"ftyp" not in header and not header.startswith(b"\x1aE\xdf\xa3"):
        raise RuntimeError(f"downloaded file is not a recognized video container: header={header!r}")


def normalize_mp4(path: Path) -> Path:
    if path.suffix.lower() != ".mp4":
        return path
    normalized = path.with_name(f"{path.stem}.normalized.mp4")
    result = run_command(["ffmpeg", "-y", "-i", str(path), "-c", "copy", "-movflags", "+faststart", str(normalized)])
    if result.returncode != 0:
        print(f"ffmpeg remux failed, using original file: {result.stdout[-2000:]}")
        return path
    validate_video_file(normalized)
    return normalized


def ytdown_download(item: dict, video_dir: Path, api_url: str) -> dict:
    response = requests.post(api_url, data={"url": item["url"]}, timeout=90)
    response.raise_for_status()
    payload = response.json()
    api = payload.get("api", {})
    if api.get("status") != "ok":
        raise RuntimeError(f"ytdown returned status {api.get('status')}: {api.get('message')}")

    media_items = api.get("mediaItems", []) or []
    videos = [media for media in media_items if str(media.get("type", "")).lower() == "video" and media.get("mediaUrl")]
    if not videos:
        raise RuntimeError("ytdown returned no video media items")
    best = max(videos, key=lambda media: parse_resolution(media.get("mediaRes") or media.get("mediaQuality")))

    resolved_video_url = resolve_ytdown_media_url(best["mediaUrl"])
    video_suffix = suffix_from_url(resolved_video_url, ".mp4")
    video_file = video_dir / f"{item['id']}{video_suffix}"
    download_url(resolved_video_url, video_file)
    validate_video_file(video_file)
    video_file = normalize_mp4(video_file)
    print(f"ytdown downloaded {video_file} ({video_file.stat().st_size} bytes)")

    thumbnail_url = best.get("mediaThumbnail") or api.get("imagePreviewUrl")
    cover_file = ""
    if thumbnail_url:
        cover_suffix = suffix_from_url(thumbnail_url, ".jpg")
        cover_path = video_dir / f"{item['id']}{cover_suffix}"
        download_url(thumbnail_url, cover_path)
        cover_file = str(cover_path)

    item["video_file"] = str(video_file)
    item["cover_file"] = cover_file
    item["download_method"] = "ytdown"
    item["download_quality"] = best.get("mediaQuality") or best.get("mediaRes") or ""
    return item


def ytdlp_download(item: dict, video_dir: Path, config: dict, archive_file: Path, youtube_cookie_file: Path) -> dict:
    download_cfg = config.get("download", {})
    output_template = str(video_dir / "%(id)s.%(ext)s")
    args = [
        "yt-dlp",
        "--no-playlist",
        "--download-archive",
        str(archive_file),
        "--js-runtimes",
        str(download_cfg.get("js_runtimes", "node")),
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
        raise RuntimeError(result.stdout[-4000:])

    video_files = sorted(
        [path for path in video_dir.iterdir() if path.is_file() and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}],
        key=lambda path: path.stat().st_size,
        reverse=True,
    )
    if not video_files:
        raise RuntimeError("yt-dlp produced no video file")

    cover_files = sorted(
        [path for path in video_dir.iterdir() if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}],
        key=lambda path: path.stat().st_size,
        reverse=True,
    )
    item["video_file"] = str(video_files[0])
    item["cover_file"] = str(cover_files[0]) if cover_files else ""
    item["download_method"] = "yt-dlp"
    return item


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
    ytdown_api_url = str(download_cfg.get("ytdown_api_url", "https://app.ytdown.to/proxy.php"))
    preferred_method = str(download_cfg.get("preferred_method", "ytdown"))

    downloaded: list[dict] = []
    failures: list[dict] = []
    max_uploads = int(config.get("search", {}).get("max_uploads_per_run", 1))
    for item in selected:
        if len(downloaded) >= max_uploads:
            break
        video_id = item["id"]
        video_dir = work_dir / video_id
        video_dir.mkdir(parents=True, exist_ok=True)
        errors: list[str] = []
        methods = ["ytdown", "yt-dlp"] if preferred_method == "ytdown" else ["yt-dlp", "ytdown"]
        for method in methods:
            try:
                if method == "ytdown":
                    item = ytdown_download(item, video_dir, ytdown_api_url)
                else:
                    item = ytdlp_download(item, video_dir, config, archive_file, youtube_cookie_file)
                downloaded.append(item)
                break
            except Exception as exc:  # noqa: BLE001
                message = f"{method} failed for {video_id}: {exc}"
                print(message)
                errors.append(message[-4000:])
        else:
            failures.append({"id": video_id, "title": item.get("title"), "output": "\n".join(errors)})

    if not downloaded:
        fail_with_log(config, "No selected candidates could be downloaded", {"failures": failures})

    write_json(runtime.get("selected_file", "data/selected.json"), downloaded)
    write_json(runtime.get("latest_log_file", "logs/latest.json"), {"ok": True, "stage": "download", "downloaded": downloaded, "failures": failures})
    print(f"Downloaded {len(downloaded)} video(s)")


if __name__ == "__main__":
    main()
