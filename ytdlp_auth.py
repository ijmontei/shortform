import os
import argparse
import configparser
import csv
import json
import socket
import shutil
import subprocess
import tempfile
import time
import urllib.request

import yt_dlp

from theme_config import BASE_DIR


DEFAULT_AUTH_TEST_URL = "https://www.youtube.com/watch?v=vyKU6Pd5KAA"
AUTH_REPORT_FILE = os.path.join(BASE_DIR, "logs", "ytdlp_auth_latest.json")
COOKIE_BACKUP_DIR = os.path.join(BASE_DIR, "logs", "cookie_backups")
BGUTIL_REPORT_FILE = os.path.join(BASE_DIR, "logs", "bgutil_provider_latest.json")
BGUTIL_DEFAULT_PORT = int(os.getenv("SHORTFORM_BGUTIL_POT_PORT", "4416"))
BGUTIL_SERVER_HOME = os.path.expanduser(
    os.getenv(
        "SHORTFORM_BGUTIL_POT_SERVER_HOME",
        os.path.join("~", "bgutil-ytdlp-pot-provider", "server"),
    )
)
_bgutil_checked = False
PRIMARY_SESSION_COOKIES = {"SID", "__Secure-1PSID", "__Secure-3PSID"}
SECONDARY_SESSION_COOKIES = {
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",
    "__Secure-1PAPISID",
    "__Secure-3PAPISID",
}


class RestrictedVideoAuthError(RuntimeError):
    pass


class QuietYtdlpLogger:
    def debug(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


def youtube_js_runtime_options():
    ensure_bgutil_pot_provider()
    runtime = os.getenv("SHORTFORM_YTDLP_JS_RUNTIME", "node").strip().lower()

    if runtime in {"", "none", "off", "0"}:
        return {}

    return {
        "js_runtimes": {runtime: {}},
        "allow_remote_features": True,
    }


def write_bgutil_report(status, detail=None):
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": status,
        "port": BGUTIL_DEFAULT_PORT,
        "server_home": BGUTIL_SERVER_HOME,
        "detail": detail or {},
    }
    os.makedirs(os.path.dirname(BGUTIL_REPORT_FILE), exist_ok=True)

    with open(BGUTIL_REPORT_FILE, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")

    return payload


def bgutil_ping(timeout=1.5):
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{BGUTIL_DEFAULT_PORT}/ping",
            timeout=timeout,
        ) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
            return {
                "ok": 200 <= int(response.status) < 300,
                "status_code": int(response.status),
                "body": body[:500],
            }
    except Exception as error:
        return {
            "ok": False,
            "error": str(error).splitlines()[0],
        }


def tcp_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", int(port))) == 0


def ensure_bgutil_pot_provider():
    global _bgutil_checked

    if _bgutil_checked:
        return

    _bgutil_checked = True

    if os.getenv("SHORTFORM_ENABLE_BGUTIL_POT_PROVIDER", "1") == "0":
        write_bgutil_report("disabled")
        return

    ping = bgutil_ping()

    if ping.get("ok"):
        write_bgutil_report("ok", {"source": "already_running", "ping": ping})
        return

    server_entry = os.path.join(BGUTIL_SERVER_HOME, "build", "main.js")

    if not os.path.exists(server_entry):
        write_bgutil_report(
            "missing",
            {
                "server_entry": server_entry,
                "ping": ping,
                "hint": "Install and build https://github.com/Brainicism/bgutil-ytdlp-pot-provider in the configured server_home.",
            },
        )
        return

    log_dir = os.path.join(BASE_DIR, "logs", "bgutil")
    os.makedirs(log_dir, exist_ok=True)
    stdout_path = os.path.join(log_dir, "bgutil_provider.out.log")
    stderr_path = os.path.join(log_dir, "bgutil_provider.err.log")
    creationflags = 0

    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        stdout_handle = open(stdout_path, "ab")
        stderr_handle = open(stderr_path, "ab")
        process = subprocess.Popen(
            ["node", "build/main.js"],
            cwd=BGUTIL_SERVER_HOME,
            stdout=stdout_handle,
            stderr=stderr_handle,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )

        for _ in range(20):
            time.sleep(0.35)
            ping = bgutil_ping()

            if ping.get("ok"):
                write_bgutil_report(
                    "ok",
                    {
                        "source": "started",
                        "pid": process.pid,
                        "ping": ping,
                        "stdout": stdout_path,
                        "stderr": stderr_path,
                    },
                )
                return

            if process.poll() is not None:
                break

        write_bgutil_report(
            "failed",
            {
                "pid": process.pid,
                "exit_code": process.poll(),
                "ping": ping,
                "stdout": stdout_path,
                "stderr": stderr_path,
            },
        )
    except Exception as error:
        write_bgutil_report("failed", {"error": str(error).splitlines()[0]})


def youtube_cookie_file():
    return os.getenv("SHORTFORM_YTDLP_COOKIES", os.path.join(BASE_DIR, "cookies.txt"))


def parse_netscape_cookie_line(line):
    line = str(line or "").rstrip("\n")

    if not line.strip():
        return None

    if line.startswith("#HttpOnly_"):
        line = line.replace("#HttpOnly_", "", 1)
        http_only = True
    elif line.startswith("#"):
        return None
    else:
        http_only = False

    parts = line.split("\t")

    if len(parts) < 7:
        return None

    expires = None

    try:
        expires = int(parts[4])
    except (TypeError, ValueError):
        pass

    return {
        "domain": parts[0].lstrip("."),
        "http_only": http_only,
        "name": parts[5],
        "expires": expires,
        "session": expires == 0,
    }


