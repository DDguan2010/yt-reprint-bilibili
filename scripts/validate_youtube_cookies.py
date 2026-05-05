from __future__ import annotations

from common import fail_with_log, load_config, root_path, write_json


AUTH_COOKIE_NAMES = {
    "APISID",
    "HSID",
    "LOGIN_INFO",
    "SAPISID",
    "SID",
    "SSID",
    "__Secure-1PAPISID",
    "__Secure-1PSID",
    "__Secure-3PAPISID",
    "__Secure-3PSID",
}


def main() -> None:
    config = load_config()
    runtime = config.get("runtime", {})
    cookie_file = root_path(runtime.get("youtube_cookie_file", "youtube-cookies.txt"))
    if not cookie_file.exists():
        fail_with_log(config, f"YouTube cookie file not found: {cookie_file}")

    names: set[str] = set()
    line_count = 0
    with cookie_file.open("r", encoding="utf-8-sig") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                parts = line.split()
            if len(parts) >= 7:
                names.add(parts[5])
                line_count += 1

    found = sorted(names & AUTH_COOKIE_NAMES)
    payload = {
        "ok": bool(found),
        "stage": "validate_youtube_cookies",
        "cookie_file_size": cookie_file.stat().st_size,
        "cookie_line_count": line_count,
        "auth_cookie_names_found": found,
    }
    write_json(runtime.get("latest_log_file", "logs/latest.json"), payload)
    print(f"YouTube cookie file size: {payload['cookie_file_size']} bytes")
    print(f"YouTube cookie lines: {line_count}")
    print(f"YouTube auth cookie names found: {', '.join(found) if found else 'none'}")
    if not found:
        fail_with_log(config, "YouTube cookie file does not contain login cookies", payload)


if __name__ == "__main__":
    main()
