from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from common import fail_with_log, load_config, root_path, run_command, video_id_from_url, write_json


YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


def parse_duration(value: str | None) -> int | None:
    if not value:
        return None
    # ISO 8601 duration subset used by YouTube, e.g. PT1H02M03S.
    import re

    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not match:
        return None
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def youtube_api_search(keyword: str, api_key: str, max_results: int) -> list[dict[str, Any]]:
    published_after = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    params = {
        "part": "snippet",
        "type": "video",
        "order": "date",
        "maxResults": max_results,
        "q": keyword,
        "publishedAfter": published_after,
        "key": api_key,
    }
    search_resp = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=30)
    search_resp.raise_for_status()
    items = search_resp.json().get("items", [])
    ids = [item["id"]["videoId"] for item in items if item.get("id", {}).get("videoId")]
    if not ids:
        return []

    details_resp = requests.get(
        YOUTUBE_VIDEOS_URL,
        params={"part": "snippet,contentDetails,statistics,status", "id": ",".join(ids), "key": api_key},
        timeout=30,
    )
    details_resp.raise_for_status()
    by_id = {item["id"]: item for item in details_resp.json().get("items", [])}

    candidates: list[dict[str, Any]] = []
    for video_id in ids:
        item = by_id.get(video_id)
        if not item:
            continue
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        status = item.get("status", {})
        candidates.append(
            {
                "id": video_id,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "title": snippet.get("title", ""),
                "channel": snippet.get("channelTitle", ""),
                "channel_id": snippet.get("channelId", ""),
                "duration": parse_duration(item.get("contentDetails", {}).get("duration")),
                "view_count": int(stats.get("viewCount", 0)),
                "upload_date": snippet.get("publishedAt", "")[:10],
                "license": status.get("license", ""),
                "keyword": keyword,
            }
        )
    return candidates


def ytdlp_search(keyword: str, max_results: int, config: dict[str, Any]) -> list[dict[str, Any]]:
    import json

    queries = [f"ytsearch{max_results}:{keyword}", f"ytsearchdate{max_results}:{keyword}"]
    args = ["yt-dlp", "--ignore-errors", "--flat-playlist", "--dump-json", "--skip-download"]
    youtube_cookie_file = root_path(config.get("runtime", {}).get("youtube_cookie_file", "youtube-cookies.txt"))
    if youtube_cookie_file.exists():
        args.extend(["--cookies", str(youtube_cookie_file)])
    results = [run_command([*args, query]) for query in queries]

    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    for result in results:
        if result.returncode != 0:
            errors.append(result.stdout)
        for line in result.stdout.splitlines():
            if not line.strip().startswith("{"):
                continue
            item = json.loads(line)
            video_id = item.get("id") or video_id_from_url(item.get("webpage_url", ""))
            if not video_id:
                continue
            candidates.append(
                {
                    "id": video_id,
                    "url": item.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}",
                    "title": item.get("title", ""),
                    "channel": item.get("channel") or item.get("uploader") or "",
                    "channel_id": item.get("channel_id") or "",
                    "duration": item.get("duration"),
                    "view_count": item.get("view_count") or 0,
                    "upload_date": str(item.get("upload_date") or ""),
                    "license": item.get("license") or "",
                    "keyword": keyword,
                }
            )
    if errors and not candidates:
        raise RuntimeError("\n".join(errors))
    return candidates


def main() -> None:
    config = load_config()
    search_cfg = config.get("search", {})
    runtime = config.get("runtime", {})
    keywords = [os.getenv("OVERRIDE_KEYWORD") or ""] if os.getenv("OVERRIDE_KEYWORD") else search_cfg.get("keywords", [])
    keywords = [keyword.strip() for keyword in keywords if keyword and keyword.strip()]
    if not keywords:
        fail_with_log(config, "No search keywords configured")

    max_per_keyword = int(search_cfg.get("max_candidates_per_keyword", 10))
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []

    for keyword in keywords:
        try:
            if api_key:
                candidates.extend(youtube_api_search(keyword, api_key, max_per_keyword))
            else:
                candidates.extend(ytdlp_search(keyword, max_per_keyword, config))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{keyword}: {exc}")

    deduped = {item["id"]: item for item in candidates if item.get("id")}
    output = list(deduped.values())
    write_json(runtime.get("candidates_file", "data/candidates.json"), output)
    write_json(runtime.get("latest_log_file", "logs/latest.json"), {"ok": True, "stage": "search", "count": len(output), "errors": errors})
    if not output:
        fail_with_log(config, "No candidates found", {"errors": errors})
    print(f"Found {len(output)} candidates")


if __name__ == "__main__":
    main()