def cookie_file_diagnostics(cookiefile=None):
    cookiefile = cookiefile or youtube_cookie_file()
    diagnostics = {
        "path": cookiefile,
        "exists": os.path.exists(cookiefile),
        "size_kb": 0.0,
        "non_comment_lines": 0,
        "http_only_lines": 0,
        "domains": [],
        "important_domain_cookie_names": {},
        "important_domain_cookie_counts": {},
        "cookie_names": [],
        "primary_session_cookie_names": [],
        "secondary_session_cookie_names": [],
        "expired_cookie_names": [],
        "session_cookie_count": 0,
        "latest_expiry": "",
        "modified_at": "",
        "age_hours": None,
        "warnings": [],
    }

    if not diagnostics["exists"]:
        diagnostics["warnings"].append("cookie file is missing")
        return diagnostics

    try:
        diagnostics["size_kb"] = round(os.path.getsize(cookiefile) / 1024, 1)
        modified = os.path.getmtime(cookiefile)
        diagnostics["modified_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(modified))
        diagnostics["age_hours"] = round((time.time() - modified) / 3600, 1)
        domains = set()
        domain_cookie_names = {}
        names = set()
        expired_names = set()
        latest_expiry = 0

        with open(cookiefile, "r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                parsed = parse_netscape_cookie_line(raw_line)

                if not parsed:
                    continue

                diagnostics["non_comment_lines"] += 1

                if parsed["http_only"]:
                    diagnostics["http_only_lines"] += 1

                domains.add(parsed["domain"])
                names.add(parsed["name"])
                domain_cookie_names.setdefault(parsed["domain"].lower(), set()).add(parsed["name"])

                expires = parsed.get("expires")

                if parsed.get("session"):
                    diagnostics["session_cookie_count"] += 1
                elif expires:
                    latest_expiry = max(latest_expiry, expires)

                    if expires < time.time():
                        expired_names.add(parsed["name"])

        diagnostics["domains"] = sorted(domains)
        diagnostics["cookie_names"] = sorted(names)
        important_domain_cookie_names = {}

        for domain, cookie_names in domain_cookie_names.items():
            if (
                domain.endswith("youtube.com")
                or domain.endswith("google.com")
                or domain.endswith("accounts.google.com")
            ):
                important_domain_cookie_names[domain] = sorted(cookie_names)

        diagnostics["important_domain_cookie_names"] = dict(sorted(important_domain_cookie_names.items()))
        diagnostics["important_domain_cookie_counts"] = {
            domain: len(cookie_names)
            for domain, cookie_names in diagnostics["important_domain_cookie_names"].items()
        }
        diagnostics["primary_session_cookie_names"] = sorted(names & PRIMARY_SESSION_COOKIES)
        diagnostics["secondary_session_cookie_names"] = sorted(names & SECONDARY_SESSION_COOKIES)
        diagnostics["expired_cookie_names"] = sorted(expired_names)

        if latest_expiry:
            diagnostics["latest_expiry"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(latest_expiry))
    except OSError as error:
        diagnostics["warnings"].append(f"could not read cookie file: {error}")
        return diagnostics

    domains_lower = {domain.lower() for domain in diagnostics["domains"]}
    names = set(diagnostics["cookie_names"])

    if diagnostics["size_kb"] < 5 or diagnostics["non_comment_lines"] < 25:
        diagnostics["warnings"].append("cookie file looks small for a fully signed-in YouTube export")

    if diagnostics.get("age_hours") is not None:
        stale_hours = float(os.getenv("SHORTFORM_COOKIE_STALE_WARNING_HOURS", "168"))

        if diagnostics["age_hours"] > stale_hours:
            diagnostics["warnings"].append(
                f"cookie export is older than {stale_hours:g} hours; export a fresh signed-in session if restricted auth fails"
            )

    if not any(domain.endswith("youtube.com") for domain in domains_lower):
        diagnostics["warnings"].append("no youtube.com cookie domain found")

    if not any(domain.endswith("google.com") or domain.endswith("accounts.google.com") for domain in domains_lower):
        diagnostics["warnings"].append(
            "no google.com account-cookie domains found; age-gated YouTube checks often need the full signed-in Google session, not only youtube.com cookies"
        )

    if not names & PRIMARY_SESSION_COOKIES:
        diagnostics["warnings"].append("missing primary signed-in Google session cookies: SID/__Secure-1PSID/__Secure-3PSID")

    if len(names & SECONDARY_SESSION_COOKIES) < 3:
        diagnostics["warnings"].append("missing several secondary signed-in Google session cookies")

    expired_primary = sorted((names & PRIMARY_SESSION_COOKIES) & set(diagnostics["expired_cookie_names"]))

    if expired_primary:
        diagnostics["warnings"].append(f"primary session cookies appear expired: {', '.join(expired_primary)}")

    return diagnostics


def cookie_file_diagnostics_text(cookiefile=None):
    diagnostics = cookie_file_diagnostics(cookiefile)

    if not diagnostics["exists"]:
        return f"{diagnostics['path']} is missing"

    domain_preview = ", ".join(diagnostics["domains"][:6]) or "none"
    important_counts = diagnostics.get("important_domain_cookie_counts") or {}
    important_text = ", ".join(
        f"{domain}:{count}"
        for domain, count in sorted(important_counts.items())
    ) or "none"
    warning_text = "; ".join(diagnostics["warnings"]) if diagnostics["warnings"] else "no obvious structural warnings"
    modified_text = ""
    session_text = ""

    if diagnostics.get("modified_at"):
        modified_text = f", modified={diagnostics['modified_at']} ({diagnostics['age_hours']}h ago)"

    if diagnostics.get("primary_session_cookie_names"):
        session_text = ", primary_session=" + ",".join(diagnostics["primary_session_cookie_names"])

    return (
        f"{diagnostics['path']} has {diagnostics['non_comment_lines']} cookie line(s), "
        f"{diagnostics['size_kb']:.1f} KB{modified_text}, domains={domain_preview}"
        f", important_domain_counts={important_text}{session_text}; {warning_text}"
    )


def browser_user_data_root(browser):
    browser = str(browser or "").strip().lower()
    local_app_data = os.getenv("LOCALAPPDATA", "")
    app_data = os.getenv("APPDATA", "")

    if browser == "chrome":
        return os.path.join(local_app_data, "Google", "Chrome", "User Data")

    if browser == "edge":
        return os.path.join(local_app_data, "Microsoft", "Edge", "User Data")

    if browser == "firefox":
        return os.path.join(app_data, "Mozilla", "Firefox")

    return ""


def browser_executable(browser):
    browser = str(browser or "").strip().lower()
    local_app_data = os.getenv("LOCALAPPDATA", "")
    program_files = [os.getenv("PROGRAMFILES", ""), os.getenv("PROGRAMFILES(X86)", "")]

    if browser == "chrome":
        candidates = [
            os.path.join(path, "Google", "Chrome", "Application", "chrome.exe")
            for path in program_files
            if path
        ]
        candidates.append(os.path.join(local_app_data, "Google", "Chrome", "Application", "chrome.exe"))
    elif browser == "edge":
        candidates = [
            os.path.join(path, "Microsoft", "Edge", "Application", "msedge.exe")
            for path in program_files
            if path
        ]
        candidates.append(os.path.join(local_app_data, "Microsoft", "Edge", "Application", "msedge.exe"))
    elif browser == "firefox":
        candidates = [
            os.path.join(path, "Mozilla Firefox", "firefox.exe")
            for path in program_files
            if path
        ]
        candidates.append(os.path.join(local_app_data, "Mozilla Firefox", "firefox.exe"))
    else:
        candidates = []

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate

    return ""


def browser_profile_cookie_db(root, profile):
    return os.path.join(root, profile, "Network", "Cookies")


def firefox_profile_entries(root):
    profiles_ini = os.path.join(root, "profiles.ini")

    if not os.path.exists(profiles_ini):
        return []

    parser = configparser.RawConfigParser()
    parser.read(profiles_ini, encoding="utf-8")
    entries = []

    for section in parser.sections():
        if not section.lower().startswith("profile"):
            continue

        name = parser.get(section, "Name", fallback="")
        path_value = parser.get(section, "Path", fallback="")

        if not path_value:
            continue

        is_relative = parser.get(section, "IsRelative", fallback="1") == "1"
        profile_path = os.path.join(root, path_value) if is_relative else os.path.abspath(path_value)
        profile_folder = os.path.basename(profile_path.rstrip("\\/"))
        cookie_db = os.path.join(profile_path, "cookies.sqlite")
        entries.append({
            "browser": "firefox",
            "profile": profile_folder,
            "name": name,
            "gaia_name": "",
            "user_name": "",
            "hosted_domain": "",
            "path": profile_path,
            "cookie_db": cookie_db,
            "cookie_db_exists": os.path.exists(cookie_db),
            "candidate": f"firefox:{profile_folder}",
            "profile_ini_path": path_value,
            "default": parser.get(section, "Default", fallback="0") == "1",
        })

    return entries


def list_browser_profiles(browser="chrome"):
    browser = str(browser or "chrome").strip().lower()
    root = browser_user_data_root(browser)

    if not root or not os.path.isdir(root):
        return []

    if browser == "firefox":
        return firefox_profile_entries(root)

    info_cache = {}
    local_state = os.path.join(root, "Local State")

    if os.path.exists(local_state):
        try:
            with open(local_state, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            info_cache = ((data.get("profile") or {}).get("info_cache") or {})
        except (OSError, json.JSONDecodeError):
            info_cache = {}

    profile_names = set(info_cache.keys())
    profile_names.update(["Default"] + [f"Profile {index}" for index in range(1, 25)])
    profiles = []

    for profile in sorted(profile_names, key=lambda item: (item != "Default", item)):
        profile_path = os.path.join(root, profile)
        cookie_db = browser_profile_cookie_db(root, profile)

        if not os.path.isdir(profile_path) and not os.path.exists(cookie_db):
            continue

        meta = info_cache.get(profile) or {}
        profiles.append({
            "browser": browser,
            "profile": profile,
            "name": meta.get("name", ""),
            "gaia_name": meta.get("gaia_name", ""),
            "user_name": meta.get("user_name", ""),
            "hosted_domain": meta.get("hosted_domain", ""),
            "path": profile_path,
            "cookie_db": cookie_db,
            "cookie_db_exists": os.path.exists(cookie_db),
            "candidate": f"{browser}:{profile}",
        })

    return profiles


def browser_profile_summary(profile):
    identity = profile.get("user_name") or profile.get("gaia_name") or profile.get("name") or "unknown"
    hosted_domain = profile.get("hosted_domain") or ""
    hosted_suffix = f", domain={hosted_domain}" if hosted_domain else ""
    cookie_status = "cookies=yes" if profile.get("cookie_db_exists") else "cookies=no"
    return (
        f"{profile.get('candidate', '')}: "
        f"name={profile.get('name') or '-'}, user={identity}{hosted_suffix}, "
        f"{cookie_status}, path={profile.get('path')}"
    )


def resolve_browser_profile(identifier, browser="chrome"):
    identifier = str(identifier or "").strip()

    if not identifier:
        raise ValueError("browser profile identifier is required")

    profiles = list_browser_profiles(browser)
    lowered = identifier.lower()

    for profile in profiles:
        values = [
            profile.get("profile", ""),
            profile.get("candidate", ""),
            profile.get("user_name", ""),
            profile.get("name", ""),
            profile.get("gaia_name", ""),
            profile.get("path", ""),
        ]

        if any(str(value or "").lower() == lowered for value in values):
            return profile

    matches = [
        profile for profile in profiles
        if any(
            lowered in str(value or "").lower()
            for value in [
                profile.get("profile", ""),
                profile.get("candidate", ""),
                profile.get("user_name", ""),
                profile.get("name", ""),
                profile.get("gaia_name", ""),
                profile.get("path", ""),
            ]
        )
    ]

    if len(matches) == 1:
        return matches[0]

    if matches:
        options = "\n".join(f"- {browser_profile_summary(profile)}" for profile in matches[:8])
        raise ValueError(f"browser profile identifier matched multiple profiles:\n{options}")

    available = "\n".join(f"- {browser_profile_summary(profile)}" for profile in profiles[:12]) or "- none"
    raise ValueError(f"browser profile not found for {identifier!r}. Available profiles:\n{available}")


def open_browser_profile(identifier, browser="chrome", url=None):
    profile = resolve_browser_profile(identifier, browser=browser)
    executable = browser_executable(profile["browser"])

    if not executable:
        raise FileNotFoundError(f"could not find {profile['browser']} executable")

    launch_url = url or DEFAULT_AUTH_TEST_URL

    if profile["browser"] == "firefox":
        command = [
            executable,
            "-no-remote",
            "-profile",
            profile["path"],
            launch_url,
        ]
    else:
        command = [
            executable,
            f"--profile-directory={profile['profile']}",
            launch_url,
        ]
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    return {
        "profile": profile,
        "command": command,
        "url": launch_url,
    }


def requested_browser_profile_candidate():
    browser = os.getenv(
        "SHORTFORM_YTDLP_COOKIES_BROWSER_NAME",
        os.getenv("SHORTFORM_YTDLP_DEFAULT_BROWSER_COOKIE_BROWSER", "firefox"),
    ).strip().lower() or "firefox"
    profile_identifier = (
        os.getenv("SHORTFORM_YTDLP_COOKIES_PROFILE")
        or os.getenv("SHORTFORM_YTDLP_COOKIES_PROFILE_EMAIL")
        or os.getenv("SHORTFORM_YTDLP_DEFAULT_BROWSER_COOKIE_PROFILE")
        or ""
    ).strip()

    if not profile_identifier:
        return ""

    try:
        return resolve_browser_profile(profile_identifier, browser=browser)["candidate"]
    except Exception:
        return f"{browser}:{profile_identifier}"


def normalize_browser_cookie_candidate(candidate):
    browser_tuple = cookie_browser_to_tuple(candidate)
    browser = browser_tuple[0].strip().lower() if browser_tuple else ""

    if browser not in {"chrome", "edge", "firefox"} or len(browser_tuple) < 2:
        return candidate

    profile_identifier = browser_tuple[1].strip()

    try:
        return resolve_browser_profile(profile_identifier, browser=browser)["candidate"]
    except Exception:
        return candidate


def write_auth_report(status, video_url=None, result=None, errors=None):
    diagnostics = cookie_file_diagnostics()
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": status,
        "video_url": video_url or os.getenv("SHORTFORM_YTDLP_AUTH_TEST_URL", DEFAULT_AUTH_TEST_URL),
        "cookie_file": diagnostics,
        "browser_lock_hint": browser_lock_hint(),
        "result": result or {},
        "errors": errors or [],
    }
    os.makedirs(os.path.dirname(AUTH_REPORT_FILE), exist_ok=True)

    with open(AUTH_REPORT_FILE, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")

    return payload


def verify_cookie_file(cookiefile, video_url=None, browser_fallback_armed=False):
    cookiefile = os.path.abspath(cookiefile)
    previous = os.environ.get("SHORTFORM_YTDLP_COOKIES")
    os.environ["SHORTFORM_YTDLP_COOKIES"] = cookiefile

    try:
        return verify_youtube_auth(
            video_url=video_url,
            include_browser_fallback=False,
            browser_fallback_armed=browser_fallback_armed,
        )
    finally:
        if previous is None:
            os.environ.pop("SHORTFORM_YTDLP_COOKIES", None)
        else:
            os.environ["SHORTFORM_YTDLP_COOKIES"] = previous


def backup_cookie_file(cookiefile=None):
    cookiefile = cookiefile or youtube_cookie_file()

    if not os.path.exists(cookiefile):
        return ""

    os.makedirs(COOKIE_BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(COOKIE_BACKUP_DIR, f"cookies_{stamp}.txt")
    shutil.copy2(cookiefile, backup_path)
    return backup_path


def install_cookie_export(source_file, destination_file=None, video_url=None, force=False):
    source_file = os.path.abspath(source_file)
    destination_file = os.path.abspath(destination_file or os.path.join(BASE_DIR, "cookies.txt"))

    if not os.path.exists(source_file):
        raise FileNotFoundError(f"cookie export not found: {source_file}")

    diagnostics = cookie_file_diagnostics(source_file)

    if diagnostics["non_comment_lines"] <= 0:
        raise ValueError(f"cookie export has no readable Netscape cookie rows: {source_file}")

    verification = None

    if not force:
        verification = verify_cookie_file(source_file, video_url=video_url)

    backup_path = backup_cookie_file(destination_file)
    os.makedirs(os.path.dirname(destination_file), exist_ok=True)
    shutil.copy2(source_file, destination_file)

    return {
        "source": source_file,
        "destination": destination_file,
        "backup": backup_path,
        "diagnostics": diagnostics,
        "verified_before_install": not force,
        "verification": verification or {},
    }


def default_cookie_export_search_dirs():
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    return [downloads] if os.path.isdir(downloads) else []


def cookie_export_key(path):
    try:
        return f"{os.path.abspath(path)}|{os.path.getmtime(path):.6f}|{os.path.getsize(path)}"
    except OSError:
        return os.path.abspath(path)


def discover_cookie_exports(search_dirs=None, newer_than=None, limit=20):
    search_dirs = search_dirs or default_cookie_export_search_dirs()
    destination = os.path.abspath(os.path.join(BASE_DIR, "cookies.txt"))
    candidates = []

    for directory in search_dirs:
        directory = os.path.abspath(os.path.expanduser(str(directory or "")))

        if not os.path.isdir(directory):
            continue

        try:
            filenames = os.listdir(directory)
        except OSError:
            continue

        for filename in filenames:
            path = os.path.join(directory, filename)

            if not os.path.isfile(path):
                continue

            if os.path.abspath(path) == destination:
                continue

            lower_name = filename.lower()

            if not lower_name.endswith(".txt"):
                continue

            if "cookie" not in lower_name and "youtube" not in lower_name:
                continue

            try:
                size = os.path.getsize(path)
                modified = os.path.getmtime(path)
            except OSError:
                continue

            if size <= 0:
                continue

            if newer_than is not None and modified <= float(newer_than):
                continue

            candidates.append({
                "path": path,
                "size": size,
                "modified": modified,
                "key": cookie_export_key(path),
            })

    candidates.sort(key=lambda item: item["modified"], reverse=True)
    return candidates[:max(1, int(limit or 20))]


def install_newest_valid_cookie_export(
    search_dirs=None,
    destination_file=None,
    video_url=None,
    newer_than=None,
    limit=12,
    exclude_keys=None,
):
    exclude_keys = set(exclude_keys or [])
    attempted = []
    attempted_keys = []
    candidates = discover_cookie_exports(
        search_dirs=search_dirs,
        newer_than=newer_than,
        limit=limit,
    )

    for candidate in candidates:
        if candidate["key"] in exclude_keys:
            continue

        attempted_keys.append(candidate["key"])
        path = candidate["path"]

        try:
            verification = verify_cookie_file(path, video_url=video_url)
            installed = install_cookie_export(
                path,
                destination_file=destination_file,
                video_url=video_url,
                force=True,
            )
            installed["verified_before_install"] = True
            installed["verification"] = verification
            return {
                "installed": True,
                "install": installed,
                "attempted": attempted,
                "attempted_keys": attempted_keys,
                "candidate_count": len(candidates),
            }
        except Exception as error:
            attempted.append({
                "path": path,
                "error": str(error).splitlines()[0][:300],
            })

    return {
        "installed": False,
        "attempted": attempted,
        "attempted_keys": attempted_keys,
        "candidate_count": len(candidates),
    }


def get_cookie_browser_candidates():
    if os.getenv("SHORTFORM_DISABLE_BROWSER_COOKIES") == "1":
        return []

    requested = os.getenv("SHORTFORM_YTDLP_COOKIES_BROWSER", "").strip()
    requested_profile = requested_browser_profile_candidate()

    if requested:
        candidates = [
            normalize_browser_cookie_candidate(browser.strip())
            for browser in requested.split(",")
            if browser.strip()
        ]
    elif requested_profile:
        candidates = [requested_profile]
    else:
        preferred_browser = os.getenv("SHORTFORM_YTDLP_DEFAULT_BROWSER_COOKIE_BROWSER", "firefox").strip().lower()
        preferred_candidates = [
            profile["candidate"]
            for profile in list_browser_profiles(preferred_browser)
            if profile.get("cookie_db_exists")
        ]

        if preferred_candidates:
            candidates = preferred_candidates
        else:
            candidates = [
                "firefox",
                "chrome:Profile 2",
                "chrome:Default",
                "chrome",
                "edge:Default",
                "edge",
            ]
            candidates.extend(discover_browser_profile_candidates())

    seen = set()
    unique = []

    for candidate in candidates:
        key = candidate.lower()

        if key in seen:
            continue

        seen.add(key)
        unique.append(candidate)

    return unique


def browser_cookie_fallback_enabled():
    return os.getenv("SHORTFORM_ALLOW_BROWSER_COOKIE_FALLBACK", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def auth_source_order():
    raw = os.getenv("SHORTFORM_YTDLP_AUTH_SOURCE_ORDER", "browser,cookiefile")
    order = []

    for item in raw.split(","):
        key = item.strip().lower().replace("-", "_")

        if key in {"browser", "browser_cookie", "browser_cookies", "cookiesfrombrowser"}:
            key = "browser"
        elif key in {"file", "cookie_file", "cookiefile", "cookies_txt", "cookies"}:
            key = "cookiefile"
        else:
            continue

        if key not in order:
            order.append(key)

    for key in ["browser", "cookiefile"]:
        if key not in order:
            order.append(key)

    return order


def discover_browser_profile_candidates():
    profile_candidates = []

    for browser in ["firefox", "chrome", "edge"]:
        for profile in list_browser_profiles(browser):
            if profile.get("cookie_db_exists"):
                profile_candidates.append(profile["candidate"])

    return profile_candidates


def cookie_browser_to_tuple(candidate):
    parts = str(candidate or "").split(":", 1)
    browser = parts[0].strip()

    if len(parts) == 1 or not parts[1].strip():
        return (browser,)

    return (browser, parts[1].strip())


def browser_process_name(browser):
    browser = str(browser or "").strip().lower()

    if browser == "chrome":
        return "chrome.exe"

    if browser == "edge":
        return "msedge.exe"

    if browser == "firefox":
        return "firefox.exe"

    return ""


def browser_cookie_candidate_browsers():
    browsers = []

    for candidate in get_cookie_browser_candidates():
        browser = cookie_browser_to_tuple(candidate)[0].strip().lower()

        if browser in {"chrome", "edge", "firefox"} and browser not in browsers:
            browsers.append(browser)

    return browsers


def browser_cookie_fallback_blockers():
    blockers = []

    for browser in browser_cookie_candidate_browsers():
        process_name = browser_process_name(browser)

        if process_name and process_running(process_name):
            blockers.append(process_name)

    return blockers


def browser_cookie_fallback_ready():
    return not browser_cookie_fallback_blockers()


def is_cookie_load_error(error):
    message = str(error).lower()
    cookie_markers = [
        "could not copy chrome cookie database",
        "could not copy edge cookie database",
        "could not find chrome cookies database",
        "could not find edge cookies database",
        "could not find firefox cookies database",
        "failed to decrypt with dpapi",
        "failed to load cookies",
        "permission denied",
        "cookie database",
        "cookies.sqlite",
    ]
    return any(marker in message for marker in cookie_markers)


def is_auth_needed_error(error):
    message = str(error).lower()
    auth_markers = [
        "sign in to confirm your age",
        "sign in to confirm",
        "this video may be inappropriate",
        "use --cookies",
        "use --cookies-from-browser",
        "confirm you're not a bot",
        "not a bot",
        "login required",
        "private video",
        "members-only",
        "members only",
        "http error 403: forbidden",
        "unable to download video data",
        "forbidden",
        "precondition check failed",
    ]
    return any(marker in message for marker in auth_markers)


def is_unavailable_video_error(error):
    message = str(error).lower()
    unavailable_markers = [
        "this video is unavailable",
        "video unavailable",
        "copyright claim",
        "has been removed",
    ]
    return any(marker in message for marker in unavailable_markers)


def is_format_unavailable_error(error):
    message = str(error).lower()
    format_markers = [
        "requested format is not available",
        "only images are available",
        "no video formats found",
    ]
    return any(marker in message for marker in format_markers)


def is_restricted_or_unavailable_error(error):
    return is_auth_needed_error(error) or is_unavailable_video_error(error)


def clear_cookie_options(opts):
    opts.pop("cookiefile", None)
    opts.pop("cookiesfrombrowser", None)
    return opts


def readonly_cookiefile_copy(cookiefile):
    if not cookiefile or not os.path.exists(cookiefile):
        return "", None

    fd, temp_path = tempfile.mkstemp(prefix="shortform_ytdlp_cookies_", suffix=".txt")
    os.close(fd)
    shutil.copy2(cookiefile, temp_path)
    return temp_path, temp_path


def cleanup_temp_cookiefile(path):
    if not path:
        return

    try:
        os.remove(path)
    except OSError:
        pass


def opts_with_readonly_cookiefile(ydl_opts):
    opts = dict(ydl_opts or {})
    cookiefile = opts.get("cookiefile")
    temp_path, cleanup_path = readonly_cookiefile_copy(cookiefile)

    if temp_path:
        opts["cookiefile"] = temp_path

    return opts, cleanup_path


def cookie_sources(include_browser=True):
    sources = []
    cookiefile = youtube_cookie_file()
    cookiefile_source = None
    browser_sources = []

    if cookiefile and os.path.exists(cookiefile) and os.path.getsize(cookiefile) > 0:
        cookiefile_source = ("cookiefile", cookiefile)

    if include_browser:
        for browser in get_cookie_browser_candidates():
            browser_sources.append(("browser", browser))

    for source_type in auth_source_order():
        if source_type == "browser":
            sources.extend(browser_sources)
        elif source_type == "cookiefile" and cookiefile_source:
            sources.append(cookiefile_source)

    return sources


def apply_cookie_source(ydl_opts, source):
    kind, value = source
    opts = clear_cookie_options(dict(ydl_opts))
    opts.setdefault("logger", QuietYtdlpLogger())
    opts.update(youtube_js_runtime_options())

    if kind == "cookiefile":
        opts["cookiefile"] = value
    elif kind == "browser":
        opts["cookiesfrombrowser"] = cookie_browser_to_tuple(value)

    return opts


def cookie_source_label(source):
    kind, value = source

    if kind == "cookiefile":
        return f"cookie file {value}"

    return f"browser cookies {value}"


def process_running(image_name):
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return False

    return image_name.lower() in (result.stdout or "").lower()


def browser_lock_hint():
    blockers = browser_cookie_fallback_blockers()

    if not blockers:
        browsers = browser_cookie_candidate_browsers()
        target = "/".join(browser.capitalize() for browser in browsers) or "configured browser"
        return f"{target} browser-cookie profile does not appear to be locked."

    running = []

    if "chrome.exe" in blockers:
        running.append("Chrome")

    if "msedge.exe" in blockers:
        running.append("Edge")

    if "firefox.exe" in blockers:
        running.append("Firefox")

    verb = "appear" if len(running) > 1 else "appears"
    return (
        f"{' and '.join(running)} currently {verb} to be running. "
        "Close that browser's windows and background processes before relying on browser-cookie fallback, "
        "or export a fresh signed-in cookies.txt instead."
    )


def browser_lock_status():
    processes = []

    for image_name in ["chrome.exe", "msedge.exe", "firefox.exe"]:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/V", "/FO", "CSV"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue

        reader = csv.DictReader(result.stdout.splitlines())

        for row in reader:
            process_name = (row.get("Image Name") or "").strip()

            if process_name.lower() != image_name:
                continue

            processes.append({
                "image_name": process_name,
                "pid": row.get("PID", "").strip(),
                "window_title": (row.get("Window Title") or "").strip(),
            })

    candidate_blockers = set(browser_cookie_fallback_blockers())
    blocking = sorted(candidate_blockers)
    target_processes = [
        item for item in processes
        if item["image_name"].lower() in {name.lower() for name in candidate_blockers}
    ]
    return {
        "chrome_running": any(item["image_name"].lower() == "chrome.exe" for item in processes),
        "edge_running": any(item["image_name"].lower() == "msedge.exe" for item in processes),
        "firefox_running": any(item["image_name"].lower() == "firefox.exe" for item in processes),
        "observed_browsers": sorted({item["image_name"] for item in processes}),
        "blocking_browsers": blocking,
        "process_count": len(processes),
        "blocking_process_count": len(target_processes),
        "processes": processes,
        "blocking_processes": target_processes,
        "hint": browser_lock_hint(),
    }


def auth_help_message(errors=None, include_browser_fallback=True, browser_fallback_armed=False):
    cookiefile = youtube_cookie_file()
    gated_video = os.getenv("SHORTFORM_YTDLP_AUTH_TEST_URL", DEFAULT_AUTH_TEST_URL)
    target_browsers = browser_cookie_candidate_browsers()
    target_label = "/".join(browser.capitalize() for browser in target_browsers) or "the configured browser"
    gate_instructions = (
        f" Open {gated_video} in the same signed-in browser account, click the "
        "sensitive/age-restricted Proceed button, confirm the video actually plays, "
        "then export cookies again with YouTube, Google, and Accounts cookies included."
    )
    if include_browser_fallback:
        message = (
            "YouTube authentication is required for restricted videos, but no available cookie source "
            "unlocked the video. Export a fresh signed-in, age-verified YouTube cookie file to "
            f"{cookiefile}, or close {target_label} fully and allow browser-cookie access. Then run "
            "`python ytdlp_auth.py` to verify before running the full pipeline."
            f"{gate_instructions}"
        )
    else:
        message = (
            "YouTube authentication is required for restricted videos, but this cookie file did not "
            "unlock the video. Export a fresh signed-in, age-verified browser session with YouTube, "
            "Google, and Accounts cookies included, then rerun this cookie-file verification."
            f"{gate_instructions}"
        )
    message += "\nCookie file diagnostics: " + cookie_file_diagnostics_text(cookiefile)
    message += "\nBrowser-cookie hint: " + browser_lock_hint()

    if not include_browser_fallback and browser_fallback_armed:
        message += (
            f"\nBrowser-cookie fallback is armed, but {target_label} still appears to be running. "
            "Close that browser's windows and background processes, then retry with "
            "--allow-browser-cookie-fallback."
        )
    elif not include_browser_fallback:
        message += (
            "\nBrowser-cookie fallback is enabled by default for production runs. "
            f"After closing {target_label}, run `python ytdlp_auth.py` without --cookie-file "
            "so the helper can try the Firefox profile first and cookies.txt as backup."
        )

    if errors:
        message += "\nAttempt details:\n" + "\n".join(f"- {item}" for item in errors[-6:])

    return message


def format_unavailable_message(error):
    return (
        "YouTube cookies loaded, but yt-dlp could not satisfy the requested media format. "
        "This is a format-selection problem, not a sign-in problem. Try updating yt-dlp or "
        "checking available formats with: python -m yt_dlp --cookies cookies.txt --list-formats "
        f"{os.getenv('SHORTFORM_YTDLP_AUTH_TEST_URL', DEFAULT_AUTH_TEST_URL)}\n"
        f"Original error: {str(error).splitlines()[0][:300]}"
    )


def run_ytdlp_authenticated(
    ydl_opts,
    operation,
    *,
    reason="restricted YouTube media",
    include_browser_fallback=None,
    browser_fallback_armed=False,
):
    if include_browser_fallback is None:
        include_browser_fallback = browser_cookie_fallback_enabled()

    sources = cookie_sources(include_browser=include_browser_fallback)

    if not sources:
        if include_browser_fallback:
            missing_reason = "No cookies.txt or browser cookie source was available."
        else:
            missing_reason = "No cookie file source was available."

        raise RestrictedVideoAuthError(
            auth_help_message(
                [missing_reason],
                include_browser_fallback=include_browser_fallback,
                browser_fallback_armed=browser_fallback_armed,
            )
        )

    errors = []

    for index, source in enumerate(sources, start=1):
        label = cookie_source_label(source)
        runtime_source = source
        cleanup_path = None

        try:
            if source[0] == "cookiefile":
                temp_cookiefile, cleanup_path = readonly_cookiefile_copy(source[1])

                if temp_cookiefile:
                    runtime_source = ("cookiefile", temp_cookiefile)

            opts = apply_cookie_source(ydl_opts, runtime_source)

            if len(sources) > 1:
                print(f" -> Trying YouTube auth via {label} ({index}/{len(sources)})")

            with yt_dlp.YoutubeDL(opts) as ydl:
                return operation(ydl)
        except Exception as error:
            if is_format_unavailable_error(error):
                raise RuntimeError(format_unavailable_message(error)) from error

            if not (is_cookie_load_error(error) or is_auth_needed_error(error)):
                raise

            errors.append(f"{label}: {str(error).splitlines()[0][:260]}")

            if index < len(sources):
                print(f" -> {label} did not unlock {reason}; trying next auth source.")
        finally:
            cleanup_temp_cookiefile(cleanup_path)

    raise RestrictedVideoAuthError(
        auth_help_message(
            errors,
            include_browser_fallback=include_browser_fallback,
            browser_fallback_armed=browser_fallback_armed,
        )
    )


def run_ytdlp_with_auth_retry(ydl_opts, operation, *, auth_required=False, reason="YouTube media"):
    if auth_required:
        return run_ytdlp_authenticated(ydl_opts, operation, reason=reason)

    try:
        readonly_opts, cleanup_path = opts_with_readonly_cookiefile(ydl_opts)

        try:
            with yt_dlp.YoutubeDL(readonly_opts) as ydl:
                return operation(ydl)
        finally:
            cleanup_temp_cookiefile(cleanup_path)
    except Exception as error:
        if not is_auth_needed_error(error):
            raise

        print(" -> Video requires sign-in; retrying with YouTube cookies.")
        return run_ytdlp_authenticated(ydl_opts, operation, reason=reason)


def media_auth_required():
    return os.getenv("SHORTFORM_REQUIRE_YOUTUBE_AUTH_FOR_MEDIA", "1") != "0"


def media_download_auth_required():
    policy = os.getenv("SHORTFORM_MEDIA_AUTH_POLICY", "on_demand").strip().lower()

    if policy in {"always", "force", "forced", "required"}:
        return media_auth_required()

    if policy in {"never", "off", "0", "public"}:
        return False

    return False


def verify_youtube_auth(video_url=None, include_browser_fallback=None, browser_fallback_armed=False):
    if include_browser_fallback is None:
        include_browser_fallback = browser_cookie_fallback_enabled()

    video_url = video_url or os.getenv("SHORTFORM_YTDLP_AUTH_TEST_URL", DEFAULT_AUTH_TEST_URL)
    attempts = max(1, int(os.getenv("SHORTFORM_YTDLP_AUTH_VERIFY_ATTEMPTS", "3")))
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "ignoreerrors": False,
        "ignore_no_formats_error": False,
        **youtube_js_runtime_options(),
    }

    last_info = None
    last_formats = []

    try:
        for attempt in range(1, attempts + 1):
            info = run_ytdlp_authenticated(
                opts,
                lambda ydl: ydl.extract_info(video_url, download=False),
                reason="age-restricted auth test",
                include_browser_fallback=include_browser_fallback,
                browser_fallback_armed=browser_fallback_armed,
            )
            formats = [
                item for item in (info or {}).get("formats", [])
                if item.get("vcodec") != "none" or item.get("acodec") != "none"
            ]
            last_info = info
            last_formats = formats

            if formats:
                break

            if attempt < attempts:
                print(
                    " -> Auth cookie loaded but media formats were missing; "
                    f"retrying challenge solve ({attempt + 1}/{attempts})."
                )
                time.sleep(2.5 * attempt)

        if not last_formats:
            error = RestrictedVideoAuthError(
                "YouTube auth passed, but yt-dlp could not see downloadable audio/video formats. "
                "Update yt-dlp and make sure Node.js is available for YouTube challenge solving. "
                "Then test with: python -m yt_dlp --cookies cookies.txt --list-formats "
                f"{video_url}"
            )
            write_auth_report("failed", video_url=video_url, errors=[str(error)])
            raise error

        result = {
            "id": (last_info or {}).get("id", ""),
            "title": (last_info or {}).get("title", ""),
            "duration": (last_info or {}).get("duration", 0),
            "format_count": len(last_formats),
            "url": video_url,
        }
        write_auth_report("ok", video_url=video_url, result=result)
        return result
    except Exception as error:
        write_auth_report("failed", video_url=video_url, errors=[str(error)])
        raise


def print_cookie_diagnostics(cookiefile):
    diagnostics = cookie_file_diagnostics(cookiefile)
    print(cookie_file_diagnostics_text(cookiefile))
    print(json.dumps(diagnostics, indent=2))
    return diagnostics


def parse_args():
    parser = argparse.ArgumentParser(description="Verify and manage YouTube cookies for restricted media downloads.")
    parser.add_argument(
        "--test-url",
        default=os.getenv("SHORTFORM_YTDLP_AUTH_TEST_URL", DEFAULT_AUTH_TEST_URL),
        help="Restricted YouTube URL to use for auth verification.",
    )
    parser.add_argument(
        "--cookie-file",
        help="Temporarily verify this cookie file without changing the project root cookies.txt.",
    )
    parser.add_argument(
        "--diagnose-cookie-file",
        nargs="?",
        const=youtube_cookie_file(),
        help="Print cookie diagnostics for a file and exit. Defaults to the configured cookie file.",
    )
    parser.add_argument(
        "--browser-lock-status",
        action="store_true",
        help="Print browser processes that currently block browser-cookie fallback, then exit.",
    )
    parser.add_argument(
        "--list-browser-profiles",
        action="store_true",
        help="List Firefox/Chrome/Edge profiles discovered on this machine, including visible account emails when available.",
    )
    parser.add_argument(
        "--open-browser-profile",
        help="Open the auth test URL in a browser profile by email, profile folder, or profile name.",
    )
    parser.add_argument(
        "--open-browser",
        choices=["chrome", "edge", "firefox"],
        default=os.getenv(
            "SHORTFORM_YTDLP_COOKIES_BROWSER_NAME",
            os.getenv("SHORTFORM_YTDLP_DEFAULT_BROWSER_COOKIE_BROWSER", "firefox"),
        ).strip().lower() or "firefox",
        help="Browser to use with --open-browser-profile. Defaults to Firefox.",
    )
    parser.add_argument(
        "--open-url",
        default=os.getenv("SHORTFORM_YTDLP_AUTH_TEST_URL", DEFAULT_AUTH_TEST_URL),
        help="URL to open with --open-browser-profile. Defaults to the restricted auth test URL.",
    )
    parser.add_argument(
        "--install-cookie-export",
        help="Verify an exported cookie file and copy it to the project root cookies.txt only if verification passes.",
    )
    parser.add_argument(
        "--scan-cookie-exports",
        nargs="*",
        metavar="DIR",
        help="List likely cookie export files in DIR. Defaults to the user's Downloads folder.",
    )
    parser.add_argument(
        "--install-newest-cookie-export",
        nargs="*",
        metavar="DIR",
        help="Find the newest cookie export in DIR and install the first one that passes restricted-video verification. Defaults to Downloads.",
    )
    parser.add_argument(
        "--destination",
        default=os.path.join(BASE_DIR, "cookies.txt"),
        help="Destination for --install-cookie-export. Defaults to project root cookies.txt.",
    )
    parser.add_argument(
        "--force-install",
        action="store_true",
        help="Copy --install-cookie-export even if restricted-video verification fails. Use only for debugging.",
    )
    parser.add_argument(
        "--allow-browser-cookie-fallback",
        action="store_true",
        help=(
            "When verifying the configured project cookie source, also try browser cookie profiles. "
            "Browser fallback is enabled by default unless SHORTFORM_ALLOW_BROWSER_COOKIE_FALLBACK=0."
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.diagnose_cookie_file:
        print_cookie_diagnostics(args.diagnose_cookie_file)
        return 0

    if args.browser_lock_status:
        status = browser_lock_status()
        blockers = ", ".join(status.get("blocking_browsers") or []) or "none"
        print(
            "Browser-cookie fallback lock status: "
            f"blocking_browsers={blockers}; process_count={status.get('process_count', 0)}"
        )
        print(status.get("hint", ""))
        print(json.dumps(status, indent=2))
        return 1 if status.get("blocking_browsers") else 0

    if args.list_browser_profiles:
        profiles = []

        for browser in ["firefox", "chrome", "edge"]:
            profiles.extend(list_browser_profiles(browser))

        print(f"Browser profiles discovered: {len(profiles)}")

        for profile in profiles:
            print(f"- {browser_profile_summary(profile)}")

        if profiles:
            example_candidate = next(
                (
                    profile["candidate"]
                    for profile in profiles
                    if profile.get("browser") == "firefox" and profile.get("cookie_db_exists")
                ),
                profiles[0]["candidate"],
            )
            print(
                "\nTo prioritize one for yt-dlp browser cookies, run for example:\n"
                f"$env:SHORTFORM_YTDLP_COOKIES_BROWSER=\"{example_candidate}\"\n"
                "$env:SHORTFORM_ALLOW_BROWSER_COOKIE_FALLBACK=\"1\""
            )

        return 0

    if args.open_browser_profile:
        opened = open_browser_profile(
            args.open_browser_profile,
            browser=args.open_browser,
            url=args.open_url,
        )
        profile = opened["profile"]
        print("Opened browser profile for YouTube auth confirmation")
        print(browser_profile_summary(profile))
        print(f"URL: {opened['url']}")
        print(
            "After the video plays in this profile, close that browser fully before "
            "testing browser-cookie fallback."
        )
        return 0

    if args.scan_cookie_exports is not None:
        search_dirs = args.scan_cookie_exports or default_cookie_export_search_dirs()
        candidates = discover_cookie_exports(search_dirs=search_dirs)

        print(f"Cookie export candidates: {len(candidates)}")

        for candidate in candidates:
            modified = time.strftime(
                "%Y-%m-%d %H:%M:%S",
                time.localtime(candidate["modified"]),
            )
            print(f"- {candidate['path']} ({candidate['size']} bytes, modified {modified})")

        return 0

    try:
        if args.install_newest_cookie_export is not None:
            search_dirs = args.install_newest_cookie_export or default_cookie_export_search_dirs()
            result = install_newest_valid_cookie_export(
                search_dirs=search_dirs,
                destination_file=args.destination,
                video_url=args.test_url,
            )

            if result.get("installed"):
                installed = result["install"]
                verification = installed.get("verification") or {}
                print("YouTube cookie export installed")
                print(f"Source: {installed['source']}")
                print(f"Destination: {installed['destination']}")

                if installed.get("backup"):
                    print(f"Backup: {installed['backup']}")

                print(f"Verified restricted video: {verification.get('id', '')} - {verification.get('title', '')}")
                return 0

            print("No valid cookie export found")
            print(f"Candidates checked: {result.get('candidate_count', 0)}")

            for item in result.get("attempted", [])[:8]:
                print(f"- {item['path']}: {item['error']}")

            return 1

        if args.install_cookie_export:
            result = install_cookie_export(
                args.install_cookie_export,
                destination_file=args.destination,
                video_url=args.test_url,
                force=args.force_install,
            )
            print("YouTube cookie export installed")
            print(f"Source: {result['source']}")
            print(f"Destination: {result['destination']}")

            if result.get("backup"):
                print(f"Backup: {result['backup']}")

            if result.get("verified_before_install"):
                verification = result.get("verification") or {}
                print(f"Verified restricted video: {verification.get('id', '')} - {verification.get('title', '')}")

            return 0

        if args.cookie_file:
            result = verify_cookie_file(
                args.cookie_file,
                video_url=args.test_url,
                browser_fallback_armed=args.allow_browser_cookie_fallback,
            )
        else:
            browser_fallback_requested = (
                args.allow_browser_cookie_fallback
                or browser_cookie_fallback_enabled()
            )

            if browser_fallback_requested:
                target_browsers = browser_cookie_candidate_browsers()
                target_label = "/".join(browser.capitalize() for browser in target_browsers) or "the target browser"
                print(f"Browser-cookie fallback enabled. Close {target_label} fully before relying on this path.")

            browser_fallback_ready = (
                browser_fallback_requested
                and browser_cookie_fallback_ready()
            )

            if browser_fallback_requested and not browser_fallback_ready:
                blockers = ", ".join(browser_cookie_fallback_blockers()) or "target browser"
                print(f"Browser-cookie fallback armed, but {blockers} still appears to be running.")

            result = verify_youtube_auth(
                video_url=args.test_url,
                include_browser_fallback=browser_fallback_ready,
                browser_fallback_armed=browser_fallback_requested,
            )

        print("YouTube restricted-video auth OK")
        print(f"Video: {result['id']} - {result['title']}")
        print(f"Formats available: {result['format_count']}")
        return 0
    except Exception as error:
        print("YouTube restricted-video auth FAILED")
        print(error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
