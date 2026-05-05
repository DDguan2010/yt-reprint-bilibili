from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from common import fail_with_log, load_config, load_posted_ids, read_json, write_json


def parse_upload_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = str(value)
    formats = ["%Y-%m-%d", "%Y%m%d"]
    for fmt in formats:
        try:
            return datetime.strptime(value[:10] if fmt == "%Y-%m-%d" else value[:8], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def is_allowed(candidate: dict[str, Any], config: dict[str, Any], posted_ids: set[str]) -> tuple[bool, str]:
    filters = config.get("filters", {})
    video_id = candidate.get("id")
    title = str(candidate.get("title") or "")
    channel_id = str(candidate.get("channel_id") or "")
    channel = str(candidate.get("channel") or "")
    duration = candidate.get("duration")
    view_count = int(candidate.get("view_count") or 0)

    if not video_id:
        return False, "missing video id"
    if video_id in posted_ids:
        return False, "already posted"
    if duration is None:
        return False, "missing duration"
    if int(duration) < int(filters.get("min_duration_seconds", 0)):
        return False, "too short"
    max_duration = int(filters.get("max_duration_seconds", 10**9))
    if int(duration) > max_duration:
        return False, "too long"
    if view_count < int(filters.get("min_view_count", 0)):
        return False, "view count too low"

    blocked_words = [str(word).lower() for word in filters.get("blocked_words", [])]
    haystack = f"{title} {channel}".lower()
    if any(word in haystack for word in blocked_words):
        return False, "blocked word"

    allowlist = set(filters.get("channel_allowlist", []) or [])
    if allowlist and channel_id not in allowlist and channel not in allowlist:
        return False, "not in channel allowlist"

    blocklist = set(filters.get("channel_blocklist", []) or [])
    if channel_id in blocklist or channel in blocklist:
        return False, "channel blocked"

    upload_date = parse_upload_date(candidate.get("upload_date"))
    within_days = int(filters.get("published_within_days", 0))
    if within_days and upload_date:
        age_days = (datetime.now(timezone.utc) - upload_date).days
        if age_days > within_days:
            return False, "too old"

    if filters.get("require_creative_commons", False):
        license_value = str(candidate.get("license") or "").lower()
        if "creative" not in license_value and license_value != "creativecommon":
            return False, "not creative commons"

    return True, "ok"


def score(candidate: dict[str, Any]) -> float:
    upload_date = parse_upload_date(candidate.get("upload_date"))
    age_penalty = 0
    if upload_date:
        age_penalty = max(0, (datetime.now(timezone.utc) - upload_date).days) * 5
    duration = int(candidate.get("duration") or 0)
    duration_penalty = abs(duration - 720) / 120
    view_score = min(int(candidate.get("view_count") or 0), 100000) / 1000
    return view_score - age_penalty - duration_penalty


def main() -> None:
    config = load_config()
    runtime = config.get("runtime", {})
    candidates = read_json(runtime.get("candidates_file", "data/candidates.json"), [])
    posted_ids = load_posted_ids(config)
    rejected: list[dict[str, Any]] = []
    allowed: list[dict[str, Any]] = []

    for candidate in candidates:
        ok, reason = is_allowed(candidate, config, posted_ids)
        if ok:
            candidate["score"] = score(candidate)
            allowed.append(candidate)
        else:
            rejected.append({"id": candidate.get("id"), "title": candidate.get("title"), "reason": reason})

    allowed.sort(key=lambda item: item.get("score", 0), reverse=True)
    max_uploads = int(config.get("search", {}).get("max_uploads_per_run", 1))
    max_attempts = max(max_uploads, int(config.get("download", {}).get("max_attempts_per_run", max_uploads)))
    selected = allowed[:max_attempts]
    write_json(runtime.get("selected_file", "data/selected.json"), selected)
    write_json(runtime.get("latest_log_file", "logs/latest.json"), {"ok": True, "stage": "select", "selected": selected, "rejected": rejected})
    if not selected:
        fail_with_log(config, "No candidate passed filters", {"rejected": rejected[:20]})
    print(f"Selected {len(selected)} candidate(s) for up to {max_uploads} upload(s)")


if __name__ == "__main__":
    main()
